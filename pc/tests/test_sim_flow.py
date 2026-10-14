"""End-to-end against the simulator: connect, health, gating, enable, calibrate,
record, play back, trips — the same path the UI takes."""
import time

import pytest

from steering import protocol as P
from steering.core.app import App
from steering.core.controller import ActionRefused
from steering.sim import SimFaults, SimTransport


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


def connect(app, faults=None, realtime=4.0):
    t = SimTransport(faults, realtime=realtime)
    app.start(t)
    wait(lambda: app.controller.live.telemetry is not None, what="telemetry")
    wait(lambda: app.controller.live.tree.nodes["C5"].state == P.HS_OK, what="C5")
    return t


def test_link_health_comes_up(app):
    connect(app)
    tree = app.controller.live.tree
    for nid in ("C1", "C2", "C3", "C4", "C5", "C6", "M4", "S1", "S2"):
        assert tree.nodes[nid].state == P.HS_OK, (nid, tree.nodes[nid].reason)
    assert tree.nodes["T2"].state == P.HS_BLOCKED          # not zeroed yet


def test_gating_refuses_with_reasons(app):
    connect(app, SimFaults(switch_armed=False))
    wait(lambda: app.controller.live.tree.nodes["S1"].state == P.HS_BLOCKED, what="S1 blocked")
    with pytest.raises(ActionRefused) as e:
        app.controller.enable()
    assert "S1" in e.value.result.nodes
    r = app.controller.can("trajectory")
    assert not r.ok and any("S1" in s for s in r.reasons)


def test_enable_calibrate_record_playback(app):
    t = connect(app)
    app.controller.enable()
    wait(lambda: app.controller.live.ctrl_state == P.CS_HOLD, what="HOLD")
    with pytest.raises(ActionRefused):                       # not zeroed / no limits
        app.controller.run_generator("sine", duration_s=1.0)
    app.controller.calibrate()
    wait(lambda: app.controller.live.health_fw and app.controller.live.health_fw.calib_stage == P.CAL_DONE,
         timeout=40, what="calibration done")
    wait(lambda: app.controller.live.tree.nodes["T2"].state == P.HS_OK, what="T2 ok")
    cfg = app.controller.live.config
    assert cfg.limits_valid and cfg.limit_left_deg < -30 and cfg.limit_right_deg > 30
    assert abs(app.controller.live.position) < 3.0           # centred and zeroed
    wait(lambda: not app.recorder.active, what="calibration recording stopped")

    rec = app.controller.run_generator("sine", amplitude_deg=20, freq_hz=1.0, duration_s=1.0)
    wait(lambda: not app.controller.streamer.active and not app.recorder.active, timeout=10, what="traj done")
    rec = app.store.get(rec.uid)
    assert rec.samples > 100 and "err_rms_deg" in rec.metrics and rec.kind == "trajectory"
    assert rec.metrics["err_rms_deg"] < 8.0

    app.controller.selected_recording = rec
    pb = app.controller.play_recording(speed=2.0)
    wait(lambda: not app.controller.streamer.active and not app.recorder.active, timeout=10, what="playback done")
    pb = app.store.get(pb.uid)
    assert pb.kind == "playback" and pb.parent_uid == rec.uid and pb.name == f"{rec.name}_pb01"
    assert app.store.get(rec.uid).playback_count == 1
    assert (pb.dir / "health.jsonl").exists() and (pb.dir / "events.jsonl").exists()

    app.controller.run_test(P.TEST_STEP, 15.0, 0.5, 0.5)
    wait(lambda: not app.recorder.active, timeout=10, what="step test done")
    tests = app.store.list(kind="test_step")
    assert tests and "step_overshoot_pct" in tests[0].metrics


def test_trip_latches_and_blocks(app):
    t = connect(app)
    app.controller.enable()
    wait(lambda: app.controller.live.ctrl_state == P.CS_HOLD, what="HOLD")
    t.sim.f.switch_armed = False
    wait(lambda: app.controller.live.ctrl_state == P.CS_TRIPPED, what="trip")
    wait(lambda: app.controller.live.tree.nodes["S2"].state == P.HS_FAIL, what="S2 fail")
    assert app.controller.live.health_fw.trip_code == P.TRIP_SWITCH_OPENED
    with pytest.raises(ActionRefused):
        app.controller.enable()
    t.sim.f.switch_armed = True
    wait(lambda: app.controller.live.tree.nodes["S1"].state == P.HS_OK, what="S1 ok")
    app.controller.clear_trip()
    wait(lambda: app.controller.live.ctrl_state == P.CS_REST, what="REST")
    wait(lambda: app.controller.live.tree.nodes["S2"].state == P.HS_OK, what="S2 ok")
    app.controller.enable()
    wait(lambda: app.controller.live.ctrl_state == P.CS_HOLD, what="HOLD again")


def test_firmware_rejection_is_surfaced(app):
    t = connect(app)
    # bypass PC gating to prove the firmware refuses with a reason
    app.link.send(P.test_start(P.TEST_STEP, 10, 1, 1))
    wait(lambda: "refused" in app.controller.live.last_rejection, what="rejection event")
    rej = app.controller.live.last_rejection
    assert "start the test" in rej and "position ctrl" in rej, rej


def test_store_reindex(app):
    connect(app)
    r = app.controller.record_start("manual-1")
    time.sleep(0.3)
    app.controller.record_stop()
    assert app.store.get(r.uid).samples > 0
    n = app.store.reindex()
    assert n == 1 and app.store.get(r.uid).name == "manual-1"


def test_reasons_are_plain_and_name_the_check(app):
    """Refusals read as sentences about the physical problem, with the check id at the end -
    never an internal state name ("HOLD", "BLOCKED", "trip")."""
    connect(app, SimFaults(switch_armed=False))
    wait(lambda: app.controller.live.tree.nodes["S1"].state == P.HS_BLOCKED, what="S1 blocked")
    r = app.controller.can("enable")
    text = " ".join(r.reasons)
    assert "Idle switch on" in text and "[S1]" in text, text
    for word in ("HOLD", "BLOCKED", "FAIL", "trip", "IDLE"):
        assert word not in text, (word, text)
    r = app.controller.can("slider")
    assert any("Position control" in x for x in r.reasons), r.reasons


def test_setpoint_source_follows_the_mode(app):
    t = connect(app)
    c = app.controller
    assert c.setpoint_source() == ""                              # motor off: no setpoint
    c.enable()
    wait(lambda: c.live.ctrl_state == P.CS_HOLD, what="HOLD")
    assert c.setpoint_source() == "user"
    c.external_setpoint(c.live.position) if c.can("external_stream").ok else None


def test_trip_detail_carries_the_measured_value(app):
    t = connect(app)
    app.controller.enable()
    wait(lambda: app.controller.live.ctrl_state == P.CS_HOLD, what="HOLD")
    t.sim.f.switch_armed = False
    wait(lambda: app.controller.live.ctrl_state == P.CS_TRIPPED, what="trip")
    from steering import words as W
    assert app.controller.live.trip_text == "pin 22 open"
    assert W.trip_line(P.TRIP_SWITCH_OPENED, app.controller.live.trip_text) == "Idle switch turned on while running (pin 22 open)"
