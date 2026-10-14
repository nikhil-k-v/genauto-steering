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
  * Planner input: with `allow_remote_control`, a client may stream
    {"type":"setpoint","pos_deg":..,"vel_ff":..} at up to 200 Hz — this is the
    intended path for the ROS2 stack on the AGX Orin (desired steering angle
    from the motion planner).  It goes through Controller.external_setpoint,
    i.e. the same gating as a local trajectory, and the firmware's 250 ms
    stream watchdog drops to HOLD if the planner dies.
  * Future devices (throttle robot, other Teensys) register as `Device`
    objects — see steering/devices/base.py.

Control from remote clients is limited to the `REMOTE_ACTIONS` allow-list
unless `allow_remote_control` is set.

Reaching it (server/net.py): http://<laptop-ip>:<port>/ on the Wi-Fi, http://<name>.local:<port>/
when zeroconf is installed, and the GitHub Pages copy of the web UI, which talks to
http://localhost:<port> directly (CORS below allows that origin) or hands other devices over
to the laptop's address.  Browsers only: the WebSocket refuses pages from any other origin,
so a random website open in the operator's browser cannot reach the hub.
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
from .. import words as W
from .net import Advertiser, hub_urls, pages_origin, qr_svg

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

REPO = Path(__file__).resolve().parents[3]
PHONE_DIR = REPO / "phone"
WEB_DIR = REPO / "web"
DOCS_DIR = REPO / "docs"

DOC_PAGES = [("README", "Overview", REPO / "README.md"), ("ARCHITECTURE", "Architecture", DOCS_DIR / "ARCHITECTURE.md"),
             ("HARDWARE", "Hardware", DOCS_DIR / "HARDWARE.md"), ("PROTOCOL", "Protocol", DOCS_DIR / "PROTOCOL.md"),
             ("HEALTH", "Health & status", DOCS_DIR / "HEALTH.md"), ("HEALTH_REFERENCE", "Health reference", DOCS_DIR / "HEALTH_REFERENCE.md"),
             ("SAFETY", "Safety", DOCS_DIR / "SAFETY.md"), ("DATA", "Data", DOCS_DIR / "DATA.md"),
             ("OPERATIONS", "Operations", DOCS_DIR / "OPERATIONS.md"), ("MIGRATION", "Migration", DOCS_DIR / "MIGRATION.md"),
             ("ROADMAP", "Roadmap", DOCS_DIR / "ROADMAP.md")]


class Hub:
    def __init__(self, app, host: str = "0.0.0.0", port: int = 8765, allow_remote_control: bool = False,
                 pages_url: str = "", mdns_name: str = ""):
        self.app = app
        self.host, self.port = host, port
        self.allow_remote_control = allow_remote_control
        self.pages_url = pages_url
        self.mdns = Advertiser(mdns_name, port) if mdns_name else None
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
        if self.mdns:
            self.mdns.stop()
        self.status["running"] = False

    def urls(self) -> dict:
        return hub_urls(self.port, self.pages_url, self.mdns.name if self.mdns else "", bool(self.mdns and self.mdns.ok))

    def origin_allowed(self, origin: Optional[str], host: Optional[str]) -> bool:
        """Browser origins that may use the hub: its own pages, and the GitHub Pages front door."""
        if not origin:                       # not a browser (ROS bridge, scripts, phones' native apps)
            return True
        from urllib.parse import urlsplit
        o = urlsplit(origin)
        if host and o.netloc == host:
            return True
        if o.hostname in ("localhost", "127.0.0.1") and o.port == self.port:
            return True
        po = pages_origin(self.pages_url)
        return bool(po) and origin == po

    def _run(self):
        api = FastAPI(title="genauto-steering hub")
        hub = self

        @api.exception_handler(WebSocketRequestValidationError)
        async def _ws_validation(sock, exc):
            log.error("websocket validation error: %s", exc.errors())
            await sock.close()

        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import Response
        from fastapi.staticfiles import StaticFiles
        from ..health.model import GROUPS, NODES
        from ..data.analysis import load_csv

        # The GitHub Pages copy of these pages may call the hub on http://localhost (same laptop).
        # Chrome also asks before a public https page talks to a private/loopback address (Private
        # Network Access preflight); answer yes for that origin only.
        po = pages_origin(hub.pages_url)
        if po:
            import inspect
            pna = "allow_private_network" in inspect.signature(CORSMiddleware.__init__).parameters
            api.add_middleware(CORSMiddleware, allow_origins=[po], allow_methods=["GET", "POST"],
                               allow_headers=["content-type"], **({"allow_private_network": True} if pna else {}))
            if not pna:                                  # older Starlette: add the header ourselves
                @api.middleware("http")
                async def private_network(request: Request, call_next):
                    resp = await call_next(request)
                    if request.headers.get("origin") == po and request.method == "OPTIONS":
                        resp.headers["Access-Control-Allow-Private-Network"] = "true"
                    return resp

        @api.get("/api/info")
        async def api_info():
            return {"name": "Gen Auto steering hub", "port": hub.port, "urls": hub.urls(),
                    "remote_control": hub.allow_remote_control, "mdns": bool(hub.mdns and hub.mdns.ok)}

        @api.get("/api/qr.svg")
        async def api_qr(text: str):
            svg = qr_svg(text)
            if svg is None:
                return JSONResponse({"error": "install segno for QR codes"}, status_code=404)
            return Response(svg, media_type="image/svg+xml")

        @api.get("/")
        async def index():
            return FileResponse(WEB_DIR / "index.html")

        @api.get("/phone")
        async def phone_page():
            return FileResponse(PHONE_DIR / "index.html")

        api.mount("/diagrams", StaticFiles(directory=str(DOCS_DIR / "diagrams")), name="diagrams")
        api.mount("/screenshots", StaticFiles(directory=str(DOCS_DIR / "screenshots")), name="screenshots")
        if (WEB_DIR / "fonts").is_dir():
            api.mount("/fonts", StaticFiles(directory=str(WEB_DIR / "fonts")), name="fonts")

        @api.get("/api/health")
        async def api_health():
            tree = hub.app.controller.live.tree
            return {"groups": [{"id": g, "name": gd.name, "short": gd.short, "question": gd.question,
                                "state": tree.group_state(g)[0]} for g, gd in GROUPS.items()],
                    "nodes": [{"id": n.id, "group": n.group, "name": n.name, "ok": n.ok_means, "bad": n.bad_means,
                               "fix": n.fix, "source": n.source, "optional": n.optional,
                               "state": tree.nodes[n.id].state, "reason": tree.nodes[n.id].reason,
                               "since": tree.nodes[n.id].since} for n in NODES]}

        @api.get("/api/recordings")
        async def api_recordings(sort: str = "recent", collection: str = "", search: str = "", playbacks: int = 1):
            recs = hub.app.store.list(sort=sort, collection=collection or None, search=search, include_playbacks=False)
            out = []
            for r in recs:
                d = hub._rec_json(r)
                if playbacks:
                    d["playbacks"] = [hub._rec_json(p) for p in hub.app.store.playbacks_of(r.uid)]
                out.append(d)
            return {"recordings": out, "collections": hub.app.store.collections()}

        @api.get("/api/recordings/{uid}")
        async def api_recording(uid: str):
            r = hub.app.store.get(uid)
            if not r:
                return JSONResponse({"error": "not found"}, status_code=404)
            d = hub._rec_json(r)
            d["playbacks"] = [hub._rec_json(p) for p in hub.app.store.playbacks_of(r.uid)]
            if r.parent_uid:
                pr = hub.app.store.get(r.parent_uid)
                d["parent"] = hub._rec_json(pr) if pr else None
            for name in ("events.jsonl", "health.jsonl", "capture.json"):
                p = r.dir / name
                d["has_" + name.split(".")[0]] = p.exists()
            d["video"] = next((f.name for f in r.dir.glob("video.*")), None)
            return d

        @api.get("/api/recordings/{uid}/data")
        async def api_recording_data(uid: str, max_points: int = 4000):
            r = hub.app.store.get(uid)
            if not r or not r.csv.exists():
                return JSONResponse({"error": "not found"}, status_code=404)
            d = load_csv(r.csv)
            n = len(d["t_s"])
            step = max(1, n // max_points)
            def col(k):
                return [None if x != x else round(float(x), 4) for x in d[k][::step]]
            return {"n": n, "step": step, "columns": {k: col(k) for k in d}}

        @api.get("/api/recordings/{uid}/events")
        async def api_recording_events(uid: str):
            r = hub.app.store.get(uid)
            if not r:
                return JSONResponse({"error": "not found"}, status_code=404)
            out = {}
            for name in ("events", "health"):
                p = r.dir / f"{name}.jsonl"
                lines = []
                if p.exists():
                    for line in p.read_text().splitlines()[:2000]:
                        try:
                            lines.append(json.loads(line))
                        except Exception:
                            pass
                out[name] = lines
            return out

        @api.get("/api/recordings/{uid}/video")
        async def api_recording_video(uid: str):
            r = hub.app.store.get(uid)
            v = next(iter(r.dir.glob("video.*")), None) if r else None
            if not v:
                return JSONResponse({"error": "no video"}, status_code=404)
            return FileResponse(v)

        @api.post("/api/recordings/{uid}")
        async def api_recording_edit(uid: str, request: Request):
            body = await request.json()
            st = hub.app.store
            if st.get(uid) is None:
                return JSONResponse({"error": "not found"}, status_code=404)
            if "pinned" in body:
                st.set_pinned(uid, bool(body["pinned"]))
            if "notes" in body:
                st.set_notes(uid, str(body["notes"]))
            if "tags" in body:
                st.set_tags(uid, [t for t in str(body["tags"]).split(",")])
            if "name" in body and body["name"]:
                st.rename(uid, str(body["name"]))
            if body.get("delete"):
                st.soft_delete(uid)
            return hub._rec_json(st.get(uid))

        @api.get("/api/docs")
        async def api_docs():
            return {"docs": [{"id": i, "title": t} for i, t, p in DOC_PAGES if p.exists()]}

        @api.get("/api/docs/{doc_id}")
        async def api_doc(doc_id: str):
            for i, t, p in DOC_PAGES:
                if i == doc_id and p.exists():
                    text = p.read_text()
                    html = hub._markdown(text)
                    return {"id": i, "title": t, "html": html}
            return JSONResponse({"error": "not found"}, status_code=404)

        @api.get("/status")
        async def status():
            t = hub.app.controller.live.telemetry
            c = hub.app.controller
            fw = c.live.health_fw
            return {"ctrl_state": P.CS_NAMES.get(c.live.ctrl_state),
                    "state_word": W.STREAM_STATE.get(c.stream_kind if c.streamer.active else "planner", W.STATE[P.CS_TRAJ])
                    if c.live.ctrl_state == P.CS_TRAJ else W.STATE.get(c.live.ctrl_state, ""),
                    "trip": W.trip_line(fw.trip_code, c.live.trip_text) + ". " + W.TRIP_WHY.get(fw.trip_code, "")
                    if fw and fw.trip_code else "",
                    "setpoint_source": c.setpoint_source(),
                    "position_deg": t.position_deg if t else None,
                    "health": hub.app.controller.live.tree.summary_line(),
                    "recording": hub.app.recorder.status, "clients": len(hub._clients),
                    "telemetry_hz": round(hub.app.link.stats.telemetry_hz, 1)}

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
            if not hub.origin_allowed(sock.headers.get("origin"), sock.headers.get("host")):
                log.warning("refused websocket from %s", sock.headers.get("origin"))
                await sock.close(code=1008)
                return
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
                    elif t == "setpoint":
                        # live planner stream (gated; needs allow_remote_control)
                        if hub.allow_remote_control:
                            r = hub.app.controller.external_setpoint(float(msg.get("pos_deg", 0.0)), float(msg.get("vel_ff", 0.0)))
                            if not r.ok and msg.get("ack"):
                                await sock.send_text(json.dumps({"type": "setpoint_refused", "reasons": r.reasons}))
                        elif msg.get("ack"):
                            await sock.send_text(json.dumps({"type": "setpoint_refused", "reasons": ["remote control not enabled"]}))
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
                    push({"type": "telemetry", "cs": t.ctrl_state, "src": hub.app.controller.setpoint_source(),
                          "pos": round(t.position_deg, 2),
                          "sp": round(t.setpoint_deg, 2), "vel": round(t.velocity_deg_s, 1),
                          "cur": round(t.current_A, 2)})
            unsub.append(hub.app.bus.subscribe("telemetry", on_telem))
            unsub.append(hub.app.bus.subscribe("recording", lambda s: push({"type": "recording", **hub._rec_msg()})))
            unsub.append(hub.app.bus.subscribe("health_transition", lambda ch: push({"type": "health_transition", **ch})))
            def on_event(e):
                said = W.event_text(e.code, e.arg, e.text_str)
                push({"type": "event", "code": P.EV_NAMES.get(e.code), "arg": e.arg, "text": e.text_str,
                      "say": said[0] if said else "", "level": said[1] if said else "info"})
            unsub.append(hub.app.bus.subscribe("event", on_event))
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
                                 "groups": {g: tree.group_state(g)[0] for g in "MSTCD"},
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
            if hub.mdns:
                threading.Thread(target=hub.mdns.start, name="mdns", daemon=True).start()

        config = uvicorn.Config(api, host=self.host, port=self.port, log_level="warning")
        self._server = uvicorn.Server(config)
        self.status["url"] = (self.urls().get("lan") or [f"http://localhost:{self.port}/"])[0]
        self.status["pages"] = {"web": "/", "phone": "/phone"}
        try:
            self._server.run()
        except Exception as e:
            self.status["error"] = str(e)
            log.exception("hub failed")
        finally:
            self.status["running"] = False

    # ---- helpers -----------------------------------------------------------------------
    @staticmethod
    def _rec_json(r) -> dict:
        return {"uid": r.uid, "name": r.name, "kind": r.kind, "collection": r.collection, "created_at": r.created_at,
                "created_str": r.created_str, "parent_uid": r.parent_uid, "duration_s": r.duration_s, "samples": r.samples,
                "pinned": r.pinned, "tags": r.tags, "notes": r.notes, "metrics": r.metrics, "health_summary": r.health_summary,
                "health_worst": r.health_worst, "gains": r.gains, "has_video": r.has_video, "playback_count": r.playback_count,
                "path": r.path}

    @staticmethod
    def _markdown(text: str) -> str:
        # make relative doc links/images resolve inside the web UI
        # relative, so the same HTML works under the hub ("/") and on GitHub Pages ("/genauto-steering/")
        text = text.replace("](docs/diagrams/", "](diagrams/").replace("](docs/screenshots/", "](screenshots/")
        try:
            import markdown
            return markdown.markdown(text, extensions=["tables", "fenced_code", "toc"])
        except Exception:
            import html
            return "<pre>" + html.escape(text) + "</pre>"

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
