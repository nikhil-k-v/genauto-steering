"""
ui/liveplot.py - the live traces, shared by Drive, Tune and Calibrate.

    ── position   - - setpoint · Position control   ··· requested · Playback      <- legend with real line styles
    ┌ wheel angle (°) ─────────────────────────────────────────────┐
    │  solid blue = measured; dashed = Teensy setpoint, coloured by  │
    │  who produced it; dotted = what the stream asked for           │
    └────────────────────────────────────────────────────────────────┘
    ▾ Speed                         (collapsible, open by default)
    ▾ Torque and current            (collapsible, open by default)
    Time span [10 s]   ☑ Auto-scale

One History buffer (filled from telemetry on the link thread) feeds every
instance; only the instance on the visible page is redrawn.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Dict, List

import dearpygui.dearpygui as dpg
import numpy as np

from .. import protocol as P
from .. import words as W
from . import lines as L
from . import theme as T
from .safe import safe

SOURCES = ("user", "playback", "trajectory", "planner", "test", "calib")
SRC_CODE = {s: i + 1 for i, s in enumerate(SOURCES)}     # 0 = no setpoint (motor off / free-spin)
STREAMS = ("playback", "trajectory", "planner")
SPANS = ["5 s", "10 s", "30 s", "60 s"]
SOURCE_LABEL = {"user": "Position control", "playback": "playback", "trajectory": "waveform", "planner": "planner",
                "test": "test", "calib": "calibration"}


class History:
    """Telemetry ring buffer with the setpoint source tagged on every sample."""
    COLS = ("t", "src", "sp", "req", "pos", "vel", "cur", "tq")

    def __init__(self, app, maxlen: int = 14000):
        self.app = app
        self.c = app.controller
        self._buf: deque = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self._req = float("nan")
        self.t0 = time.monotonic()
        app.bus.subscribe("telemetry", self._on_t)
        app.bus.subscribe("stream_target", lambda v: setattr(self, "_req", float("nan") if v is None else float(v)))

    def _on_t(self, t: P.TelemetryPacket):
        src = self.c.setpoint_source()
        req = self._req if src in STREAMS else float("nan")
        row = (time.monotonic() - self.t0, SRC_CODE.get(src, 0), t.setpoint_deg, req, t.position_deg,
               t.velocity_deg_s, t.current_A, t.torque_cmd_Nm)
        with self._lock:
            self._buf.append(row)

    def window(self, seconds: float) -> Dict[str, np.ndarray]:
        with self._lock:
            rows = list(self._buf)
        if len(rows) < 2:
            return {}
        a = np.asarray(rows, dtype=float)
        now = a[-1, 0]
        a = a[a[:, 0] >= now - seconds]
        out = {k: a[:, i] for i, k in enumerate(self.COLS)}
        out["t"] = out["t"] - now
        return out


class LivePlot:
    def __init__(self, ui, key: str, speed: bool = True, torque: bool = True):
        self.ui = ui
        self.app = ui.app
        self.key = key
        self.has_speed, self.has_torque = speed, torque
        self._h = 500
        self._w = 600
        self._open = (None, None)
        self._legend_sig = None
        self._legend_h = 22

    def tag(self, name: str) -> str:
        return f"lp_{self.key}_{name}"

    # ---- build -------------------------------------------------------------------------------------
    def _plot(self, name: str, ylab: str, height: int):
        with dpg.plot(height=height, width=-1, tag=self.tag(name), no_title=True, no_mouse_pos=True,
                      no_menus=True, no_box_select=True) as p:
            T.plot_font(p)
            dpg.add_plot_axis(dpg.mvXAxis, tag=self.tag(f"{name}_x"))
            y = dpg.add_plot_axis(dpg.mvYAxis, label=ylab, tag=self.tag(f"{name}_y"))
        return p, y

    def build(self):
        k = self.tag
        s = self.app.settings
        self.leg = dpg.add_drawlist(width=600, height=22, tag=k("legend"))
        _, y = self._plot("pos", "wheel angle (°)", 300)
        for src in SOURCES:
            it = dpg.add_line_series([], [], parent=y, tag=k(f"sp_{src}"))
            T.series(f"sp_{src}", it)
        for src in STREAMS:
            it = dpg.add_line_series([], [], parent=y, tag=k(f"req_{src}"))
            T.series(f"req_{src}", it)
        it = dpg.add_line_series([], [], parent=y, tag=k("position"))
        T.series("position", it)

        if self.has_speed:
            h = dpg.add_collapsing_header(label="Speed", default_open=s.plot_speed_open, tag=k("speed_h"))
            T.bind_font(h, "label")
            T.tip(h, "Measured wheel speed in degrees per second. Click to show or hide.")
            with dpg.group(parent=h):
                _, y = self._plot("spd", "speed (°/s)", 140)
                it = dpg.add_line_series([], [], parent=y, tag=k("velocity"))
                T.series("velocity", it)
        if self.has_torque:
            h = dpg.add_collapsing_header(label="Torque and current", default_open=s.plot_torque_open, tag=k("torque_h"))
            T.bind_font(h, "label")
            T.tip(h, "Dashed: the torque the Teensy commanded (N·m, left axis). Solid: the current the motor "
                     "reports (A, right axis). Click to show or hide.")
            with dpg.group(parent=h):
                with dpg.plot(height=140, width=-1, tag=k("tq"), no_title=True, no_mouse_pos=True, no_menus=True,
                              no_box_select=True) as p:
                    T.plot_font(p)
                    dpg.add_plot_axis(dpg.mvXAxis, tag=k("tq_x"))
                    y1 = dpg.add_plot_axis(dpg.mvYAxis, label="torque (N·m)", tag=k("tq_y"))
                    y2 = dpg.add_plot_axis(dpg.mvYAxis2, label="current (A)", tag=k("tq_y2"), opposite=True)
                    it = dpg.add_line_series([], [], parent=y1, tag=k("torque"))
                    T.series("torque", it)
                    it = dpg.add_line_series([], [], parent=y2, tag=k("current"))
                    T.series("current", it)

        with dpg.group(horizontal=True, tag=k("opts")):
            T.label("Time span")
            span = f"{int(s.plot_seconds)} s"
            c = dpg.add_combo(SPANS, default_value=span if span in SPANS else "10 s", width=80, tag=k("span"),
                              callback=safe(self._span))
            T.tip(c, "How many seconds of history the plots show. The right edge is now.")
            dpg.add_spacer(width=14)
            T.toggle("Auto-scale", s.auto_bounds, safe(self._fit), tip_text=(
                "On: the vertical axes follow the data. Off: drag or scroll a plot to set its range yourself."))

    # ---- settings ------------------------------------------------------------------------------------
    def _span(self, sender, value):
        self.app.settings.plot_seconds = float(value.split()[0])
        self.app.settings.save()

    def _fit(self, sender, value):
        self.app.settings.auto_bounds = bool(value)
        self.app.settings.save()

    # ---- layout --------------------------------------------------------------------------------------
    def on_resize(self, w: int, h: int):
        self._w, self._h = w, h
        self._open = (None, None)
        self.layout()

    def layout(self):
        k = self.tag
        sp = bool(self.has_speed and dpg.get_value(k("speed_h")))
        tq = bool(self.has_torque and dpg.get_value(k("torque_h")))
        if (sp, tq, self._legend_h) == self._open:
            return
        self._open = (sp, tq, self._legend_h)
        s = self.app.settings
        if self.has_speed and s.plot_speed_open != sp or self.has_torque and s.plot_torque_open != tq:
            s.plot_speed_open, s.plot_torque_open = sp, tq
            s.save()
        headers = 37 * (int(self.has_speed) + int(self.has_torque))
        n_small = int(sp) + int(tq)
        avail = max(200, self._h - (self._legend_h + 8) - headers - 42 - 8 * n_small)
        small = int(avail * 0.24) if n_small else 0
        big = avail - n_small * (small + 8)
        dpg.configure_item(k("pos"), height=max(150, big))
        if self.has_speed:
            dpg.configure_item(k("spd"), height=max(90, small))
        if self.has_torque:
            dpg.configure_item(k("tq"), height=max(90, small))
        dpg.configure_item(k("legend"), width=max(200, self._w))
        # time labels only under the lowest open plot
        dpg.configure_item(k("pos_x"), no_tick_labels=sp or tq)
        if self.has_speed:
            dpg.configure_item(k("spd_x"), no_tick_labels=tq)

    # ---- per frame -------------------------------------------------------------------------------------
    def refresh(self):
        self.layout()
        if self.ui._frame % 2:
            return
        k = self.tag
        span = float(dpg.get_value(k("span")).split()[0])
        d = self.ui.history.window(span)
        if not d:
            return
        t = d["t"]
        fit = self.app.settings.auto_bounds
        dpg.set_axis_limits(k("pos_x"), -span, 0)
        sx, sy = L.scale(k("pos"), k("pos_x"), k("pos_y"))
        present: List[str] = []
        for src in SOURCES:
            m = d["src"] == SRC_CODE[src]
            if m.any():
                present.append(src)
            m2 = m.copy()
            m2[1:] |= m[:-1]                 # run each segment one sample into the next: no gap at a hand-over
            y = np.where(m2, d["sp"], np.nan)
            L.set_line(k(f"sp_{src}"), f"sp_{src}", t, y, sx, sy)
            dpg.configure_item(k(f"sp_{src}"), show=bool(m.any()))
        reqs = []
        for src in STREAMS:
            m = (d["src"] == SRC_CODE[src]) & np.isfinite(d["req"])
            if m.any():
                reqs.append(src)
            L.set_line(k(f"req_{src}"), f"req_{src}", t, np.where(m, d["req"], np.nan), sx, sy)
            dpg.configure_item(k(f"req_{src}"), show=bool(m.any()))
        L.set_line(k("position"), "position", t, d["pos"], sx, sy)
        if fit:
            dpg.fit_axis_data(k("pos_y"))

        sp_open = self.has_speed and dpg.get_value(k("speed_h"))
        tq_open = self.has_torque and dpg.get_value(k("torque_h"))
        if sp_open:
            dpg.set_axis_limits(k("spd_x"), -span, 0)
            sx2, sy2 = L.scale(k("spd"), k("spd_x"), k("spd_y"))
            L.set_line(k("velocity"), "velocity", t, d["vel"], sx2, sy2)
            if fit:
                dpg.fit_axis_data(k("spd_y"))
        if tq_open:
            dpg.set_axis_limits(k("tq_x"), -span, 0)
            sx3, sy3 = L.scale(k("tq"), k("tq_x"), k("tq_y"))
            L.set_line(k("torque"), "torque", t, d["tq"], sx3, sy3)
            L.set_line(k("current"), "current", t, d["cur"], sx3, sy3)
            if fit:
                dpg.fit_axis_data(k("tq_y"))
                dpg.fit_axis_data(k("tq_y2"))

        entries = [("position", "position (measured)")]
        entries += [(f"sp_{s}", f"setpoint · {SOURCE_LABEL[s]}") for s in present]
        entries += [(f"req_{s}", f"requested · {SOURCE_LABEL[s]}") for s in reqs]
        if tq_open:
            entries += [("torque", "torque command"), ("current", "motor current")]
        sig = (tuple(entries), self._w)
        if sig != self._legend_sig:
            self._legend_sig = sig
            h = L.legend(self.leg, entries, max(200, self._w))
            dpg.configure_item(self.leg, height=h)
            self._legend_h = h
