"""
words.py - what the operator reads.  One place for every user-facing name.

Rules (keep them when adding text):
  * Name a mode by what the motor is doing, not by an internal state name.
    "Position control" (the motor servos to a setpoint) - never "Hold", which
    could mean a mode, holding a position with torque, pausing, or stopping.
  * A problem says what is physically wrong and, where it helps, the number
    that shows it: "Motor not replying on CAN (id 2)", "CAN TX: frames not
    acknowledged (error count 128)".  Never just "blocked", "trip" or "FAIL".
  * A latched trip is a "safety stop".  It is reset, not "cleared".
  * Buttons say exactly what happens: "Move to 0°" moves; "Set 0° here" sets.

The wire/log names (CS_NAMES, TRIP_NAMES in protocol.py, node ids) stay as
they are for logs and docs; this module is presentation only.
"""
from __future__ import annotations

from . import protocol as P

# ---- controller state, as an operator would say it -------------------------------------------
STATE = {
    P.CS_REST: "Motor off",
    P.CS_HOLD: "Position control",
    P.CS_TRAJ: "Following setpoints",
    P.CS_TEST: "Running a test",
    P.CS_FREESPIN: "Free-spin",
    P.CS_CALIB: "Calibrating",
    P.CS_TRIPPED: "Safety stop",
}

# what the motor does in that state - used in tooltips and the Health page, not as captions
STATE_MEANS = {
    P.CS_REST: "No torque, motor driver off. The wheel turns freely; the Teensy still asks the motor for its angle 100 times a second.",
    P.CS_HOLD: "The motor servos the wheel to the setpoint (slider, or where it was when you turned it on).",
    P.CS_TRAJ: "The motor follows a setpoint stream: a recording, a waveform or the planner.",
    P.CS_TEST: "The Teensy is running a step or relay test.",
    P.CS_FREESPIN: "Driver on with zero torque: turn the wheel by hand; its angle is recorded.",
    P.CS_CALIB: "The Teensy is finding the end stops.",
    P.CS_TRIPPED: "A safety check stopped the motor. It stays off until you reset the safety stop.",
}

# while TRAJ, the name depends on who is streaming
STREAM_STATE = {"playback": "Playing back", "trajectory": "Playing waveform", "planner": "Planner control"}

# ---- safety stops (latched trips) ----------------------------------------------------------------
TRIP = {
    P.TRIP_NONE: "",
    P.TRIP_VELOCITY: "Wheel turned too fast",
    P.TRIP_STALL: "Wheel stuck: could not reach the setpoint",
    P.TRIP_OVERCURRENT: "Motor current too high",
    P.TRIP_SWITCH_OPENED: "Idle switch turned on while running",
    P.TRIP_PC_LINK_LOST: "Laptop stopped sending setpoints",
    P.TRIP_CAN_LOST: "Motor stopped replying on CAN",
    P.TRIP_LIMIT: "Wheel went past an end stop",
    P.TRIP_CALIB_FAILED: "Calibration failed",
    P.TRIP_PC_SHUTDOWN: "Laptop app closed",
    P.TRIP_ISR_OVERRUN: "Teensy control loop fell behind",
}
TRIP_WHY = {
    P.TRIP_VELOCITY: "Speed went over 1430°/s (VELOCITY_CUTOFF_DEG_S). Usually Kp too high or Kd too low, or the wheel was shoved.",
    P.TRIP_STALL: "The wheel stayed more than 28.6° from the setpoint for too long (STALL_*). Something blocks it, or the gains are too low to move it.",
    P.TRIP_OVERCURRENT: "Current stayed over 30 A (CURRENT_CUTOFF_A). A jam, gains too high, or the wrong torque range in config.h.",
    P.TRIP_SWITCH_OPENED: "The idle switch was turned on while the motor had torque. Turn it off, then reset.",
    P.TRIP_PC_LINK_LOST: "The laptop went silent while the motor was following its stream: the UI froze or USB was unplugged.",
    P.TRIP_CAN_LOST: "No reply from the motor while it had torque: motor power, CAN wiring or transceiver.",
    P.TRIP_LIMIT: "The measured angle went 15° past a calibrated stop: the stops are wrong or the zero moved.",
    P.TRIP_CALIB_FAILED: "The wheel never reached a stop within 3.5 Nm, or the range it found was too small.",
    P.TRIP_PC_SHUTDOWN: "The laptop app exited and turned the motor off.",
    P.TRIP_ISR_OVERRUN: "The 1 kHz loop missed its deadline repeatedly: an I2C/OLED stall or a firmware bug.",
}

# ---- what a refused command was trying to do --------------------------------------------------------
CMD_DOING = {
    P.CMD_ENABLE: "turn on position control",
    P.CMD_DISABLE: "turn the motor off",
    P.CMD_SET_ZERO: "set 0° here",
    P.CMD_CLEAR_TRIP: "reset the safety stop",
    P.CMD_FREESPIN_ON: "start free-spin",
    P.CMD_FREESPIN_OFF: "leave free-spin",
    P.CMD_CALIB_START: "start calibration",
    P.CMD_CALIB_ABORT: "stop calibration",
    P.CMD_CAN_SCAN: "scan the CAN bus",
    P.CMD_HOLD_HERE: "keep the current position",
    P.CMD_REQ_CONFIG: "report its settings",
    P.CMD_RESET_COUNTERS: "reset its counters",
    P.CMD_CAPTURE_LEFT: "save the left end stop",
    P.CMD_CAPTURE_RIGHT: "save the right end stop",
    P.CMD_GO_CENTER_ZERO: "move to the middle and set 0°",
    P.CMD_SET_MOTOR_ID: "change the motor CAN id",
    P.PKT_TEST_START: "start the test",
    0: "set the end stops",
}

CAL_STAGE = {
    P.CAL_IDLE: "", P.CAL_SEEK_LEFT: "finding the left stop", P.CAL_CONFIRM_LEFT: "confirming the left stop",
    P.CAL_SEEK_RIGHT: "finding the right stop", P.CAL_CONFIRM_RIGHT: "confirming the right stop",
    P.CAL_GO_CENTER: "moving to the middle", P.CAL_SETTLE: "settling, then setting 0°", P.CAL_DONE: "done",
    P.CAL_ABORTED: "stopped", P.CAL_FAILED: "failed",
}

# ---- health verdicts ---------------------------------------------------------------------------------
VERDICT = {P.HS_OK: "ok", P.HS_BLOCKED: "not ready", P.HS_FAIL: "fault", P.HS_UNKNOWN: "no data"}

# setpoint sources (plot colours follow these)
SOURCE = {"user": "Position control", "playback": "Playback", "trajectory": "Waveform", "planner": "Planner",
          "test": "Test", "calib": "Calibration"}


def can_scan_line(status: str, ids, rng, motor_id) -> str:
    """The Settings line under 'Scan the CAN bus' (status from LiveState.can_scan_status)."""
    a, b = rng
    if status == "scanning":
        return f"Scanning ids {a} to {b}…"
    if status == "refused":
        return "Scan refused by the Teensy (see the reason in the events)"
    if status == "no_result":
        return "No scan result from the Teensy after 3 s: is the firmware the same version as this app?"
    if status != "done":
        return ""
    if not ids:
        return f"No motor answered on ids {a} to {b}: check the 24 V supply and the CAN wiring"
    line = "Motor answering on id " if len(ids) == 1 else "Motors answering on ids "
    line += ", ".join(str(i) for i in ids)
    if motor_id is not None and motor_id not in ids:
        line += f". The Teensy commands id {motor_id}: enter {ids[0]} above and press Use this id"
    return line


def signed(x: float, d: int = 1) -> str:
    """+12.3 / −4.0 with a real minus sign."""
    return f"{x:+.{d}f}".replace("-", "−")


def refused(cmd: int, why: str) -> str:
    return f"Teensy refused to {CMD_DOING.get(cmd, 'do that')}: {why}"


def trip_line(code: int, detail: str = "") -> str:
    """'Motor current too high (31.2 A)' - firmware detail carries the measured value."""
    name = TRIP.get(code, f"safety stop {code}")
    d = (detail or "").strip()
    if d and d.lower() not in name.lower():
        return f"{name} ({d})"
    return name


def event_text(code: int, arg: int, text: str):
    """(sentence, level) for a firmware event, or None for ones not worth showing.  level: info / warn / bad."""
    if code == P.EV_TRIP:
        return f"Safety stop: {trip_line(arg, text)}", "bad"
    if code == P.EV_CMD_REJECTED:
        return refused(arg, text), "warn"
    if code == P.EV_STATE:
        return f"now: {STATE.get(arg, arg)}", "info"
    if code == P.EV_CALIB_STAGE:
        return f"calibration: {CAL_STAGE.get(arg, arg)}", "info"
    if code == P.EV_CMD_ACCEPTED:
        return None
    if code == P.EV_ZERO_SET:
        return "0° set at the current angle", "info"
    if code == P.EV_LIMITS_SET:
        return "end stops saved", "info"
    if code == P.EV_TEST_DONE:
        return "test finished", "info"
    if code == P.EV_BOOT:
        return "Teensy started", "info"
    if code == P.EV_WARNING:
        return f"Teensy: {text}", "warn"
    return f"{P.EV_NAMES.get(code, str(code))} {arg} {text}".strip(), "info"
