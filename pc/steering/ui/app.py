"""
ui/app.py - the desktop UI shell (Dear PyGui).

    +--------------------------------------------------------------------------+
    |  connect  [ SYSTEM STRIP: laptop <=USB=> teensy <=CAN=> motor ]  REST    |
    +---------------+----------------------------------------------------------+
    | MOTOR         |  tabs:  Live | Trajectory | Playback | Tuning | Calib    |
    | WHEEL         |         Health | Settings                                |
    | GAINS         |                                                          |
    | RECORDING     |                                                          |
    | EVENTS (mono) |                                                          |
    +---------------+----------------------------------------------------------+

Rules the shell enforces:
  * every callback goes through safe() - the UI cannot crash
  * every motion control is bound through GateBinder - disabled with the exact
    reason when the health tree says so, and literally wired to the status
    tiles it depends on (hover it: lines appear)
  * sizes are derived from the viewport each frame; only lists scroll
"""
from __future__ import annotations

import logging
import time
from collections import deque
from typing import Dict, Optional

import dearpygui.dearpygui as dpg

from .. import protocol as P
from ..core.app import App
from ..link import list_serial_ports
from . import theme as T
from .gate import GateBinder
from .overlay import Overlay
from .safe import attach_evaluator, safe, toast, toasts
from .strip import STRIP_H, SystemStrip
from .panels.live import LivePanel
from .panels.trajectory import TrajectoryPanel
from .panels.playback import PlaybackPanel
from .panels.tuning import TuningPanel
from .panels.calibration import CalibrationPanel
from .panels.health import HealthPanel
from .panels.settings import SettingsPanel

log = logging.getLogger(__name__)

LEFT_W = 350
TOP_H = STRIP_H + 52


class UI:
    def __init__(self, app: App, sim: bool = False):
        self.app = app
        self.c = app.controller
        self.sim = sim
        self.gate = GateBinder(self.c)
        self.strip = SystemStrip(self)
        self.overlay = Overlay(self)
        self.events: deque = deque(maxlen=200)
        self.panels: Dict[str, object] = {}
        self._frame = 0
        self._last_slow = 0.0
        self.tags: Dict[str, int] = {}
        app.bus.subscribe("event", self._on_event)
        app.bus.subscribe("ui_action", self._on_action)
        attach_evaluator(app.evaluator)

    # ---- event feed ---------------------------------------------------------------------
    def _on_event(self, e: P.EventPacket):
        name = P.EV_NAMES.get(e.code, str(e.code))
        if e.code == P.EV_TRIP:
            txt, lvl = f"TRIP {P.TRIP_NAMES.get(e.arg, e.arg)} - {e.text_str}", "bad"
        elif e.code == P.EV_CMD_REJECTED:
            txt, lvl = f"Teensy refused {P.CMD_NAMES.get(e.arg, hex(e.arg))}: {e.text_str}", "warn"
        elif e.code == P.EV_STATE:
            txt, lvl = f"state -> {P.CS_NAMES.get(e.arg, e.arg)}", "info"
        elif e.code == P.EV_CALIB_STAGE:
            txt, lvl = f"calibration: {P.CAL_NAMES.get(e.arg, e.arg)}", "info"
        elif e.code == P.EV_CMD_ACCEPTED:
            return
        else:
            txt, lvl = f"{name} {e.arg} {e.text_str}".strip(), "info"
        self.events.appendleft((time.strftime("%H:%M:%S"), lvl, txt))
        if lvl != "info":
            toast(txt, lvl, 6)

    def _on_action(self, a: dict):
        if not a.get("allowed", True):
            self.events.appendleft((time.strftime("%H:%M:%S"), "warn", f"blocked {a['action']}: " + "; ".join(a.get("reasons", []))))

    # ---- build ----------------------------------------------------------------------------
    def build(self):
        dpg.create_context()
        T.build()
        dpg.create_viewport(title="Gen Auto - Steering", width=1560, height=980, min_width=1200, min_height=760)
        with dpg.window(tag="root", no_title_bar=True, no_move=True, no_resize=True, no_collapse=True,
                        no_scrollbar=True, no_bring_to_front_on_focus=True):
            self._build_top()
            with dpg.group(horizontal=True):
                with dpg.child_window(tag="left", width=LEFT_W, border=True):
                    self._build_left()
                with dpg.child_window(tag="right", border=False, no_scrollbar=True):
                    with dpg.tab_bar(tag="tabs"):
                        for key, label, cls in (("live", "Live", LivePanel), ("traj", "Trajectory", TrajectoryPanel),
                                                ("play", "Playback & Library", PlaybackPanel),
                                                ("tune", "Tuning", TuningPanel), ("cal", "Calibration", CalibrationPanel),
                                                ("health", "Health", HealthPanel), ("settings", "Settings", SettingsPanel)):
                            with dpg.tab(label=label, tag=f"tab_{key}"):
                                with dpg.child_window(tag=f"tabc_{key}", border=False, no_scrollbar=(key in ("live",))):
                                    p = cls(self)
                                    p.build()
                                    self.panels[key] = p
            self._build_toasts()
        self.overlay.build()
        dpg.set_primary_window("root", True)
        dpg.set_viewport_resize_callback(safe(self._on_resize))
        dpg.setup_dearpygui()
        dpg.show_viewport()
        self._on_resize()

    def _build_top(self):
        with dpg.child_window(tag="topbar", height=TOP_H, border=False, no_scrollbar=True):
            with dpg.group(horizontal=True):
                ports = list_serial_ports()
                items = ["sim"] + [p[0] for p in ports]
                default = "sim" if self.sim else (self.app.settings.last_port or (items[1] if len(items) > 1 else "sim"))
                self.tags["port"] = dpg.add_combo(items, default_value=default, width=170)
                dpg.bind_item_theme(self.tags["port"], T.theme("input"))
                T.bind_font(self.tags["port"], "mono")
                self.tags["connect"] = T.action("Connect", "accent", safe(self._connect), width=110)
                T.action("refresh ports", "ghost", safe(self._refresh_ports), width=110)
                dpg.add_spacer(width=30)
                self.tags["state"] = dpg.add_text("NO LINK", color=T.DIM)
                T.bind_font(self.tags["state"], "big")
                self.tags["state_sub"] = dpg.add_text("", color=T.DIM, wrap=640)
                T.bind_font(self.tags["state_sub"], "small")
                dpg.add_spacer(width=30)
                b = T.action("REST MOTOR", "bad", safe(lambda: self.c.emergency_rest("button")), width=150)
                with dpg.tooltip(b):
                    dpg.add_text("Always available: stops any stream/recording and sends DISABLE.")
            self.strip.build()

    def _build_left(self):
        g, c = self.gate, self.c
        T.section("Motor")
        with dpg.group(horizontal=True):
            b = T.action("Enable", "ok", safe(c.enable), 100); g.bind(b, "enable", "Enter FOC and hold the current position.")
            b = T.action("Disable", "neutral", safe(c.disable), 100); g.bind(b, "disable", "Exit FOC (motor goes limp).")
            b = T.action("Clear trip", "neutral", safe(c.clear_trip), 100); g.bind(b, "clear_trip", "Unlatch a safety trip -> REST.")
        with dpg.group(horizontal=True):
            b = T.action("Free-spin", "warn", safe(c.freespin_on), 100); g.bind(b, "freespin_on", "Zero torque: turn the wheel by hand (and record it).")
            b = T.action("Re-grip", "neutral", safe(c.freespin_off), 100); g.bind(b, "freespin_off", "Leave free-spin and hold here.")
            b = T.action("Hold here", "neutral", safe(c.hold_here), 100); g.bind(b, "hold_here", "Stop following and hold the current position.")
        dpg.add_spacer(height=6)

        T.section("Wheel")
        with dpg.child_window(height=86, border=True, no_scrollbar=True) as rd:
            dpg.bind_item_theme(rd, T.theme("readout"))
            self.tags["pos_big"] = dpg.add_text("--", color=T.TEXT)
            T.bind_font(self.tags["pos_big"], "big")
            self.tags["posline"] = T.mono_text("setpoint --   error --   vel --")
        self.tags["slider"] = dpg.add_slider_float(default_value=0.0, min_value=-180, max_value=180, width=-1, format="%.1f deg",
                                                   callback=safe(self._slider))
        dpg.bind_item_theme(self.tags["slider"], T.theme("slider"))
        g.bind(self.tags["slider"], "slider", "Drag to command a position (HOLD only). The firmware slews it, so it can never jump.")
        T.action("Center (0 deg)", "ghost", safe(lambda: self._set_slider(0.0)), 120)
        dpg.add_spacer(height=6)

        T.section("Gains  -  motor loop Kp Kd, Teensy Ki Tff")
        gains = self.app.settings.gains
        with dpg.group(horizontal=True):
            self.tags["kp"] = T.number("Kp", gains["kp"], 80, "%.1f")
            self.tags["kd"] = T.number("Kd", gains["kd"], 80, "%.2f")
            self.tags["ki"] = T.number("Ki", gains["ki"], 80, "%.2f")
        with dpg.group(horizontal=True):
            self.tags["tff"] = T.number("Tff", gains["tff"], 80, "%.2f")
            b = T.action("Apply gains", "accent", safe(self._apply_gains), 120); g.bind(b, "set_gains", "Send Kp/Kd/Ki/Tff. The line below shows what the Teensy is actually using.")
        self.tags["gains_echo"] = T.mono_text("teensy: --", color=T.DIM)
        with dpg.tooltip(self.tags["kp"]):
            dpg.add_text("Kp [Nm/rad] and Kd [Nm/(rad/s)] run inside the motor's 20 kHz loop.\nKi [Nm/(rad s)] and Tff [Nm] are added by the Teensy as torque feed-forward.", wrap=360)
        dpg.add_spacer(height=6)

        T.section("Recording")
        with dpg.group(horizontal=True):
            self.tags["rec_name"] = T.text_input("manual", 140, "name")
            self.tags["rec_coll"] = dpg.add_combo(self.app.store.collections(), default_value=self.app.settings.collection,
                                                  width=120, callback=safe(self._set_collection))
            dpg.bind_item_theme(self.tags["rec_coll"], T.theme("input"))
            T.action("+", "ghost", safe(self._new_collection), 26)
        with dpg.group(horizontal=True):
            b = T.action("Record", "bad", safe(self._record), 100); g.bind(b, "record", "Record telemetry + health + events now (any state).")
            b = T.action("Stop", "neutral", safe(c.record_stop), 100); g.bind(b, "stop_record")
            self.tags["rec_status"] = T.mono_text("idle", color=T.DIM)
        dpg.add_spacer(height=6)

        T.section("Events  -  firmware + blocked actions")
        with dpg.child_window(tag="events", height=-1, border=True) as ev:
            dpg.bind_item_theme(ev, T.theme("readout"))
            self.tags["events"] = [T.mono_text("", wrap=LEFT_W - 30) for _ in range(16)]
            for t in self.tags["events"]:
                T.bind_font(t, "mono_s")

    def _build_toasts(self):
        with dpg.window(tag="toasts", no_title_bar=True, no_move=True, no_resize=True,
                        no_focus_on_appearing=True, autosize=True, show=False):
            self.tags["toast_lines"] = [dpg.add_text("", wrap=560) for _ in range(6)]
            for t in self.tags["toast_lines"]:
                T.bind_font(t, "mono_b")

    # ---- callbacks ------------------------------------------------------------------------------
    def _refresh_ports(self):
        dpg.configure_item(self.tags["port"], items=["sim"] + [p[0] for p in list_serial_ports()])

    def _connect(self):
        port = dpg.get_value(self.tags["port"])
        if self.app.link.stats.port_open:
            self.app.link.disconnect()
            return
        if port == "sim":
            from ..sim import SimTransport
            self.app.link.connect(SimTransport())
        else:
            self.app.connect_port(port)
        toast(f"connecting to {port}")

    def goto_health(self, group: str):
        dpg.set_value("tabs", "tab_health")
        self.panels["health"].select_group(group)

    def _slider(self, sender, value):
        r = self.c.slider(value)
        if not r.ok:
            toast(r.tooltip, "warn", 2)

    def _set_slider(self, v):
        dpg.set_value(self.tags["slider"], v)
        self._slider(None, v)

    def _apply_gains(self):
        kp, kd, ki, tff = (dpg.get_value(self.tags[k]) for k in ("kp", "kd", "ki", "tff"))
        self.c.set_gains(kp, kd, ki, tff)
        self.app.settings.gains = {"kp": kp, "kd": kd, "ki": ki, "tff": tff}
        self.app.settings.save()

    def set_gain_inputs(self, kp, kd, ki, tff=None):
        dpg.set_value(self.tags["kp"], kp); dpg.set_value(self.tags["kd"], kd); dpg.set_value(self.tags["ki"], ki)
        if tff is not None:
            dpg.set_value(self.tags["tff"], tff)

    def _record(self):
        kind = "freespin" if self.c.live.ctrl_state == P.CS_FREESPIN else "manual"
        self.c.record_start(dpg.get_value(self.tags["rec_name"]) or "manual", kind=kind)

    def _set_collection(self, sender, value):
        self.app.settings.collection = value
        self.app.settings.save()

    def _new_collection(self):
        name = (dpg.get_value(self.tags["rec_name"]) or "").strip()
        if not name:
            toast("type the new collection name in the name box, then press +", "warn")
            return
        items = sorted(set(self.app.store.collections()) | {name})
        dpg.configure_item(self.tags["rec_coll"], items=items)
        dpg.set_value(self.tags["rec_coll"], name)
        self._set_collection(None, name)

    def _on_resize(self):
        w, h = dpg.get_viewport_client_width(), dpg.get_viewport_client_height()
        dpg.configure_item("left", height=h - TOP_H - 16)
        dpg.configure_item("right", width=w - LEFT_W - 24, height=h - TOP_H - 16)
        self.strip.set_width(w - 16)
        for key, p in self.panels.items():
            if hasattr(p, "on_resize"):
                p.on_resize(w - LEFT_W - 40, h - TOP_H - 70)
        dpg.configure_item("toasts", pos=(w - 620, h - 150))

    # ---- per-frame ----------------------------------------------------------------------------------
    def _tick(self):
        self.app.evaluator.note_ui_frame()
        self._frame += 1
        live = self.c.live
        t = live.telemetry
        self.gate.refresh()
        self.strip.refresh()
        node_tiles = self.panels["health"].tiles if "health" in self.panels else {}
        self.overlay.refresh(self.gate, self.strip, node_tiles)

        cs = live.ctrl_state
        dpg.set_value(self.tags["state"], P.CS_NAMES.get(cs, "?") if t else "NO LINK")
        dpg.configure_item(self.tags["state"], color=T.CS_COLOR.get(cs, T.DIM) if t else T.BAD)
        banner = ""
        if live.health_fw and live.health_fw.trip_code:
            banner = f"TRIPPED: {P.TRIP_NAMES.get(live.health_fw.trip_code)} - " + P.TRIP_EXPLAIN.get(live.health_fw.trip_code, "")
        elif live.last_rejection and time.monotonic() - live.last_rejection_t < 6:
            banner = live.last_rejection
        if banner:
            dpg.set_value(self.tags["state_sub"], banner)
            dpg.configure_item(self.tags["state_sub"], color=T.BAD)
        else:
            dpg.set_value(self.tags["state_sub"], P.CS_EXPLAIN.get(cs, "") if t else "connect to the Teensy (or sim) to begin")
            dpg.configure_item(self.tags["state_sub"], color=T.DIM)
        dpg.set_item_label(self.tags["connect"], "Disconnect" if self.app.link.stats.port_open else "Connect")

        if t:
            dpg.set_value(self.tags["pos_big"], f"{t.position_deg:+7.1f} deg")
            dpg.set_value(self.tags["posline"], f"setpoint {t.setpoint_deg:+7.1f}   error {t.setpoint_deg - t.position_deg:+6.1f}   vel {t.velocity_deg_s:+6.0f}")
        cfg = live.config
        if cfg:
            pend = "  (pending...)" if live.pending_gains else ""
            dpg.set_value(self.tags["gains_echo"], f"teensy: Kp {cfg.kp:.1f}  Kd {cfg.kd:.2f}  Ki {cfg.ki:.2f}  Tff {cfg.tff_Nm:.2f}{pend}")
            dpg.configure_item(self.tags["gains_echo"], color=T.WARN if live.pending_gains else T.DIM)
            if cfg.limits_valid:
                dpg.configure_item(self.tags["slider"], min_value=cfg.limit_left_deg + 3, max_value=cfg.limit_right_deg - 3)
        if cs != P.CS_HOLD and t:
            dpg.set_value(self.tags["slider"], t.position_deg)
        rs = self.app.recorder.status
        dpg.set_value(self.tags["rec_status"], f"REC {rs['name']} {rs['elapsed']:.0f}s {rs['samples']} rows" if rs["active"] else "idle")
        dpg.configure_item(self.tags["rec_status"], color=T.BAD if rs["active"] else T.DIM)
        for i, line in enumerate(self.tags["events"]):
            if i < len(self.events):
                ts, lvl, txt = self.events[i]
                dpg.set_value(line, f"{ts}  {txt}")
                dpg.configure_item(line, color={"bad": T.BAD, "warn": T.WARN}.get(lvl, T.TEXT))
            else:
                dpg.set_value(line, "")
        ts = toasts()
        dpg.configure_item("toasts", show=bool(ts))
        for i, line in enumerate(self.tags["toast_lines"]):
            if i < len(ts):
                dpg.set_value(line, ts[i][1]); dpg.configure_item(line, color={"bad": T.BAD, "warn": T.WARN}.get(ts[i][0], T.OK), show=True)
            else:
                dpg.configure_item(line, show=False)
        active = dpg.get_value("tabs")
        for key, p in self.panels.items():
            try:
                if f"tab_{key}" == active or key == "live":
                    p.refresh()
            except Exception:
                log.exception("panel %s refresh failed", key)
        now = time.monotonic()
        if now - self._last_slow > 0.5:
            self._last_slow = now
            for key, p in self.panels.items():
                try:
                    if hasattr(p, "slow_refresh"):
                        p.slow_refresh()
                except Exception:
                    log.exception("panel %s slow_refresh failed", key)

    def run(self):
        tick = safe(self._tick)
        try:
            while dpg.is_dearpygui_running():
                tick()
                dpg.render_dearpygui_frame()
        finally:
            self.app.shutdown()
            dpg.destroy_context()


def run(app: App, sim: bool = False, auto_connect: bool = True, frames: Optional[int] = None):
    ui = UI(app, sim=sim)
    ui.build()
    if sim:
        from ..sim import SimTransport
        app.start(SimTransport())
    else:
        app.start()
        if auto_connect and app.settings.auto_connect:
            app.connect_auto()
    if app.settings.server_enabled:
        app.start_server()
    if frames is None:
        ui.run()
    else:
        tick = safe(ui._tick)
        for _ in range(frames):
            tick()
            dpg.render_dearpygui_frame()
        return ui
