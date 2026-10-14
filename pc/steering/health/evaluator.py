"""
health/evaluator.py - turns raw observations into a HealthTree, 10x per second.

Inputs (all optional; missing = UNKNOWN):
  * the latest firmware HealthPacket  -> A/B/C/E1 nodes (the Teensy decided)
  * LinkStats                         -> D nodes
  * recorder / store / server / UI timing -> F nodes
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
        bus.subscribe("health_fw", self._on_fw)
        bus.subscribe("link", self._on_link)

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
                put(nd.id, HS_UNKNOWN, "no firmware health" if fw is None else f"stale {fw_age:.1f}s")
                continue
            st = fw.node(idx)
            reason = self._fw_reason(nd.id, st, fw)
            put(nd.id, st, reason)

        # --- D: PC link ---
        ls = self._link
        if ls is None or not ls.port_open:
            err = (ls.port_error if ls else "") or "not connected"
            put("D1", HS_BLOCKED if not (ls and ls.port_error) else HS_FAIL, err)
            for nid in ("D2", "D3", "D4", "D5", "D6"):
                put(nid, HS_UNKNOWN, "port closed")
        else:
            put("D1", HS_OK, "open")
            b_age = ls.age("byte", now)
            just_opened = now - ls.opened_at < 1.5
            if b_age > BYTES_STALE_S:
                put("D2", HS_BLOCKED if just_opened else HS_FAIL, "no bytes" if ls.bytes_in == 0 else f"silent {b_age:.1f}s")
            else:
                put("D2", HS_OK, f"{ls.bytes_in} B")
            f_age = ls.age("frame", now)
            crc_rate = ls.crc_errors / max(1, ls.frames_ok + ls.crc_errors)
            if f_age > BYTES_STALE_S:
                put("D3", HS_UNKNOWN if just_opened else HS_FAIL, "no frames decode (baud/version?)" if ls.frames_ok == 0 else "frames stopped")
            elif crc_rate > 0.05:
                put("D3", HS_FAIL, f"CRC errors {crc_rate:.0%}", crc=ls.crc_errors)
            elif ls.drops and ls.drops / max(1, ls.frames_ok) > 0.02:
                put("D3", HS_BLOCKED, f"drops {ls.drops}", drops=ls.drops)
            else:
                put("D3", HS_OK, f"{ls.frames_hz:.0f} fps")
            t_age = ls.age("telemetry", now)
            put("D4", HS_OK if t_age < TELEMETRY_STALE_S else (HS_UNKNOWN if just_opened else HS_FAIL),
                f"{ls.telemetry_hz:.0f} Hz" if t_age < TELEMETRY_STALE_S else f"stale {min(t_age, 999):.1f}s")
            if not fw_fresh:
                put("D5", HS_UNKNOWN, "no firmware health yet")
            elif fw.pc_hb_age_ms == 0xFFFF:
                put("D5", HS_BLOCKED if just_opened else HS_FAIL, "Teensy never heard a heartbeat")
            elif fw.pc_hb_age_ms > 1000:
                put("D5", HS_FAIL, f"Teensy last heard us {fw.pc_hb_age_ms} ms ago")
            else:
                put("D5", HS_OK, f"round trip ok ({fw.pc_hb_age_ms} ms)")
            put("D6", HS_OK if fw_fresh else (HS_UNKNOWN if just_opened else HS_FAIL),
                "fresh" if fw_fresh else "no HealthPacket")

        # --- E2 bridge on USB ---
        if ls and ls.port_open and ls.age("bridge", now) < 1.0:
            put("E2", HS_OK, "bridge status seen")
        else:
            put("E2", HS_BLOCKED, "not seen (fine if Arduino not on USB)")

        # --- F ---
        r = self.recorder_status
        if not r["ok"]:
            put("F1", HS_FAIL, r["error"] or "recorder error")
        elif r["active"] and r["dropped"]:
            put("F1", HS_FAIL, f"dropping samples ({r['dropped']})")
        else:
            put("F1", HS_OK, "recording" if r["active"] else "idle")
        s = self.store_status
        put("F2", HS_UNKNOWN if s["ok"] is None else HS_OK if s["ok"] else HS_FAIL, s["error"] or ("ok" if s["ok"] else ""))
        sv = self.server_status
        put("F3", HS_FAIL if sv["error"] else HS_OK if sv["running"] else HS_BLOCKED,
            sv["error"] or (f"{sv['clients']} client(s)" if sv["running"] else "not running"))
        ph = self.phone_status
        if not ph["connected"]:
            put("F4", HS_BLOCKED, "no phone")
        elif ph["jitter_ms"] is not None and ph["jitter_ms"] > 50:
            put("F4", HS_FAIL, f"clock jitter {ph['jitter_ms']:.0f} ms")
        else:
            put("F4", HS_OK, f"offset {ph['offset_ms']:.0f} ms" if ph["offset_ms"] is not None else "synced")
        ui_age = now - self._ui_frame_t
        if not self.ui_present:
            put("F5", HS_OK, "headless")
        elif ui_age > UI_STALL_S:
            put("F5", HS_FAIL, f"UI stalled {ui_age:.1f}s" + (f" - {self._last_ui_error}" if self._last_ui_error else ""))
        elif self._ui_frame_dt > UI_SLOW_S:
            put("F5", HS_BLOCKED, f"slow frame {self._ui_frame_dt * 1000:.0f} ms")
        else:
            put("F5", HS_OK, f"{self._ui_frame_dt * 1000:.0f} ms/frame")

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
    def _fw_reason(nid: str, st: int, fw: P.HealthPacket) -> str:
        if nid == "A1":
            return ["active", "warning", "passive", "BUS-OFF"][min(fw.can_bus_state, 3)] + f" TEC={fw.can_tec} REC={fw.can_rec}"
        if nid == "A2":
            return f"TEC={fw.can_tec}"
        if nid == "A3":
            return f"{fw.can_rx_motor_hz + fw.can_rx_other_hz} Hz on bus"
        if nid == "A4":
            if fw.motor_age_ms == 0xFFFF:
                return "motor never replied"
            return f"{fw.can_rx_motor_hz} Hz, last {fw.motor_age_ms} ms ago"
        if nid == "B1":
            return "ARMED" if st == HS_OK else "IDLE (switch open)"
        if nid == "B2":
            return "none" if st == HS_OK else P.TRIP_NAMES.get(fw.trip_code, str(fw.trip_code))
        if nid == "C1":
            return f"{fw.loop_hz} Hz, {fw.isr_overruns} overruns"
        if nid == "C3":
            return P.CAL_NAMES.get(fw.calib_stage, "")
        if nid == "E1":
            return "never" if fw.bridge_age_ms == 0xFFFF else f"last {fw.bridge_age_ms} ms ago"
        return ""
