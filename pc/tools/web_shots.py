"""tools/web_shots.py - run the hub against the simulator and screenshot the browser UI.

    python tools/web_shots.py --chrome /path/to/chrome --out docs/screenshots

Shots: the hub's own pages (web_01..05), then the GitHub Pages build served
locally with no hub (web_06: docs offline, connect panel) and connected in place
to the hub on localhost (web_07) - the same path the real Pages site takes on
the laptop.  Uses Playwright when installed (exits non-zero on a page error),
otherwise headless Chrome's --screenshot.
"""
import argparse
import functools
import http.server
import pathlib
import subprocess
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from steering import protocol as P  # noqa: E402
from steering.core.app import App  # noqa: E402
from steering.sim import SimTransport  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--chrome", required=True)
ap.add_argument("--out", default="docs/screenshots")
ap.add_argument("--port", type=int, default=18771)
ap.add_argument("--pages-port", type=int, default=18772)
a_ = ap.parse_args()
out = pathlib.Path(a_.out)
out.mkdir(parents=True, exist_ok=True)

# the Pages build, served by a plain static server (stands in for github.io)
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import build_pages  # noqa: E402
site = build_pages.build(pathlib.Path(tempfile.mkdtemp()) / "site")
handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(site))
httpd = http.server.ThreadingHTTPServer(("127.0.0.1", a_.pages_port), handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
pages = f"http://127.0.0.1:{a_.pages_port}/"

app = App(pathlib.Path(tempfile.mkdtemp()) / "data")
app.settings.server_port = a_.port
app.settings.pages_url = pages             # let the local stand-in call the hub like github.io would
app.start(SimTransport(realtime=3.0))
app.start_server()
t0 = time.monotonic()
while not app.server.status["running"] and time.monotonic() - t0 < 10:
    time.sleep(0.05)


def wait(c, to=30):
    t = time.monotonic()
    while time.monotonic() - t < to:
        if c():
            return
        time.sleep(0.05)
    raise SystemExit("timeout")


wait(lambda: app.controller.live.tree.nodes["C5"].state == P.HS_OK)
app.controller.enable()
wait(lambda: app.controller.live.ctrl_state == P.CS_HOLD)
app.controller.calibrate()
wait(lambda: app.controller.live.health_fw and app.controller.live.health_fw.calib_stage == P.CAL_DONE
     and not app.recorder.active, 60)
r = app.controller.run_generator("sine", duration_s=1.5)
wait(lambda: not app.recorder.active)
app.controller.selected_recording = app.store.get(r.uid)
app.controller.play_recording()
wait(lambda: not app.recorder.active)
base = f"http://127.0.0.1:{a_.port}"
hub_shots = [("web_01_system", base + "/#system", (1400, 1000)), ("web_02_recordings", base + "/#recordings", (1400, 1000)),
             ("web_03_recording", base + f"/#recordings/{r.uid}", (1400, 1000)),
             ("web_04_docs", base + "/#docs/HEALTH", (1400, 1000)), ("web_05_phone", base + "/phone", (430, 900))]
errors = []
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

if sync_playwright:
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=a_.chrome, args=["--no-sandbox"])
        for name, url, (w, h) in hub_shots:
            pg = b.new_page(viewport={"width": w, "height": h})
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.goto(url)
            pg.wait_for_timeout(2500)
            pg.screenshot(path=str(out / f"{name}.png"))
            print("saved", name)
            pg.close()
        # GitHub Pages copy: no hub (docs work), then connected in place to this laptop's hub
        pg = b.new_page(viewport={"width": 1400, "height": 1000})
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(pages + "?pages=1#docs/OPERATIONS")
        pg.wait_for_timeout(1500)
        pg.screenshot(path=str(out / "web_06_pages_offline.png"))
        print("saved web_06_pages_offline")
        pg.fill("#hubAddr", f"localhost:{a_.port}")
        pg.click("#hubGo")
        pg.goto(pages + "?pages=1#system")
        pg.wait_for_timeout(500)
        pg.fill("#hubAddr", f"localhost:{a_.port}")
        pg.click("#hubGo")
        pg.wait_for_timeout(3000)
        connected = pg.inner_text("#hubNote")
        state = pg.inner_text("#state")
        pg.screenshot(path=str(out / "web_07_pages_connected.png"))
        print("saved web_07_pages_connected:", connected.strip(), "|", state.strip())
        if "Connected" not in connected or state in ("Not connected", "Connecting"):
            errors.append(f"pages copy did not connect: {connected!r} / {state!r}")
        b.close()
else:
    for name, url, (w, h) in hub_shots:
        subprocess.run([a_.chrome, "--headless", "--no-sandbox", "--disable-gpu", "--hide-scrollbars", f"--window-size={w},{h}",
                        "--virtual-time-budget=4000", f"--screenshot={out}/{name}.png", url], capture_output=True, timeout=60)
        print("saved", name)
app.shutdown()
httpd.shutdown()
if errors:
    print("PAGE ERRORS:", errors)
    sys.exit(1)
print("web shots OK")
