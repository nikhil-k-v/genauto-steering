"""
server/hub.py — the device hub: lets phones and other devices join the system.

Design (docs/ARCHITECTURE.md#hub):
  * The hub is OPTIONAL and sits beside the laptop UI, never between the UI
    and the Teensy.  It subscribes to the same Bus and calls the same
    Controller, so every remote action is gated identically.
  * Transport: HTTP for the phone page + uploads, one WebSocket per client
    for a JSON stream (telemetry 20 Hz, health 2 Hz, events, recording state)
    and for client -> hub messages (time-sync pings, IMU samples, commands).
  * Time sync: NTP-style ping/pong; the phone keeps a running offset and
    reports it; the hub stores the offset with every capture so video / IMU
    can be aligned to the recording's PC time base afterwards.
  * Capture: when a recording starts, the hub tells armed phones to start
    their camera; when it stops, the phone uploads the clip, which lands in
    the recording folder as video.webm + capture.json; IMU samples stream
    live into imu.csv.
  * Future devices (throttle robot, other Teensys) register as `DeviceClient`
    objects — see steering/devices/base.py.

Control from remote clients is limited to the `REMOTE_ACTIONS` allow-list
unless `allow_remote_control` is set.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from pathlib import Path
from typing import Dict, Optional, Set

from .. import protocol as P

try:   # optional dependency; imported at module level so `from __future__ import annotations` resolves them
    from fastapi import FastAPI, Request, UploadFile, WebSocket, WebSocketDisconnect
    from fastapi.exceptions import WebSocketRequestValidationError
    from fastapi.responses import FileResponse, JSONResponse
    import uvicorn
    HAVE_SERVER = True
except ImportError:                                   # pragma: no cover
    HAVE_SERVER = False

log = logging.getLogger(__name__)

REMOTE_ACTIONS_SAFE = {"disable", "emergency_rest", "record_start", "record_stop", "stop_stream"}

PHONE_DIR = Path(__file__).resolve().parents[3] / "phone"


class Hub:
    def __init__(self, app, host: str = "0.0.0.0", port: int = 8765, allow_remote_control: bool = False):
        self.app = app
        self.host, self.port = host, port
        self.allow_remote_control = allow_remote_control
        self.status = {"running": False, "clients": 0, "error": "", "url": ""}
        self.phone_status = {"connected": False, "offset_ms": None, "jitter_ms": None, "capturing": False}
        self._clients: Set = set()
        self._phones: Dict[int, dict] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._server = None
        self._telemetry_n = 0
        self._active_rec_uid: Optional[str] = None

    # ---- lifecycle --------------------------------------------------------------------
    def start(self):
        if self.status["running"]:
            return
        if not HAVE_SERVER:
            self.status["error"] = "install with: pip install 'genauto-steering[server]'"
            log.error(self.status["error"])
            return
        self._thread = threading.Thread(target=self._run, name="hub", daemon=True)
        self._thread.start()

    def stop(self):
        if self._server:
            self._server.should_exit = True
        self.status["running"] = False

    def _run(self):
        api = FastAPI(title="genauto-steering hub")
        hub = self

        @api.exception_handler(WebSocketRequestValidationError)
        async def _ws_validation(sock, exc):
            log.error("websocket validation error: %s", exc.errors())
            await sock.close()

        @api.get("/")
        async def index():
            return FileResponse(PHONE_DIR / "index.html")

        @api.get("/status")
        async def status():
            t = hub.app.controller.live.telemetry
            return {"ctrl_state": P.CS_NAMES.get(hub.app.controller.live.ctrl_state),
                    "position_deg": t.position_deg if t else None,
                    "health": hub.app.controller.live.tree.summary_line(),
                    "recording": hub.app.recorder.status, "clients": len(hub._clients)}

        @api.post("/capture/upload")
        async def upload(request: Request, file: UploadFile, uid: str, start_server_ms: float,
                         offset_ms: float = 0.0, kind: str = "video"):
            rec = hub.app.store.get(uid)
            if rec is None:
                return JSONResponse({"error": "unknown recording"}, status_code=404)
            ext = "webm" if "webm" in (file.content_type or "") else "mp4"
            dst = rec.dir / f"video.{ext}"
            with open(dst, "wb") as f:
                while chunk := await file.read(1 << 20):
                    f.write(chunk)
            meta = {"file": dst.name, "start_server_ms": start_server_ms, "phone_offset_ms": offset_ms,
                    "recording_created_at_ms": rec.created_at * 1000,
                    "video_start_rel_s": (start_server_ms - rec.created_at * 1000) / 1000.0}
            (rec.dir / "capture.json").write_text(json.dumps(meta, indent=2))
            rec.has_video = True
            hub.app.store.finalize(rec)
            log.info("video stored for %s (%s)", rec.name, dst)
            return {"ok": True, **meta}

        @api.websocket("/ws")
        async def ws(sock: WebSocket):
            await sock.accept()
            cid = id(sock)
            hub._clients.add(sock)
            hub.status["clients"] = len(hub._clients)
            imu_fh = None
            try:
                await sock.send_text(json.dumps({"type": "hello", "server_ms": time.time() * 1000,
                                                 "recording": hub._rec_msg()}))
                while True:
                    msg = json.loads(await sock.receive_text())
                    t = msg.get("type")
                    if t == "ping":
                        await sock.send_text(json.dumps({"type": "pong", "t0": msg.get("t0"),
                                                         "server_ms": time.time() * 1000}))
                    elif t == "sync":
                        hub._phones[cid] = {"offset_ms": msg.get("offset_ms"), "jitter_ms": msg.get("jitter_ms"),
                                            "capturing": msg.get("capturing", False), "t": time.time()}
                        hub._refresh_phone_status()
                    elif t == "imu":
                        uid = msg.get("uid")
                        rec = hub.app.store.get(uid) if uid else None
                        if rec is not None:
                            if imu_fh is None or imu_fh.name != str(rec.dir / "imu.csv"):
                                if imu_fh:
                                    imu_fh.close()
                                new = not (rec.dir / "imu.csv").exists()
                                imu_fh = open(rec.dir / "imu.csv", "a")
                                if new:
                                    imu_fh.write("t_rel_s,ax,ay,az,gx,gy,gz\n")
                            for s in msg.get("samples", []):
                                t_rel = (s[0] - rec.created_at * 1000) / 1000.0
                                imu_fh.write(f"{t_rel:.4f}," + ",".join(f"{v:.4f}" for v in s[1:7]) + "\n")
                    elif t == "cmd":
                        await sock.send_text(json.dumps({"type": "cmd_result", **hub._remote_cmd(msg)}))
            except WebSocketDisconnect:
                pass
            except Exception:
                log.exception("ws client error")
            finally:
                if imu_fh:
                    imu_fh.close()
                hub._clients.discard(sock)
                hub._phones.pop(cid, None)
                hub.status["clients"] = len(hub._clients)
                hub._refresh_phone_status()

        async def broadcaster():
            unsub = []
            q: asyncio.Queue = asyncio.Queue(maxsize=200)
            loop = asyncio.get_running_loop()

            def push(item):
                try:
                    loop.call_soon_threadsafe(q.put_nowait, item)
                except Exception:
                    pass

            def on_telem(t):
                hub._telemetry_n += 1
                if hub._telemetry_n % 10 == 0:          # 20 Hz to phones
                    push({"type": "telemetry", "cs": t.ctrl_state, "pos": round(t.position_deg, 2),
                          "sp": round(t.setpoint_deg, 2), "vel": round(t.velocity_deg_s, 1),
                          "cur": round(t.current_A, 2)})
            unsub.append(hub.app.bus.subscribe("telemetry", on_telem))
            unsub.append(hub.app.bus.subscribe("recording", lambda s: push({"type": "recording", **hub._rec_msg()})))
            unsub.append(hub.app.bus.subscribe("health_transition", lambda ch: push({"type": "health_transition", **ch})))
            unsub.append(hub.app.bus.subscribe("event", lambda e: push({"type": "event", "code": P.EV_NAMES.get(e.code),
                                                                        "arg": e.arg, "text": e.text_str})))
            last_health = 0.0
            while hub.status["running"]:
                try:
                    item = await asyncio.wait_for(q.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    item = None
                now = time.monotonic()
                msgs = [item] if item else []
                if now - last_health > 0.5:
                    last_health = now
                    tree = hub.app.controller.live.tree
                    msgs.append({"type": "health", "summary": tree.summary_line(),
                                 "groups": {g: tree.group_state(g)[0] for g in "ABCDEF"},
                                 "bad": [{"id": s.id, "s": s.state, "r": s.reason} for s in tree.bad_nodes()]})
                for m in msgs:
                    data = json.dumps(m)
                    for c in list(hub._clients):
                        try:
                            await c.send_text(data)
                        except Exception:
                            hub._clients.discard(c)
            for u in unsub:
                u()

        @api.on_event("startup")
        async def _startup():
            hub.status["running"] = True
            asyncio.create_task(broadcaster())

        config = uvicorn.Config(api, host=self.host, port=self.port, log_level="warning")
        self._server = uvicorn.Server(config)
        self.status["url"] = f"http://<laptop-ip>:{self.port}/"
        try:
            self._server.run()
        except Exception as e:
            self.status["error"] = str(e)
            log.exception("hub failed")
        finally:
            self.status["running"] = False

    # ---- helpers -----------------------------------------------------------------------
    def _rec_msg(self) -> dict:
        r = self.app.recorder
        return {"active": r.active, "uid": r.rec.uid if r.rec else None, "name": r.rec.name if r.rec else None,
                "created_at_ms": r.rec.created_at * 1000 if r.rec else None}

    def _refresh_phone_status(self):
        live = [p for p in self._phones.values() if time.time() - p["t"] < 5]
        if not live:
            self.phone_status = {"connected": False, "offset_ms": None, "jitter_ms": None, "capturing": False}
        else:
            p = live[-1]
            self.phone_status = {"connected": True, "offset_ms": p["offset_ms"], "jitter_ms": p["jitter_ms"],
                                 "capturing": bool(p["capturing"])}

    def _remote_cmd(self, msg: dict) -> dict:
        action = msg.get("action", "")
        if action not in REMOTE_ACTIONS_SAFE and not self.allow_remote_control:
            return {"ok": False, "error": f"{action} not allowed remotely"}
        c = self.app.controller
        try:
            if action == "emergency_rest":
                c.emergency_rest("remote")
            elif action == "disable":
                c.disable()
            elif action == "record_start":
                c.record_start(msg.get("name", "phone"), notes="started from phone")
            elif action == "record_stop":
                c.record_stop()
            elif action == "stop_stream":
                c.stop_all()
            elif action == "enable":
                c.enable()
            elif action == "set_zero":
                c.set_zero()
            else:
                return {"ok": False, "error": "unknown action"}
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}
