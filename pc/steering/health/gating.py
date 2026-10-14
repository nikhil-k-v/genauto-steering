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
from ..words import STATE, VERDICT
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
        return "" if self.ok else "Not available: " + "; ".join(self.reasons)


Req = Callable[[GateContext], ReqResult]


def node(nid: str) -> Req:
    nd = NODE_BY_ID[nid]

    def f(ctx: GateContext) -> ReqResult:
        s = ctx.tree.nodes[nid]
        if s.state == HS_OK:
            return True, "", []
        return False, s.reason or f"{nd.name}: {VERDICT[s.state]}", [nid]
    return f


def group(letter: str) -> Req:
    def f(ctx: GateContext) -> ReqResult:
        st, first = ctx.tree.group_state(letter)
        if st == HS_OK:
            return True, "", []
        s = ctx.tree.nodes[first]
        return False, s.reason or f"{NODE_BY_ID[first].name}: {VERDICT[s.state]}", [first]
    return f


def state_in(*states: int, what: str = "") -> Req:
    def f(ctx: GateContext) -> ReqResult:
        if ctx.ctrl_state in states:
            return True, "", []
        return False, what or f"not while {STATE[ctx.ctrl_state].lower()}", []
    return f


def state_not(*states: int, what: str = "") -> Req:
    def f(ctx: GateContext) -> ReqResult:
        if ctx.ctrl_state not in states:
            return True, "", []
        return False, what or f"not while {STATE[ctx.ctrl_state].lower()}", []
    return f


def flag(bit: int, name: str, nid: Optional[str] = None) -> Req:
    def f(ctx: GateContext) -> ReqResult:
        if ctx.flags & bit:
            return True, "", []
        return False, name, [nid] if nid else []
    return f


def not_busy(what: str = "") -> Req:
    def f(ctx: GateContext) -> ReqResult:
        if ctx.streaming:
            return False, what or "a playback or waveform is running: stop it first", []
        if ctx.recording and what:
            return False, what, []
        return True, "", []
    return f


def need(cond: Callable[[GateContext], bool], reason: str) -> Req:
    def f(ctx: GateContext) -> ReqResult:
        return (True, "", []) if cond(ctx) else (False, reason, [])
    return f


LINK_UP = [node("C1"), node("C2"), node("C3"), node("C4"), node("C5"), node("C6")]
MOTOR_UP = [node("M1"), node("M3"), node("M4"), node("M5")]
SAFE = [node("S1"), node("S2")]

IN_POSITION_CONTROL = "only in Position control: press Position control first"
MOTOR_IS_ON = "the motor is already on"

# action key -> (label, requirements).  Labels are the button names the operator sees.
ACTIONS: Dict[str, Tuple[str, List[Req]]] = {
    "connect":        ("Connect", []),
    "disconnect":     ("Disconnect", [node("C1")]),
    "enable":         ("Position control (turn the motor on)", LINK_UP + MOTOR_UP + SAFE + [node("T1"),
                        state_in(P.CS_REST, what=MOTOR_IS_ON)]),
    "disable":        ("Stop motor", [node("C1"), node("C5"), state_not(P.CS_REST, what="the motor is already off")]),
    "clear_trip":     ("Reset safety stop", [node("C1"), node("C5"), state_in(P.CS_TRIPPED, what="there is no safety stop to reset")]),
    "set_zero":       ("Set 0° at the current angle", LINK_UP + [node("M4"), node("M5"),
                        state_not(P.CS_TRAJ, P.CS_TEST, P.CS_CALIB, what="not while following setpoints, testing or calibrating"),
                        not_busy()]),
    "freespin_on":    ("Free-spin", LINK_UP + MOTOR_UP + SAFE + [state_in(P.CS_REST, P.CS_HOLD,
                        what="only from Motor off or Position control"), not_busy()]),
    "freespin_off":   ("Position control (grip again after free-spin)", [node("C1"), node("C5"),
                        state_in(P.CS_FREESPIN, what="not in free-spin")]),
    "set_gains":      ("Send gains", [node("C1"), node("C5")]),
    "slider":         ("Setpoint slider", LINK_UP + [flag(P.TF_ZEROED, "0° is not set: run Calibrate first", "T2"),
                        state_in(P.CS_HOLD, what=IN_POSITION_CONTROL), not_busy()]),
    "move_to_zero":   ("Move to 0°", LINK_UP + [flag(P.TF_ZEROED, "0° is not set: run Calibrate first", "T2"),
                        state_in(P.CS_HOLD, what=IN_POSITION_CONTROL), not_busy()]),
    "hold_here":      ("Position control (stop following, keep this angle)", [node("C1"), node("C5"),
                        state_in(P.CS_TRAJ, P.CS_HOLD, what="nothing to stop")]),
    "trajectory":     ("Run waveform", LINK_UP + MOTOR_UP + SAFE + [node("T1"), node("T2"), node("T3"), node("M6"),
                        node("D1"), node("D2"), node("D5"),
                        state_in(P.CS_HOLD, what=IN_POSITION_CONTROL),
                        not_busy()]),
    "playback":       ("Play on motor", LINK_UP + MOTOR_UP + SAFE + [node("T1"), node("T2"), node("T3"), node("M6"),
                        node("D1"), node("D2"), node("D5"),
                        state_in(P.CS_HOLD, what=IN_POSITION_CONTROL),
                        not_busy(), need(lambda c: c.has_recording_selected, "pick a recording first")]),
    "tests":          ("Run step or relay test", LINK_UP + MOTOR_UP + SAFE + [node("T1"), node("T2"), node("T3"), node("M6"),
                        node("D1"), node("D2"),
                        state_in(P.CS_HOLD, what=IN_POSITION_CONTROL), not_busy()]),
    "record":         ("Record", [node("C1"), node("C4"), node("D2"), need(lambda c: not c.recording, "already recording")]),
    "stop_record":    ("Stop recording", [need(lambda c: c.recording, "not recording")]),
    "record_freespin":("Record a hand motion (free-spin)", LINK_UP + [node("D2"), state_in(P.CS_FREESPIN,
                        what="press Free-spin first"), need(lambda c: not c.recording, "already recording")]),
    "calibrate":      ("Find end stops and set 0°", LINK_UP + MOTOR_UP + SAFE + [node("T1"),
                        state_in(P.CS_REST, P.CS_HOLD, P.CS_FREESPIN, what="not while following setpoints, testing or calibrating"),
                        not_busy()]),
    "calib_abort":    ("Stop calibration", [node("C1"), state_in(P.CS_CALIB, what="calibration is not running")]),
    "capture_limits": ("Save an end stop", LINK_UP + [node("M4"), node("M5"),
                        state_not(P.CS_TRAJ, P.CS_TEST, P.CS_CALIB, what="not while following setpoints, testing or calibrating")]),
    "go_center_zero": ("Move to the middle of the stops and set 0°", LINK_UP + MOTOR_UP + SAFE + [
                        state_in(P.CS_REST, P.CS_HOLD, P.CS_FREESPIN, what="not while following setpoints, testing or calibrating"),
                        not_busy()]),
    "can_scan":       ("Scan the CAN bus / change the motor id", [node("C1"), node("C5"),
                        state_in(P.CS_REST, what="only while the motor is off: press Stop motor")]),
    "phone_capture":  ("Phone capture", [node("D3"), node("D4")]),
    "stop_stream":    ("Stop playback", [need(lambda c: c.streaming, "nothing is playing")]),
    "external_stream":("Planner setpoint stream", LINK_UP + MOTOR_UP + SAFE + [node("T1"), node("T2"), node("T3"),
                        node("M6"), node("D5"), state_in(P.CS_HOLD, P.CS_TRAJ, what="the motor must be in Position control"),
                        need(lambda c: not c.streaming, "a waveform or playback is already playing")]),
}


def can(action: str, ctx: GateContext) -> GateResult:
    """Evaluate every requirement.  Reasons read as plain sentences with the node ids
    they come from at the end ("Idle switch on: ... [S1]").  Identical reasons from
    several nodes are merged, and "no data" reasons are dropped when a real problem
    upstream already explains them (a closed port makes every later check unknown)."""
    label, reqs = ACTIONS[action]
    found: List[Tuple[str, List[str], bool]] = []        # (reason, node ids, is_unknown)
    nodes: List[str] = []
    for r in reqs:
        ok, reason, nids = r(ctx)
        if ok:
            continue
        unknown = bool(nids) and all(ctx.tree.nodes[n].state == P.HS_UNKNOWN for n in nids)
        for item in found:
            if item[0] == reason:
                item[1].extend(n for n in nids if n not in item[1])
                break
        else:
            found.append((reason, list(nids), unknown))
        nodes.extend(n for n in nids if n not in nodes)
    if any(not u for _, _, u in found):
        found = [f for f in found if not f[2]]
    reasons = [f"{reason} [{', '.join(ids)}]" if ids else reason for reason, ids, _ in found]
    if found and not reasons:
        reasons = [found[0][0]]
    return GateResult(not found, reasons, nodes)


def required_nodes(action: str) -> List[str]:
    """Every health node an action depends on (for the UI's connection lines)."""
    from .model import GROUP_NODES, NODE_BY_ID
    out: List[str] = []
    for r in ACTIONS[action][1]:
        for c in getattr(r, "__closure__", None) or ():
            v = getattr(c, "cell_contents", None)
            if isinstance(v, str):
                if v in NODE_BY_ID and v not in out:
                    out.append(v)
                elif v in GROUP_NODES:
                    out.extend(n.id for n in GROUP_NODES[v] if n.id not in out)
    return out


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
