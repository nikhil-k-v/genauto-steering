"""tools/web_shots.py - run the hub against the simulator and screenshot the browser UI
with headless Chromium (path via --chrome). Used to produce docs/screenshots/web_*.png."""
import argparse, subprocess, sys, tempfile, time, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from steering.core.app import App
from steering.sim import SimTransport
from steering import protocol as P

ap = argparse.ArgumentParser(); ap.add_argument("--chrome", required=True); ap.add_argument("--out", default="docs/screenshots"); ap.add_argument("--port", type=int, default=18771)
a_ = ap.parse_args()
app = App(pathlib.Path(tempfile.mkdtemp()) / "data"); app.settings.server_port = a_.port
app.start(SimTransport(realtime=3.0)); app.start_server()
t0 = time.monotonic()
while not app.server.status["running"] and time.monotonic() - t0 < 10: time.sleep(0.05)
def wait(c, to=30):
    t = time.monotonic()
    while time.monotonic() - t < to:
        if c(): return
        time.sleep(0.05)
    raise SystemExit("timeout")
wait(lambda: app.controller.live.tree.nodes["C5"].state == P.HS_OK)
app.controller.enable(); wait(lambda: app.controller.live.ctrl_state == P.CS_HOLD)
app.controller.calibrate(); wait(lambda: app.controller.live.health_fw and app.controller.live.health_fw.calib_stage == P.CAL_DONE and not app.recorder.active, 60)
r = app.controller.run_generator("sine", duration_s=1.5); wait(lambda: not app.recorder.active)
app.controller.selected_recording = app.store.get(r.uid); app.controller.play_recording(); wait(lambda: not app.recorder.active)
base = f"http://127.0.0.1:{a_.port}"
for name, url, size in [("web_01_system", "#system", "1400,1000"), ("web_02_recordings", "#recordings", "1400,1000"),
                        ("web_03_recording", f"#recordings/{r.uid}", "1400,1000"), ("web_04_docs", "#docs/HEALTH", "1400,1000"),
                        ("web_05_phone", "phone", "430,900")]:
    subprocess.run([a_.chrome, "--headless", "--no-sandbox", "--disable-gpu", "--hide-scrollbars", f"--window-size={size}",
                    "--virtual-time-budget=4000", f"--screenshot={a_.out}/{name}.png", base + "/" + url], capture_output=True, timeout=60)
    print("saved", name)
app.shutdown()
