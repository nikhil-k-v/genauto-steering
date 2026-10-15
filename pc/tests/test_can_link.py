"""CAN behaviour end to end against the simulator, which models the bus like the
hardware: the motor answers only frames sent to its id, the Teensy polls it with
the motor off.  These are the paths that "never worked" when the firmware was
silent in Motor off (0 Hz, Position control refused for "no motor CAN reply")."""
import time

import pytest

from steering import protocol as P
from steering.core.app import App
from steering.core.controller import ActionRefused
from steering.sim import SimFaults, SimTransport
from steering.words import can_scan_line


@pytest.fixture
def app(tmp_path):
    a = App(tmp_path / "data")
    a.settings.auto_connect = False
    yield a
    a.shutdown()


def wait(cond, timeout=5.0, what="condition"):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if cond():
            return True
        time.sleep(0.02)
    raise AssertionError(f"timeout waiting for {what}")


def connect(app, faults=None, realtime=1.0):
    t = SimTransport(faults, realtime=realtime)
    app.start(t)
    wait(lambda: app.controller.live.tree.nodes["C5"].state == P.HS_OK, what="C5")
    return t


def node(app, nid):
    return app.controller.live.tree.nodes[nid]


def test_motor_is_heard_with_the_motor_off_and_turns_on(app):
    connect(app)
    c = app.controller
    wait(lambda: c.live.health_fw and c.live.health_fw.can_rx_motor_hz >= 50, what="motor replies in Motor off")
    assert c.live.ctrl_state == P.CS_REST
    assert 50 <= c.live.health_fw.can_rx_motor_hz <= 150
    for nid in ("M1", "M2", "M3", "M4", "M5"):
        assert node(app, nid).state == P.HS_OK, (nid, node(app, nid).reason)
    assert c.can("enable").ok, c.can("enable").reasons
    c.enable()
    wait(lambda: c.live.ctrl_state == P.CS_HOLD, what="Position control")
    wait(lambda: c.live.health_fw.can_rx_motor_hz >= 600, what="1 kHz replies while on")
    assert not c.live.last_rejection


def test_can_scan_reports_the_motor_without_stalling(app):
    connect(app)
    c = app.controller
    gaps, last = [], [time.monotonic()]

    def on_t(_):
        now = time.monotonic(); gaps.append(now - last[0]); last[0] = now
    app.bus.subscribe("telemetry", on_t)
    c.can_scan()
    assert c.live.can_scan_status == "scanning"
    wait(lambda: c.live.can_scan_status == "done", timeout=3, what="scan result")
    assert c.live.can_scan_ids == [2]
    assert max(gaps) < 0.1, "telemetry stalled during the scan"
    assert can_scan_line("done", [2], (1, 127), 2) == "Motor answering on id 2"
    wait(lambda: node(app, "M4").state == P.HS_OK, what="M4 back after the scan")


def test_scan_is_gated_while_the_motor_is_on(app):
    connect(app)
    c = app.controller
    wait(lambda: c.can("enable").ok, what="enable allowed")
    c.enable()
    wait(lambda: c.live.ctrl_state == P.CS_HOLD, what="Position control")
    with pytest.raises(ActionRefused):
        c.can_scan()


def test_wrong_motor_id_is_found_and_fixed(app):
    connect(app, SimFaults(motor_can_id=5))
    c = app.controller
    wait(lambda: c.live.config is not None and c.live.health_fw is not None, what="config")
    assert node(app, "M4").state == P.HS_UNKNOWN            # quiet while off: no data, not a fault
    assert c.can("enable").ok                               # turning on does not need a reply first
    c.enable()
    wait(lambda: c.live.health_fw.trip_code == P.TRIP_CAN_LOST, what="safety stop: no reply after on")
    c.clear_trip()
    wait(lambda: c.live.ctrl_state == P.CS_REST, what="Motor off")
    c.can_scan()
    wait(lambda: c.live.can_scan_status == "done", timeout=3, what="scan result")
    assert c.live.can_scan_ids == [5]
    assert "Use this id" in can_scan_line("done", [5], (1, 127), c.live.config.motor_id)
    c.set_motor_id(5)
    wait(lambda: c.live.config.motor_id == 5, what="id echo")
    wait(lambda: node(app, "M4").state == P.HS_OK, what="M4 with the right id")
    c.enable()
    wait(lambda: c.live.ctrl_state == P.CS_HOLD, what="Position control")


def test_unpowered_motor_explains_itself(app):
    connect(app, SimFaults(motor_power=False))
    c = app.controller
    wait(lambda: node(app, "M1").state == P.HS_BLOCKED, what="M1 error-passive")
    assert "not acknowledged" in node(app, "M1").reason
    r = c.can("enable")
    assert not r.ok and any("M1" in s for s in r.reasons)  # nobody ACKs: the motor has no power
    c.can_scan()
    wait(lambda: c.live.can_scan_status == "done", timeout=3, what="scan result")
    assert c.live.can_scan_ids == []
    assert can_scan_line("done", [], (1, 127), 2).startswith("No motor answered")


def test_motor_that_only_answers_when_on(app):
    """Datasheet reading: in REST the motor may not reply at all.  Turning on must still work."""
    connect(app, SimFaults(answers_in_rest=False))
    c = app.controller
    wait(lambda: c.live.health_fw is not None, what="health")
    time.sleep(0.3)
    assert c.live.health_fw.can_rx_motor_hz == 0
    assert node(app, "M4").state == P.HS_UNKNOWN
    assert c.can("enable").ok, c.can("enable").reasons
    c.enable()
    wait(lambda: c.live.ctrl_state == P.CS_HOLD, what="Position control")
    wait(lambda: c.live.health_fw.can_rx_motor_hz >= 600, what="1 kHz replies while on")
    time.sleep(0.5)
    assert c.live.ctrl_state == P.CS_HOLD and c.live.health_fw.trip_code == 0


def test_power_loss_while_on_is_a_safety_stop(app):
    t = connect(app)
    c = app.controller
    wait(lambda: c.can("enable").ok, what="enable allowed")
    c.enable()
    wait(lambda: c.live.ctrl_state == P.CS_HOLD, what="Position control")
    t.sim.f.motor_power = False
    wait(lambda: c.live.health_fw.trip_code == P.TRIP_CAN_LOST, what="safety stop: motor CAN lost")
    t.sim.f.motor_power = True
    wait(lambda: node(app, "M4").state == P.HS_OK, what="motor heard again while stopped")
