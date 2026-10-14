"""
health/model.py - the health tree: every node, what it means, what it affects.

This file IS the documentation of the status bar.  docs/HEALTH.md is generated
from it (`python -m steering docs-health`), the UI tooltips come from it, and
the log files reference node ids from it.  If you add a check anywhere, add a
node here or it does not exist.

Node id convention: <group letter><index>.  Groups:
  A  Motor & CAN         (Teensy <-> transceiver <-> motor)
  B  Safety              (idle switch, latched trips)
  C  Controller          (loop timing, calibration/zero readiness, OLED)
  D  PC link             (PC <-> Teensy, both directions)
  E  Bridge / joystick   (Arduino, RF)
  F  Data & services     (recorder, store, server hub, phone capture, UI loop)

State vocabulary (shared with firmware HS_*):
  UNKNOWN  nothing observed yet
  OK       working
  BLOCKED  not broken, but prevents some action (switch idle, not zeroed, ...)
  FAIL     broken / tripped
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .. import protocol as P

HS_UNKNOWN, HS_OK, HS_BLOCKED, HS_FAIL = P.HS_UNKNOWN, P.HS_OK, P.HS_BLOCKED, P.HS_FAIL
STATE_NAMES = {HS_UNKNOWN: "UNKNOWN", HS_OK: "OK", HS_BLOCKED: "BLOCKED", HS_FAIL: "FAIL"}
RANK = {HS_OK: 0, HS_UNKNOWN: 1, HS_BLOCKED: 2, HS_FAIL: 3}


@dataclass(frozen=True)
class GroupDef:
    letter: str
    name: str
    question: str          # the question this group answers


@dataclass(frozen=True)
class NodeDef:
    id: str
    key: str
    group: str
    name: str
    ok_means: str
    bad_means: str
    fix: str
    affects: tuple          # action keys from gating.ACTIONS
    source: str             # "fw" (Teensy decides) or "pc"
    fw_index: Optional[int] = None


GROUPS: Dict[str, GroupDef] = {
    "A": GroupDef("A", "Motor & CAN", "Can the Teensy talk to a powered, sane motor?"),
    "B": GroupDef("B", "Safety", "Is anything physically or by latch preventing torque?"),
    "C": GroupDef("C", "Controller", "Is the Teensy control loop ready to do absolute-position work?"),
    "D": GroupDef("D", "PC link", "Is the PC talking to the Teensy, and does the Teensy hear the PC?"),
    "E": GroupDef("E", "Bridge", "Is the Arduino joystick/RF bridge alive?"),
    "F": GroupDef("F", "Data & services", "Will what happens now be recorded, stored and served?"),
}

NODES: List[NodeDef] = [
    # ---- A: motor & CAN (firmware) ---------------------------------------------
    NodeDef("A1", "can_ctrl", "A", "CAN controller",
            "FlexCAN3 is error-active with low error counters.",
            "BLOCKED: error counters high (noise, bad termination). FAIL: bus-off - the transceiver is not seeing a valid bus at all.",
            "Check transceiver power and STBY pin, CAN_H/CAN_L wiring, 120 ohm termination at both ends, and that the motor is on the same bus.",
            ("enable", "freespin", "calibrate", "set_zero"), "fw", P.HN_CAN_CTRL),
    NodeDef("A2", "can_tx", "A", "CAN transmit",
            "Command frames are leaving the mailbox (no TX overflow, TEC low).",
            "Frames are queued but not acknowledged: nobody on the bus ACKs. Usually means A1-level wiring or the motor is unpowered.",
            "Same checks as A1; also confirm TX_SIZE_16 and that nothing else writes CAN from the main loop.",
            ("enable", "freespin", "calibrate"), "fw", P.HN_CAN_TX),
    NodeDef("A3", "can_rx_any", "A", "Bus activity",
            "The Teensy has received at least one frame recently (from anyone).",
            "Silence on the bus. Either nothing is powered, or RX wiring is broken while TX looks fine.",
            "Power the motor (it only talks when commanded). Swap CAN_H/CAN_L if TX ACKs but RX is dead.",
            ("enable", "freespin", "calibrate", "set_zero"), "fw", P.HN_CAN_RX_ANY),
    NodeDef("A4", "can_motor", "A", "Motor replies",
            "Reply frames from the configured motor id arrive at the expected rate (~1 kHz while enabled).",
            "BLOCKED (in REST): the motor has never answered / stopped answering - unpowered, wrong CAN id, or in a fault. FAIL (enabled): replies stopped mid-run (power dropout) -> TRIP_CAN_LOST.",
            "Check the 24 V supply, run the CAN scanner (Settings) to find the real id, power-cycle the motor.",
            ("enable", "freespin", "calibrate", "set_zero", "capture_limits"), "fw", P.HN_CAN_MOTOR),
    NodeDef("A5", "motor_data", "A", "Motor data sane",
            "Position/velocity values decode to finite numbers and change over time.",
            "Replies decode to NaN or the payload is frozen (encoder or driver fault, or wrong reply layout).",
            "Power-cycle the motor; if it persists, re-run the motor's own encoder calibration (datasheet §4.2).",
            ("enable", "trajectory", "playback", "tests"), "fw", P.HN_MOTOR_DATA),
    NodeDef("A6", "motor_current", "A", "Motor current",
            "|current| is below 70 % of CURRENT_CUTOFF_A.",
            "BLOCKED: running hot (near the cutoff). FAIL: over the cutoff - a trip will follow.",
            "Lower Kp/Ki, check for a jam, verify MOTOR_T_* ranges in config.h match the datasheet.",
            ("trajectory", "playback", "tests"), "fw", P.HN_MOTOR_CURRENT),

    # ---- B: safety ------------------------------------------------------------------
    NodeDef("B1", "switch", "B", "Idle switch",
            "The physical idle switch (pin 22 -> GND) is closed: motor may be enabled.",
            "Switch open = IDLE. The firmware will not enable, and opening it while enabled trips the motor.",
            "Close the switch. If it reads IDLE with the switch closed, check the wire to pin 22 / GND.",
            ("enable", "freespin", "calibrate", "trajectory", "playback", "tests"), "fw", P.HN_SWITCH),
    NodeDef("B2", "trip", "B", "No trip latched",
            "No safety trip is latched.",
            "A trip is latched (see the trip name and explanation in the Health panel). The motor is in REST until cleared.",
            "Fix the cause, then Clear Trip. Trips are listed in docs/SAFETY.md.",
            ("enable", "freespin", "calibrate", "trajectory", "playback", "tests"), "fw", P.HN_TRIP),

    # ---- C: controller ----------------------------------------------------------------
    NodeDef("C1", "isr", "C", "Control loop timing",
            "The 1 kHz tick runs on time with no overruns.",
            "Overruns or low loop rate: the ISR is being starved (I2C stall, long main-loop work) or is too expensive.",
            "Check DISPLAY_HZ / OLED wiring; report isr_overruns from the Health panel.",
            ("enable", "trajectory", "playback", "tests"), "fw", P.HN_ISR),
    NodeDef("C2", "ctrl_ready", "C", "Zeroed + limits",
            "Zero has been set and end-stop limits are valid: absolute positions mean something.",
            "Not zeroed and/or limits unknown. Trajectories, playback and tests are refused because 0 deg is meaningless.",
            "Run Calibrate (auto) or capture L/R stops and Go-Center-Zero in the Calibration panel.",
            ("trajectory", "playback", "tests", "slider"), "fw", P.HN_CTRL_READY),
    NodeDef("C3", "calib", "C", "Calibration",
            "No calibration running and the last one did not fail.",
            "BLOCKED: calibration in progress (other motion is refused). FAIL: last calibration failed.",
            "Wait for it to finish, or abort. On FAIL read the event text (seek timeout / range too small).",
            ("trajectory", "playback", "tests", "slider", "freespin"), "fw", P.HN_CALIB),
    NodeDef("C4", "oled", "C", "Teensy OLED",
            "The SSD1309 answered on I2C and is being refreshed.",
            "No OLED (not fatal: the UI shows the same information).",
            "Check I2C wiring (18/19) and address 0x3C.", (), "fw", P.HN_OLED),

    # ---- D: PC link ----------------------------------------------------------------------
    NodeDef("D1", "port", "D", "Serial port",
            "The serial port is open.",
            "Port not open: not connected, wrong port, or the OS pulled the device.",
            "Pick the Teensy in Connect; re-plug USB; on Linux check dialout group.",
            ("everything",), "pc"),
    NodeDef("D2", "rx_bytes", "D", "Bytes arriving",
            "Bytes are arriving on the port.",
            "Port open but silent: the Teensy is not running this firmware, is in the bootloader, or the cable is charge-only.",
            "Press the Teensy reset button; flash firmware; try another cable.",
            ("everything",), "pc"),
    NodeDef("D3", "rx_frames", "D", "Valid frames",
            "Frames decode with good CRC at a healthy rate and few drops.",
            "Bytes arrive but do not frame: wrong baud/protocol version, or a noisy link with many CRC errors.",
            "Match PROTOCOL_VERSION on both sides; check the USB cable.",
            ("everything",), "pc"),
    NodeDef("D4", "telemetry", "D", "Telemetry fresh",
            "A TelemetryPacket arrived in the last 100 ms.",
            "Frames arrive but no telemetry: firmware stuck before its main loop, or a different device is on the port.",
            "Reset the Teensy; check the port is the Teensy, not the Arduino.",
            ("everything",), "pc"),
    NodeDef("D5", "teensy_hears_pc", "D", "Teensy hears PC",
            "The Teensy reports our heartbeat as fresh (round trip proven).",
            "We receive, but the Teensy does not hear us: TX side of the USB link is broken or the firmware's parser is rejecting our frames.",
            "Check CRC/version; the firmware refuses control when this is down (TRIP_PC_LINK_LOST).",
            ("enable", "trajectory", "playback", "tests", "set_gains"), "pc"),
    NodeDef("D6", "fw_health", "D", "Firmware health fresh",
            "HealthPackets are arriving (the A/B/C groups are current).",
            "No HealthPacket for > 500 ms: A/B/C are stale and may be wrong.",
            "Usually accompanies D4; same fixes.",
            ("enable", "trajectory", "playback", "tests"), "pc"),

    # ---- E: bridge -------------------------------------------------------------------------
    NodeDef("E1", "bridge_rf", "E", "Bridge RF",
            "The Teensy hears the Arduino bridge over NRF24.",
            "No bridge packets at the Teensy. Joystick mode unavailable; in wireless mode the PC link is down.",
            "Power the Arduino, check NRF24 wiring/channel 108, both radios on the same addresses.",
            ("joystick",), "fw", P.HN_BRIDGE_LINK),
    NodeDef("E2", "bridge_usb", "E", "Bridge USB",
            "The Arduino bridge is sending BridgeStatus to the PC (only when it is also on USB).",
            "Not seen. Normal when the Arduino is not plugged into the PC.",
            "Plug the Arduino in if you want its status here.", (), "pc"),

    # ---- F: data & services -----------------------------------------------------------------
    NodeDef("F1", "recorder", "F", "Recorder",
            "Recorder idle or recording without dropped samples.",
            "FAIL: recording but samples are being dropped (disk slow) or the writer thread died.",
            "Check free disk space; see data/logs/app-*.log.",
            ("trajectory", "playback", "tests"), "pc"),
    NodeDef("F2", "store", "F", "Store",
            "The data folder is writable and the catalog database opens.",
            "Cannot write to the data folder or the SQLite catalog is locked/corrupt.",
            "Check permissions / free space; delete data/catalog.sqlite-journal if left over from a crash.",
            ("record", "trajectory", "playback", "tests"), "pc"),
    NodeDef("F3", "server", "F", "Device hub",
            "The optional server hub is running (phones / other devices can connect).",
            "Hub not running (BLOCKED, fine unless you want phone capture).",
            "Start it from Settings or `python -m steering ui --server`.", ("phone_capture",), "pc"),
    NodeDef("F4", "phone", "F", "Phone capture",
            "A phone is connected and time-synced.",
            "No phone connected (BLOCKED) or its clock offset is unstable (FAIL).",
            "Open the hub URL on the phone, allow camera/motion.", ("phone_capture",), "pc"),
    NodeDef("F5", "ui_loop", "F", "UI responsiveness",
            "The UI frame loop is keeping up (< 100 ms per frame).",
            "UI frames are slow or stalled: a callback is blocking. If it stalls > 1 s the firmware treats the PC as dead.",
            "Look for the last exception in the Health panel log; never block in callbacks.",
            ("trajectory", "playback", "tests"), "pc"),
]

NODE_BY_ID: Dict[str, NodeDef] = {n.id: n for n in NODES}
NODE_BY_KEY: Dict[str, NodeDef] = {n.key: n for n in NODES}
FW_NODES: Dict[int, NodeDef] = {n.fw_index: n for n in NODES if n.fw_index is not None}
GROUP_NODES: Dict[str, List[NodeDef]] = {g: [n for n in NODES if n.group == g] for g in GROUPS}


@dataclass
class NodeState:
    id: str
    state: int = HS_UNKNOWN
    reason: str = ""
    since: float = field(default_factory=time.time)
    detail: dict = field(default_factory=dict)

    @property
    def name(self) -> str:
        return STATE_NAMES[self.state]


@dataclass
class HealthTree:
    nodes: Dict[str, NodeState]
    t: float = field(default_factory=time.time)

    def __getitem__(self, node_id: str) -> NodeState:
        return self.nodes[node_id]

    def group_state(self, letter: str):
        """(worst state, first bad node id or None)"""
        worst, first = HS_OK, None
        for n in GROUP_NODES[letter]:
            s = self.nodes[n.id]
            if RANK[s.state] > RANK[worst]:
                worst = s.state
            if s.state != HS_OK and first is None:
                first = n.id
        return worst, first

    def summary_line(self) -> str:
        parts = []
        for g in GROUPS:
            st, first = self.group_state(g)
            parts.append(g if st == HS_OK else f"{g}:{first}" if first else f"{g}?")
        return " ".join(parts)

    def ok(self, node_id: str) -> bool:
        return self.nodes[node_id].state == HS_OK

    def bad_nodes(self):
        return [s for s in self.nodes.values() if s.state != HS_OK]

    def to_dict(self) -> dict:
        return {"t": self.t, "summary": self.summary_line(),
                "nodes": {k: {"s": v.state, "r": v.reason, "since": v.since, **({"d": v.detail} if v.detail else {})}
                          for k, v in self.nodes.items()}}

    def pc_bits_for_heartbeat(self) -> int:
        """Group F summary relayed to the Teensy OLED: bit i = Fi ok (i = 1..4)."""
        bits = 0
        for i, nid in enumerate(("F1", "F2", "F3", "F4")):
            if self.nodes[nid].state == HS_OK:
                bits |= 1 << i
        return bits


def empty_tree() -> HealthTree:
    return HealthTree({n.id: NodeState(n.id) for n in NODES})
