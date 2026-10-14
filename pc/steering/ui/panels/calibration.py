"""Calibration tab - end stops + zero (item 6).  Auto routine runs on the Teensy;
manual capture is the fallback."""
from __future__ import annotations

import dearpygui.dearpygui as dpg

from ... import protocol as P
from .. import theme as T
from ..safe import safe


class CalibrationPanel:
    def __init__(self, ui):
        self.ui = ui
        self.app = ui.app
        self.c = ui.app.controller
        self.tags = {}

    def build(self):
        g = self.ui.gate
        T.section("Automatic")
        dpg.add_text("The Teensy creeps the wheel left at a bounded speed with the least torque that overcomes friction, "
                     "leans harder once it stops, bumps once more to confirm it is a real stop (not friction), repeats to the right, "
                     "moves slowly to the exact middle, sets zero there. Limits in config.h: CAL_* (max 3.5 Nm).", wrap=900)
        with dpg.group(horizontal=True):
            b = T.action("Auto-calibrate end stops + zero", "accent", safe(self.c.calibrate), 280)
            g.bind(b, "calibrate", "Needs: motor replying, switch armed, no trip, nothing streaming. Recording 'autocal' is made automatically.")
            b = T.action("Abort", "bad", safe(self.c.calib_abort), 90); g.bind(b, "calib_abort")
        self.tags["stage"] = T.mono_text("stage: -", bold=True)
        dpg.add_spacer(height=12)
        T.section("Manual")
        dpg.add_text("Free-spin, turn the wheel to the left stop, capture; same on the right; then let it centre and zero.", wrap=900)
        with dpg.group(horizontal=True):
            b = T.action("Capture LEFT stop", "neutral", safe(self.c.capture_left), 170); g.bind(b, "capture_limits")
            b = T.action("Capture RIGHT stop", "neutral", safe(self.c.capture_right), 170); g.bind(b, "capture_limits")
            b = T.action("Go to centre + set zero", "accent", safe(self.c.go_center_zero), 210)
            g.bind(b, "go_center_zero", "Slews to (L+R)/2 with gentle gains and zeroes there.")
            b = T.action("Set zero HERE", "neutral", safe(self.c.set_zero), 130)
            g.bind(b, "set_zero", "Current position becomes 0 deg. Limits are shifted accordingly.")
        dpg.add_spacer(height=12)
        T.section("State")
        self.tags["state"] = T.mono_text("", wrap=900)
        with dpg.group(horizontal=True):
            self.tags["l"] = T.number("left [deg]", -180, 100, "%.1f")
            self.tags["r"] = T.number("right [deg]", 180, 100, "%.1f")
            b = T.action("Set limits manually", "neutral", safe(self._set_limits), 170); g.bind(b, "capture_limits")

    def _set_limits(self):
        self.c.set_limits(dpg.get_value(self.tags["l"]), dpg.get_value(self.tags["r"]))

    def refresh(self):
        live = self.c.live
        fw, cfg, t = live.health_fw, live.config, live.telemetry
        if fw:
            stage = P.CAL_NAMES.get(fw.calib_stage, "?")
            dpg.set_value(self.tags["stage"], f"stage: {stage}" + (f" | pos {t.position_deg:+.1f} deg | torque {t.torque_cmd_Nm:+.2f} Nm" if t and fw.ctrl_state == P.CS_CALIB else ""))
            dpg.configure_item(self.tags["stage"], color=T.WARN if fw.ctrl_state == P.CS_CALIB else T.BAD if fw.calib_stage == P.CAL_FAILED else T.TEXT)
        if cfg and t:
            z = "zeroed" if cfg.zeroed else "NOT zeroed"
            lim = f"limits {cfg.limit_left_deg:+.1f} deg ... {cfg.limit_right_deg:+.1f} deg ({cfg.limit_right_deg - cfg.limit_left_deg:.0f} deg range)" if cfg.limits_valid else "limits NOT valid (default +/-200 deg)"
            dpg.set_value(self.tags["state"], f"{z} | {lim} | position now {t.position_deg:+.1f} deg")
