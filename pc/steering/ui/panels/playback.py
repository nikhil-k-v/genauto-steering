"""Playback & Library tab.

Left: the library - recordings sorted by recency / pinned / playback count,
filtered by collection and search; each recording expands to show its
playbacks (<name>_pb01...).  Right: the selected recording's plots with a
cursor and trim, its metrics and health summary, and the Play-back button
(gated).  Everything on the right re-sizes with the window; the only
scrollable region is the library list itself (item 4)."""
from __future__ import annotations

import os
import subprocess
import sys
from typing import Optional

import dearpygui.dearpygui as dpg
import numpy as np

from ... import protocol as P
from ...data.analysis import load_csv, trim_csv, compute_metrics
from ...data.store import Recording
from .. import theme as T
from ..safe import safe, toast

LIB_W = 420


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
        self.app.bus.subscribe("recording_done", lambda r: setattr(self, "_dirty", True))

    # ---- build ---------------------------------------------------------------------------
    def build(self):
        g = self.ui.gate
        with dpg.group(horizontal=True):
            with dpg.child_window(width=LIB_W, border=True, tag="lib_col"):
                with dpg.group(horizontal=True):
                    self.tags["sort"] = dpg.add_combo(["recent", "pinned", "playbacks", "name"], default_value="recent",
                                                      width=100, callback=safe(self._mark))
                    self.tags["coll"] = dpg.add_combo(["all"] + self.store.collections(), default_value="all", width=110,
                                                      callback=safe(self._mark))
                    self.tags["search"] = dpg.add_input_text(hint="search", width=150, callback=safe(self._mark))
                dpg.add_separator()
                with dpg.child_window(tag="lib_list", border=False):
                    pass
            with dpg.child_window(border=False, no_scrollbar=True, tag="pb_right"):
                with dpg.group(horizontal=True):
                    self.tags["title"] = dpg.add_text("select a recording", color=T.ACCENT)
                    self.tags["pin"] = dpg.add_button(label="pin", width=70, callback=safe(self._toggle_pin))
                    dpg.add_button(label="open folder", width=100, callback=safe(self._open_folder))
                    dpg.add_button(label="delete", width=70, callback=safe(self._delete))
                with dpg.group(horizontal=True):
                    dpg.add_text("speed", color=T.DIM)
                    self.tags["speed"] = dpg.add_slider_float(default_value=1.0, min_value=0.25, max_value=2.0, width=160, format="x%.2f")
                    b = dpg.add_button(label="> Play back on motor", width=190, callback=safe(self._play))
                    g.bind(b, "playback", "Streams this recording's position trace to the motor. A new recording <name>_pbNN is created and linked to it.")
                    dpg.bind_item_theme(b, T.theme("btn_accent"))
                    b = dpg.add_button(label="STOP Stop", width=70, callback=safe(self.c.stop_all)); g.bind(b, "stop_stream")
                    self.tags["pb_status"] = dpg.add_text("", color=T.DIM)
                for key, label, series in (("pos", "deg", ("setpoint", "target", "position")),
                                           ("err", "error deg", ("error",)),
                                           ("vel", "deg/s", ("velocity",)),
                                           ("cur", "A / Nm", ("current", "torque"))):
                    with dpg.plot(height=170, width=-1, tag=f"pb_plot_{key}", no_title=True):
                        dpg.add_plot_legend(location=dpg.mvPlot_Location_NorthWest)
                        dpg.add_plot_axis(dpg.mvXAxis, label="t [s]", tag=f"pb_x_{key}")
                        y = dpg.add_plot_axis(dpg.mvYAxis, label=label, tag=f"pb_y_{key}")
                        for s in series:
                            dpg.add_line_series([], [], label=s, parent=y, tag=f"pb_s_{key}_{s}")
                            dpg.bind_item_theme(f"pb_s_{key}_{s}", T.series_theme(s))
                        dpg.add_inf_line_series([], parent=y, tag=f"pb_cur_{key}")
                        dpg.bind_item_theme(f"pb_cur_{key}", T.series_theme("cursor"))
                        dpg.add_inf_line_series([], parent=y, tag=f"pb_trim_{key}")
                        dpg.bind_item_theme(f"pb_trim_{key}", T.series_theme("error"))
                with dpg.group(horizontal=True):
                    self.tags["cursor"] = dpg.add_slider_float(label="cursor", default_value=0, min_value=0, max_value=1, width=380, format="%.2f s", callback=safe(self._cursor))
                    self.tags["cursor_txt"] = dpg.add_text("", color=T.DIM)
                with dpg.group(horizontal=True):
                    self.tags["trim"] = dpg.add_slider_float(label="trim end", default_value=0, min_value=0, max_value=1, width=380, format="%.2f s", callback=safe(self._trim_preview))
                    dpg.add_button(label="Trim file permanently", width=170, callback=safe(self._trim))
                with dpg.group(horizontal=True):
                    with dpg.child_window(width=460, height=170, border=True):
                        dpg.add_text("METRICS", color=T.DIM)
                        self.tags["metrics"] = dpg.add_text("", wrap=440)
                    with dpg.child_window(width=-1, height=170, border=True):
                        dpg.add_text("SETUP | HEALTH DURING RECORDING", color=T.DIM)
                        self.tags["setup"] = dpg.add_text("", wrap=520)
                with dpg.group(horizontal=True):
                    self.tags["notes"] = dpg.add_input_text(hint="notes", width=460, callback=safe(self._save_notes), on_enter=True)
                    self.tags["tagsin"] = dpg.add_input_text(hint="tags, comma separated", width=300, callback=safe(self._save_tags), on_enter=True)

    def on_resize(self, w, h):
        ph = max(110, (h - 330) // 4)
        for key in ("pos", "err", "vel", "cur"):
            dpg.configure_item(f"pb_plot_{key}", height=ph)
        dpg.configure_item("pb_right", width=max(500, w - LIB_W - 30))

    # ---- library list --------------------------------------------------------------------------
    def _mark(self, *_):
        self._dirty = True

    def _rebuild_list(self):
        self._dirty = False
        coll = dpg.get_value(self.tags["coll"])
        self.rows = self.store.list(sort=dpg.get_value(self.tags["sort"]), collection=None if coll == "all" else coll,
                                    search=dpg.get_value(self.tags["search"]))
        dpg.configure_item(self.tags["coll"], items=["all"] + self.store.collections())
        dpg.delete_item("lib_list", children_only=True)
        for r in self.rows:
            self._row(r, 0)
            if self.selected and self.selected.uid in (r.uid, getattr(self.selected, "parent_uid", None)):
                for pb in self.store.playbacks_of(r.uid):
                    self._row(pb, 1)

    def _row(self, r: Recording, depth: int):
        sel = self.selected and self.selected.uid == r.uid
        label = ("    > " if depth else "") + ("[P] " if r.pinned else "") + r.name
        with dpg.group(horizontal=True, parent="lib_list"):
            b = dpg.add_selectable(label=label, default_value=bool(sel), width=LIB_W - 150, callback=safe(self._select), user_data=r.uid)
            info = f"{r.created_str[5:16]}"
            if not depth and r.playback_count:
                info += f" | {r.playback_count} pb"
            if r.health_worst:
                info += f" | {r.health_worst}"
            dpg.add_text(info, color=T.BAD if r.health_worst else T.DIM)
        with dpg.tooltip(b):
            m = r.metrics
            dpg.add_text(f"{r.kind} | {r.duration_s:.1f}s | {r.samples} samples | {r.collection}\n"
                         f"err rms {m.get('err_rms_deg', float('nan')):.2f} deg max {m.get('err_max_abs_deg', float('nan')):.2f} deg\n"
                         f"{r.notes}\n{r.health_summary}", wrap=380)

    def _select(self, sender, app_data, uid):
        self.selected = self.store.get(uid)
        self.c.selected_recording = self.selected
        self._load()
        self._dirty = True

    # ---- selected recording -------------------------------------------------------------------------
    def _load(self):
        r = self.selected
        if r is None:
            return
        dpg.set_value(self.tags["title"], f"{r.name}   [{r.kind}]   {r.created_str}   {r.duration_s:.1f}s" +
                      (f"   > playback of {self.store.get(r.parent_uid).name}" if r.parent_uid and self.store.get(r.parent_uid) else ""))
        dpg.set_item_label(self.tags["pin"], "pinned" if r.pinned else "pin")
        try:
            self.data = load_csv(r.csv)
        except Exception as e:
            toast(f"cannot load {r.csv}: {e}", "bad")
            self.data = None
            return
        d = self.data
        t = d["t_s"].tolist()
        for key, series in (("pos", ("setpoint", "target", "position")), ("err", ("error",)), ("vel", ("velocity",)), ("cur", ("current", "torque"))):
            for s in series:
                col = {"setpoint": "setpoint_deg", "target": "target_deg", "position": "position_deg", "error": "error_deg",
                       "velocity": "velocity_deg_s", "current": "current_A", "torque": "torque_cmd_Nm"}[s]
                dpg.set_value(f"pb_s_{key}_{s}", [t, d[col].tolist()])
            dpg.fit_axis_data(f"pb_x_{key}"); dpg.fit_axis_data(f"pb_y_{key}")
            dpg.set_value(f"pb_trim_{key}", [[]])
        tmax = float(t[-1]) if t else 1.0
        for k in ("cursor", "trim"):
            dpg.configure_item(self.tags[k], max_value=tmax)
        dpg.set_value(self.tags["cursor"], 0.0); dpg.set_value(self.tags["trim"], tmax)
        self._cursor(None, 0.0)
        m = r.metrics
        keys = ["duration_s", "sample_rate_hz", "max_gap_ms", "tracking_score_pct", "err_rms_deg", "err_max_abs_deg",
                "err_p95_abs_deg", "vel_max_abs_deg_s", "current_max_abs_A", "pos_range_deg", "step_rise_s",
                "step_overshoot_pct", "step_settle_s", "step_ss_err_deg", "relay_Tu_s", "relay_Ku_Nm_per_rad"]
        lines = [f"{k:<22}{m[k]:>10.3f}" for k in keys if k in m]
        dpg.set_value(self.tags["metrics"], "\n".join(lines) or "no metrics")
        gains = r.gains
        setup = (f"Kp {gains.get('kp', '?')}  Kd {gains.get('kd', '?')}  Ki {gains.get('ki', '?')}  Tff {gains.get('tff_Nm', '?')}\n"
                 f"limits {gains.get('limit_left_deg', '?')} ... {gains.get('limit_right_deg', '?')}\n"
                 f"collection {r.collection} | tags {', '.join(r.tags)}\n\nhealth: {r.health_summary or 'all OK'}")
        dpg.set_value(self.tags["setup"], setup)
        dpg.set_value(self.tags["notes"], r.notes)
        dpg.set_value(self.tags["tagsin"], ", ".join(r.tags))

    def _cursor(self, sender, t):
        if self.data is None:
            return
        for key in ("pos", "err", "vel", "cur"):
            dpg.set_value(f"pb_cur_{key}", [[t]])
        d = self.data
        i = int(np.searchsorted(d["t_s"], t))
        i = min(max(i, 0), len(d["t_s"]) - 1)
        dpg.set_value(self.tags["cursor_txt"], f"t {d['t_s'][i]:.3f}s  sp {d['setpoint_deg'][i]:.2f}  pos {d['position_deg'][i]:.2f}  "
                                               f"err {d['error_deg'][i]:.2f}  vel {d['velocity_deg_s'][i]:.1f}  I {d['current_A'][i]:.2f}A")

    def _trim_preview(self, sender, t):
        for key in ("pos", "err", "vel", "cur"):
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
        toast(f"trimmed to {t_end:.2f}s ({kept} samples)")
        self._load(); self._dirty = True

    def _play(self):
        self.c.play_recording(self.selected, speed=dpg.get_value(self.tags["speed"]))
        toast(f"playing back {self.selected.name}")

    def _toggle_pin(self):
        if self.selected:
            self.store.set_pinned(self.selected.uid, not self.selected.pinned)
            self.selected = self.store.get(self.selected.uid)
            self._load(); self._dirty = True

    def _save_notes(self, sender, text):
        if self.selected:
            self.store.set_notes(self.selected.uid, text)

    def _save_tags(self, sender, text):
        if self.selected:
            self.store.set_tags(self.selected.uid, text.split(","))
            self._dirty = True

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
            toast(f"cannot open folder: {e}", "warn")

    def _delete(self):
        if self.selected:
            self.store.soft_delete(self.selected.uid)
            toast(f"hidden {self.selected.name} (files kept on disk)")
            self.selected = None
            self.c.selected_recording = None
            self._dirty = True

    def refresh(self):
        st = self.c.streamer
        if st.active and self.app.recorder.rec and self.app.recorder.rec.kind == "playback":
            dpg.set_value(self.tags["pb_status"], f"REC {self.app.recorder.rec.name}  {st.progress * 100:.0f} %")
        else:
            dpg.set_value(self.tags["pb_status"], "")

    def slow_refresh(self):
        if self._dirty:
            self._rebuild_list()
