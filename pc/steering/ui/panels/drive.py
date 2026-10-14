"""Drive - command the wheel, watch it, record it.

    Setpoint +25.0°              [Move to 0°]                     Position +25.1°
    ├──────────────────────────────●▮───────────────────────────────────────┤
    left stop −220°     −90      0      +90                   right stop +220°

    ┌ Now ──────────────┐  ┌ legend: real line styles ─────────────────────┐
    │ Setpoint from …   │  │ wheel angle                                    │
    │ Error    +0.1°    │  │                                                │
    │ Speed    …        │  ├ ▾ Speed ───────────────────────────────────────┤
    │ Current  …        │  ├ ▾ Torque and current ──────────────────────────┤
    │ Torque   …        │  │                                                │
    ├ Record ───────────┤  └ Time span [10 s]  ☑ Auto-scale ────────────────┘
    │ [name ] [Record]  │
    │ Saves to [coll ▾] │
    └───────────────────┘
"""
from __future__ import annotations

import time

import dearpygui.dearpygui as dpg

from ... import protocol as P
from ... import words as W
from .. import theme as T
from ..liveplot import LivePlot
from ..safe import safe
from ..wheel import WheelStrip

LEFT_W = 300


class DrivePanel:
    def __init__(self, ui):
        self.ui = ui
        self.app = ui.app
        self.c = ui.app.controller
        self.tags = {}
        self.wheel = WheelStrip(ui, "drive")
        self.plot = LivePlot(ui, "drive")
        self._h = 600

    # ---- build -----------------------------------------------------------------------------------
    def build(self):
        g = self.ui.gate
        self.wheel.build()
        T.gap(10)
        with dpg.group(horizontal=True, horizontal_spacing=28):
            with dpg.child_window(width=LEFT_W, border=False, no_scrollbar=True, tag="drive_left") as lc:
                dpg.bind_item_theme(lc, T.theme("bare"))
                T.heading("Now")
                with dpg.table(header_row=False, policy=dpg.mvTable_SizingFixedFit, borders_innerH=False) as tb:
                    dpg.bind_item_theme(tb, T.theme("compact"))
                    dpg.add_table_column(width_fixed=True, init_width_or_weight=118)
                    dpg.add_table_column(width_fixed=True, init_width_or_weight=LEFT_W - 130)
                    for key, lab, tip in (
                        ("src", "Setpoint from", "What is producing the setpoint: you (Position control), a playback, "
                                                 "a waveform, the planner, a test or calibration. Nothing while the "
                                                 "motor is off or in free-spin."),
                        ("err", "Error", "Setpoint minus position: how far the wheel is from where it was told to be."),
                        ("vel", "Speed", "Measured wheel speed."),
                        ("cur", "Motor current", "Phase current the motor reports. The safety stop is at 30 A."),
                        ("tq", "Torque command", "The torque the Teensy adds on top of the motor's own position "
                                                 "loop (integral + feed-forward)."),
                        ("gains", "Gains in use", "What the Teensy reports it is using. Change them on the Tune page."),
                    ):
                        with dpg.table_row():
                            l = T.label(lab)
                            T.tip(l, tip)
                            self.tags[key] = dpg.add_text("—")
                T.gap(18)
                T.heading("Record")
                self.tags["name"] = T.text_input("manual", LEFT_W - 4, "name")
                T.tip(self.tags["name"], "Name for the next recording. The folder gets the time and kind in front of it.")
                with dpg.group(horizontal=True):
                    self.tags["rec"] = T.action("Record", "primary", safe(self._record), 130)
                    g.bind(self.tags["rec"], self._rec_action, {
                        "record": "Save telemetry, health and events from now until you press Stop recording. "
                                  "It appears in Library.",
                        "record_freespin": "Record the wheel as you move it by hand. Library can play it back on the "
                                           "motor afterwards.",
                        "stop_record": "Stop and save. It appears in Library."})
                    self.tags["rec_info"] = T.label("")
                T.gap(4)
                with dpg.group(horizontal=True):
                    T.label("Saves to")
                    self.tags["coll"] = dpg.add_combo(self.app.store.collections() or ["default"],
                                                      default_value=self.app.settings.collection,
                                                      width=150, callback=safe(self._set_collection))
                    T.tip(self.tags["coll"], "The collection (top-level folder) new recordings go into. "
                                             "Each day gets its own folder inside it.")
                    nb = T.action("New…", "quiet", None, tip_text="Make a new collection.")
                    with dpg.popup(nb, mousebutton=dpg.mvMouseButton_Left, tag="new_coll_pop"):
                        self.tags["new_coll"] = T.text_input("", 200, "collection name", callback=safe(self._new_collection),
                                                             on_enter=True)
                        T.action("Create", "primary", safe(self._new_collection))
                self.tags["path"] = T.mono_text("", T.MUTED, small=True)
                T.tip(self.tags["path"], "Folder the next recording will be written to, under the data folder.")
                T.gap(18)
                h = T.heading("Events")
                T.tip(h, "What the Teensy and the laptop did lately: state changes, refusals with their reason, "
                         "safety stops. The full list is on the Health page and in each recording.")
                self.tags["events"] = [T.mono_text("", T.MUTED, small=True, wrap=LEFT_W - 6) for _ in range(7)]
            with dpg.child_window(border=False, no_scrollbar=True, tag="drive_right") as rc:
                dpg.bind_item_theme(rc, T.theme("bare"))
                self.plot.build()

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

    def set_slider(self, v):
        self.wheel.set(v)

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
        self.wheel.on_resize(w)
        body_h = h - 84
        dpg.configure_item("drive_left", height=body_h)
        dpg.configure_item("drive_right", width=max(400, w - LEFT_W - 28), height=body_h)
        self.plot.on_resize(max(400, w - LEFT_W - 28), body_h)

    def refresh(self):
        live = self.c.live
        cfg, t = live.config, live.telemetry
        self.wheel.refresh()
        self.plot.refresh()

        src = self.c.setpoint_source() if t else ""
        if t:
            label = {"user": "you (Position control)"}.get(src, W.SOURCE.get(src, "").lower()) if src else "nothing (motor not servoing)"
            dpg.set_value(self.tags["src"], label)
            dpg.configure_item(self.tags["src"], color=T.SOURCE_COLOR.get(src, T.MUTED))
            dpg.set_value(self.tags["err"], f"{W.signed(t.setpoint_deg - t.position_deg, 2)}°" if src else "—")
            dpg.set_value(self.tags["vel"], f"{W.signed(t.velocity_deg_s, 0)}°/s")
            dpg.set_value(self.tags["cur"], f"{W.signed(t.current_A)} A")
            dpg.set_value(self.tags["tq"], f"{W.signed(t.torque_cmd_Nm, 2)} N·m")
        if cfg:
            dpg.set_value(self.tags["gains"], f"Kp {cfg.kp:.1f}   Kd {cfg.kd:.2f}   Ki {cfg.ki:.2f}")

        rs = self.app.recorder.status
        rec = self.app.recorder.active
        dpg.set_item_label(self.tags["rec"], "Stop recording" if rec else "Record")
        dpg.bind_item_theme(self.tags["rec"], T.theme("btn_danger" if rec else "btn_primary"))
        if rec:
            el = int(rs["elapsed"])
            dpg.set_value(self.tags["rec_info"], f"{el // 60}:{el % 60:02d}, {rs['samples']:,} samples")
        else:
            dpg.set_value(self.tags["rec_info"], "hand motion" if live.ctrl_state == P.CS_FREESPIN and t else "")
        dpg.set_value(self.tags["path"], f"{self.app.settings.collection}/{time.strftime('%Y-%m-%d')}/")
        ev = self.ui.events
        for i, line in enumerate(self.tags["events"]):
            if i < len(ev):
                ts, lvl, txt = ev[i]
                dpg.set_value(line, f"{ts[:5]}  {txt}")
                dpg.configure_item(line, color={"bad": T.BAD, "warn": T.WARN}.get(lvl, T.MUTED))
            else:
                dpg.set_value(line, "")
