"""Trajectory tab - the primary workflow is "record the wheel by hand, play it back"
(Playback tab).  Synthetic generators live here, collapsed by default (item 8)."""
from __future__ import annotations

import dearpygui.dearpygui as dpg

from ... import protocol as P
from ...control.trajectories import GENERATOR_PARAMS, make
from .. import theme as T
from ..safe import safe, toast


class TrajectoryPanel:
    def __init__(self, ui):
        self.ui = ui
        self.app = ui.app
        self.c = ui.app.controller
        self.tags = {}

    def build(self):
        g = self.ui.gate
        T.section("Record a steering motion by hand")
        h = dpg.add_text("1. Enable -> Free-spin   2. Record   3. turn the wheel   4. Stop   -> it appears in Playback & Library.", wrap=900, color=T.DIM)
        T.bind_font(h, "small")
        with dpg.group(horizontal=True):
            self.tags["fs_name"] = T.text_input("hand-motion", 200, "name")
            b = T.action("Free-spin + Record", "warn", safe(self._free_record), 180)
            g.bind(b, "freespin_on", "Enters free-spin (zero torque) and starts recording the wheel position.")
            b = T.action("Stop + Re-grip", "neutral", safe(self._stop_regrip), 150)
            g.bind(b, "stop_record")
        dpg.add_spacer(height=10)
        T.section("Stream status")
        self.tags["stream"] = T.mono_text("idle")
        self.tags["progress"] = dpg.add_progress_bar(default_value=0.0, width=500)
        b = T.action("Stop stream", "bad", safe(self.c.stop_all), 150); g.bind(b, "stop_stream")
        dpg.add_spacer(height=10)
        with dpg.collapsing_header(label="Synthetic generators (tuning aids)", default_open=self.app.settings.show_generators):
            h2 = dpg.add_text("Useful for evaluating tracking; not the main workflow.", color=T.DIM)
            T.bind_font(h2, "small")
            with dpg.group(horizontal=True):
                self.tags["gen"] = dpg.add_combo(list(GENERATOR_PARAMS), default_value="sine", width=140,
                                                 callback=safe(self._gen_changed))
                dpg.bind_item_theme(self.tags["gen"], T.theme("input"))
                b = T.action("Run (auto-records)", "accent", safe(self._run_gen), 170)
                g.bind(b, "trajectory", "Streams the waveform at 200 Hz; recording starts and stops automatically.")
            with dpg.group(tag="gen_params"):
                pass
            with dpg.plot(height=220, width=600, tag="gen_preview", no_title=True):
                dpg.add_plot_axis(dpg.mvXAxis, label="t [s]", tag="gen_px")
                y = dpg.add_plot_axis(dpg.mvYAxis, label="deg", tag="gen_py")
                dpg.add_line_series([], [], parent=y, tag="gen_ps")
                dpg.bind_item_theme("gen_ps", T.series_theme("setpoint"))
            self._gen_changed(None, "sine")

    def _gen_changed(self, sender, name):
        dpg.delete_item("gen_params", children_only=True)
        self.tags["params"] = {}
        with dpg.group(horizontal=True, parent="gen_params"):
            for k, v in GENERATOR_PARAMS[name].items():
                self.tags["params"][k] = T.number(k, v, 90, "%.2f", callback=safe(self._preview))
        self._preview()

    def _params(self):
        return {k: dpg.get_value(t) for k, t in self.tags["params"].items()}

    def _preview(self, *_):
        if not dpg.does_item_exist("gen_ps"):
            return
        tr = make(dpg.get_value(self.tags["gen"]), **self._params())
        dpg.set_value("gen_ps", [tr.t.tolist(), tr.pos.tolist()])
        dpg.fit_axis_data("gen_px"); dpg.fit_axis_data("gen_py")

    def _run_gen(self):
        self.c.run_generator(dpg.get_value(self.tags["gen"]), **self._params())

    def _free_record(self):
        if self.c.live.ctrl_state != P.CS_FREESPIN:
            self.c.freespin_on()
        self._pending_record = dpg.get_value(self.tags["fs_name"]) or "hand-motion"

    _pending_record = None

    def _stop_regrip(self):
        if self.app.recorder.active:
            self.c.record_stop()
        if self.c.live.ctrl_state == P.CS_FREESPIN:
            self.c.freespin_off()

    def refresh(self):
        if self._pending_record and self.c.live.ctrl_state == P.CS_FREESPIN:
            name, self._pending_record = self._pending_record, None
            try:
                self.c.record_start(name, kind="freespin", notes="hand motion in free-spin")
                toast(f"recording {name} - turn the wheel", "info")
            except Exception as e:
                toast(str(e), "warn")
        s = self.app.bus.latest("stream") or {}
        st = self.c.streamer
        if st.active:
            dpg.set_value(self.tags["stream"], f"streaming {s.get('name')} - {st.progress * 100:.0f} %")
            dpg.set_value(self.tags["progress"], st.progress)
        else:
            why = s.get("reason", "")
            dpg.set_value(self.tags["stream"], "idle" if not s else f"last: {s.get('name')} {'completed' if s.get('completed') else 'stopped: ' + why}")
            dpg.set_value(self.tags["progress"], 0.0)
