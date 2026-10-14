"""Live tab - three tall plots that fill the tab, with auto-fit toggle and window length."""
from __future__ import annotations

import time
from collections import deque

import dearpygui.dearpygui as dpg

from ... import protocol as P
from .. import theme as T
from ..safe import safe


class LivePanel:
    def __init__(self, ui):
        self.ui = ui
        self.app = ui.app
        self.buf = deque(maxlen=4000)        # (t, sp, target, pos, vel, cur, tq)
        self.t0 = time.monotonic()
        self._target = float("nan")
        self.app.bus.subscribe("telemetry", self._on_t)
        self.app.bus.subscribe("stream_target", lambda v: setattr(self, "_target", float("nan") if v is None else float(v)))
        self.tags = {}

    def _on_t(self, t: P.TelemetryPacket):
        self.buf.append((time.monotonic() - self.t0, t.setpoint_deg, self._target, t.position_deg,
                         t.velocity_deg_s, t.current_A, t.torque_cmd_Nm))

    def build(self):
        with dpg.group(horizontal=True):
            self.tags["fit"] = dpg.add_checkbox(label="Auto-fit axes", default_value=self.app.settings.auto_bounds)
            self.tags["win"] = dpg.add_slider_float(label="window (s)", default_value=self.app.settings.plot_seconds,
                                                    min_value=2, max_value=60, width=220, format="%.0f s")
            dpg.add_button(label="Clear", callback=safe(self.buf.clear))
            self.tags["rate"] = dpg.add_text("", color=T.DIM)
        self.plots = {}
        for key, label, series in (("pos", "Position [deg]", ("setpoint", "target", "position")),
                                   ("vel", "Velocity [deg/s]", ("velocity",)),
                                   ("cur", "Current [A] / Torque FF [Nm]", ("current", "torque"))):
            with dpg.plot(height=280, width=-1, tag=f"live_plot_{key}", no_title=True):
                dpg.add_plot_legend(location=dpg.mvPlot_Location_NorthWest)
                x = dpg.add_plot_axis(dpg.mvXAxis, label="t [s]", tag=f"live_x_{key}")
                y = dpg.add_plot_axis(dpg.mvYAxis, label=label, tag=f"live_y_{key}")
                for s in series:
                    tag = f"live_s_{key}_{s}"
                    dpg.add_line_series([], [], label=s, parent=y, tag=tag)
                    dpg.bind_item_theme(tag, T.series_theme(s))
            self.plots[key] = (x, y)

    def on_resize(self, w, h):
        each = max(160, (h - 60) // 3)
        for key in self.plots:
            dpg.configure_item(f"live_plot_{key}", height=each)

    def refresh(self):
        if self.ui._frame % 2:
            return
        if not self.buf:
            return
        win = dpg.get_value(self.tags["win"])
        now_t = self.buf[-1][0]
        rows = [r for r in self.buf if r[0] >= now_t - win]
        if len(rows) < 2:
            return
        t = [r[0] for r in rows]
        cols = {"setpoint": [r[1] for r in rows], "target": [r[2] for r in rows], "position": [r[3] for r in rows],
                "velocity": [r[4] for r in rows], "current": [r[5] for r in rows], "torque": [r[6] for r in rows]}
        for key, series in (("pos", ("setpoint", "target", "position")), ("vel", ("velocity",)), ("cur", ("current", "torque"))):
            for s in series:
                ys = cols[s]
                if s == "target":
                    ys = [y if y == y else float("nan") for y in ys]
                dpg.set_value(f"live_s_{key}_{s}", [t, ys])
            x, y = self.plots[key]
            dpg.set_axis_limits(x, now_t - win, now_t)
            if dpg.get_value(self.tags["fit"]):
                dpg.fit_axis_data(y)
            else:
                dpg.set_axis_limits_auto(y)
        st = self.app.link.stats
        dpg.set_value(self.tags["rate"], f"telemetry {st.telemetry_hz:.0f} Hz | frames {st.frames_hz:.0f}/s | drops {st.drops} | crc {st.crc_errors}")
