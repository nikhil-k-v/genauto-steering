"""Library - every recording, newest first, playbacks nested under their source.

Left: search, sort, collection, the list (the only part that scrolls).
Right: the selected recording - what it is, Play on motor, its traces with a
draggable cursor, the numbers that matter, notes and tags.
"""
from __future__ import annotations

import os
import subprocess
import sys
from typing import Optional

import dearpygui.dearpygui as dpg
import numpy as np

from ...data.analysis import compute_metrics, load_csv, trim_csv
from ...data.store import Recording
from .. import theme as T
from ..safe import safe, toast

LIB_W = 360
KIND_WORD = {"manual": "Recording", "freespin": "Hand motion (free-spin)", "trajectory": "Waveform", "playback": "Playback",
             "test_step": "Step test", "test_relay": "Relay test", "calibration": "Calibration"}
SPEEDS = ["×0.5", "×0.75", "×1", "×1.5", "×2"]
METRICS = [("tracking_score_pct", "Tracking score", "{:.0f}%"), ("err_rms_deg", "RMS error", "{:.2f}°"),
           ("err_max_abs_deg", "Worst error", "{:.2f}°"), ("vel_max_abs_deg_s", "Peak speed", "{:.0f}°/s"),
           ("current_max_abs_A", "Peak current", "{:.1f} A"), ("pos_range_deg", "Range used", "{:.0f}°"),
           ("step_rise_s", "Rise time", "{:.3f} s"), ("step_overshoot_pct", "Overshoot", "{:.1f}%"),
           ("step_settle_s", "Settling", "{:.2f} s"), ("relay_Ku_Nm_per_rad", "Ku", "{:.1f} Nm/rad"),
           ("relay_Tu_s", "Tu", "{:.3f} s"), ("max_gap_ms", "Longest gap", "{:.0f} ms")]
COLS = {"setpoint": "setpoint_deg", "target": "target_deg", "position": "position_deg", "error": "error_deg",
        "velocity": "velocity_deg_s", "current": "current_A"}
PLOTS = (("pos", "degrees", ("setpoint", "target", "position")), ("err", "error °", ("error",)),
         ("dyn", "°/s, A", ("velocity", "current")))


class PlaybackPanel:
    def __init__(self, ui):
        self.ui = ui
        self.app = ui.app
        self.c = ui.app.controller
        self.store = ui.app.store
        self.tags = {}
        self.rows = []
        self.selected: Optional[Recording] = None
        self.data = None
        self._dirty = True
        self._h = 600
        self.app.bus.subscribe("recording_done", lambda r: setattr(self, "_dirty", True))

    # ---- build ---------------------------------------------------------------------------------
    def build(self):
        g = self.ui.gate
        with dpg.group(horizontal=True, horizontal_spacing=28):
            with dpg.child_window(width=LIB_W, border=False, tag="lib_col") as lc:
                dpg.bind_item_theme(lc, T.theme("bare"))
                self.tags["search"] = T.text_input("", LIB_W - 4, "Search names, notes, tags", callback=safe(self._mark))
                with dpg.group(horizontal=True, horizontal_spacing=6):
                    self.tags["sort"] = dpg.add_combo(["newest", "pinned", "most played", "name"], default_value="newest",
                                                      width=(LIB_W - 10) // 2, callback=safe(self._mark))
                    self.tags["coll"] = dpg.add_combo(["all collections"] + self.store.collections(),
                                                      default_value="all collections", width=(LIB_W - 10) // 2, callback=safe(self._mark))
                T.gap(4)
                with dpg.child_window(tag="lib_list", border=False) as ll:
                    dpg.bind_item_theme(ll, T.theme("bare"))

            with dpg.child_window(border=False, no_scrollbar=True, tag="pb_right") as pr:
                dpg.bind_item_theme(pr, T.theme("bare"))
                with dpg.group(tag="pb_empty"):
                    T.heading("Nothing selected")
                    T.label("Pick a recording on the left. Free-spin recordings are hand motions you can play back on the motor.")
                with dpg.group(tag="pb_body", show=False):
                    self.tags["title"] = dpg.add_text("")
                    T.bind_font(self.tags["title"], "head")
                    self.tags["meta"] = T.label("", wrap=900)
                    T.gap(4)
                    with dpg.group(horizontal=True):
                        self.tags["play"] = T.action("Play on motor", "primary", safe(self._play), 150)
                        g.bind(self.tags["play"], "playback",
                               "Streams this position trace to the motor from where the wheel is now. Saved as a new playback, linked here.")
                        self.tags["speed"] = dpg.add_combo(SPEEDS, default_value="×1", width=80)
                        b = T.action("Stop", "secondary", safe(self.c.stop_all), 80)
                        g.bind(b, "stop_stream")
                        self.tags["pb_status"] = T.label("")
                        dpg.add_spacer(width=20)
                        self.tags["pin"] = T.action("Pin", "quiet", safe(self._toggle_pin))
                        T.action("Open folder", "quiet", safe(self._open_folder))
                        T.action("Hide", "quiet", safe(self._delete))
                    for key, ylab, series in PLOTS:
                        with dpg.plot(height=170, width=-1, tag=f"pb_plot_{key}", no_title=True, no_frame=True, no_mouse_pos=True, no_menus=True,
                                      no_box_select=True, show=key != "dyn"):
                            dpg.add_plot_legend(location=dpg.mvPlot_Location_NorthEast, horizontal=True)
                            dpg.add_plot_axis(dpg.mvXAxis, tag=f"pb_x_{key}", no_tick_labels=key != "dyn" and key != "err")
                            y = dpg.add_plot_axis(dpg.mvYAxis, label=ylab, tag=f"pb_y_{key}")
                            for s in series:
                                dpg.add_line_series([], [], label={"target": "stream target", "velocity": "speed"}.get(s, s),
                                                    parent=y, tag=f"pb_s_{key}_{s}")
                                dpg.bind_item_theme(f"pb_s_{key}_{s}", T.series_theme(s))
                            dpg.add_drag_line(tag=f"pb_cur_{key}", color=T.INK, thickness=1, default_value=0,
                                              callback=safe(self._drag), user_data=key)
                            dpg.add_inf_line_series([], parent=y, tag=f"pb_trim_{key}")
                            dpg.bind_item_theme(f"pb_trim_{key}", T.series_theme("trim"))
                    with dpg.group(horizontal=True):
                        self.tags["more"] = T.toggle("Speed and current", False, safe(self._more))
                        dpg.add_spacer(width=18)
                        self.tags["cursor_txt"] = T.mono_text("", T.MUTED, small=True)
                    T.gap(10)
                    with dpg.group(horizontal=True, horizontal_spacing=40):
                        with dpg.group():
                            t = dpg.add_text("Results"); T.bind_font(t, "label")
                            with dpg.group(horizontal=True, horizontal_spacing=14, tag="pb_metrics") as mg:
                                dpg.bind_item_theme(mg, T.theme("compact"))
                                for c in range(4):
                                    dpg.add_group(tag=f"pb_mcol{c}")
                        with dpg.group():
                            t = dpg.add_text("Setup"); T.bind_font(t, "label")
                            self.tags["setup"] = T.label("", T.INK, wrap=320)
                        with dpg.group():
                            t = dpg.add_text("Notes"); T.bind_font(t, "label")
                            self.tags["notes"] = T.text_input("", 320, "what was this run? Enter to save",
                                                              callback=safe(self._save_notes), on_enter=True)
                            self.tags["tagsin"] = T.text_input("", 320, "tags, comma separated. Enter to save",
                                                               callback=safe(self._save_tags), on_enter=True)
                            T.gap(6)
                            with dpg.collapsing_header(label="Trim the end") as ch:
                                T.bind_font(ch, "small")
                                self.tags["trim"] = dpg.add_slider_float(default_value=0, min_value=0, max_value=1, width=320,
                                                                         format="keep 0 to %.2f s", callback=safe(self._trim_preview))
                                T.action("Trim permanently", "secondary", safe(self._trim))

    def on_resize(self, w, h):
        self._h = h
        dpg.configure_item("lib_col", height=h + 30)
        dpg.configure_item("lib_list", height=h - 60)
        dpg.configure_item("pb_right", width=max(500, w - LIB_W - 28), height=h + 30)
        self._layout()

    def _layout(self):
        more = dpg.get_value(self.tags["more"]) if "more" in self.tags else False
        avail = max(240, self._h - 350)
        if more:
            hs = (int(avail * 0.45), int(avail * 0.25), int(avail * 0.3))
        else:
            hs = (int(avail * 0.64), int(avail * 0.36), 0)
        for (key, _, _), hh in zip(PLOTS, hs):
            dpg.configure_item(f"pb_plot_{key}", height=max(hh, 60), show=hh > 0)
        dpg.configure_item("pb_x_err", no_tick_labels=more)

    def _more(self, *_):
        self._layout()

    # ---- list ----------------------------------------------------------------------------------
    def _mark(self, *_):
        self._dirty = True

    def _rebuild_list(self):
        self._dirty = False
        coll = dpg.get_value(self.tags["coll"])
        sort = {"newest": "recent", "most played": "playbacks"}.get(dpg.get_value(self.tags["sort"]), dpg.get_value(self.tags["sort"]))
        self.rows = self.store.list(sort=sort, collection=None if coll == "all collections" else coll,
                                    search=dpg.get_value(self.tags["search"]))
        dpg.configure_item(self.tags["coll"], items=["all collections"] + self.store.collections())
        dpg.delete_item("lib_list", children_only=True)
        if not self.rows:
            dpg.add_text("No recordings yet. Press Record on the Drive page, or free-spin and record a hand motion.",
                         color=T.MUTED, wrap=LIB_W - 10, parent="lib_list")
        for r in self.rows:
            self._row(r, 0)
            for pb in self.store.playbacks_of(r.uid):
                self._row(pb, 1)

    def _row(self, r: Recording, depth: int):
        sel = bool(self.selected and self.selected.uid == r.uid)
        name = r.name
        meta = r.created_str[5:16].replace("-", "/", 1)
        if not depth and r.playback_count:
            meta = f"{r.playback_count}×  " + meta
        with dpg.group(horizontal=True, parent="lib_list", horizontal_spacing=0):
            if depth:
                dpg.add_spacer(width=18)
            b = dpg.add_selectable(label=name, default_value=sel, width=LIB_W - 120 - (18 if depth else 0),
                                   callback=safe(self._select), user_data=r.uid)
            dpg.bind_item_theme(b, T.theme("row"))
            T.bind_font(b, "label" if not depth else "body")
            it = dpg.add_text(meta + ("  pinned" if r.pinned else ""), color=T.BAD if r.health_worst == "FAIL" else T.MUTED)
            T.bind_font(it, "small")

    def _select(self, sender, app_data, uid):
        self.selected = self.store.get(uid)
        self.c.selected_recording = self.selected
        self._load()
        self._dirty = True

    # ---- selected recording ------------------------------------------------------------------------
    def _load(self):
        r = self.selected
        dpg.configure_item("pb_empty", show=r is None)
        dpg.configure_item("pb_body", show=r is not None)
        if r is None:
            return
        dpg.set_value(self.tags["title"], r.name)
        parent = self.store.get(r.parent_uid) if r.parent_uid else None
        meta = f"{KIND_WORD.get(r.kind, r.kind)}, {r.duration_s:.1f} s, {r.samples:,} samples. In {r.collection}, {r.created_str}."
        if parent:
            meta += f" Playback of {parent.name}."
        elif r.playback_count:
            meta += f" Played back {r.playback_count} time{'s' if r.playback_count != 1 else ''}."
        if r.health_summary:
            meta += f" Health during it: {r.health_summary}."
        dpg.set_value(self.tags["meta"], meta)
        dpg.set_item_label(self.tags["pin"], "Unpin" if r.pinned else "Pin")
        try:
            self.data = load_csv(r.csv)
        except Exception as e:
            toast(f"Cannot read {r.csv}: {e}", "bad")
            self.data = None
            return
        d = self.data
        t = d["t_s"].tolist()
        for key, _, series in PLOTS:
            for s in series:
                dpg.set_value(f"pb_s_{key}_{s}", [t, d[COLS[s]].tolist()])
            dpg.fit_axis_data(f"pb_x_{key}"); dpg.fit_axis_data(f"pb_y_{key}")
            dpg.set_value(f"pb_trim_{key}", [[]])
        tmax = float(t[-1]) if t else 1.0
        dpg.configure_item(self.tags["trim"], max_value=tmax)
        dpg.set_value(self.tags["trim"], tmax)
        self._set_cursor(0.0)

        m = r.metrics
        for c in range(4):
            dpg.delete_item(f"pb_mcol{c}", children_only=True)
        items = [(lab, fmt.format(m[k])) for k, lab, fmt in METRICS if k in m and m[k] == m[k]][:8]
        half = (len(items) + 1) // 2
        for i, (lab, val) in enumerate(items):
            c = 0 if i < half else 2
            dpg.add_text(lab, color=T.MUTED, parent=f"pb_mcol{c}")
            dpg.add_text(val, parent=f"pb_mcol{c + 1}")
        if not items:
            t = dpg.add_text("No results", color=T.MUTED, parent="pb_mcol0"); T.bind_font(t, "small")
        gains = r.gains or {}
        lim = ""
        if gains.get("limits_valid"):
            lim = f"\nEnd stops {gains.get('limit_left_deg', 0):+.0f}° and {gains.get('limit_right_deg', 0):+.0f}°"
        dpg.set_value(self.tags["setup"], f"Kp {gains.get('kp', '?')}  Kd {gains.get('kd', '?')}  Ki {gains.get('ki', '?')}  "
                                          f"Tff {gains.get('tff_Nm', '?')}{lim}\nFolder {r.dir.name}")
        dpg.set_value(self.tags["notes"], r.notes)
        dpg.set_value(self.tags["tagsin"], ", ".join(r.tags))

    def _drag(self, sender, app_data, key):
        self._set_cursor(dpg.get_value(sender))

    def _set_cursor(self, t):
        if self.data is None:
            return
        for key, _, _ in PLOTS:
            dpg.set_value(f"pb_cur_{key}", t)
        d = self.data
        i = int(np.clip(np.searchsorted(d["t_s"], t), 0, len(d["t_s"]) - 1))
        f = lambda v: "—" if v != v else f"{v:+.1f}"
        dpg.set_value(self.tags["cursor_txt"], f"t {d['t_s'][i]:.2f} s   setpoint {f(d['setpoint_deg'][i])}°   position {f(d['position_deg'][i])}°   "
                                               f"error {f(d['error_deg'][i])}°   speed {f(d['velocity_deg_s'][i])}°/s   current {f(d['current_A'][i])} A")

    def _trim_preview(self, sender, t):
        for key, _, _ in PLOTS:
            dpg.set_value(f"pb_trim_{key}", [[t]])

    def _trim(self):
        r = self.selected
        if r is None or self.data is None:
            return
        t_end = dpg.get_value(self.tags["trim"])
        kept = trim_csv(r.csv, t_end)
        self.data = load_csv(r.csv)
        r.metrics = compute_metrics(self.data, r.kind)
        r.samples = kept
        r.duration_s = float(self.data["t_s"][-1]) if kept else 0.0
        self.store.finalize(r)
        toast(f"Trimmed to {t_end:.2f} s ({kept:,} samples).")
        self._load(); self._dirty = True

    def _play(self):
        speed = float(dpg.get_value(self.tags["speed"]).lstrip("×"))
        self.c.play_recording(self.selected, speed=speed)
        toast(f"Playing back {self.selected.name}.")

    def _toggle_pin(self):
        if self.selected:
            self.store.set_pinned(self.selected.uid, not self.selected.pinned)
            self.selected = self.store.get(self.selected.uid)
            self._load(); self._dirty = True

    def _save_notes(self, sender, text):
        if self.selected:
            self.store.set_notes(self.selected.uid, text)
            toast("Notes saved.")

    def _save_tags(self, sender, text):
        if self.selected:
            self.store.set_tags(self.selected.uid, text.split(","))
            self._dirty = True
            toast("Tags saved.")

    def _open_folder(self):
        if not self.selected:
            return
        p = str(self.selected.dir)
        try:
            if sys.platform == "win32":
                os.startfile(p)                   # noqa
            elif sys.platform == "darwin":
                subprocess.Popen(["open", p])
            else:
                subprocess.Popen(["xdg-open", p])
        except Exception as e:
            toast(f"Cannot open the folder: {e}", "warn")

    def _delete(self):
        if self.selected:
            self.store.soft_delete(self.selected.uid)
            toast(f"Hid {self.selected.name}. The files stay on disk.")
            self.selected = None
            self.c.selected_recording = None
            self._load()
            self._dirty = True

    def refresh(self):
        st = self.c.streamer
        rec = self.app.recorder.rec
        if st.active and rec and rec.kind == "playback":
            dpg.set_value(self.tags["pb_status"], f"Playing, {st.progress * 100:.0f}%. Saving as {rec.name}.")
        else:
            dpg.set_value(self.tags["pb_status"], "")

    def slow_refresh(self):
        if self._dirty:
            self._rebuild_list()
