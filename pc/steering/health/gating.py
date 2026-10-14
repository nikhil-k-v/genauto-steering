"""
health/gating.py - "can I do X right now, and if not, exactly why?"

Every UI action is declared here with its requirements.  The UI calls
`can(action, ctx)` every frame: a failing requirement disables the control
and puts the reasons in its tooltip, and the Health panel highlights the
nodes involved when you hover the control (item 1B).  The controller calls
the same function before sending anything, so the rules cannot drift between
"what is greyed out" and "what is refused".

Requirements are small callables returning (ok, reason, node_ids).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from .. import protocol as P
from .model import HS_OK, NODE_BY_ID, HealthTree

ReqResult = Tuple[bool, str, List[str]]


@dataclass
class GateContext:
    tree: HealthTree
    ctrl_state: int = P.CS_REST
    flags: int = 0
    recording: bool = False
    playing: bool = False
    streaming: bool = False           # a trajectory/playback stream is active
    calib_stage: int = P.CAL_IDLE
    has_recording_selected: bool = False
    is_sim: bool = False

    @property
    def enabled(self) -> bool:
        return self.ctrl_state in P.CS_ENABLED

    @property
    def zeroed(self) -> bool:
        return bool(self.flags & P.TF_ZEROED)


@dataclass
class GateResult:
    ok: bool
    reasons: List[str] = field(default_factory=list)
    nodes: List[str] = field(default_factory=list)   # health nodes that are responsible

    @property
    def tooltip(self) -> str:
        return "" if self.ok else "Blocked: " + "; ".join(self.reasons)


Req = Callable[[GateContext], ReqResult]


def node(nid: str) -> Req:
    nd = NODE_BY_ID[nid]

    def f(ctx: GateContext) -> ReqResult:
        s = ctx.tree.nodes[nid]
        if s.state == HS_OK:
            return True, "", []
        return False, f"{nid} {nd.name}: {s.name.lower()}" + (f" ({s.reason})" if s.reason else ""), [nid]
    return f


def group(letter: str) -> Req:
    def f(ctx: GateContext) -> ReqResult:
        st, first = ctx.tree.group_state(letter)
        if st == HS_OK:
            return True, "", []
        s = ctx.tree.nodes[first]
        return False, f"{first} {NODE_BY_ID[first].name}: {s.name.lower()} ({s.reason})", [first]
    return f


def state_in(*states: int, what: str = "") -> Req:
    names = "/".join(P.CS_NAMES[s] for s in states)

    def f(ctx: GateContext) -> ReqResult:
        if ctx.ctrl_state in states:
            return True, "", []
        return False, what or f"needs {names}, motor is {P.CS_NAMES[ctx.ctrl_state]}", []
    return f


def state_not(*states: int, what: str = "") -> Req:
    def f(ctx: GateContext) -> ReqResult:
        if ctx.ctrl_state not in states:
            return True, "", []
        return False, what or f"not while {P.CS_NAMES[ctx.ctrl_state]}", []
    return f


def flag(bit: int, name: str, nid: Optional[str] = None) -> Req:
    def f(ctx: GateContext) -> ReqResult:
        if ctx.flags & bit:
            return True, "", []
        return False, f"{name} required", [nid] if nid else []
    return f


def not_busy(what: str = "") -> Req:
    def f(ctx: GateContext) -> ReqResult:
        if ctx.streaming:
            return False, what or "a trajectory / playback is streaming - stop it first", []
        if ctx.recording and what:
            return False, what, []
        return True, "", []
    return f


def need(cond: Callable[[GateContext], bool], reason: str) -> Req:
    def f(ctx: GateContext) -> ReqResult:
        return (True, "", []) if cond(ctx) else (False, reason, [])
    return f


LINK_UP = [node("D1"), node("D2"), node("D3"), node("D4"), node("D5"), node("D6")]
MOTOR_UP = [node("A1"), node("A3"), node("A4"), node("A5")]
SAFE = [node("B1"), node("B2")]

# action key -> (label, requirements)
ACTIONS: Dict[str, Tuple[str, List[Req]]] = {
    "connect":        ("Connect", []),
    "disconnect":     ("Disconnect", [node("D1")]),
    "enable":         ("Enable motor", LINK_UP + MOTOR_UP + SAFE + [node("C1"),
                        state_in(P.CS_REST, what="motor must be in REST (already enabled, or tripped?)")]),
    "disable":        ("Disable motor", [node("D1"), node("D5"), state_not(P.CS_REST, what="already resting")]),
    "clear_trip":     ("Clear trip", [node("D1"), node("D5"), state_in(P.CS_TRIPPED, what="no trip latched")]),
    "set_zero":       ("Set zero here", LINK_UP + [node("A4"), node("A5"),
                        state_not(P.CS_TRAJ, P.CS_TEST, P.CS_CALIB), not_busy()]),
    "freespin_on":    ("Free-spin", LINK_UP + MOTOR_UP + SAFE + [state_in(P.CS_REST, P.CS_HOLD, P.CS_JOY), not_busy()]),
    "freespin_off":   ("Re-grip", [node("D1"), node("D5"), state_in(P.CS_FREESPIN, what="not in free-spin")]),
    "set_gains":      ("Apply gains", [node("D1"), node("D5")]),
    "slider":         ("Setpoint slider", LINK_UP + [flag(P.TF_ZEROED, "zero must be set (Calibration panel)", "C2"),
                        state_in(P.CS_HOLD, what="slider only drives HOLD; enable the motor first"), not_busy()]),
    "hold_here":      ("Hold here", [node("D1"), node("D5"), state_in(P.CS_TRAJ, P.CS_JOY, P.CS_HOLD)]),
    "trajectory":     ("Run trajectory", LINK_UP + MOTOR_UP + SAFE + [node("C1"), node("C2"), node("C3"), node("A6"),
                        node("F1"), node("F2"), node("F5"),
                        state_in(P.CS_HOLD, what="motor must be enabled and holding (not free-spin / joystick / calibrating)"),
                        not_busy()]),
    "playback":       ("Play back recording", LINK_UP + MOTOR_UP + SAFE + [node("C1"), node("C2"), node("C3"), node("A6"),
                        node("F1"), node("F2"), node("F5"),
                        state_in(P.CS_HOLD, what="motor must be enabled and holding (not free-spin / joystick / calibrating)"),
                        not_busy(), need(lambda c: c.has_recording_selected, "select a recording")]),
    "tests":          ("Run tuning test", LINK_UP + MOTOR_UP + SAFE + [node("C1"), node("C2"), node("C3"), node("A6"),
                        node("F1"), node("F2"),
                        state_in(P.CS_HOLD, what="motor must be enabled and holding"), not_busy()]),
    "record":         ("Record", [node("D1"), node("D4"), node("F2"), need(lambda c: not c.recording, "already recording")]),
    "stop_record":    ("Stop recording", [need(lambda c: c.recording, "not recording")]),
    "record_freespin":("Record wheel motion (free-spin)", LINK_UP + [node("F2"), state_in(P.CS_FREESPIN,
                        what="turn on free-spin to record hand motion"), need(lambda c: not c.recording, "already recording")]),
    "calibrate":      ("Auto-calibrate end stops", LINK_UP + MOTOR_UP + SAFE + [node("C1"),
                        state_in(P.CS_REST, P.CS_HOLD, P.CS_FREESPIN, what="not while trajectory/test/calibration"), not_busy()]),
    "calib_abort":    ("Abort calibration", [node("D1"), state_in(P.CS_CALIB, what="not calibrating")]),
    "capture_limits": ("Capture end stop", LINK_UP + [node("A4"), node("A5"), state_not(P.CS_TRAJ, P.CS_TEST, P.CS_CALIB)]),
    "go_center_zero": ("Go to center & zero", LINK_UP + MOTOR_UP + SAFE + [state_in(P.CS_REST, P.CS_HOLD, P.CS_FREESPIN), not_busy()]),
    "joystick":       ("Joystick mode", LINK_UP + [node("E1"), state_in(P.CS_HOLD, P.CS_JOY)]),
    "can_scan":       ("CAN scan", [node("D1"), node("D5"), state_in(P.CS_REST, what="scan only in REST")]),
    "phone_capture":  ("Phone capture", [node("F3"), node("F4")]),
    "stop_stream":    ("Stop", [need(lambda c: c.streaming, "nothing streaming")]),
    "external_stream":("External setpoint stream (planner / remote)", LINK_UP + MOTOR_UP + SAFE + [node("C1"), node("C2"), node("C3"),
                        node("A6"), node("F5"), state_in(P.CS_HOLD, P.CS_TRAJ, what="motor must be enabled and holding/following"),
                        need(lambda c: not c.streaming, "a local trajectory / playback is streaming")]),
}


def can(action: str, ctx: GateContext) -> GateResult:
    label, reqs = ACTIONS[action]
    reasons, nodes = [], []
    for r in reqs:
        ok, reason, nids = r(ctx)
        if not ok:
            reasons.append(reason)
            nodes.extend(n for n in nids if n not in nodes)
    return GateResult(not reasons, reasons, nodes)


def affected_actions(node_id: str) -> List[str]:
    """Which actions list this node (used by the Health panel to explain impact)."""
    out = []
    ctx_probe = None  # static inspection: walk requirement closures
    for key, (label, reqs) in ACTIONS.items():
        for r in reqs:
            cell = getattr(r, "__closure__", None)
            if cell and any(getattr(c, "cell_contents", None) == node_id for c in cell):
                out.append(key)
                break
    return out
