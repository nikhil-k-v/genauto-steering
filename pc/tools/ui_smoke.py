"""
tools/ui_smoke.py — scripted UI session against the simulator, headless.

    xvfb-run -a -s "-screen 0 1600x1000x24" python tools/ui_smoke.py --shots docs/screenshots

Drives the real UI through the same callbacks a user would click, switches
through every tab, injects faults so each health group shows BLOCKED/FAIL,
and saves screenshots.  Exit code != 0 if any UI callback raised.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import dearpygui.dearpygui as dpg  # noqa: E402

from steering import protocol as P  # noqa: E402
from steering.core.app import App  # noqa: E402
from steering.sim import SimTransport  # noqa: E402
from steering.ui import safe as S  # noqa: E402
from steering.ui.app import UI  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", default="")
    ap.add_argument("--data", default="/tmp/steering-ui-smoke")
    args = ap.parse_args()
    shots = Path(args.shots) if args.shots else None
    if shots:
        shots.mkdir(parents=True, exist_ok=True)

    app = App(Path(args.data))
    ui = UI(app, sim=True)
    ui.build()
    t = SimTransport(realtime=2.0)
    app.start(t)
    tick = S.safe(ui._tick)
    errors = []

    def frames(n, dt=0.0):
        for _ in range(n):
            tick()
            dpg.render_dearpygui_frame()
            if S.last_error() and S.last_error() not in errors:
                errors.append(S.last_error())
            if dt:
                time.sleep(dt)

    def shot(name):
        if shots:
            frames(2)
            dpg.output_frame_buffer(str(shots / f"{name}.png"))
            frames(2)                     # the buffer is written on a later frame
            print("saved", shots / f"{name}.png")

    def until(cond, timeout=30, what=""):
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            frames(1, 0.02)
            if cond():
                return
        raise SystemExit(f"timeout: {what}")

    c = app.controller
    until(lambda: c.live.tree.nodes["C5"].state == P.HS_OK, what="link up")
    frames(30, 0.02)
    shot("01_drive_resting")
    c.enable()
    until(lambda: c.live.ctrl_state == P.CS_HOLD, what="HOLD")
    # plain words: the state, the reason lines and refusals must not use internal names
    from steering import words as W
    frames(3)
    assert dpg.get_value(ui.rail.tags["state"]) == W.STATE[P.CS_HOLD]
    c.calibrate()
    dpg.set_value("tabs", "tab_cal")
    frames(20, 0.03)
    shot("02_calibrating")
    until(lambda: c.live.health_fw and c.live.health_fw.calib_stage == P.CAL_DONE and not app.recorder.active, 60, "calibration")
    dpg.set_value("tabs", "tab_drive")
    ui.panels["drive"].set_slider(25.0)
    frames(60, 0.03)
    shot("03_drive_position_control")
    dpg.set_value("tabs", "tab_drive")
    frames(5)
    c.run_generator("sine", amplitude_deg=25, freq_hz=0.8, duration_s=2.0)
    frames(30, 0.03)
    shot("04_drive_following")
    until(lambda: not c.streamer.active and not app.recorder.active, 30, "traj done")
    dpg.set_value("tabs", "tab_tune")
    c.run_test(P.TEST_RELAY, 0, 3.0, 1.0)
    until(lambda: not app.recorder.active, 30, "relay")
    frames(10)
    shot("05_tuning_relay")
    dpg.set_value("tabs", "tab_play")
    frames(5)
    ui.panels["play"]._rebuild_list()
    rows = ui.panels["play"].rows
    sine = next(r for r in rows if r.name == "sine")
    ui.panels["play"]._select(None, None, sine.uid)
    frames(5)
    ui.panels["play"]._play()
    frames(30, 0.03)
    shot("06_playback_streaming")
    until(lambda: not c.streamer.active and not app.recorder.active, 30, "playback done")
    ui.panels["play"]._rebuild_list()
    frames(5)
    shot("07_library")
    # faults: switch open -> trip
    t.sim.f.switch_armed = False
    until(lambda: c.live.ctrl_state == P.CS_TRIPPED, 10, "trip")
    frames(10)
    dpg.set_value("tabs", "tab_health")
    ui.panels["health"].select("S1")
    frames(10)
    shot("08_health_safety_stop")
    # literal connection lines: pretend the Enable button is hovered while S1/S2 block it
    dpg.set_value("tabs", "tab_drive")
    rec_btn = ui.panels["drive"].tags["rec"]
    ui.overlay.force = (ui.rail.tags["clear"], "clear_trip")
    frames(5)
    ui.overlay.force = (rec_btn, ui.gate.bindings[rec_btn])
    frames(3)
    shot("12_lines_record")
    t.sim.f.switch_armed = True
    frames(20, 0.03)
    c.clear_trip()
    until(lambda: c.live.ctrl_state == P.CS_REST, 10, "rest")
    t.sim.f.switch_armed = False
    frames(20, 0.03)
    ui.overlay.force = (ui.rail.tags["hold"], "enable")
    frames(5)
    shot("11_connection_lines")
    ui.overlay.force = None
    t.sim.f.switch_armed = True
    t.sim.f.motor_power = False
    frames(40, 0.03)
    ui.panels["health"].select("M4")
    dpg.set_value("tabs", "tab_health")
    frames(5)
    shot("09_health_motor_off")
    dpg.set_value("tabs", "tab_settings")
    frames(5)
    shot("10_settings")
    pb = [r for r in app.store.list(include_playbacks=True) if r.kind == "playback"]
    print("recordings:", [(r.name, r.kind) for r in app.store.list(include_playbacks=True)])
    assert pb and pb[0].parent_uid == sine.uid, "playback link missing"
    app.shutdown()
    dpg.destroy_context()
    if errors:
        print("UI ERRORS:", errors)
        sys.exit(1)
    print("ui smoke OK")


if __name__ == "__main__":
    main()
