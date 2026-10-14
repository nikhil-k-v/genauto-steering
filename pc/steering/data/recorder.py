"""
data/recorder.py — capture telemetry + health + events into a recording folder.

A writer thread flushes CSV rows every 250 ms so a crash loses at most that
much.  Health snapshots are written once per second and on every transition,
and every firmware event / PC action lands in events.jsonl — so when
something goes wrong during a run, the recording itself carries the evidence
(item 1A / item 3).
"""
from __future__ import annotations

import json
import logging
import math
import queue
import threading
import time
from typing import Optional

from .. import protocol as P
from ..bus import Bus
from .analysis import CSV_COLUMNS, compute_metrics, load_csv
from .store import Recording, Store

log = logging.getLogger(__name__)

from ..health.model import OPTIONAL_NODES


class Recorder:
    def __init__(self, bus: Bus, store: Store):
        self.bus = bus
        self.store = store
        self.rec: Optional[Recording] = None
        self._q: "queue.Queue[tuple]" = queue.Queue(maxsize=20000)
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._t0 = 0.0
        self._samples = 0
        self.dropped = 0
        self.error = ""
        self._target: float = math.nan
        self._worst_health = {}
        self._gains = {}
        self._limits = {}
        self._last_health_snap = 0.0
        bus.subscribe("telemetry", self._on_telemetry)
        bus.subscribe("health", self._on_health)
        bus.subscribe("health_transition", lambda ch: self._put(("health", ch)))
        bus.subscribe("event", self._on_event)
        bus.subscribe("config", self._on_config)
        bus.subscribe("stream_target", self._on_target)
        bus.subscribe("ui_action", lambda a: self._put(("event", {"src": "pc", **a})))

    @property
    def active(self) -> bool:
        return self.rec is not None

    @property
    def status(self) -> dict:
        return {"active": self.active, "dropped": self.dropped, "ok": not self.error, "error": self.error,
                "samples": self._samples, "elapsed": (time.monotonic() - self._t0) if self.active else 0.0,
                "name": self.rec.name if self.rec else ""}

    # ---- control ----------------------------------------------------------------------
    def start(self, kind: str, name: str, collection: str = "default", parent: Optional[Recording] = None,
              notes: str = "", tags=()) -> Recording:
        if self.rec is not None:
            raise RuntimeError("already recording")
        rec = self.store.new_recording_dir(kind, name, collection, parent)
        rec.notes, rec.tags = notes, list(tags)
        rec.gains = dict(self._gains)
        self._worst_health = {}
        self.dropped = 0
        self.error = ""
        self._samples = 0
        self._t0 = time.monotonic()
        self._stop.clear()
        self._q = queue.Queue(maxsize=20000)
        self.rec = rec
        self._thread = threading.Thread(target=self._writer, args=(rec,), name="recorder", daemon=True)
        self._thread.start()
        tree = self.bus.latest("health")
        if tree is not None:
            self._put(("health_snapshot", tree.to_dict()))
        self._put(("event", {"src": "pc", "action": "record_start", "kind": kind, "name": rec.name,
                             "parent": parent.uid if parent else None}))
        self.bus.publish("recording", self.status)
        log.info("recording started: %s (%s)", rec.name, rec.path)
        return rec

    def stop(self) -> Optional[Recording]:
        rec = self.rec
        if rec is None:
            return None
        self._put(("event", {"src": "pc", "action": "record_stop"}))
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3.0)
        rec.duration_s = time.monotonic() - self._t0
        rec.samples = self._samples
        try:
            rec.metrics = compute_metrics(load_csv(rec.csv), rec.kind)
        except Exception as e:
            log.exception("metrics failed")
            rec.metrics = {"error": str(e)}
        rec.health_summary, rec.health_worst = self._health_summary()
        rec.gains = dict(self._gains, **{f"limit_{k}": v for k, v in self._limits.items()})
        self.store.finalize(rec)
        self.rec = None                       # only now does `active` go False: metrics are on disk
        self.bus.publish("recording", self.status)
        self.bus.publish("recording_done", rec)
        log.info("recording stopped: %s (%d samples, %.1fs)", rec.name, rec.samples, rec.duration_s)
        return rec

    # ---- inputs -------------------------------------------------------------------------
    def _put(self, item):
        if self.rec is None:
            return
        try:
            self._q.put_nowait(item)
        except queue.Full:
            self.dropped += 1

    def _on_target(self, v):
        self._target = float(v) if v is not None else math.nan

    def _on_telemetry(self, t: P.TelemetryPacket):
        if self.rec is None:
            return
        now = time.monotonic() - self._t0
        err = t.setpoint_deg - t.position_deg if t.ctrl_state in (P.CS_HOLD, P.CS_TRAJ, P.CS_TEST) else math.nan
        self._put(("row", (now, t.t_us, t.ctrl_state, t.flags, self._target, t.setpoint_deg, t.position_deg,
                           t.velocity_deg_s, t.current_A, t.torque_cmd_Nm, err)))

    def _on_health(self, tree):
        if self.rec is None:
            return
        for nid, s in tree.nodes.items():
            if s.state == P.HS_BLOCKED and nid in OPTIONAL_NODES:
                continue                      # "not plugged in" is not a problem worth flagging
            if s.state != P.HS_OK:
                w = self._worst_health.get(nid)
                if w is None or s.state > w["s"]:
                    self._worst_health[nid] = {"s": s.state, "r": s.reason}
        now = time.monotonic()
        if now - self._last_health_snap >= 1.0:
            self._last_health_snap = now
            self._put(("health_snapshot", tree.to_dict()))

    def _on_event(self, e: P.EventPacket):
        self._put(("event", {"src": "fw", "code": P.EV_NAMES.get(e.code, e.code), "arg": e.arg,
                             "text": e.text_str, "t_fw_ms": e.t_ms}))

    def _on_config(self, c: P.ConfigEchoPacket):
        self._gains = {"kp": c.kp, "kd": c.kd, "ki": c.ki, "tff_Nm": c.tff_Nm}
        self._limits = {"left_deg": c.limit_left_deg, "right_deg": c.limit_right_deg, "valid": bool(c.limits_valid)}

    def _health_summary(self):
        if not self._worst_health:
            return "all OK", ""
        worst = sorted(self._worst_health.items(), key=lambda kv: -kv[1]["s"])
        summary = "; ".join(f"{k}={['?', 'OK', 'BLOCKED', 'FAIL'][v['s']]} ({v['r']})" for k, v in worst[:6])
        return summary, worst[0][0]

    # ---- writer thread -------------------------------------------------------------------
    def _writer(self, rec: Recording):
        try:
            with open(rec.csv, "w", buffering=1 << 16) as fcsv, \
                 open(rec.dir / "health.jsonl", "a") as fh, open(rec.dir / "events.jsonl", "a") as fe:
                fcsv.write(f"# genauto-steering recording {rec.uid} kind={rec.kind} name={rec.name} "
                           f"created={rec.created_str}\n")
                fcsv.write(",".join(CSV_COLUMNS) + "\n")
                last_flush = time.monotonic()
                while True:
                    try:
                        kind, item = self._q.get(timeout=0.1)
                    except queue.Empty:
                        if self._stop.is_set():
                            break
                        continue
                    if kind == "row":
                        fcsv.write(",".join("" if (isinstance(v, float) and math.isnan(v)) else
                                            (f"{v:.4f}" if isinstance(v, float) else str(v)) for v in item) + "\n")
                        self._samples += 1
                    elif kind == "health":
                        fh.write(json.dumps({"t": time.monotonic() - self._t0, "kind": "transition", **item}) + "\n")
                    elif kind == "health_snapshot":
                        fh.write(json.dumps({"t": time.monotonic() - self._t0, "kind": "snapshot", **item}) + "\n")
                    elif kind == "event":
                        fe.write(json.dumps({"t": time.monotonic() - self._t0, **item}) + "\n")
                    now = time.monotonic()
                    if now - last_flush > 0.25:
                        fcsv.flush(); fh.flush(); fe.flush()
                        last_flush = now
                    if self._stop.is_set() and self._q.empty():
                        break
        except Exception as e:
            self.error = f"writer: {e}"
            log.exception("recorder writer died")
