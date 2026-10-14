"""
tools/make_sim_data.py - generate example recordings with the simulator.

    cd pc && python tools/make_sim_data.py                 # writes ../examples/sim_data
    python -m steering ui --sim --data ../examples/sim_data   # open them in the app

Everything goes through the real Controller (gated actions, recorder, store),
so the folders are exactly what the app writes on hardware: data.csv, meta.json,
health.jsonl, events.jsonl.  The catalog is not committed; the store rebuilds it
from the folders the first time it opens them.

What it records (collection / name):
  sim-demo / autocal                   end stops + zero
  sim-demo / hand-left-right           free-spin: a "hand" turns the wheel left, right, left
  sim-demo / hand-left-right_pb01      played back at x1   (Kp 30)
  sim-demo / hand-left-right_pb02      played back at x0.5 with stiffer gains (Kp 60, Ki 0.2)
  tuning   / step, relay               the two tests
  tuning   / sine, chirp               test waveforms
  faults   / switch-opened             slider moves, then the idle switch opens (trip inside the recording)
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from steering import protocol as P  # noqa: E402
from steering.core.app import App  # noqa: E402
from steering.sim import SimTransport  # noqa: E402

REALTIME = 1.0          # recordings keep true time stamps; the sim runs at wall-clock speed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[2] / "examples" / "sim_data"))
    args = ap.parse_args()
    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)

    app = App(out)
    tr = SimTransport(realtime=REALTIME)
    app.start(tr)
    sim = tr.sim
    c = app.controller

    def wait(cond, timeout=60, what=""):
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            if cond():
                return
            time.sleep(0.02)
        raise SystemExit(f"timeout: {what}")

    def idle():
        wait(lambda: not app.recorder.active and not c.streamer.active, 90, "recording to finish")
        time.sleep(0.4)

    def collection(name):
        app.settings.collection = name

    def gains(kp, kd, ki, tff=0.0):
        c.set_gains(kp, kd, ki, tff)
        wait(lambda: not c.live.pending_gains, 5, "gain echo")

    wait(lambda: c.live.tree.nodes["C5"].state == P.HS_OK, 20, "link")
    time.sleep(0.5)

    # ---- sim-demo ---------------------------------------------------------------------------
    collection("sim-demo")
    gains(30, 2.0, 0.0)
    c.enable()
    wait(lambda: c.live.ctrl_state == P.CS_HOLD, 10, "hold")
    c.calibrate()
    wait(lambda: c.live.health_fw and c.live.health_fw.calib_stage == P.CAL_DONE, 120, "calibration")
    idle()
    print("autocal done")

    # hand motion in free-spin: a smooth push left, right, left (torque profile on the "hand")
    c.freespin_on()
    wait(lambda: c.live.ctrl_state == P.CS_FREESPIN, 5, "free-spin")
    rec = c.record_start("hand-left-right", kind="freespin", notes="simulated hand: left, right, left")
    t0 = time.monotonic()
    while time.monotonic() - t0 < 7.0:
        t = time.monotonic() - t0
        # torque above static friction (0.8 Nm), shaped so the wheel swings about ±60°
        sim.f.hand_Nm = 1.6 * math.sin(2 * math.pi * t / 3.5) + (0.0 if t < 6.2 else -1.2)
        time.sleep(0.01)
    sim.f.hand_Nm = 0.0
    time.sleep(0.8)
    c.record_stop()
    c.freespin_off()
    wait(lambda: c.live.ctrl_state == P.CS_HOLD, 5, "re-grip")
    time.sleep(1.0)
    hand = app.store.get(rec.uid)
    app.store.set_pinned(hand.uid, True)
    app.store.set_tags(hand.uid, ["demo", "hand"])
    print("hand motion recorded")

    c.play_recording(hand, speed=1.0)
    idle()
    gains(60, 2.5, 0.2)
    c.play_recording(hand, speed=0.5)
    idle()
    gains(30, 2.0, 0.0)
    print("playbacks done")

    # ---- tuning ------------------------------------------------------------------------------
    collection("tuning")
    gains(60, 2.5, 0.2)
    c.run_test(P.TEST_STEP, 30.0, 2.5, 2.5)
    idle()
    c.run_test(P.TEST_RELAY, 0.0, 6.0, 1.0)
    idle()
    c.run_generator("sine", amplitude_deg=25, freq_hz=0.5, duration_s=6.0)
    idle()
    c.run_generator("chirp", amplitude_deg=12, f0_hz=0.1, f1_hz=1.5, duration_s=10.0)
    idle()
    print("tuning done")

    # ---- faults: a run interrupted by the idle switch ------------------------------------------
    collection("faults")
    rec = c.record_start("switch-opened", kind="manual",
                         notes="slider moves while holding, then the idle switch opens: the trip, the health change "
                               "and the events are all in this folder")
    for target in (20.0, -20.0, 10.0):
        c.slider(target)
        time.sleep(1.2)
    sim.f.switch_armed = False
    wait(lambda: c.live.ctrl_state == P.CS_TRIPPED, 5, "trip")
    time.sleep(1.5)                       # keep recording so the health change and trip event are inside
    c.record_stop()
    idle()
    app.store.set_tags(rec.uid, ["demo", "fault"])
    sim.f.switch_armed = True
    time.sleep(0.5)
    c.clear_trip()
    time.sleep(0.5)
    print("fault run done")

    app.settings.collection = "sim-demo"
    app.shutdown()
    for f in ("catalog.sqlite", "settings.json"):
        (out / f).unlink(missing_ok=True)
    shutil.rmtree(out / "logs", ignore_errors=True)
    for meta in (out / "recordings").glob("*/*/*/meta.json"):     # no machine-specific absolute paths in the repo
        d = json.loads(meta.read_text())
        d["path"] = str(meta.parent.relative_to(out))
        meta.write_text(json.dumps(d, indent=2))
    n = len(list((out / "recordings").glob("*/*/*/meta.json")))
    print(f"{n} recordings in {out}")


if __name__ == "__main__":
    main()
