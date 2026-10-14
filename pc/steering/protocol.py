"""
protocol.py - Python mirror of protocol/protocol.h.

Every constant and struct here is checked against the C header by
tests/test_protocol_sync.py, which parses protocol.h at test time.  If you
change the header, this file must change too, and the test tells you where.
"""
from __future__ import annotations

import ctypes as C
from dataclasses import dataclass
from typing import Optional

PROTOCOL_VERSION = 2

FRAME_SYNC0 = 0xAB
FRAME_SYNC1 = 0xCD
FRAME_OVERHEAD = 5
MAX_PAYLOAD = 32

# ---- packet types ------------------------------------------------------------
PKT_TELEMETRY     = 0xA1
PKT_HEALTH        = 0xA2
PKT_CONFIG_ECHO   = 0xA3
PKT_EVENT         = 0xA4
PKT_CAN_SCAN      = 0xA5
PKT_GAINS         = 0xB1
PKT_SETPOINT      = 0xB2
PKT_MODE_REQUEST  = 0xB3
PKT_COMMAND       = 0xC1
PKT_TEST_START    = 0xC2
PKT_HEARTBEAT     = 0xC3
PKT_LIMITS        = 0xC4
PKT_JOYSTICK      = 0xD1
PKT_BRIDGE_STATUS = 0xD2

# ---- controller states -------------------------------------------------------
CS_REST, CS_HOLD, CS_TRAJ, CS_JOY, CS_TEST, CS_FREESPIN, CS_CALIB, CS_TRIPPED = range(8)
CS_NAMES = {CS_REST: "REST", CS_HOLD: "HOLD", CS_TRAJ: "TRAJ", CS_JOY: "JOYSTICK",
            CS_TEST: "TEST", CS_FREESPIN: "FREE-SPIN", CS_CALIB: "CALIBRATING", CS_TRIPPED: "TRIPPED"}
CS_ENABLED = {CS_HOLD, CS_TRAJ, CS_JOY, CS_TEST, CS_FREESPIN, CS_CALIB}

MODE_AUTO, MODE_HOLD, MODE_TRAJ, MODE_JOY, MODE_FREESPIN = range(5)

# ---- commands ----------------------------------------------------------------
CMD_ENABLE         = 0x01
CMD_DISABLE        = 0x02
CMD_SET_ZERO       = 0x03
CMD_CLEAR_TRIP     = 0x04
CMD_FREESPIN_ON    = 0x05
CMD_FREESPIN_OFF   = 0x06
CMD_CALIB_START    = 0x07
CMD_CALIB_ABORT    = 0x08
CMD_CAN_SCAN       = 0x09
CMD_HOLD_HERE      = 0x0A
CMD_REQ_CONFIG     = 0x0B
CMD_RESET_COUNTERS = 0x0C
CMD_CAPTURE_LEFT   = 0x0D
CMD_CAPTURE_RIGHT  = 0x0E
CMD_GO_CENTER_ZERO = 0x0F
CMD_SET_MOTOR_ID   = 0x10
CMD_NAMES = {v: k[4:] for k, v in list(globals().items()) if k.startswith("CMD_")}

TEST_NONE, TEST_STEP, TEST_RELAY = 0, 1, 2
TEST_NAMES = {TEST_STEP: "STEP", TEST_RELAY: "RELAY"}

# ---- trips -------------------------------------------------------------------
TRIP_NONE, TRIP_VELOCITY, TRIP_STALL, TRIP_OVERCURRENT, TRIP_SWITCH_OPENED, TRIP_PC_LINK_LOST, \
    TRIP_CAN_LOST, TRIP_LIMIT, TRIP_CALIB_FAILED, TRIP_PC_SHUTDOWN, TRIP_ISR_OVERRUN = range(11)
TRIP_NAMES = {
    TRIP_NONE: "none", TRIP_VELOCITY: "Overspeed", TRIP_STALL: "Stall", TRIP_OVERCURRENT: "Overcurrent",
    TRIP_SWITCH_OPENED: "Idle switch opened", TRIP_PC_LINK_LOST: "PC link lost", TRIP_CAN_LOST: "Motor CAN lost",
    TRIP_LIMIT: "Past end stop", TRIP_CALIB_FAILED: "Calibration failed", TRIP_PC_SHUTDOWN: "PC shut down",
    TRIP_ISR_OVERRUN: "Control loop overrun",
}
TRIP_EXPLAIN = {
    TRIP_VELOCITY: "Wheel exceeded VELOCITY_CUTOFF_DEG_S. Check gains (too high Kp / low Kd) or an external shove.",
    TRIP_STALL: "Error stayed above STALL_ERROR_DEG for STALL_TIME_MS. Something is blocking the wheel, or gains are too low to move it.",
    TRIP_OVERCURRENT: "Motor current above CURRENT_CUTOFF_A for CURRENT_TIME_MS. Jam, too-high gains, or wrong torque range.",
    TRIP_SWITCH_OPENED: "The physical idle switch (pin 22) was opened while the motor was enabled.",
    TRIP_PC_LINK_LOST: "PC heartbeat stopped while the PC was in control (TRAJ/TEST). UI frozen or USB unplugged.",
    TRIP_CAN_LOST: "Motor stopped replying while enabled. Motor power, CAN wiring or transceiver.",
    TRIP_LIMIT: "Measured position went LIMIT_TRIP_OVERSHOOT_DEG past a calibrated stop. Limits wrong or zero moved.",
    TRIP_CALIB_FAILED: "End-stop calibration timed out or found an implausible range.",
    TRIP_PC_SHUTDOWN: "The PC app exited and asked the motor to rest.",
    TRIP_ISR_OVERRUN: "The 1 kHz loop fell behind. Firmware bug or I2C/OLED stall.",
}

CAL_IDLE, CAL_SEEK_LEFT, CAL_CONFIRM_LEFT, CAL_SEEK_RIGHT, CAL_CONFIRM_RIGHT, CAL_GO_CENTER, \
    CAL_SETTLE, CAL_DONE, CAL_ABORTED, CAL_FAILED = range(10)
CAL_NAMES = {CAL_IDLE: "idle", CAL_SEEK_LEFT: "Seeking left stop", CAL_CONFIRM_LEFT: "Confirming left stop",
             CAL_SEEK_RIGHT: "Seeking right stop", CAL_CONFIRM_RIGHT: "Confirming right stop",
             CAL_GO_CENTER: "Moving to center", CAL_SETTLE: "Settling", CAL_DONE: "Done",
             CAL_ABORTED: "Aborted", CAL_FAILED: "Failed"}

# ---- firmware health nodes -----------------------------------------------------
HN_CAN_CTRL, HN_CAN_TX, HN_CAN_RX_ANY, HN_CAN_MOTOR, HN_MOTOR_DATA, HN_MOTOR_CURRENT, HN_SWITCH, HN_TRIP, \
    HN_ISR, HN_CTRL_READY, HN_CALIB, HN_PC_LINK, HN_BRIDGE_LINK, HN_OLED = range(14)
HN_COUNT = 14
HS_UNKNOWN, HS_OK, HS_BLOCKED, HS_FAIL = range(4)

# ---- events --------------------------------------------------------------------
EV_BOOT, EV_TRIP, EV_STATE, EV_CMD_ACCEPTED, EV_CMD_REJECTED, EV_CALIB_STAGE, EV_LIMITS_SET, EV_ZERO_SET, \
    EV_TEST_DONE, EV_WARNING = range(1, 11)
EV_NAMES = {EV_BOOT: "boot", EV_TRIP: "trip", EV_STATE: "state", EV_CMD_ACCEPTED: "cmd_ok",
            EV_CMD_REJECTED: "cmd_rejected", EV_CALIB_STAGE: "calib", EV_LIMITS_SET: "limits_set",
            EV_ZERO_SET: "zero_set", EV_TEST_DONE: "test_done", EV_WARNING: "warning"}

# ---- flag bits ---------------------------------------------------------------
TF_ENABLED, TF_ZEROED, TF_AT_LIMIT, TF_SWITCH_ARMED, TF_TEST_RUNNING, TF_LIMITS_VALID, TF_FREESPIN, TF_JOY_PRESENT = \
    (1 << i for i in range(8))
HB_RECORDING, HB_UI_ALIVE, HB_SERVER_UP, HB_PHONE_CAPTURE = (1 << i for i in range(4))
BS_RF_TEENSY, BS_USB_PC, BS_JOY_PRESENT, BS_TELEM_SEEN = (1 << i for i in range(4))


# ==============================================================================
# structs (ctypes, packed, little-endian)
# ==============================================================================
class _P(C.LittleEndianStructure):
    _pack_ = 1

    def to_bytes(self) -> bytes:
        return bytes(self)

    @classmethod
    def from_bytes(cls, b: bytes):
        return cls.from_buffer_copy(b)


class TelemetryPacket(_P):
    _fields_ = [("type", C.c_uint8), ("ctrl_state", C.c_uint8), ("flags", C.c_uint8), ("seq_setpoint", C.c_uint8),
                ("t_us", C.c_uint32), ("setpoint_deg", C.c_float), ("position_deg", C.c_float),
                ("velocity_deg_s", C.c_float), ("current_A", C.c_float), ("torque_cmd_Nm", C.c_float)]


class HealthPacket(_P):
    _fields_ = [("type", C.c_uint8), ("trip_code", C.c_uint8), ("calib_stage", C.c_uint8), ("ctrl_state", C.c_uint8),
                ("t_ms", C.c_uint32), ("node_states", C.c_uint32), ("can_rx_motor_hz", C.c_uint16),
                ("can_rx_other_hz", C.c_uint16), ("can_tec", C.c_uint8), ("can_rec", C.c_uint8),
                ("can_bus_state", C.c_uint8), ("isr_overruns", C.c_uint8), ("loop_hz", C.c_uint16),
                ("pc_hb_age_ms", C.c_uint16), ("bridge_age_ms", C.c_uint16), ("motor_age_ms", C.c_uint16)]

    def node(self, i: int) -> int:
        return (self.node_states >> (2 * i)) & 0x3


class ConfigEchoPacket(_P):
    _fields_ = [("type", C.c_uint8), ("motor_id", C.c_uint8), ("zeroed", C.c_uint8), ("limits_valid", C.c_uint8),
                ("kp", C.c_float), ("kd", C.c_float), ("ki", C.c_float), ("tff_Nm", C.c_float),
                ("limit_left_deg", C.c_float), ("limit_right_deg", C.c_float)]


class EventPacket(_P):
    _fields_ = [("type", C.c_uint8), ("code", C.c_uint8), ("arg", C.c_uint16), ("t_ms", C.c_uint32),
                ("text", C.c_char * 20)]

    @property
    def text_str(self) -> str:
        return self.text.decode(errors="replace").rstrip("\x00")


class CanScanPacket(_P):
    _fields_ = [("type", C.c_uint8), ("count", C.c_uint8), ("ids", C.c_uint8 * 16)]


class GainsPacket(_P):
    _fields_ = [("type", C.c_uint8), ("reserved", C.c_uint8 * 3), ("kp", C.c_float), ("kd", C.c_float),
                ("ki", C.c_float), ("tff_Nm", C.c_float)]


class SetpointPacket(_P):
    _fields_ = [("type", C.c_uint8), ("flags", C.c_uint8), ("seq", C.c_uint16), ("t_ms", C.c_uint32),
                ("pos_deg", C.c_float), ("vel_ff_deg_s", C.c_float)]


class ModeRequestPacket(_P):
    _fields_ = [("type", C.c_uint8), ("mode", C.c_uint8), ("sticky", C.c_uint8), ("reserved", C.c_uint8)]


class CommandPacket(_P):
    _fields_ = [("type", C.c_uint8), ("cmd", C.c_uint8), ("arg", C.c_uint16), ("farg", C.c_float)]


class TestStartPacket(_P):
    _fields_ = [("type", C.c_uint8), ("test_type", C.c_uint8), ("reserved", C.c_uint8 * 2),
                ("amplitude_deg", C.c_float), ("duration_s", C.c_float), ("param", C.c_float)]


class HeartbeatPacket(_P):
    _fields_ = [("type", C.c_uint8), ("flags", C.c_uint8), ("pc_health_bits", C.c_uint16), ("t_ms", C.c_uint32)]


class LimitsPacket(_P):
    _fields_ = [("type", C.c_uint8), ("reserved", C.c_uint8 * 3), ("left_deg", C.c_float), ("right_deg", C.c_float)]


class JoystickPacket(_P):
    _fields_ = [("type", C.c_uint8), ("buttons", C.c_uint8), ("x", C.c_int16), ("y", C.c_int16), ("t_ms", C.c_uint32)]


class BridgeStatusPacket(_P):
    _fields_ = [("type", C.c_uint8), ("bits", C.c_uint8), ("rf_rx_hz", C.c_uint8), ("reserved", C.c_uint8),
                ("t_ms", C.c_uint32)]


PACKET_CLASSES = {
    PKT_TELEMETRY: TelemetryPacket, PKT_HEALTH: HealthPacket, PKT_CONFIG_ECHO: ConfigEchoPacket,
    PKT_EVENT: EventPacket, PKT_CAN_SCAN: CanScanPacket, PKT_GAINS: GainsPacket, PKT_SETPOINT: SetpointPacket,
    PKT_MODE_REQUEST: ModeRequestPacket, PKT_COMMAND: CommandPacket, PKT_TEST_START: TestStartPacket,
    PKT_HEARTBEAT: HeartbeatPacket, PKT_LIMITS: LimitsPacket, PKT_JOYSTICK: JoystickPacket,
    PKT_BRIDGE_STATUS: BridgeStatusPacket,
}
EXPECTED_SIZES = {
    "TelemetryPacket": 28, "HealthPacket": 28, "ConfigEchoPacket": 28, "EventPacket": 28, "CanScanPacket": 18,
    "GainsPacket": 20, "SetpointPacket": 16, "ModeRequestPacket": 4, "CommandPacket": 8, "TestStartPacket": 16,
    "HeartbeatPacket": 8, "LimitsPacket": 12, "JoystickPacket": 10, "BridgeStatusPacket": 8,
}
for _cls in PACKET_CLASSES.values():
    assert C.sizeof(_cls) == EXPECTED_SIZES[_cls.__name__], f"{_cls.__name__} size mismatch"


def decode(payload: bytes):
    """Return a packet instance or None if the type/size is unknown."""
    if not payload:
        return None
    cls = PACKET_CLASSES.get(payload[0])
    if cls is None or len(payload) != C.sizeof(cls):
        return None
    return cls.from_bytes(payload)


# ==============================================================================
# framing
# ==============================================================================
def crc8(data: bytes, crc: int = 0) -> int:
    """CRC-8/MAXIM (poly 0x31 reflected 0x8C), identical to protocol_crc8()."""
    for b in data:
        for _ in range(8):
            mix = (crc ^ b) & 1
            crc >>= 1
            if mix:
                crc ^= 0x8C
            b >>= 1
    return crc


def encode(payload: bytes, seq: int) -> bytes:
    assert 1 <= len(payload) <= MAX_PAYLOAD
    hdr = bytes((len(payload), seq & 0xFF))
    return bytes((FRAME_SYNC0, FRAME_SYNC1)) + hdr + payload + bytes((crc8(hdr + payload),))


@dataclass
class ParserStats:
    frames_ok: int = 0
    crc_errors: int = 0
    sync_errors: int = 0
    drops: int = 0
    bytes_in: int = 0


class FrameParser:
    """Streaming parser; feed bytes, get payloads.  Mirrors the C++ FrameParser."""

    def __init__(self):
        self.stats = ParserStats()
        self._state = 0
        self._len = 0
        self._seq = 0
        self._buf = bytearray()
        self._last_seq: Optional[int] = None

    def feed(self, data: bytes):
        out = []
        self.stats.bytes_in += len(data)
        for b in data:
            p = self._push(b)
            if p is not None:
                out.append(p)
        return out

    def _push(self, b: int):
        s = self._state
        if s == 0:
            if b == FRAME_SYNC0:
                self._state = 1
            else:
                self.stats.sync_errors += 1
        elif s == 1:
            if b == FRAME_SYNC1:
                self._state = 2
            else:
                self._state = 1 if b == FRAME_SYNC0 else 0
                self.stats.sync_errors += 1
        elif s == 2:
            if b == 0 or b > MAX_PAYLOAD:
                self._state = 0
                self.stats.sync_errors += 1
            else:
                self._len = b
                self._buf = bytearray()
                self._state = 3
        elif s == 3:
            self._seq = b
            self._state = 4
        elif s == 4:
            self._buf.append(b)
            if len(self._buf) >= self._len:
                self._state = 5
        elif s == 5:
            self._state = 0
            if crc8(bytes((self._len, self._seq)) + bytes(self._buf)) != b:
                self.stats.crc_errors += 1
                return None
            if self._last_seq is not None:
                gap = (self._seq - self._last_seq - 1) & 0xFF
                if gap:
                    self.stats.drops += gap
            self._last_seq = self._seq
            self.stats.frames_ok += 1
            return bytes(self._buf)
        return None


# ---- convenience builders ------------------------------------------------------------
def command(cmd: int, arg: int = 0, farg: float = 0.0) -> bytes:
    return CommandPacket(type=PKT_COMMAND, cmd=cmd, arg=arg, farg=farg).to_bytes()


def gains(kp: float, kd: float, ki: float, tff: float) -> bytes:
    return GainsPacket(type=PKT_GAINS, kp=kp, kd=kd, ki=ki, tff_Nm=tff).to_bytes()


def setpoint(seq: int, pos_deg: float, vel_ff: float = 0.0, t_ms: int = 0, last: bool = False) -> bytes:
    return SetpointPacket(type=PKT_SETPOINT, flags=1 if last else 0, seq=seq & 0xFFFF, t_ms=t_ms & 0xFFFFFFFF,
                          pos_deg=pos_deg, vel_ff_deg_s=vel_ff).to_bytes()


def mode_request(mode: int, sticky: bool = True) -> bytes:
    return ModeRequestPacket(type=PKT_MODE_REQUEST, mode=mode, sticky=1 if sticky else 0).to_bytes()


def test_start(test_type: int, amplitude_deg: float, duration_s: float, param: float) -> bytes:
    return TestStartPacket(type=PKT_TEST_START, test_type=test_type, amplitude_deg=amplitude_deg,
                           duration_s=duration_s, param=param).to_bytes()


def heartbeat(flags: int, pc_health_bits: int, t_ms: int) -> bytes:
    return HeartbeatPacket(type=PKT_HEARTBEAT, flags=flags, pc_health_bits=pc_health_bits & 0xFFFF,
                           t_ms=t_ms & 0xFFFFFFFF).to_bytes()


def limits(left_deg: float, right_deg: float) -> bytes:
    return LimitsPacket(type=PKT_LIMITS, left_deg=left_deg, right_deg=right_deg).to_bytes()
