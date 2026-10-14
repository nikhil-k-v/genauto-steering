"""Tuning tab - exactly two tests (step, relay), run on the Teensy for exact
timing, auto-recorded; results come back from the recording's metrics with
proposed gains you can push into the gain inputs (item 2)."""
from __future__ import annotations

import dearpygui.dearpygui as dpg

from ... import protocol as P
from ...data.analysis import propose_gains
from .. import theme as T
from ..safe import safe, toast


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
        T.section("Current control")
        self.tags["mode"] = T.mono_text("", wrap=900)
        dpg.add_spacer(height=8)
        with dpg.group(horizontal=True):
            with dpg.child_window(width=420, height=190, border=True):
                T.section("Step test")
                dpg.add_text("Jumps the setpoint by `amplitude`, holds, returns. Reports rise / overshoot / settling / steady-state error.", wrap=390)
                self.tags["s_amp"] = T.number("amplitude [deg]", 30.0, 100, "%.1f")
                self.tags["s_hold"] = T.number("hold [s]", 3.0, 100, "%.1f")
                b = T.action("Run step test", "accent", safe(self._step), 160)
                g.bind(b, "tests", "Runs on the Teensy; recording starts and stops automatically.")
            with dpg.child_window(width=420, height=190, border=True):
                T.section("Relay auto-tune (Astrom-Hagglund)")
                dpg.add_text("Bang-bang +/-2 Nm around the current position; the oscillation gives Ku and Tu, from which gains are proposed.", wrap=390)
                self.tags["r_hys"] = T.number("hysteresis [deg]", 1.0, 100, "%.1f")
                self.tags["r_dur"] = T.number("duration [s]", 8.0, 100, "%.1f")
                b = T.action("Run relay test", "accent", safe(self._relay), 160)
                g.bind(b, "tests", "Runs on the Teensy; recording starts and stops automatically.")
        dpg.add_spacer(height=8)
        T.section("Last result")
        self.tags["result"] = T.mono_text("-", wrap=900)
        with dpg.group(tag="proposals"):
            pass
        dpg.add_spacer(height=8)
        with dpg.collapsing_header(label="How to tune a steering wheel (short)"):
            dpg.add_text(
                "1. Calibrate (end stops + zero) and enable.\n"
                "2. Step test at 30 deg. Doesn't reach target -> add Ki (0.05 steps). Overshoots -> raise Kd, lower Kp. Too slow -> raise Kp.\n"
                "3. Or run the relay test and start from the 'Steering-conservative' proposal, then step-test again.\n"
                "4. Typical BM-18 on a steering column: Kp 30-80, Kd 1-4, Ki 0.05-0.5. Re-grip is gain-ramped, so a bad guess cannot snap the wheel.\n"
                "Firmware trips (overspeed/stall/overcurrent) will catch runaway gains - if you see one, back off by half.", wrap=900)

    def _step(self):
        self.c.run_test(P.TEST_STEP, dpg.get_value(self.tags["s_amp"]), dpg.get_value(self.tags["s_hold"]), dpg.get_value(self.tags["s_hold"]))

    def _relay(self):
        self.c.run_test(P.TEST_RELAY, 0.0, dpg.get_value(self.tags["r_dur"]), dpg.get_value(self.tags["r_hys"]))

    def _done(self, rec):
        if rec.kind.startswith("test_"):
            self.last = rec

    def refresh(self):
        live = self.c.live
        cfg = live.config
        cs = P.CS_NAMES.get(live.ctrl_state, "?")
        if cfg:
            txt = (f"state {cs} | motor loop: Kp {cfg.kp:.1f} Nm/rad  Kd {cfg.kd:.2f} Nm/(rad/s) | Teensy: Ki {cfg.ki:.2f}  Tff {cfg.tff_Nm:.2f} Nm"
                   + ("  | gains pending..." if live.pending_gains else ""))
        else:
            txt = f"state {cs} | no config echo yet"
        dpg.set_value(self.tags["mode"], txt)
        if self.last is not None:
            rec, self.last = self.last, None
            m = rec.metrics
            if rec.kind == "test_step":
                dpg.set_value(self.tags["result"], f"{rec.name}: rise {m.get('step_rise_s', float('nan')):.3f}s  overshoot {m.get('step_overshoot_pct', float('nan')):.1f}%  "
                                                   f"settle {m.get('step_settle_s', float('nan')):.2f}s  ss-err {m.get('step_ss_err_deg', float('nan')):.2f} deg  (err rms {m.get('err_rms_deg', float('nan')):.2f} deg)")
                dpg.delete_item("proposals", children_only=True)
            else:
                Ku, Tu = m.get("relay_Ku_Nm_per_rad"), m.get("relay_Tu_s")
                if Ku and Tu:
                    dpg.set_value(self.tags["result"], f"{rec.name}: Ku {Ku:.1f} Nm/rad  Tu {Tu:.3f}s  amplitude {m.get('relay_amp_deg', 0):.1f} deg  periods {m.get('relay_periods', 0):.0f}")
                    dpg.delete_item("proposals", children_only=True)
                    for name, gg in propose_gains(Ku, Tu).items():
                        with dpg.group(horizontal=True, parent="proposals"):
                            T.action(f"use {name}", "neutral", safe(self._use), 220, user_data=gg)
                            T.mono_text(f"Kp {gg['kp']:.1f}  Kd {gg['kd']:.2f}  Ki {gg['ki']:.2f}")
                else:
                    dpg.set_value(self.tags["result"], f"{rec.name}: not enough oscillation to estimate Ku/Tu (try a longer duration or smaller hysteresis)")

    def _use(self, sender, app_data, gg):
        self.ui.set_gain_inputs(gg["kp"], gg["kd"], gg["ki"])
        toast("gains copied into the inputs - press Apply gains")
