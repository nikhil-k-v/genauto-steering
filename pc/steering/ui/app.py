"""
ui/app.py - the desktop UI shell (Dear PyGui).

Layout:  top bar (connection | A-F health | state | trip banner | REST)
         left column (motor | setpoint | gains | recorder | events)
         right: tabs  Live | Trajectory | Playback | Tuning | Calibration | Health | Settings

Rules the shell enforces:
  * every callback goes through safe() - the UI cannot crash (item 7)
  * every motion control is bound through GateBinder - it is disabled with
    the exact reason when the health tree says so (item 1B)
  * sizes are derived from the viewport each frame; no nested scroll regions
    except deliberate lists (item 4)
"""
from __future__ import annotations

import logging
import time
from collections import deque
from typing import Dict, Optional

import dearpygui.dearpygui as dpg

from .. import protocol as P
from ..core.app import App
from ..health.model import GROUPS, NODE_BY_ID
from ..link import SerialTransport, list_serial_ports
from . import theme as T
from .gate import GateBinder
from .safe import attach_evaluator, safe, toast, toasts
from .panels.live import LivePanel
from .panels.trajectory import TrajectoryPanel
from .panels.playback import PlaybackPanel
from .panels.tuning import TuningPanel
from .panels.calibration import CalibrationPanel
from .panels.health import HealthPanel
from .panels.settings import SettingsPanel

log = logging.getLogger(__name__)

LEFT_W = 360
TOP_H = 46


class UI:
    def __init__(self, app: App, sim: bool = False):
        self.app = app
        self.c = app.controller
        self.sim = sim
        self.gate = GateBinder(self.c)
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
            txt = f"TRIP {P.TRIP_NAMES.get(e.arg, e.arg)} - {e.text_str}"
            lvl = "bad"
        elif e.code == P.EV_CMD_REJECTED:
            txt = f"Teensy refused {P.CMD_NAMES.get(e.arg, hex(e.arg))}: {e.text_str}"
            lvl = "warn"
        elif e.code == P.EV_STATE:
            txt = f"state -> {P.CS_NAMES.get(e.arg, e.arg)}"
            lvl = "info"
        elif e.code == P.EV_CALIB_STAGE:
            txt = f"calibration: {P.CAL_NAMES.get(e.arg, e.arg)}"
            lvl = "info"
        elif e.code == P.EV_CMD_ACCEPTED:
            return
        else:
            txt = f"{name} {e.arg} {e.text_str}".strip()
            lvl = "info"
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
        with dpg.font_registry():
            pass
        dpg.create_viewport(title="Gen Auto - Steering", width=1540, height=960, min_width=1100, min_height=700)
        with dpg.window(tag="root", no_title_bar=True, no_move=True, no_resize=True, no_collapse=True,
                        no_scrollbar=True, no_bring_to_front_on_focus=True):
            self._build_topbar()
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
        dpg.set_primary_window("root", True)
        dpg.set_viewport_resize_callback(safe(self._on_resize))
        dpg.setup_dearpygui()
        dpg.show_viewport()
        self._on_resize()

    def _build_topbar(self):
        with dpg.child_window(tag="topbar", height=TOP_H, border=False, no_scrollbar=True):
            with dpg.group(horizontal=True):
                ports = list_serial_ports()
                items = ["sim"] + [p[0] for p in ports]
                default = "sim" if self.sim else (self.app.settings.last_port or (items[1] if len(items) > 1 else "sim"))
                self.tags["port"] = dpg.add_combo(items, default_value=default, width=150)
                self.tags["connect"] = dpg.add_button(label="Connect", callback=safe(self._connect))
                dpg.add_button(label="R", callback=safe(self._refresh_ports), width=28)
                dpg.add_spacer(width=14)
                for g in GROUPS:
                    b = dpg.add_button(label=g, width=58, callback=safe(self._goto_health), user_data=g)
                    self.tags[f"grp_{g}"] = b
                    with dpg.tooltip(b):
                        self.tags[f"grp_tt_{g}"] = dpg.add_text("", wrap=420)
                dpg.add_spacer(width=14)
                self.tags["state"] = dpg.add_text("-", color=T.DIM)
                dpg.add_spacer(width=10)
                self.tags["banner"] = dpg.add_text("", color=T.BAD, wrap=520)
                dpg.add_spacer(width=10)
                b = dpg.add_button(label="REST MOTOR", width=120, callback=safe(lambda: self.c.emergency_rest("button")))
                dpg.bind_item_theme(b, T.theme("btn_bad"))
                with dpg.tooltip(b):
                    dpg.add_text("Always available: stops any stream/recording and sends DISABLE.")

    def _build_left(self):
        g = self.gate
        c = self.c
        dpg.add_text("MOTOR", color=T.DIM)
        with dpg.group(horizontal=True):
            b = dpg.add_button(label="Enable", width=104, callback=safe(c.enable)); g.bind(b, "enable", "Enter FOC and hold the current position.")
            dpg.bind_item_theme(b, T.theme("btn_ok"))
            b = dpg.add_button(label="Disable", width=104, callback=safe(c.disable)); g.bind(b, "disable", "Exit FOC (motor goes limp).")
            b = dpg.add_button(label="Clear trip", width=104, callback=safe(c.clear_trip)); g.bind(b, "clear_trip", "Unlatch a safety trip -> REST.")
        with dpg.group(horizontal=True):
            b = dpg.add_button(label="Free-spin", width=104, callback=safe(c.freespin_on)); g.bind(b, "freespin_on", "Zero torque: turn the wheel by hand (and record it).")
            dpg.bind_item_theme(b, T.theme("btn_warn"))
            b = dpg.add_button(label="Re-grip", width=104, callback=safe(c.freespin_off)); g.bind(b, "freespin_off", "Leave free-spin and hold here.")
            b = dpg.add_button(label="Hold here", width=104, callback=safe(c.hold_here)); g.bind(b, "hold_here", "Stop following and hold the current position.")
        dpg.add_spacer(height=4)
        dpg.add_text("SETPOINT", color=T.DIM)
        self.tags["slider"] = dpg.add_slider_float(default_value=0.0, min_value=-180, max_value=180, width=-1,
                                                   format="%.1f deg", callback=safe(self._slider))
        g.bind(self.tags["slider"], "slider", "Drag to command a position (HOLD only). Release -> stays.")
        with dpg.group(horizontal=True):
            dpg.add_button(label="Center", width=70, callback=safe(lambda: self._set_slider(0.0)))
            self.tags["posline"] = dpg.add_text("pos - | sp - | err -")
        dpg.add_spacer(height=4)
        dpg.add_text("GAINS  (sent to the motor every tick)", color=T.DIM)
        gains = self.app.settings.gains
        with dpg.group(horizontal=True):
            self.tags["kp"] = dpg.add_input_float(label="Kp", default_value=gains["kp"], width=80, step=0, format="%.1f")
            self.tags["kd"] = dpg.add_input_float(label="Kd", default_value=gains["kd"], width=80, step=0, format="%.2f")
        with dpg.group(horizontal=True):
            self.tags["ki"] = dpg.add_input_float(label="Ki", default_value=gains["ki"], width=80, step=0, format="%.2f")
            self.tags["tff"] = dpg.add_input_float(label="Tff", default_value=gains["tff"], width=80, step=0, format="%.2f")
        with dpg.group(horizontal=True):
            b = dpg.add_button(label="Apply gains", width=120, callback=safe(self._apply_gains)); g.bind(b, "set_gains", "Send Kp/Kd/Ki/Tff. The echo line below confirms what the Teensy is using.")
            self.tags["gains_echo"] = dpg.add_text("active: -", color=T.DIM)
        with dpg.tooltip(self.tags["kp"]):
            dpg.add_text("Kp [Nm/rad] and Kd [Nm/(rad/s)] run inside the motor's 20 kHz loop.\nKi [Nm/(rad|s)] and Tff [Nm] are added by the Teensy as torque feed-forward.", wrap=360)
        dpg.add_spacer(height=4)
        dpg.add_text("RECORDER", color=T.DIM)
        with dpg.group(horizontal=True):
            self.tags["rec_name"] = dpg.add_input_text(default_value="manual", width=150, hint="name")
            self.tags["rec_coll"] = dpg.add_combo(self.app.store.collections(), default_value=self.app.settings.collection,
                                                  width=120, callback=safe(self._set_collection))
            dpg.add_button(label="+", width=24, callback=safe(self._new_collection))
        with dpg.group(horizontal=True):
            b = dpg.add_button(label="REC Record", width=104, callback=safe(self._record)); g.bind(b, "record", "Record telemetry + health + events now (any state).")
            dpg.bind_item_theme(b, T.theme("btn_bad"))
            b = dpg.add_button(label="STOP Stop", width=104, callback=safe(c.record_stop)); g.bind(b, "stop_record")
            self.tags["rec_status"] = dpg.add_text("idle", color=T.DIM)
        dpg.add_spacer(height=4)
        dpg.add_text("EVENTS", color=T.DIM)
        with dpg.child_window(tag="events", height=-1, border=True):
            self.tags["events"] = [dpg.add_text("", wrap=LEFT_W - 30) for _ in range(14)]

    def _build_toasts(self):
        with dpg.window(tag="toasts", no_title_bar=True, no_move=True, no_resize=True, no_background=True,
                        no_focus_on_appearing=True, no_bring_to_front_on_focus=False, autosize=True, show=False):
            self.tags["toast_lines"] = [dpg.add_text("", wrap=560) for _ in range(6)]

    # ---- callbacks ------------------------------------------------------------------------------
    def _refresh_ports(self):
        ports = list_serial_ports()
        dpg.configure_item(self.tags["port"], items=["sim"] + [p[0] for p in ports])

    def _connect(self):
        port = dpg.get_value(self.tags["port"])
        if self.app.link.stats.port_open and dpg.get_item_label(self.tags["connect"]) == "Disconnect":
            self.app.link.disconnect()
            return
        if port == "sim":
            from ..sim import SimTransport
            self.app.link.connect(SimTransport())
        else:
            self.app.connect_port(port)
        toast(f"connecting to {port}")

    def _goto_health(self, sender, app_data, group):
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
        for key, p in self.panels.items():
            if hasattr(p, "on_resize"):
                p.on_resize(w - LEFT_W - 40, h - TOP_H - 70)
        dpg.configure_item("toasts", pos=(LEFT_W + 30, h - 170))

    # ---- per-frame --------------------------------------------------------------------------------
    def _tick(self):
        self.app.evaluator.note_ui_frame()
        self._frame += 1
        live = self.c.live
        tree = live.tree
        t = live.telemetry
        # gates + top bar
        self.gate.refresh()
        for g in GROUPS:
            st, first = tree.group_state(g)
            btn = self.tags[f"grp_{g}"]
            label = g if st == P.HS_OK else f"{g} {first[1:] if first else '?'}"
            dpg.set_item_label(btn, label)
            th = {P.HS_OK: "btn_ok", P.HS_BLOCKED: "btn_warn", P.HS_FAIL: "btn_bad", P.HS_UNKNOWN: "btn_unknown"}[st]
            if g in self.gate.highlight or (first and first in self.gate.highlight):
                th = "btn_accent"
            dpg.bind_item_theme(btn, T.theme(th))
            tip = GROUPS[g].name + " - " + GROUPS[g].question
            if first:
                n = tree.nodes[first]
                tip += f"\n\n{first} {NODE_BY_ID[first].name}: {n.name} - {n.reason}\n{NODE_BY_ID[first].bad_means}"
            dpg.set_value(self.tags[f"grp_tt_{g}"], tip)
        cs = live.ctrl_state
        dpg.set_value(self.tags["state"], P.CS_NAMES.get(cs, "?") if t else "NO LINK")
        dpg.configure_item(self.tags["state"], color=T.CS_COLOR.get(cs, T.DIM) if t else T.BAD)
        banner = ""
        if live.health_fw and live.health_fw.trip_code:
            banner = f"TRIPPED: {P.TRIP_NAMES.get(live.health_fw.trip_code)} - " + P.TRIP_EXPLAIN.get(live.health_fw.trip_code, "")
        elif live.last_rejection and time.monotonic() - live.last_rejection_t < 6:
            banner = live.last_rejection
        dpg.set_value(self.tags["banner"], banner)
        dpg.set_item_label(self.tags["connect"], "Disconnect" if self.app.link.stats.port_open else "Connect")
        # left panel live text
        if t:
            err = t.setpoint_deg - t.position_deg
            dpg.set_value(self.tags["posline"], f"pos {t.position_deg:+7.1f} deg   sp {t.setpoint_deg:+7.1f} deg   err {err:+6.1f} deg")
        cfg = live.config
        if cfg:
            pend = "  (pending...)" if live.pending_gains else ""
            dpg.set_value(self.tags["gains_echo"], f"active: Kp {cfg.kp:.1f} Kd {cfg.kd:.2f} Ki {cfg.ki:.2f} Tff {cfg.tff_Nm:.2f}{pend}")
            dpg.configure_item(self.tags["gains_echo"], color=T.WARN if live.pending_gains else T.DIM)
            if cfg.limits_valid:
                dpg.configure_item(self.tags["slider"], min_value=cfg.limit_left_deg + 3, max_value=cfg.limit_right_deg - 3)
        if cs not in (P.CS_HOLD,) and t:
            dpg.set_value(self.tags["slider"], t.position_deg)    # slider follows the wheel when it can't drive it
        rs = self.app.recorder.status
        dpg.set_value(self.tags["rec_status"], f"REC {rs['name']} {rs['elapsed']:.0f}s {rs['samples']}" if rs["active"] else "idle")
        dpg.configure_item(self.tags["rec_status"], color=T.BAD if rs["active"] else T.DIM)
        # events
        for i, line in enumerate(self.tags["events"]):
            if i < len(self.events):
                ts, lvl, txt = self.events[i]
                dpg.set_value(line, f"{ts}  {txt}")
                dpg.configure_item(line, color={"bad": T.BAD, "warn": T.WARN}.get(lvl, T.TEXT))
            else:
                dpg.set_value(line, "")
        # toasts
        ts = toasts()
        dpg.configure_item("toasts", show=bool(ts))
        for i, line in enumerate(self.tags["toast_lines"]):
            if i < len(ts):
                dpg.set_value(line, ts[i][1]); dpg.configure_item(line, color={"bad": T.BAD, "warn": T.WARN}.get(ts[i][0], T.OK))
            else:
                dpg.set_value(line, "")
        # panels
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
    else:                                   # headless smoke test
        tick = safe(ui._tick)
        for _ in range(frames):
            tick()
            dpg.render_dearpygui_frame()
        return ui
