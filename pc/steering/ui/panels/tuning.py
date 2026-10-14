"""Tune - gains, the two tests, and synthetic waveforms.

Gains are applied explicitly and the line under them shows what the Teensy
says it is using (the config echo), so there is never doubt about which gains
are live.  Exactly two tests (step, relay), run on the Teensy for exact timing
and recorded automatically.  Waveforms are a tuning aid, collapsed by default.
"""
from __future__ import annotations

import dearpygui.dearpygui as dpg

from ... import protocol as P
from ...control.trajectories import GENERATOR_PARAMS, make
from ...data.analysis import propose_gains
from .. import theme as T
from ..safe import safe, toast

PARAM_LABEL = {"amplitude_deg": "amplitude °", "freq_hz": "frequency Hz", "duration_s": "duration s",
               "f0_hz": "from Hz", "f1_hz": "to Hz", "hold_s": "hold s"}


class TuningPanel:
    def __init__(self, ui):
        self.ui = ui
        self.app = ui.app
        self.c = ui.app.controller
        self.tags = {}
        self.last = None
        self.app.bus.subscribe("recording_done", self._done)

    def build(self):
        g = self.ui.gate
        gains = self.app.settings.gains
        T.heading("Gains", "Kp and Kd run inside the motor's 20 kHz loop. Ki and Tff are added by the Teensy as torque.")
        with dpg.group(horizontal=True, horizontal_spacing=22):
            self.tags["kp"] = T.number("Kp", gains["kp"], 80, "%.1f")
            self.tags["kd"] = T.number("Kd", gains["kd"], 80, "%.2f")
            self.tags["ki"] = T.number("Ki", gains["ki"], 80, "%.2f")
            self.tags["tff"] = T.number("Tff", gains["tff"], 80, "%.2f")
            b = T.action("Apply", "primary", safe(self._apply), 100)
            g.bind(b, "set_gains", "Send these gains. The line below confirms what the Teensy is using.")
        self.tags["echo"] = T.label("")

        T.gap(22)
        T.heading("Tests", "They run on the Teensy and record themselves. The wheel must be holding.")
        with dpg.group(horizontal=True, horizontal_spacing=48):
            with dpg.group():
                t = dpg.add_text("Step response"); T.bind_font(t, "label")
                T.label("Jump by the amplitude, hold, return.")
                self.tags["s_amp"] = T.number("amplitude °", 30.0, 80, "%.1f")
                self.tags["s_hold"] = T.number("hold s", 3.0, 80, "%.1f")
                b = T.action("Run step test", "secondary", safe(self._step), 160)
                g.bind(b, "tests")
            with dpg.group():
                t = dpg.add_text("Relay auto-tune"); T.bind_font(t, "label")
                T.label("±2 Nm bang-bang around here; proposes gains.")
                self.tags["r_hys"] = T.number("hysteresis °", 1.0, 80, "%.1f")
                self.tags["r_dur"] = T.number("duration s", 8.0, 80, "%.1f")
                b = T.action("Run relay test", "secondary", safe(self._relay), 160)
                g.bind(b, "tests")
        T.gap(8)
        self.tags["result"] = dpg.add_text("", wrap=900)
        with dpg.group(tag="proposals"):
            pass

        T.gap(22)
        with dpg.collapsing_header(label="Test waveforms", default_open=self.app.settings.show_generators) as ch:
            T.bind_font(ch, "label")
            T.label("Synthetic setpoint streams for judging tracking. Recorded automatically.")
            with dpg.group(horizontal=True):
                self.tags["gen"] = dpg.add_combo(list(GENERATOR_PARAMS), default_value="sine", width=140,
                                                 callback=safe(self._gen_changed))
                b = T.action("Run waveform", "secondary", safe(self._run_gen), 150)
                g.bind(b, "trajectory", "Streams the waveform at 200 Hz from where the wheel is now.")
            with dpg.group(tag="gen_params", horizontal=True, horizontal_spacing=22):
                pass
            with dpg.plot(height=170, width=-1, tag="gen_preview", no_title=True, no_frame=True, no_mouse_pos=True, no_menus=True):
                dpg.add_plot_axis(dpg.mvXAxis, tag="gen_px")
                y = dpg.add_plot_axis(dpg.mvYAxis, label="degrees", tag="gen_py")
                dpg.add_line_series([], [], parent=y, tag="gen_ps")
                dpg.bind_item_theme("gen_ps", T.series_theme("setpoint"))
            self._gen_changed(None, "sine")
        with dpg.collapsing_header(label="How to tune") as ch2:
            T.bind_font(ch2, "label")
            T.label("1  Calibrate end stops and zero, then Hold.\n"
                    "2  Step test at 30°. Doesn't reach: add Ki in 0.05 steps. Overshoots: raise Kd, lower Kp. Slow: raise Kp.\n"
                    "3  Or run the relay test, start from the steering-conservative proposal, step-test again.\n"
                    "4  Typical on a steering column: Kp 30 to 80, Kd 1 to 4, Ki 0.05 to 0.5.\n"
                    "Gripping again ramps the gains, so a bad guess cannot snap the wheel. A trip (overspeed, stall, overcurrent) means back off by half.",
                    T.INK, wrap=900)

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
        toast("Copied into the gain fields. Press Apply to send.")

    # ---- waveforms -------------------------------------------------------------------------------
    def _gen_changed(self, sender, name):
        dpg.delete_item("gen_params", children_only=True)
        self.tags["params"] = {}
        for k, v in GENERATOR_PARAMS[name].items():
            with dpg.group(parent="gen_params"):
                self.tags["params"][k] = T.number(PARAM_LABEL.get(k, k), v, 70, "%.2f", callback=safe(self._preview))
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

    # ---- refresh ---------------------------------------------------------------------------------
    def refresh(self):
        live = self.c.live
        cfg = live.config
        if live.pending_gains:
            dpg.set_value(self.tags["echo"], "Sent. Waiting for the Teensy to confirm.")
            dpg.configure_item(self.tags["echo"], color=T.WARN)
        elif cfg:
            dpg.set_value(self.tags["echo"], f"The Teensy is using Kp {cfg.kp:.1f}, Kd {cfg.kd:.2f}, Ki {cfg.ki:.2f}, Tff {cfg.tff_Nm:.2f}.")
            dpg.configure_item(self.tags["echo"], color=T.MUTED)
        else:
            dpg.set_value(self.tags["echo"], "No gain report from the Teensy yet.")
            dpg.configure_item(self.tags["echo"], color=T.MUTED)
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
            dpg.set_value(self.tags["result"], "Relay: not enough oscillation to estimate Ku and Tu. Try longer, or a smaller hysteresis.")
            return
        dpg.set_value(self.tags["result"], f"Relay: Ku {Ku:.1f} Nm/rad, Tu {Tu:.3f} s, amplitude {m.get('relay_amp_deg', 0):.1f}°. Proposed gains:")
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
                    T.action("Use", "quiet", safe(self._use), user_data=gg)
