"""Drive - command the wheel, watch it, record it.

    Wheel angle  [===========o=================]   End stops −142° and +138°
                 [Centre]
    ┌ plot: position (blue), setpoint (ink), stream target (violet) ┐
    └──────────────────────────────────────────────────────────────┘
    ☐ Speed and current      Window [10 s]
    Record   [name      ] [Record]   saves to  default / 2026-10-14
"""
from __future__ import annotations

import time
from collections import deque

import dearpygui.dearpygui as dpg

from ... import protocol as P
from .. import theme as T
from ..safe import safe, toast

WINDOWS = ["5 s", "10 s", "30 s", "60 s"]


class DrivePanel:
    def __init__(self, ui):
        self.ui = ui
        self.app = ui.app
        self.c = ui.app.controller
        self.buf = deque(maxlen=12000)        # (t, sp, target, pos, vel, cur)
        self.t0 = time.monotonic()
        self._target = float("nan")
        self.app.bus.subscribe("telemetry", self._on_t)
        self.app.bus.subscribe("stream_target", lambda v: setattr(self, "_target", float("nan") if v is None else float(v)))
        self.tags = {}
        self._h = 600

    def _on_t(self, t: P.TelemetryPacket):
        self.buf.append((time.monotonic() - self.t0, t.setpoint_deg, self._target, t.position_deg,
                         t.velocity_deg_s, t.current_A))

    # ---- build -----------------------------------------------------------------------------------
    def build(self):
        g = self.ui.gate
        T.heading("Wheel angle")
        self.tags["slider"] = dpg.add_slider_float(default_value=0.0, min_value=-180, max_value=180, width=-1,
                                                   format="%+.1f°", callback=safe(self._slider))
        dpg.bind_item_theme(self.tags["slider"], T.theme("slider_big"))
        g.bind(self.tags["slider"], "slider", "Drag to command an angle. The Teensy slews it, so the wheel never jumps.")
        with dpg.group(horizontal=True):
            b = T.action("Centre", "secondary", safe(lambda: self._set_slider(0.0)))
            g.bind(b, "slider", "Command 0°.")
            self.tags["limits"] = T.label("")
        T.gap(10)

        with dpg.plot(height=360, width=-1, tag="drive_plot", no_title=True, no_frame=True, no_mouse_pos=True, no_menus=True, no_box_select=True):
            dpg.add_plot_legend(location=dpg.mvPlot_Location_NorthEast, horizontal=True)
            dpg.add_plot_axis(dpg.mvXAxis, tag="drive_x", no_tick_labels=False)
            y = dpg.add_plot_axis(dpg.mvYAxis, label="degrees", tag="drive_y")
            for s, lab in (("setpoint", "setpoint"), ("target", "stream target"), ("position", "position")):
                dpg.add_line_series([], [], label=lab, parent=y, tag=f"drive_{s}")
                dpg.bind_item_theme(f"drive_{s}", T.series_theme(s))
        with dpg.plot(height=160, width=-1, tag="drive_plot2", no_title=True, no_frame=True, no_mouse_pos=True, no_menus=True, no_box_select=True, show=False):
            dpg.add_plot_legend(location=dpg.mvPlot_Location_NorthEast, horizontal=True)
            dpg.add_plot_axis(dpg.mvXAxis, tag="drive_x2")
            y1 = dpg.add_plot_axis(dpg.mvYAxis, label="deg/s", tag="drive_y2")
            y2 = dpg.add_plot_axis(dpg.mvYAxis2, label="A", tag="drive_y3", opposite=True) if hasattr(dpg, "mvYAxis2") else y1
            dpg.add_line_series([], [], label="speed", parent=y1, tag="drive_velocity")
            dpg.bind_item_theme("drive_velocity", T.series_theme("velocity"))
            dpg.add_line_series([], [], label="current", parent=y2, tag="drive_current")
            dpg.bind_item_theme("drive_current", T.series_theme("current"))
        with dpg.group(horizontal=True):
            self.tags["more"] = T.toggle("Speed and current", False, safe(self._more))
            dpg.add_spacer(width=18)
            self.tags["fit"] = T.toggle("Fit vertical axis", self.app.settings.auto_bounds)
            dpg.add_spacer(width=18)
            T.label("Window")
            win = f"{int(self.app.settings.plot_seconds)} s"
            self.tags["win"] = dpg.add_combo(WINDOWS, default_value=win if win in WINDOWS else "10 s", width=80)

        T.gap(16)
        T.heading("Record")
        with dpg.group(horizontal=True):
            self.tags["name"] = T.text_input("manual", 220, "name")
            self.tags["rec"] = T.action("Record", "primary", safe(self._record), 150)
            g.bind(self.tags["rec"], self._rec_action, {
                "record": "Record telemetry, health and events now.",
                "record_freespin": "Record the wheel moved by hand (kind: free-spin). Play it back from Library.",
                "stop_record": "Stop and save. It appears in Library."})
            self.tags["rec_info"] = T.label("")
        with dpg.group(horizontal=True):
            T.label("Saves to")
            self.tags["coll"] = dpg.add_combo(self.app.store.collections() or ["default"], default_value=self.app.settings.collection,
                                              width=160, callback=safe(self._set_collection))
            self.tags["path"] = T.mono_text("", T.MUTED, small=True)
            nb = T.action("New collection", "quiet", None)
            with dpg.popup(nb, mousebutton=dpg.mvMouseButton_Left, tag="new_coll_pop"):
                self.tags["new_coll"] = T.text_input("", 200, "collection name", callback=safe(self._new_collection), on_enter=True)
                T.action("Create", "primary", safe(self._new_collection))

    # ---- callbacks ---------------------------------------------------------------------------------
    def _rec_action(self) -> str:
        if self.app.recorder.active:
            return "stop_record"
        return "record_freespin" if self.c.live.ctrl_state == P.CS_FREESPIN and self.c.live.telemetry else "record"

    def _record(self):
        if self.app.recorder.active:
            self.c.record_stop()
            return
        kind = "freespin" if self.c.live.ctrl_state == P.CS_FREESPIN else "manual"
        self.c.record_start(dpg.get_value(self.tags["name"]).strip() or "manual", kind=kind)

    def _slider(self, sender, value):
        r = self.c.slider(value)
        if not r.ok:
            toast(r.tooltip, "warn", 2)

    def _set_slider(self, v):
        dpg.set_value(self.tags["slider"], v)
        self._slider(None, v)

    def set_slider(self, v):
        self._set_slider(v)

    def _more(self, sender, on):
        dpg.configure_item("drive_plot2", show=on)
        self._layout()

    def _set_collection(self, sender, value):
        self.app.settings.collection = value
        self.app.settings.save()

    def _new_collection(self, *_):
        name = (dpg.get_value(self.tags["new_coll"]) or "").strip()
        if not name:
            return
        items = sorted(set(self.app.store.collections()) | {name, self.app.settings.collection})
        dpg.configure_item(self.tags["coll"], items=items)
        dpg.set_value(self.tags["coll"], name)
        self._set_collection(None, name)
        dpg.set_value(self.tags["new_coll"], "")
        dpg.configure_item("new_coll_pop", show=False)

    # ---- layout / refresh -----------------------------------------------------------------------------
    def on_resize(self, w, h):
        self._h = h
        self._layout()

    def _layout(self):
        more = dpg.get_value(self.tags["more"]) if "more" in self.tags else False
        avail = max(260, self._h - 300)
        if more:
            dpg.configure_item("drive_plot", height=int(avail * 0.62))
            dpg.configure_item("drive_plot2", height=int(avail * 0.38) - 8)
        else:
            dpg.configure_item("drive_plot", height=avail)

    def refresh(self):
        live = self.c.live
        cfg, t = live.config, live.telemetry
        if cfg and cfg.limits_valid:
            dpg.configure_item(self.tags["slider"], min_value=cfg.limit_left_deg + 3, max_value=cfg.limit_right_deg - 3)
            dpg.set_value(self.tags["limits"], f"End stops at {cfg.limit_left_deg:+.0f}° and {cfg.limit_right_deg:+.0f}°".replace("-", "−"))
            dpg.configure_item(self.tags["limits"], color=T.MUTED)
        elif cfg:
            dpg.set_value(self.tags["limits"], "End stops not set. Run Calibrate first.")
            dpg.configure_item(self.tags["limits"], color=T.WARN)
        if live.ctrl_state != P.CS_HOLD and t:
            dpg.set_value(self.tags["slider"], t.position_deg)

        rs = self.app.recorder.status
        rec = self.app.recorder.active
        dpg.set_item_label(self.tags["rec"], "Stop recording" if rec else "Record")
        dpg.bind_item_theme(self.tags["rec"], T.theme("btn_danger" if rec else "btn_primary"))
        if rec:
            el = int(rs["elapsed"])
            dpg.set_value(self.tags["rec_info"], f"{rs['name']}, {el // 60}:{el % 60:02d}, {rs['samples']:,} samples")
        else:
            dpg.set_value(self.tags["rec_info"], "Free-spin recordings can be played back from Library."
                          if live.ctrl_state == P.CS_FREESPIN else "")
        dpg.set_value(self.tags["path"], f"/{self.app.settings.collection}/{time.strftime('%Y-%m-%d')}/")

        if self.ui._frame % 2 or not self.buf:
            return
        win = float(dpg.get_value(self.tags["win"]).split()[0])
        now_t = self.buf[-1][0]
        rows = [r for r in self.buf if r[0] >= now_t - win]
        if len(rows) < 2:
            return
        tt = [r[0] - now_t for r in rows]
        dpg.set_value("drive_setpoint", [tt, [r[1] for r in rows]])
        dpg.set_value("drive_target", [tt, [r[2] for r in rows]])
        dpg.set_value("drive_position", [tt, [r[3] for r in rows]])
        dpg.set_axis_limits("drive_x", -win, 0)
        fit = dpg.get_value(self.tags["fit"])
        if fit:
            dpg.fit_axis_data("drive_y")
        if dpg.get_value(self.tags["more"]):
            dpg.set_value("drive_velocity", [tt, [r[4] for r in rows]])
            dpg.set_value("drive_current", [tt, [r[5] for r in rows]])
            dpg.set_axis_limits("drive_x2", -win, 0)
            if fit:
                dpg.fit_axis_data("drive_y2")
                if dpg.does_item_exist("drive_y3"):
                    dpg.fit_axis_data("drive_y3")
