"""
ui/app.py - the desktop UI shell (Dear PyGui).

    ┌──────────┬───────────────────────────────────────────────────────┐
    │  rail    │  Drive   Library   Tune   Calibrate   Health   Settings │
    │          │ ┌───────────────────────────────────────────────────┐ │
    │  state   │ │                                                   │ │
    │  angle   │ │   page                                            │ │
    │  mode    │ │                                                   │ │
    │  chain   │ │                                                   │ │
    │  event   │ └───────────────────────────────────────────────────┘ │
    └──────────┴───────────────────────────────────────────────────────┘

The rail (ui/rail.py) is always visible: what the system is doing, whether
each part of the chain is healthy, and the controls that change the mode.
Pages hold one job each.

Rules the shell enforces:
  * every callback goes through safe() - the UI cannot crash
  * every motion control is bound through GateBinder - disabled with the exact
    reason when the health tree says so, and literally wired to the rail rows
    it depends on (hover it: lines appear)
  * sizes are derived from the viewport; only lists scroll
"""
from __future__ import annotations

import logging
import time
from collections import deque
from typing import Dict, Optional

import dearpygui.dearpygui as dpg

from .. import protocol as P
from .. import words as W
from ..core.app import App
from ..health.gating import ACTIONS
from . import theme as T
from .gate import GateBinder
from .liveplot import History
from .overlay import Overlay
from .rail import RAIL_W, Rail
from .safe import attach_evaluator, safe, toasts
from .panels.drive import DrivePanel
from .panels.playback import PlaybackPanel
from .panels.tuning import TuningPanel
from .panels.calibration import CalibrationPanel
from .panels.health import HealthPanel
from .panels.settings import SettingsPanel

log = logging.getLogger(__name__)

TABS = (("drive", "Drive", DrivePanel), ("play", "Library", PlaybackPanel), ("tune", "Tune", TuningPanel),
        ("cal", "Calibrate", CalibrationPanel), ("health", "Health", HealthPanel), ("settings", "Settings", SettingsPanel))
MAIN_PAD = 14
TAB_H = 40


class UI:
    def __init__(self, app: App, sim: bool = False):
        self.app = app
        self.c = app.controller
        self.sim = sim
        self.gate = GateBinder(self.c)
        self.history = History(app)
        self.rail = Rail(self)
        self.overlay = Overlay(self)
        self.events: deque = deque(maxlen=300)
        self.panels: Dict[str, object] = {}
        self._frame = 0
        self._last_slow = 0.0
        self._active_tab = None
        self.tags: Dict[str, int] = {}
        app.bus.subscribe("event", self._on_event)
        app.bus.subscribe("ui_action", self._on_action)
        attach_evaluator(app.evaluator)

    # ---- event feed ---------------------------------------------------------------------
    def _on_event(self, e: P.EventPacket):
        said = W.event_text(e.code, e.arg, e.text_str)
        if said is None:
            return
        txt, lvl = said
        self.events.appendleft((time.strftime("%H:%M:%S"), lvl, txt))
        if lvl != "info":
            from .safe import toast
            toast(txt, lvl, 6)

    def _on_action(self, a: dict):
        if not a.get("allowed", True):
            label = ACTIONS[a["action"]][0] if a["action"] in ACTIONS else a["action"]
            self.events.appendleft((time.strftime("%H:%M:%S"), "warn",
                                    f"{label} not available: {'; '.join(a.get('reasons', []))}"))

    # ---- build ----------------------------------------------------------------------------
    def build(self):
        dpg.create_context()
        T.build()
        dpg.create_viewport(title="Gen Auto steering", width=1520, height=960, min_width=1180, min_height=760,
                            clear_color=T.PAPER)
        with dpg.window(tag="root", no_title_bar=True, no_move=True, no_resize=True, no_collapse=True,
                        no_scrollbar=True, no_bring_to_front_on_focus=True):
            self.rail.build("root")
            # NB: a tab bar inside a child window makes its first tab stretch (DPG 2.x);
            # a positioned group avoids that.
            with dpg.group(tag="main", pos=(RAIL_W + MAIN_PAD, 8)):
                with dpg.tab_bar(tag="tabs", draw_selected_overline=True):
                    for key, label, cls in TABS:
                        with dpg.tab(label=label, tag=f"tab_{key}"):
                            with dpg.child_window(tag=f"page_{key}", border=False, always_use_window_padding=True,
                                                  no_scrollbar=key in ("drive", "play", "health")) as page:
                                dpg.bind_item_theme(page, T.theme("page"))
                                p = cls(self)
                                p.build()
                                self.panels[key] = p
        self.overlay.build()
        dpg.set_primary_window("root", True)
        dpg.set_viewport_resize_callback(safe(self._on_resize))
        dpg.setup_dearpygui()
        dpg.show_viewport()
        self._on_resize()

    # ---- navigation ---------------------------------------------------------------------------
    def goto(self, key: str):
        dpg.set_value("tabs", f"tab_{key}")

    def goto_health(self, node_id: str):
        self.goto("health")
        self.panels["health"].select(node_id)

    # gains live in Tune; Library uses this to copy a recording's gains back
    def set_gain_inputs(self, kp, kd, ki, tff=None):
        self.panels["tune"].set_inputs(kp, kd, ki, tff)

    def _on_resize(self):
        w, h = dpg.get_viewport_client_width(), dpg.get_viewport_client_height()
        dpg.configure_item("rail", height=h)
        mw = w - RAIL_W
        pw, ph = mw - 2 * MAIN_PAD, h - TAB_H - 22
        for key, _, _ in TABS:
            dpg.configure_item(f"page_{key}", width=pw, height=ph)
        for p in self.panels.values():
            if hasattr(p, "on_resize"):
                p.on_resize(pw - 48, ph - 36)

    # ---- per-frame ----------------------------------------------------------------------------
    def _tick(self):
        self.app.evaluator.note_ui_frame()
        self._frame += 1
        self.gate.refresh()
        self.rail.refresh()
        self.overlay.refresh(self.gate, self.rail, self.panels["health"].rows if "health" in self.panels else {})
        self._draw_toasts()

        active = dpg.get_value("tabs")
        for key, p in self.panels.items():
            try:
                if f"tab_{key}" == active:
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

    def _draw_toasts(self):
        """Toasts are drawn on the overlay layer: exact size, bottom-right, never steal focus."""
        ts = toasts()[:3]
        if not ts:
            return
        font = T.font("body")
        lines = [(lvl, txt[:110]) for lvl, txt in ts]
        sizes = [dpg.get_text_size(t, font=font) or (len(t) * 8, 18) for _, t in lines]
        w = max(s[0] for s in sizes) + 28
        lh = T.FONT_SIZE.get("body", 17) + 6
        h = lh * len(lines) + 16
        vw, vh = dpg.get_viewport_client_width(), dpg.get_viewport_client_height()
        x, y = vw - w - 24, vh - h - 24
        dl = self.overlay.dl
        dpg.draw_rectangle((x, y), (x + w, y + h), fill=T.SURFACE, color=T.RULE, rounding=6, parent=dl)
        for i, (lvl, txt) in enumerate(lines):
            col = {"bad": T.BAD, "warn": T.WARN}.get(lvl, T.INK)
            it = dpg.draw_text((x + 14, y + 8 + i * lh), txt, color=col, size=T.FONT_SIZE.get("body", 17), parent=dl)
            T.bind_font(it, "body")

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
