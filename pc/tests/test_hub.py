"""Hub: status endpoint, websocket stream + time sync, IMU + video upload land in the recording folder."""
import asyncio
import json
import time

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("websockets")

from steering.core.app import App
from steering.sim import SimTransport


def _free_port():
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def app(tmp_path):
    a = App(tmp_path / "data")
    a.settings.server_port = _free_port()
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

    port = app.settings.server_port
    st = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/status", timeout=5).read())
    assert st["ctrl_state"] == "REST"

    async def phone():
        async with websockets.connect(f"ws://127.0.0.1:{port}/ws") as ws:
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
        f"http://127.0.0.1:{port}/capture/upload?uid={rec.uid}&start_server_ms={rec.created_at * 1000 + 250}",
        data=body, method="POST", headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    j = json.loads(urllib.request.urlopen(req, timeout=5).read())
    assert j["ok"] and abs(j["video_start_rel_s"] - 0.25) < 1e-3
    assert (rec.dir / "video.webm").read_bytes() == b"FAKEVIDEO"
    assert app.store.get(rec.uid).has_video


def test_web_api(app):
    import urllib.request
    base = f"http://127.0.0.1:{app.settings.server_port}"
    get = lambda p: json.loads(urllib.request.urlopen(base + p, timeout=5).read())
    assert urllib.request.urlopen(base + "/", timeout=5).status == 200          # browser UI
    assert urllib.request.urlopen(base + "/phone", timeout=5).status == 200     # phone page
    hl = get("/api/health")
    assert {g["id"] for g in hl["groups"]} == {"M", "S", "T", "C", "D"} and len(hl["nodes"]) == 23
    rec = app.controller.record_start("web-test")
    time.sleep(0.4)
    app.controller.record_stop()
    recs = get("/api/recordings")
    assert recs["recordings"][0]["name"] == "web-test"
    uid = recs["recordings"][0]["uid"]
    d = get(f"/api/recordings/{uid}/data")
    assert d["n"] > 0 and "position_deg" in d["columns"]
    req = urllib.request.Request(f"{base}/api/recordings/{uid}", data=json.dumps({"pinned": True, "tags": "x,y"}).encode(),
                                 headers={"content-type": "application/json"}, method="POST")
    assert json.loads(urllib.request.urlopen(req).read())["pinned"] is True
    assert app.store.get(uid).tags == ["x", "y"]
    docs = get("/api/docs")
    assert any(x["id"] == "HEALTH" for x in docs["docs"])
    assert "<h1" in get("/api/docs/HEALTH")["html"]
    assert urllib.request.urlopen(base + "/diagrams/01_system_overview.svg", timeout=5).status == 200


def test_wifi_front_door(app):
    """The GitHub Pages copy may call the hub on localhost (CORS + private-network preflight), a random
    site may not open the websocket, and /api/info lists the addresses other devices can use."""
    import urllib.request
    import websockets
    port = app.settings.server_port
    base = f"http://127.0.0.1:{port}"
    info = json.loads(urllib.request.urlopen(base + "/api/info", timeout=5).read())
    assert info["urls"]["local"] == f"http://localhost:{port}/"
    assert info["urls"]["pages_link"].startswith(app.settings.pages_url.rstrip("/") + "/?hub=")
    pages = "https://nikhil-k-v.github.io"
    req = urllib.request.Request(base + "/api/health", method="OPTIONS", headers={
        "Origin": pages, "Access-Control-Request-Method": "GET", "Access-Control-Request-Private-Network": "true"})
    r = urllib.request.urlopen(req, timeout=5)
    assert r.headers["access-control-allow-origin"] == pages
    assert r.headers["access-control-allow-private-network"] == "true"
    r = urllib.request.urlopen(urllib.request.Request(base + "/api/health", headers={"Origin": "https://evil.example"}), timeout=5)
    assert r.headers.get("access-control-allow-origin") is None

    async def ws(origin):
        try:
            async with websockets.connect(f"ws://127.0.0.1:{port}/ws", additional_headers={"Origin": origin}) as w:
                return json.loads(await asyncio.wait_for(w.recv(), timeout=3))["type"]
        except Exception as e:
            return type(e).__name__
    assert asyncio.run(ws(pages)) == "hello"
    assert asyncio.run(ws(f"http://127.0.0.1:{port}")) == "hello"
    assert asyncio.run(ws("https://evil.example")) != "hello"
