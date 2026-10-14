"""Tune - gains, the two tests, and synthetic waveforms, with the live response beside them.

    ┌ Gains ─────────────────────┐  ┌ live traces (same as Drive) ─────────────┐
    │ Kp [30.0]   Kd [2.00]      │  │                                          │
    │ Ki [0.00]   Tff [0.00]     │  │                                          │
    │ [Send gains]  in use: …    │  │                                          │
    ├ Tests ─────────────────────┤  │                                          │
    │ Step   amp [30]  hold [3]  │  ├ ▾ Speed ─────────────────────────────────┤
    │ Relay  hys [1]   dur [8]   │  ├ ▾ Torque and current ────────────────────┤
    │ result, proposed gains     │  │                                          │
    ├ ▸ Waveforms                │  │                                          │
    └ ▸ How to tune ─────────────┘  └──────────────────────────────────────────┘

Gains are sent explicitly and the "in use" line is the Teensy's own echo, so
there is never doubt about which gains are live.
"""
from __future__ import annotations

import dearpygui.dearpygui as dpg

from ... import protocol as P
from ...control.trajectories import GENERATOR_PARAMS, make
from ...data.analysis import propose_gains
from .. import lines as L
from .. import theme as T
from ..liveplot import LivePlot
from ..safe import safe, toast

LEFT_W = 470
PARAM_LABEL = {"amplitude_deg": "amplitude °", "freq_hz": "frequency Hz", "duration_s": "duration s",
               "f0_hz": "from Hz", "f1_hz": "to Hz", "hold_s": "hold s"}
PARAM_TIP = {"amplitude_deg": "Peak angle away from where the wheel is when the waveform starts.",
             "freq_hz": "Cycles per second.", "duration_s": "How long the waveform runs.",
             "f0_hz": "Chirp start frequency.", "f1_hz": "Chirp end frequency.", "hold_s": "How long each step is held."}
GEN_TIP = {"sine": "Smooth back-and-forth: shows lag and amplitude loss.",
           "triangle": "Constant-speed ramps: shows tracking at steady speed.",
           "square": "Repeated steps: shows overshoot and settling (slewed by the Teensy).",
           "chirp": "Sine sweeping from low to high frequency: shows where tracking falls off.",
           "step": "One step out and back."}
GAIN_TIP = {
    "kp": "Position stiffness, N·m per radian of error. Runs inside the motor's own 20 kHz loop. "
          "Higher = stiffer and faster, too high = oscillation or a 'too fast' safety stop.",
    "kd": "Damping, N·m per rad/s. Also in the motor's loop. Raise it to calm overshoot; too high makes it buzz.",
    "ki": "Integral, added by the Teensy as torque, to push through steering friction so the wheel reaches "
          "the setpoint. Small steps (0.05). Leaks and is clamped so it can't wind up.",
    "tff": "Constant torque offset (feed-forward), N·m, added to every command. Use it to cancel a steady pull.",
}


class TuningPanel:
    def __init__(self, ui):
        self.ui = ui
        self.app = ui.app
        self.c = ui.app.controller
        self.tags = {}
        self.last = None
        self.plot = LivePlot(ui, "tune")
        self.app.bus.subscribe("recording_done", self._done)

    def build(self):
        g = self.ui.gate
        gains = self.app.settings.gains
        with dpg.group(horizontal=True, horizontal_spacing=28):
            with dpg.child_window(width=LEFT_W, border=False, tag="tune_left") as lc:
                dpg.bind_item_theme(lc, T.theme("bare"))
                T.heading("Gains")
                with dpg.table(header_row=False, policy=dpg.mvTable_SizingFixedFit, borders_innerH=False) as tb:
                    dpg.bind_item_theme(tb, T.theme("compact"))
                    for w in (34, 100, 34, 100):
                        dpg.add_table_column(width_fixed=True, init_width_or_weight=w)
                    for row in (("kp", "Kp", "%.1f", "kd", "Kd", "%.2f"), ("ki", "Ki", "%.2f", "tff", "Tff", "%.2f")):
                        with dpg.table_row():
                            for key, lab, fmt in (row[:3], row[3:]):
                                l = T.label(lab)
                                self.tags[key] = dpg.add_input_float(default_value=gains[key], width=90, step=0, format=fmt)
                                T.tip(l, GAIN_TIP[key])
                                T.tip(self.tags[key], GAIN_TIP[key])
                with dpg.group(horizontal=True):
                    b = T.action("Send gains", "primary", safe(self._apply), 130)
                    g.bind(b, "set_gains", "Send these four gains to the Teensy. They take effect immediately, "
                                           "ramped in gently. The line next to this button shows what the Teensy "
                                           "confirms it is using.")
                    self.tags["echo"] = T.label("")

                T.gap(20)
                T.heading("Tests")
                with dpg.table(header_row=False, policy=dpg.mvTable_SizingFixedFit, borders_innerH=False) as tb:
                    dpg.bind_item_theme(tb, T.theme("compact"))
                    for w in (120, 150, 150):
                        dpg.add_table_column(width_fixed=True, init_width_or_weight=w)
                    with dpg.table_row():
                        b = T.action("Step test", "secondary", safe(self._step), 110)
                        g.bind(b, "tests", "Jump the setpoint by the amplitude, hold, jump back. Runs on the Teensy "
                                           "with exact timing and is recorded automatically. Measures rise time, "
                                           "overshoot and settling.")
                        self.tags["s_amp"] = T.number("amplitude °", 30.0, 60, "%.1f",
                                                      tip_text="How far the step goes from the current angle.")
                        self.tags["s_hold"] = T.number("hold s", 3.0, 60, "%.1f",
                                                       tip_text="How long each side of the step is held.")
                    with dpg.table_row():
                        b = T.action("Relay test", "secondary", safe(self._relay), 110)
                        g.bind(b, "tests", "Bang-bang ±2 N·m around the current angle until it oscillates "
                                           "steadily, then estimate the ultimate gain and period and propose gains. "
                                           "Recorded automatically.")
                        self.tags["r_hys"] = T.number("hysteresis °", 1.0, 60, "%.1f",
                                                      tip_text="Switching band. Smaller = closer to the true ultimate gain, "
                                                               "but noisier.")
                        self.tags["r_dur"] = T.number("duration s", 8.0, 60, "%.1f",
                                                      tip_text="How long to oscillate. Longer = steadier estimate.")
                T.gap(4)
                self.tags["result"] = dpg.add_text("", wrap=LEFT_W - 10)
                with dpg.group(tag="proposals"):
                    pass

                T.gap(16)
                with dpg.collapsing_header(label="Waveforms", default_open=self.app.settings.show_generators) as ch:
                    T.bind_font(ch, "label")
                    T.tip(ch, "Synthetic setpoint streams for judging tracking. Each run is recorded and can be "
                              "replayed from Library.")
                    with dpg.group(horizontal=True):
                        self.tags["gen"] = dpg.add_combo(list(GENERATOR_PARAMS), default_value="sine", width=140,
                                                         callback=safe(self._gen_changed))
                        T.tip(self.tags["gen"], "Shape of the waveform. " + " ".join(f"{k}: {v}" for k, v in GEN_TIP.items()))
                        b = T.action("Run waveform", "secondary", safe(self._run_gen), 150)
                        g.bind(b, "trajectory", "Stream the waveform at 200 Hz, starting from where the wheel is now. "
                                                "Recorded automatically.")
                    with dpg.group(tag="gen_params"):
                        pass
                    with dpg.plot(height=130, width=-1, tag="gen_preview", no_title=True, no_mouse_pos=True,
                                  no_menus=True) as p:
                        T.plot_font(p)
                        dpg.add_plot_axis(dpg.mvXAxis, tag="gen_px", label="seconds")
                        y = dpg.add_plot_axis(dpg.mvYAxis, label="setpoint (°)", tag="gen_py")
                        it = dpg.add_line_series([], [], parent=y, tag="gen_ps")
                        T.series("preview", it)
                    self._gen_changed(None, "sine")
                with dpg.collapsing_header(label="How to tune") as ch2:
                    T.bind_font(ch2, "label")
                    T.label("1  Calibrate (end stops and 0°), then press Position control.\n"
                            "2  Step test at 30°. Never reaches the setpoint: add Ki in 0.05 steps. "
                            "Overshoots: raise Kd, lower Kp. Slow: raise Kp.\n"
                            "3  Or run the relay test, start from the steering-conservative proposal, "
                            "then step-test again.\n"
                            "4  Typical on a steering column: Kp 30 to 80, Kd 1 to 4, Ki 0.05 to 0.5.\n"
                            "Every grip ramps the gains in, so a bad guess cannot snap the wheel. "
                            "A safety stop for speed, stall or current means: back off by half.",
                            T.INK, wrap=LEFT_W - 20)
            with dpg.child_window(border=False, no_scrollbar=True, tag="tune_right") as rc:
                dpg.bind_item_theme(rc, T.theme("bare"))
                self.plot.build()

    def on_resize(self, w, h):
        dpg.configure_item("tune_left", height=h + 30)
        rw = max(400, w - LEFT_W - 28)
        dpg.configure_item("tune_right", width=rw, height=h + 30)
        self.plot.on_resize(rw, h + 30)

    # ---- gains -----------------------------------------------------------------------------------
    def _apply(self):
        kp, kd, ki, tff = (dpg.get_value(self.tags[k]) for k in ("kp", "kd", "ki", "tff"))
        self.c.set_gains(kp, kd, ki, tff)
        self.app.settings.gains = {"kp": kp, "kd": kd, "ki": ki, "tff": tff}
        self.app.settings.save()

    def set_inputs(self, kp, kd, ki, tff=None):
        dpg.set_value(self.tags["kp"], kp); dpg.set_value(self.tags["kd"], kd); dpg.set_value(self.tags["ki"], ki)
        if tff is not None:
            dpg.set_value(self.tags["tff"], tff)

    # ---- tests -----------------------------------------------------------------------------------
    def _step(self):
        h = dpg.get_value(self.tags["s_hold"])
        self.c.run_test(P.TEST_STEP, dpg.get_value(self.tags["s_amp"]), h, h)

    def _relay(self):
        self.c.run_test(P.TEST_RELAY, 0.0, dpg.get_value(self.tags["r_dur"]), dpg.get_value(self.tags["r_hys"]))

    def _done(self, rec):
        if rec.kind.startswith("test_"):
            self.last = rec

    def _use(self, sender, app_data, gg):
        self.set_inputs(gg["kp"], gg["kd"], gg["ki"])
        toast("Copied into the gain fields. Press Send gains to use them.")

    # ---- waveforms -------------------------------------------------------------------------------
    def _gen_changed(self, sender, name):
        dpg.delete_item("gen_params", children_only=True)
        self.tags["params"] = {}
        with dpg.group(horizontal=True, horizontal_spacing=18, parent="gen_params"):
            for k, v in GENERATOR_PARAMS[name].items():
                self.tags["params"][k] = T.number(PARAM_LABEL.get(k, k), v, 60, "%.2f", callback=safe(self._preview),
                                                  tip_text=PARAM_TIP.get(k, ""))
        self._preview()

    def _params(self):
        return {k: dpg.get_value(t) for k, t in self.tags["params"].items()}

    def _preview(self, *_):
        if not dpg.does_item_exist("gen_ps"):
            return
        tr = make(dpg.get_value(self.tags["gen"]), **self._params())
        dpg.fit_axis_data("gen_px"); dpg.fit_axis_data("gen_py")
        dpg.set_value("gen_ps", [tr.t.tolist(), tr.pos.tolist()])
        dpg.fit_axis_data("gen_px"); dpg.fit_axis_data("gen_py")
        self._preview_data = (tr.t, tr.pos)
        self._preview_sig = None

    def _run_gen(self):
        self.c.run_generator(dpg.get_value(self.tags["gen"]), **self._params())

    # ---- refresh ---------------------------------------------------------------------------------
    def refresh(self):
        self.plot.refresh()
        live = self.c.live
        cfg = live.config
        if live.pending_gains:
            dpg.set_value(self.tags["echo"], "sent, waiting for the Teensy to confirm")
            dpg.configure_item(self.tags["echo"], color=T.WARN)
        elif cfg:
            dpg.set_value(self.tags["echo"], f"in use: Kp {cfg.kp:.1f}  Kd {cfg.kd:.2f}  Ki {cfg.ki:.2f}  Tff {cfg.tff_Nm:.2f}")
            dpg.configure_item(self.tags["echo"], color=T.MUTED)
        else:
            dpg.set_value(self.tags["echo"], "no gain report from the Teensy yet")
            dpg.configure_item(self.tags["echo"], color=T.MUTED)
        # dashed preview: re-cut the dashes when the preview's zoom changes
        pd = getattr(self, "_preview_data", None)
        if pd is not None and dpg.is_item_visible("gen_preview"):
            sig = (dpg.get_axis_limits("gen_px"), dpg.get_axis_limits("gen_py"), dpg.get_item_rect_size("gen_preview"))
            if sig != getattr(self, "_preview_sig", None):
                self._preview_sig = sig
                sx, sy = L.scale("gen_preview", "gen_px", "gen_py")
                L.set_line("gen_ps", "preview", pd[0], pd[1], sx, sy)
        if self.last is None:
            return
        rec, self.last = self.last, None
        m = rec.metrics
        nan = float("nan")
        dpg.delete_item("proposals", children_only=True)
        if rec.kind == "test_step":
            dpg.set_value(self.tags["result"],
                          f"Step: rise {m.get('step_rise_s', nan):.3f} s, overshoot {m.get('step_overshoot_pct', nan):.1f}%, "
                          f"settles in {m.get('step_settle_s', nan):.2f} s, steady error {m.get('step_ss_err_deg', nan):.2f}°.")
            return
        Ku, Tu = m.get("relay_Ku_Nm_per_rad"), m.get("relay_Tu_s")
        if not (Ku and Tu):
            dpg.set_value(self.tags["result"], "Relay: the wheel never oscillated steadily, so there is no estimate. "
                                               "Run it longer, or with a smaller hysteresis.")
            return
        dpg.set_value(self.tags["result"], f"Relay: ultimate gain {Ku:.1f} N·m/rad, period {Tu:.3f} s, "
                                           f"amplitude {m.get('relay_amp_deg', 0):.1f}°. Proposed gains:")
        with dpg.table(parent="proposals", header_row=False, borders_innerH=False, policy=dpg.mvTable_SizingFixedFit) as tb:
            dpg.bind_item_theme(tb, T.theme("compact"))
            for _ in range(5):
                dpg.add_table_column()
            for name, gg in propose_gains(Ku, Tu).items():
                with dpg.table_row():
                    t = dpg.add_text(name); T.bind_font(t, "label")
                    dpg.add_text(f"Kp {gg['kp']:.1f}")
                    dpg.add_text(f"Kd {gg['kd']:.2f}")
                    dpg.add_text(f"Ki {gg['ki']:.2f}")
                    T.action("Use", "quiet", safe(self._use), user_data=gg,
                             tip_text="Copy these into the gain fields above (not sent until you press Send gains).")
