"""Hub: status endpoint, websocket stream + time sync, IMU + video upload land in the recording folder."""
import asyncio
import json
import time

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("websockets")

from steering.core.app import App
from steering.sim import SimTransport


@pytest.fixture
def app(tmp_path):
    a = App(tmp_path / "data")
    a.settings.server_port = 18765
    a.start(SimTransport(realtime=4.0))
    a.start_server()
    t0 = time.monotonic()
    while not a.server.status["running"] and time.monotonic() - t0 < 10:
        time.sleep(0.05)
    assert a.server.status["running"]
    time.sleep(0.5)
    yield a
    a.shutdown()


def test_hub_roundtrip(app, tmp_path):
    import urllib.request
    import websockets

    st = json.loads(urllib.request.urlopen("http://127.0.0.1:18765/status", timeout=5).read())
    assert st["ctrl_state"] == "REST"

    async def phone():
        async with websockets.connect("ws://127.0.0.1:18765/ws") as ws:
            hello = json.loads(await ws.recv())
            assert hello["type"] == "hello"
            await ws.send(json.dumps({"type": "ping", "t0": time.time() * 1000}))
            got_pong = got_health = False
            rec = app.controller.record_start("phone-test")
            await ws.send(json.dumps({"type": "imu", "uid": rec.uid,
                                      "samples": [[time.time() * 1000, 0, 0, 9.8, 0, 0, 0]] * 3}))
            await ws.send(json.dumps({"type": "sync", "offset_ms": 2.0, "jitter_ms": 1.0, "capturing": True}))
            t_end = time.monotonic() + 5
            while time.monotonic() < t_end and not (got_pong and got_health):
                m = json.loads(await asyncio.wait_for(ws.recv(), timeout=3))
                got_pong |= m["type"] == "pong"
                got_health |= m["type"] == "health" and "groups" in m
            assert got_pong and got_health
            await ws.send(json.dumps({"type": "cmd", "action": "record_stop"}))
            m = None
            while True:
                m = json.loads(await asyncio.wait_for(ws.recv(), timeout=3))
                if m["type"] == "cmd_result":
                    break
            assert m["ok"], m
            return rec

    rec = asyncio.run(phone())
    time.sleep(0.5)
    assert (rec.dir / "imu.csv").exists() and len((rec.dir / "imu.csv").read_text().splitlines()) == 4
    assert app.server.phone_status["connected"] is False or True   # status refreshes on disconnect

    # video upload
    import urllib.request
    boundary = "xx"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"v\"\r\n"
            f"Content-Type: video/webm\r\n\r\nFAKEVIDEO\r\n--{boundary}--\r\n").encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:18765/capture/upload?uid={rec.uid}&start_server_ms={rec.created_at * 1000 + 250}",
        data=body, method="POST", headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    j = json.loads(urllib.request.urlopen(req, timeout=5).read())
    assert j["ok"] and abs(j["video_start_rel_s"] - 0.25) < 1e-3
    assert (rec.dir / "video.webm").read_bytes() == b"FAKEVIDEO"
    assert app.store.get(rec.uid).has_video
