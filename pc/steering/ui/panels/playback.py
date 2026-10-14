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

from ... import protocol as P
from ... import words as W
from ...data.analysis import compute_metrics, load_csv, trim_csv
from ...data.store import Recording
from .. import lines as L
from .. import theme as T
from ..liveplot import SOURCE_LABEL, SOURCES, STREAMS
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
# plots: key, y label, (series name, column, y axis)
PLOTS = (("pos", "wheel angle (°)", [(f"sp_{s}", "setpoint_deg", 1) for s in SOURCES] +
                                     [(f"req_{s}", "target_deg", 1) for s in STREAMS] + [("position", "position_deg", 1)]),
         ("err", "error (°)", [("error", "error_deg", 1)]),
         ("spd", "speed (°/s)", [("velocity", "velocity_deg_s", 1)]),
         ("tq", "torque (N·m)", [("torque", "torque_cmd_Nm", 1), ("current", "current_A", 2)]))
STATE_SOURCE = {P.CS_HOLD: "user", P.CS_TEST: "test", P.CS_CALIB: "calib"}


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
                T.tip(self.tags["search"], "Filters the list as you type: matches names, notes and tags.")
                with dpg.group(horizontal=True, horizontal_spacing=6):
                    self.tags["sort"] = dpg.add_combo(["newest", "pinned", "most played", "name"], default_value="newest",
                                                      width=(LIB_W - 10) // 2, callback=safe(self._mark))
                    self.tags["coll"] = dpg.add_combo(["all collections"] + self.store.collections(),
                                                      default_value="all collections", width=(LIB_W - 10) // 2, callback=safe(self._mark))
                    T.tip(self.tags["sort"], "Order of the list. Playbacks always sit under the recording they replayed.")
                    T.tip(self.tags["coll"], "Show one collection only.")
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
                        T.tip(self.tags["speed"], "Playback speed. ×2 plays the motion twice as fast (and twice as "
                                                  "aggressively); the Teensy's speed limit still applies.")
                        b = T.action("Stop playback", "secondary", safe(self.c.stop_all), 130)
                        g.bind(b, "stop_stream", "Stop the playback; the motor keeps the angle it reached "
                                                 "(Position control). The partial run is still saved.")
                        dpg.add_spacer(width=10)
                        self.tags["pin"] = T.action("Pin", "quiet", safe(self._toggle_pin),
                                                    tip_text="Pinned recordings sort first with \"pinned\".")
                        T.action("Open folder", "quiet", safe(self._open_folder),
                                 tip_text="Open this recording's folder (data.csv, meta.json, events, health) "
                                          "in the file manager.")
                        T.action("Hide", "quiet", safe(self._delete),
                                 tip_text="Remove from the library list. The files stay on disk; "
                                          "Settings > Rebuild catalog brings it back.")
                    self.tags["pb_status"] = T.label("", T.SOURCE_COLOR["playback"])
                    self.leg = dpg.add_drawlist(width=600, height=22, tag="pb_legend")
                    for key, ylab, series in PLOTS:
                        with dpg.plot(height=170, width=-1, tag=f"pb_plot_{key}", no_title=True, no_mouse_pos=True,
                                      no_menus=True, no_box_select=True, show=key in ("pos", "err")) as pl:
                            T.plot_font(pl)
                            dpg.add_plot_axis(dpg.mvXAxis, tag=f"pb_x_{key}", no_tick_labels=key == "pos")
                            y = dpg.add_plot_axis(dpg.mvYAxis, label=ylab, tag=f"pb_y_{key}")
                            y2 = dpg.add_plot_axis(dpg.mvYAxis2, label="current (A)", tag=f"pb_y2_{key}", opposite=True) \
                                if key == "tq" else None
                            for name, col, ax in series:
                                it = dpg.add_line_series([], [], parent=y if ax == 1 else y2, tag=f"pb_s_{key}_{name}")
                                T.series(name, it)
                            dpg.add_drag_line(tag=f"pb_cur_{key}", color=T.INK, thickness=1, default_value=0,
                                              callback=safe(self._drag), user_data=key)
                            it = dpg.add_inf_line_series([], parent=y, tag=f"pb_trim_{key}")
                            T.series("trim", it)
                    with dpg.group(horizontal=True):
                        self.tags["show_spd"] = T.toggle("Speed", False, safe(self._more),
                                                         tip_text="Show the measured speed under the angle plot.")
                        dpg.add_spacer(width=8)
                        self.tags["show_tq"] = T.toggle("Torque and current", False, safe(self._more),
                                                        tip_text="Show the torque command (dashed) and the motor "
                                                                 "current (solid) under the angle plot.")
                        dpg.add_spacer(width=18)
                        self.tags["cursor_txt"] = T.mono_text("", T.MUTED, small=True)
                        T.tip(self.tags["cursor_txt"], "Values at the cursor line. Drag the line in any plot to move it.")
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
                                T.tip(self.tags["trim"], "Drag to choose where the recording should end (red line).")
                                T.action("Trim permanently", "secondary", safe(self._trim),
                                         tip_text="Delete every sample after the red line from data.csv. Cannot be undone.")

    def on_resize(self, w, h):
        self._h = h
        self._w = max(500, w - LIB_W - 28)
        dpg.configure_item("lib_col", height=h + 30)
        dpg.configure_item("lib_list", height=h - 60)
        dpg.configure_item("pb_right", width=max(500, w - LIB_W - 28), height=h + 30)
        self._layout()

    def _layout(self):
        if "show_spd" not in self.tags:
            return
        spd, tq = dpg.get_value(self.tags["show_spd"]), dpg.get_value(self.tags["show_tq"])
        avail = max(240, self._h - 372)
        n = int(spd) + int(tq)
        small = int(avail * (0.2 if n == 2 else 0.24))
        err = int(avail * 0.22)
        big = avail - err - n * small
        hs = {"pos": big, "err": err, "spd": small if spd else 0, "tq": small if tq else 0}
        for key, _, _ in PLOTS:
            dpg.configure_item(f"pb_plot_{key}", height=max(hs[key], 60), show=hs[key] > 0)
        last = "tq" if tq else "spd" if spd else "err"
        for key in ("err", "spd", "tq"):
            dpg.configure_item(f"pb_x_{key}", no_tick_labels=key != last)
        dpg.configure_item("pb_legend", width=max(300, self._w))
        self._sig = {}

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
        t = d["t_s"]
        # the setpoint's source on every sample, from the controller state and the recording's kind
        cs = np.nan_to_num(d["ctrl_state"], nan=-1).astype(int)
        traj_src = r.kind if r.kind in ("playback", "trajectory") else "planner"
        src = np.array([traj_src if c == P.CS_TRAJ else STATE_SOURCE.get(c, "") for c in cs], dtype=object)
        self._cols = {}
        for key, _, series in PLOTS:
            for name, col, _ in series:
                y = d[col]
                if name.startswith(("sp_", "req_")):
                    m = src == name.split("_", 1)[1]
                    if name.startswith("sp_"):
                        m2 = m.copy(); m2[1:] |= m[:-1]
                        m = m2
                    y = np.where(m, y, np.nan)
                self._cols[(key, name)] = y
                dpg.set_value(f"pb_s_{key}_{name}", [t.tolist(), y.tolist()])
                dpg.configure_item(f"pb_s_{key}_{name}", show=bool(np.isfinite(y).any()))
            dpg.fit_axis_data(f"pb_x_{key}"); dpg.fit_axis_data(f"pb_y_{key}")
            if key == "tq":
                dpg.fit_axis_data("pb_y2_tq")
            dpg.set_value(f"pb_trim_{key}", [[]])
        self._t = t
        self._sig = {}
        present = [s for s in SOURCES if np.isfinite(self._cols[("pos", f"sp_{s}")]).any()]
        reqs = [s for s in STREAMS if np.isfinite(self._cols[("pos", f"req_{s}")]).any()]
        entries = [("position", "position (measured)")] + [(f"sp_{s}", f"setpoint · {SOURCE_LABEL[s]}") for s in present]
        entries += [(f"req_{s}", f"requested · {SOURCE_LABEL[s]}") for s in reqs]
        entries += [("error", "error = setpoint − position")]
        h = L.legend(self.leg, entries, max(300, getattr(self, "_w", 600)))
        dpg.configure_item(self.leg, height=h)
        t = t.tolist()
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
        f = lambda v: "—" if v != v else W.signed(v)
        dpg.set_value(self.tags["cursor_txt"], f"t {d['t_s'][i]:.2f} s   setpoint {f(d['setpoint_deg'][i])}°   "
                                               f"position {f(d['position_deg'][i])}°   error {f(d['error_deg'][i])}°   "
                                               f"speed {f(d['velocity_deg_s'][i])}°/s   current {f(d['current_A'][i])} A")

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

    def _restyle(self):
        """Re-cut dashes for any plot whose zoom or size changed (dash length is in pixels)."""
        if self.selected is None or getattr(self, "_t", None) is None:
            return
        for key, _, series in PLOTS:
            pl = f"pb_plot_{key}"
            if not dpg.is_item_shown(pl):
                continue
            sig = (dpg.get_axis_limits(f"pb_x_{key}"), dpg.get_axis_limits(f"pb_y_{key}"), tuple(dpg.get_item_rect_size(pl)))
            if self._sig.get(key) == sig:
                continue
            self._sig[key] = sig
            sx, sy = L.scale(pl, f"pb_x_{key}", f"pb_y_{key}")
            for name, col, ax in series:
                if T.SERIES[name][1] != "solid":
                    L.set_line(f"pb_s_{key}_{name}", name, self._t, self._cols[(key, name)], sx, sy)

    def refresh(self):
        self._restyle()
        st = self.c.streamer
        rec = self.app.recorder.rec
        if st.active and rec and rec.kind == "playback":
            dpg.set_value(self.tags["pb_status"], f"playing, {st.progress * 100:.0f}%, saving as {rec.name}")
        else:
            dpg.set_value(self.tags["pb_status"], "")
        dpg.configure_item(self.tags["pb_status"], show=bool(dpg.get_value(self.tags["pb_status"])))

    def slow_refresh(self):
        if self._dirty:
            self._rebuild_list()
