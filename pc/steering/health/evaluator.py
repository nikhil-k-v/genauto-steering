"""
health/evaluator.py - turns raw observations into a HealthTree, 10x per second.

Inputs (all optional; missing = UNKNOWN):
  * the latest firmware HealthPacket  -> M/S/T nodes + C5 (the Teensy decided)
  * LinkStats                         -> C nodes
  * recorder / store / server / UI timing -> D nodes
Outputs:
  * bus "health"            : HealthTree (every evaluation)
  * bus "health_transition" : dict per node change (what, from, to, reason)
  * a JSONL health log via HealthLogger (data/logs/health-YYYY-MM-DD.jsonl):
    one line per transition, plus a full snapshot every SNAPSHOT_S.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Optional

from .. import protocol as P
from ..bus import Bus
from .model import (FW_NODES, HS_BLOCKED, HS_FAIL, HS_OK, HS_UNKNOWN, NODES, STATE_NAMES, HealthTree,
                    NodeState, empty_tree)

log = logging.getLogger(__name__)

TELEMETRY_STALE_S = 0.10
HEALTH_STALE_S = 0.50
BYTES_STALE_S = 0.50
UI_SLOW_S = 0.25
UI_STALL_S = 1.00


class HealthLogger:
    SNAPSHOT_S = 10.0

    def __init__(self, log_dir: Path):
        self.dir = Path(log_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._fh = None
        self._day = None
        self._last_snapshot = 0.0

    def _file(self):
        day = time.strftime("%Y-%m-%d")
        if day != self._day:
            if self._fh:
                self._fh.close()
            self._fh = open(self.dir / f"health-{day}.jsonl", "a", buffering=1)
            self._day = day
        return self._fh

    def write(self, kind: str, payload: dict):
        try:
            self._file().write(json.dumps({"t": time.time(), "kind": kind, **payload}) + "\n")
        except Exception:
            log.exception("health log write failed")

    def maybe_snapshot(self, tree: HealthTree):
        now = time.time()
        if now - self._last_snapshot >= self.SNAPSHOT_S:
            self._last_snapshot = now
            self.write("snapshot", tree.to_dict())

    def close(self):
        if self._fh:
            self._fh.close()
            self._fh = None


class HealthEvaluator:
    def __init__(self, bus: Bus, logger: Optional[HealthLogger] = None):
        self.bus = bus
        self.logger = logger
        self.tree = empty_tree()
        self._fw: Optional[P.HealthPacket] = None
        self._fw_t = 0.0
        self._link = None
        self._ui_frame_t = time.monotonic()
        self._ui_frame_dt = 0.0
        self.ui_present = False
        self._last_ui_error = ""
        self.recorder_status = {"active": False, "dropped": 0, "ok": True, "error": ""}
        self.store_status = {"ok": None, "error": ""}
        self.server_status = {"running": False, "clients": 0, "error": ""}
        self.phone_status = {"connected": False, "offset_ms": None, "jitter_ms": None, "capturing": False}
        self._cfg = None              # ConfigEchoPacket: motor id, zeroed, limits valid
        self._current_A = 0.0
        bus.subscribe("health_fw", self._on_fw)
        bus.subscribe("link", self._on_link)
        bus.subscribe("config", lambda c: setattr(self, "_cfg", c))
        bus.subscribe("telemetry", lambda t: setattr(self, "_current_A", t.current_A))

    # ---- inputs -------------------------------------------------------------------
    def _on_fw(self, pkt):
        self._fw, self._fw_t = pkt, time.monotonic()

    def _on_link(self, stats):
        self._link = stats

    def note_ui_frame(self):
        self.ui_present = True
        now = time.monotonic()
        self._ui_frame_dt = now - self._ui_frame_t
        self._ui_frame_t = now

    def ui_alive(self) -> bool:
        return (not self.ui_present) or (time.monotonic() - self._ui_frame_t) < UI_STALL_S

    def note_ui_error(self, text: str):
        self._last_ui_error = text

    # ---- evaluation ---------------------------------------------------------------
    def evaluate(self) -> HealthTree:
        now = time.monotonic()
        new = {}

        def put(nid, state, reason="", **detail):
            new[nid] = (state, reason, detail)

        # --- firmware nodes ---
        fw, fw_age = self._fw, (now - self._fw_t if self._fw else 1e9)
        fw_fresh = fw is not None and fw_age < HEALTH_STALE_S
        for idx, nd in FW_NODES.items():
            if not fw_fresh:
                put(nd.id, HS_UNKNOWN, "no health report from the Teensy yet" if fw is None
                    else f"Teensy health report is {fw_age:.1f} s old")
                continue
            st = fw.node(idx)
            reason = self._fw_reason(nd.id, st, fw, self._cfg, self._current_A)
            put(nd.id, st, reason)

        # --- C: PC link ---
        ls = self._link
        if ls is None or not ls.port_open:
            err = (ls.port_error if ls else "") or "not connected: pick a port and press Connect"
            put("C1", HS_BLOCKED if not (ls and ls.port_error) else HS_FAIL,
                err if not (ls and ls.port_error) else f"USB port error: {err}")
            for nid in ("C2", "C3", "C4", "C5", "C6"):
                put(nid, HS_UNKNOWN, "USB port not open")
        else:
            put("C1", HS_OK, "USB port open")
            b_age = ls.age("byte", now)
            just_opened = now - ls.opened_at < 1.5
            if b_age > BYTES_STALE_S:
                put("C2", HS_BLOCKED if just_opened else HS_FAIL,
                    "USB: no bytes received yet" if ls.bytes_in == 0 else f"USB: nothing received for {b_age:.1f} s")
            else:
                put("C2", HS_OK, f"{ls.bytes_in:,} bytes received")
            f_age = ls.age("frame", now)
            crc_rate = ls.crc_errors / max(1, ls.frames_ok + ls.crc_errors)
            if f_age > BYTES_STALE_S:
                put("C3", HS_UNKNOWN if just_opened else HS_FAIL,
                    "USB: bytes arrive but none form a valid frame (protocol version?)" if ls.frames_ok == 0
                    else f"USB: no valid frame for {f_age:.1f} s")
            elif crc_rate > 0.05:
                put("C3", HS_FAIL, f"USB: {crc_rate:.0%} of frames fail the CRC check (cable?)", crc=ls.crc_errors)
            elif ls.drops and ls.drops / max(1, ls.frames_ok) > 0.02:
                put("C3", HS_BLOCKED, f"USB: {ls.drops} frames lost in transit", drops=ls.drops)
            else:
                put("C3", HS_OK, f"{ls.frames_hz:.0f} frames/s")
            t_age = ls.age("telemetry", now)
            put("C4", HS_OK if t_age < TELEMETRY_STALE_S else (HS_UNKNOWN if just_opened else HS_FAIL),
                f"{ls.telemetry_hz:.0f} Hz" if t_age < TELEMETRY_STALE_S
                else f"no telemetry from the Teensy for {min(t_age, 999):.1f} s")
            if not fw_fresh:
                put("C5", HS_UNKNOWN, "no health report from the Teensy yet")
            elif fw.pc_hb_age_ms == 0xFFFF:
                put("C5", HS_BLOCKED if just_opened else HS_FAIL, "Teensy has not heard from the laptop at all")
            elif fw.pc_hb_age_ms > 1000:
                put("C5", HS_FAIL, f"Teensy last heard the laptop {fw.pc_hb_age_ms / 1000:.1f} s ago")
            else:
                put("C5", HS_OK, f"Teensy hears the laptop ({fw.pc_hb_age_ms} ms)")
            put("C6", HS_OK if fw_fresh else (HS_UNKNOWN if just_opened else HS_FAIL),
                "fresh" if fw_fresh else "no health report from the Teensy for over 0.5 s")

        # --- D data & services ---
        r = self.recorder_status
        if not r["ok"]:
            put("D1", HS_FAIL, f"Recorder stopped: {r['error']}" if r["error"] else "Recorder stopped with an error")
        elif r["active"] and r["dropped"]:
            put("D1", HS_FAIL, f"Recorder dropping samples ({r['dropped']} lost, disk too slow?)")
        else:
            put("D1", HS_OK, "recording" if r["active"] else "idle")
        s = self.store_status
        put("D2", HS_UNKNOWN if s["ok"] is None else HS_OK if s["ok"] else HS_FAIL,
            (f"Can't write the data folder: {s['error']}" if s["error"] else "") or ("writable" if s["ok"] else ""))
        sv = self.server_status
        put("D3", HS_FAIL if sv["error"] else HS_OK if sv["running"] else HS_BLOCKED,
            f"Web hub failed: {sv['error']}" if sv["error"] else
            (f"{sv['clients']} browser(s) connected" if sv["running"] else "web hub off"))
        ph = self.phone_status
        if not ph["connected"]:
            put("D4", HS_BLOCKED, "no phone connected")
        elif ph["jitter_ms"] is not None and ph["jitter_ms"] > 50:
            put("D4", HS_FAIL, f"Phone clock unstable (jitter {ph['jitter_ms']:.0f} ms)")
        else:
            put("D4", HS_OK, f"clock offset {ph['offset_ms']:.0f} ms" if ph["offset_ms"] is not None else "synced")
        ui_age = now - self._ui_frame_t
        if not self.ui_present:
            put("D5", HS_OK, "no UI (headless)")
        elif ui_age > UI_STALL_S:
            put("D5", HS_FAIL, f"UI frozen for {ui_age:.1f} s" + (f": {self._last_ui_error}" if self._last_ui_error else ""))
        elif self._ui_frame_dt > UI_SLOW_S:
            put("D5", HS_BLOCKED, f"UI slow: one frame took {self._ui_frame_dt * 1000:.0f} ms")
        else:
            put("D5", HS_OK, f"{self._ui_frame_dt * 1000:.0f} ms per frame")

        # --- commit, detect transitions ---
        changed = []
        for nd in NODES:
            st, reason, detail = new.get(nd.id, (HS_UNKNOWN, "not evaluated", {}))
            cur = self.tree.nodes[nd.id]
            if cur.state != st:
                changed.append({"node": nd.id, "name": nd.name, "from": STATE_NAMES[cur.state],
                                "to": STATE_NAMES[st], "reason": reason})
                cur.since = time.time()
            cur.state, cur.reason, cur.detail = st, reason, detail
        self.tree.t = time.time()
        for ch in changed:
            self.bus.publish("health_transition", ch)
            if self.logger:
                self.logger.write("transition", ch)
            (log.warning if ch["to"] in ("FAIL",) else log.info)("health %s %s -> %s (%s)",
                                                                  ch["node"], ch["from"], ch["to"], ch["reason"])
        if self.logger:
            self.logger.maybe_snapshot(self.tree)
        self.bus.publish("health", self.tree)
        return self.tree

    @staticmethod
    def _fw_reason(nid: str, st: int, fw: P.HealthPacket, cfg=None, current_A: float = 0.0) -> str:
        """A plain sentence for a firmware-decided node: what is physically going on, with the number."""
        ok = st == HS_OK
        mid = f"id {cfg.motor_id}" if cfg else "the configured id"
        if st == HS_UNKNOWN:
            return {"M5": "no motor data yet", "M6": "no motor data yet", "T4": "screen not checked yet"}.get(nid, "no data yet")
        if nid == "M1":
            if fw.can_bus_state >= 3:
                return "CAN bus-off: the transceiver sees no valid bus (wiring, power, termination)"
            if fw.can_bus_state == 2:
                return f"CAN error-passive: too many errors (TX {fw.can_tec}, RX {fw.can_rec})"
            if not ok or fw.can_bus_state == 1:
                return f"CAN errors high (TX {fw.can_tec}, RX {fw.can_rec}): noise or termination"
            return f"CAN ok, errors TX {fw.can_tec} RX {fw.can_rec}"
        if nid == "M2":
            if ok:
                return "frames acknowledged"
            return f"CAN TX: frames not acknowledged by anyone (error count {fw.can_tec})"
        if nid == "M3":
            hz = fw.can_rx_motor_hz + fw.can_rx_other_hz
            return f"{hz} frames/s received" if ok or hz else "CAN RX: no frames received (0 Hz)"
        if nid == "M4":
            if fw.motor_age_ms == 0xFFFF:
                return f"Motor has never replied on CAN ({mid}): off, unpowered or wrong id"
            if ok:
                return f"{fw.can_rx_motor_hz} replies/s"
            if fw.motor_age_ms > 200:
                return f"Motor stopped replying on CAN {fw.motor_age_ms / 1000:.1f} s ago ({mid})"
            if st == HS_BLOCKED:
                return f"Motor replies only when commanded; last {fw.motor_age_ms} ms ago"
            return f"Motor replying at only {fw.can_rx_motor_hz} Hz (expected ~1000)"
        if nid == "M5":
            return "values decode and change" if ok else "Motor angle is NaN or has repeated the same value 200 times"
        if nid == "M6":
            if ok:
                return f"{abs(current_A):.1f} A"
            return (f"Motor current {abs(current_A):.1f} A, over the cut-out" if st == HS_FAIL
                    else f"Motor current {abs(current_A):.1f} A, close to the cut-out")
        if nid == "S1":
            return "idle switch off (armed)" if ok else "Idle switch on: the motor is not allowed to have torque"
        if nid == "S2":
            if ok:
                return "no safety stop"
            from ..words import TRIP
            return f"Safety stop: {TRIP.get(fw.trip_code, f'code {fw.trip_code}')}"
        if nid == "T1":
            if ok:
                return f"{fw.loop_hz} Hz, {fw.isr_overruns} overruns"
            return f"Control loop at {fw.loop_hz} Hz with {fw.isr_overruns} overruns (expected 1000 Hz, 0)"
        if nid == "T2":
            if ok:
                return "0° and end stops set"
            if cfg is not None:
                missing = [w for w, have in (("0°", cfg.zeroed), ("end stops", cfg.limits_valid)) if not have]
                if missing:
                    return f"Not calibrated: no {' and no '.join(missing)}"
            return "Not calibrated: 0° or end stops missing"
        if nid == "T3":
            from ..words import CAL_STAGE
            if st == HS_FAIL:
                return "Last calibration failed"
            if st == HS_BLOCKED:
                return f"Calibration running: {CAL_STAGE.get(fw.calib_stage, '')}"
            return "idle" if fw.calib_stage in (P.CAL_IDLE,) else CAL_STAGE.get(fw.calib_stage, "")
        if nid == "T4":
            return "screen answering" if ok else "no OLED screen on I2C (optional)"
        return ""
