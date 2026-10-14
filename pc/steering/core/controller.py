"""
core/controller.py - the one place that turns intentions into packets.

Every public method:
  1. builds a GateContext from the latest telemetry/health,
  2. asks gating.can(action) - refuses with the exact reasons if not allowed,
  3. logs the action to the bus ("ui_action", also written into any active
     recording's events.jsonl),
  4. sends the packet(s) and/or starts the stream / recorder.

The UI never sends packets itself.  The server hub calls the same methods, so
a phone or another device gets the same guarantees.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from .. import protocol as P
from ..bus import Bus
from ..control.streamer import Streamer
from ..control.trajectories import Trajectory, from_recording, make, GENERATOR_PARAMS
from ..data.analysis import load_csv
from ..data.recorder import Recorder
from ..data.store import Recording, Store
from ..health.gating import GateContext, GateResult, can
from ..health.model import HealthTree, empty_tree
from ..link import Link

log = logging.getLogger(__name__)


class ActionRefused(Exception):
    def __init__(self, action: str, result: GateResult):
        super().__init__(f"{action}: " + "; ".join(result.reasons))
        self.action, self.result = action, result


@dataclass
class LiveState:
    telemetry: Optional[P.TelemetryPacket] = None
    telemetry_t: float = 0.0
    health_fw: Optional[P.HealthPacket] = None
    config: Optional[P.ConfigEchoPacket] = None
    tree: HealthTree = field(default_factory=empty_tree)
    last_event: Optional[P.EventPacket] = None
    last_rejection: str = ""
    last_rejection_t: float = 0.0
    can_scan_ids: list = field(default_factory=list)
    joystick: Optional[P.JoystickPacket] = None
    pending_gains: Optional[dict] = None     # gains sent but not yet echoed back

    @property
    def ctrl_state(self) -> int:
        return self.telemetry.ctrl_state if self.telemetry else P.CS_REST

    @property
    def flags(self) -> int:
        return self.telemetry.flags if self.telemetry else 0

    @property
    def position(self) -> float:
        return self.telemetry.position_deg if self.telemetry else 0.0


class Controller:
    def __init__(self, bus: Bus, link: Link, store: Store, recorder: Recorder, collection_getter=lambda: "default"):
        self.bus, self.link, self.store, self.recorder = bus, link, store, recorder
        self.streamer = Streamer(bus, link)
        self.live = LiveState()
        self.selected_recording: Optional[Recording] = None
        self.collection = collection_getter
        self._lock = threading.Lock()
        bus.subscribe("telemetry", self._on_telemetry)
        bus.subscribe("health_fw", lambda p: setattr(self.live, "health_fw", p))
        bus.subscribe("health", lambda t: setattr(self.live, "tree", t))
        bus.subscribe("config", self._on_config)
        bus.subscribe("event", self._on_event)
        bus.subscribe("can_scan", lambda p: setattr(self.live, "can_scan_ids", list(p.ids[: p.count])))
        bus.subscribe("joystick", lambda p: setattr(self.live, "joystick", p))

    # ---- inputs --------------------------------------------------------------------------
    def _on_telemetry(self, t):
        self.live.telemetry, self.live.telemetry_t = t, time.monotonic()

    def _on_config(self, c):
        self.live.config = c
        pg = self.live.pending_gains
        if pg and all(abs(getattr(c, k) - v) < 1e-3 for k, v in pg.items()):
            self.live.pending_gains = None

    def _on_event(self, e: P.EventPacket):
        self.live.last_event = e
        if e.code == P.EV_CMD_REJECTED:
            self.live.last_rejection = f"Teensy refused {P.CMD_NAMES.get(e.arg, hex(e.arg))}: {e.text_str}"
            self.live.last_rejection_t = time.monotonic()
            log.warning(self.live.last_rejection)
        elif e.code == P.EV_TRIP:
            log.error("TRIP %s: %s", P.TRIP_NAMES.get(e.arg, e.arg), e.text_str)

    # ---- gating -----------------------------------------------------------------------------
    def context(self) -> GateContext:
        return GateContext(tree=self.live.tree, ctrl_state=self.live.ctrl_state, flags=self.live.flags,
                           recording=self.recorder.active, streaming=self.streamer.active,
                           calib_stage=self.live.health_fw.calib_stage if self.live.health_fw else P.CAL_IDLE,
                           has_recording_selected=self.selected_recording is not None,
                           is_sim=getattr(self.link.transport, "name", "").startswith("sim"))

    def can(self, action: str) -> GateResult:
        return can(action, self.context())

    def _gate(self, action: str, **log_fields):
        r = self.can(action)
        self.bus.publish("ui_action", {"action": action, "allowed": r.ok, "reasons": r.reasons, **log_fields})
        if not r.ok:
            log.info("refused %s: %s", action, "; ".join(r.reasons))
            raise ActionRefused(action, r)

    # ---- simple commands ----------------------------------------------------------------------
    def enable(self):          self._gate("enable");       self.link.send(P.command(P.CMD_ENABLE))
    def disable(self):         self._gate("disable");      self.stop_all(); self.link.send(P.command(P.CMD_DISABLE))
    def clear_trip(self):      self._gate("clear_trip");   self.link.send(P.command(P.CMD_CLEAR_TRIP))
    def set_zero(self):        self._gate("set_zero");     self.link.send(P.command(P.CMD_SET_ZERO))
    def freespin_on(self):     self._gate("freespin_on");  self.link.send(P.command(P.CMD_FREESPIN_ON))
    def freespin_off(self):    self._gate("freespin_off"); self.link.send(P.command(P.CMD_FREESPIN_OFF))
    def hold_here(self):       self._gate("hold_here");    self.link.send(P.command(P.CMD_HOLD_HERE))
    def calib_abort(self):     self._gate("calib_abort");  self.link.send(P.command(P.CMD_CALIB_ABORT))
    def capture_left(self):    self._gate("capture_limits"); self.link.send(P.command(P.CMD_CAPTURE_LEFT))
    def capture_right(self):   self._gate("capture_limits"); self.link.send(P.command(P.CMD_CAPTURE_RIGHT))
    def go_center_zero(self):  self._gate("go_center_zero"); self.link.send(P.command(P.CMD_GO_CENTER_ZERO))
    def can_scan(self, first=1, last=127):
        self._gate("can_scan"); self.live.can_scan_ids = []; self.link.send(P.command(P.CMD_CAN_SCAN, first, float(last)))
    def request_config(self):  self.link.send(P.command(P.CMD_REQ_CONFIG))
    def set_motor_id(self, cid: int):
        self._gate("can_scan"); self.link.send(P.command(P.CMD_SET_MOTOR_ID, cid))

    def emergency_rest(self, why: str = "user"):
        """Not gated on purpose: always sends DISABLE and stops everything."""
        self.bus.publish("ui_action", {"action": "emergency_rest", "allowed": True, "why": why})
        self.stop_all()
        self.link.send(P.command(P.CMD_DISABLE))

    def set_gains(self, kp: float, kd: float, ki: float, tff: float):
        self._gate("set_gains", kp=kp, kd=kd, ki=ki, tff=tff)
        self.live.pending_gains = {"kp": kp, "kd": kd, "ki": ki, "tff_Nm": tff}
        self.link.send(P.gains(kp, kd, ki, tff))

    def set_limits(self, left: float, right: float):
        self._gate("capture_limits", left=left, right=right)
        self.link.send(P.limits(left, right))

    def slider(self, pos_deg: float):
        """Direct setpoint in HOLD. Sent as a one-shot setpoint stream element in HOLD mode:
        the firmware slews it, so the slider can never jump the wheel."""
        r = self.can("slider")
        if not r.ok:
            return r
        self.link.send(P.mode_request(P.MODE_HOLD, sticky=True))
        # HOLD takes setpoint from sp_target; a SetpointPacket in HOLD updates sp_target but
        # does not switch to TRAJ because mode_req is sticky HOLD.
        self.link.send(P.setpoint(0, pos_deg))
        return r

    def external_setpoint(self, pos_deg: float, vel_ff: float = 0.0) -> GateResult:
        """Live setpoint from an external planner (ROS2/Orin via the hub) or a remote
        device.  Same gating as a trajectory; the firmware falls back to HOLD if the
        stream stops for 250 ms, so a dead planner never leaves a stale command."""
        r = self.can("external_stream")
        if not r.ok:
            return r
        if self.live.ctrl_state != P.CS_TRAJ:
            self.link.send(P.mode_request(P.MODE_TRAJ, sticky=True))
        self._ext_seq = (getattr(self, "_ext_seq", 0) + 1) & 0xFFFF
        self.bus.publish("stream_target", pos_deg)
        self.link.send(P.setpoint(self._ext_seq, pos_deg, vel_ff, int(time.monotonic() * 1000)))
        return r

    def joystick_mode(self, on: bool):
        self._gate("joystick")
        self.link.send(P.mode_request(P.MODE_JOY if on else P.MODE_HOLD, sticky=True))

    def calibrate(self):
        self._gate("calibrate")
        self.link.send(P.command(P.CMD_CALIB_START))
        self._auto_record("calibration", "autocal")

    # ---- recording ---------------------------------------------------------------------------
    def record_start(self, name: str = "manual", kind: str = "manual", notes: str = "", tags=()):
        action = "record_freespin" if kind == "freespin" else "record"
        self._gate(action, name=name)
        return self.recorder.start(kind, name, self.collection(), notes=notes, tags=tags)

    def record_stop(self):
        self._gate("stop_record")
        return self.recorder.stop()

    def _auto_record(self, kind: str, name: str, parent: Optional[Recording] = None, notes: str = ""):
        if self.recorder.active:
            self.recorder.stop()
        return self.recorder.start(kind, name, self.collection(), parent=parent, notes=notes)

    # ---- streaming: trajectories, playback, tests --------------------------------------------------
    def _abort_check(self) -> Optional[str]:
        t = self.live.telemetry
        if t is None or time.monotonic() - self.live.telemetry_t > 0.3:
            return "telemetry lost"
        if t.ctrl_state not in (P.CS_HOLD, P.CS_TRAJ):
            return f"motor left TRAJ/HOLD ({P.CS_NAMES.get(t.ctrl_state)})"
        tree = self.live.tree
        for nid in ("B1", "B2", "A4", "D5"):
            if tree.nodes[nid].state == P.HS_FAIL or (nid in ("B1", "B2") and tree.nodes[nid].state == P.HS_BLOCKED):
                return f"{nid} {tree.nodes[nid].reason}"
        return None

    def _run(self, traj: Trajectory, kind: str, name: str, parent: Optional[Recording] = None, notes: str = ""):
        cfg = self.live.config
        lo, hi = (-180.0, 180.0)
        if cfg and cfg.limits_valid:
            lo, hi = cfg.limit_left_deg + 3.0, cfg.limit_right_deg - 3.0
        traj = traj.clipped(lo, hi).offset(self.live.position, blend_s=0.6)
        rec = self._auto_record(kind, name, parent, notes)
        self.streamer.on_done = lambda ok: self.recorder.stop()
        self.streamer.start(traj, self._abort_check)
        return rec

    def run_generator(self, gen: str, **params):
        self._gate("trajectory", generator=gen, params=params)
        p = dict(GENERATOR_PARAMS[gen]); p.update(params)
        return self._run(make(gen, **p), "trajectory", gen, notes=str(p))

    def run_trajectory(self, traj: Trajectory, name: str, notes: str = ""):
        self._gate("trajectory", name=name)
        return self._run(traj, "trajectory", name, notes=notes)

    def play_recording(self, rec: Optional[Recording] = None, speed: float = 1.0):
        rec = rec or self.selected_recording
        self.selected_recording = rec
        self._gate("playback", uid=rec.uid if rec else None, speed=speed)
        d = load_csv(rec.csv)
        src = d["position_deg"]
        traj = from_recording(d["t_s"], src, name=rec.name, uid=rec.uid, speed=speed)
        if traj.t.size == 0:
            raise ValueError("recording has no usable position samples")
        return self._run(traj, "playback", rec.name, parent=rec, notes=f"playback of {rec.uid} x{speed}")

    def run_test(self, test_type: int, amplitude_deg: float, duration_s: float, param: float):
        self._gate("tests", test=test_type, amplitude=amplitude_deg, duration=duration_s, param=param)
        kind = "test_step" if test_type == P.TEST_STEP else "test_relay"
        self._auto_record(kind, P.TEST_NAMES[test_type].lower(),
                          notes=f"amp={amplitude_deg} dur={duration_s} param={param}")
        self.link.send(P.test_start(test_type, amplitude_deg, duration_s, param))
        # the recorder is stopped by App when EV_TEST_DONE arrives (or after duration + 3 s)
        self._test_deadline = time.monotonic() + duration_s + max(param, 1.0) + 3.0

    def stop_all(self):
        if self.streamer.active:
            self.streamer.stop()
        if self.recorder.active:
            self.recorder.stop()

    _test_deadline: float = 0.0

    def tick(self):
        """Call ~10 Hz from App: ends firmware-driven recordings (tests, calibration)
        once the Teensy has left that state."""
        rec = self.recorder.rec
        if not (self.recorder.active and rec):
            return
        cs = self.live.ctrl_state
        started_s = time.monotonic() - self.recorder._t0
        if rec.kind.startswith("test_"):
            if (started_s > 0.5 and cs != P.CS_TEST) or time.monotonic() > self._test_deadline:
                self.recorder.stop()
        elif rec.kind == "calibration":
            if started_s > 0.5 and cs != P.CS_CALIB:
                self.recorder.stop()
