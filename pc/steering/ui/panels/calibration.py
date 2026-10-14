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
        dpg.add_text("AUTOMATIC", color=T.ACCENT)
        dpg.add_text("The Teensy creeps the wheel left at a bounded speed with the least torque that overcomes friction, "
                     "leans harder once it stops, bumps once more to confirm it is a real stop (not friction), repeats to the right, "
                     "moves slowly to the exact middle, sets zero there. Limits in config.h: CAL_* (max 3.5 Nm).", wrap=900)
        with dpg.group(horizontal=True):
            b = dpg.add_button(label="Auto-calibrate end stops + zero", width=260, callback=safe(self.c.calibrate))
            g.bind(b, "calibrate", "Needs: motor replying, switch armed, no trip, nothing streaming. Recording 'autocal' is made automatically.")
            dpg.bind_item_theme(b, T.theme("btn_accent"))
            b = dpg.add_button(label="Abort", width=90, callback=safe(self.c.calib_abort)); g.bind(b, "calib_abort")
        self.tags["stage"] = dpg.add_text("stage: -")
        dpg.add_spacer(height=12)
        dpg.add_text("MANUAL", color=T.ACCENT)
        dpg.add_text("Free-spin, turn the wheel to the left stop, capture; same on the right; then let it centre and zero.", wrap=900)
        with dpg.group(horizontal=True):
            b = dpg.add_button(label="Capture LEFT stop", width=170, callback=safe(self.c.capture_left)); g.bind(b, "capture_limits")
            b = dpg.add_button(label="Capture RIGHT stop", width=170, callback=safe(self.c.capture_right)); g.bind(b, "capture_limits")
            b = dpg.add_button(label="Go to centre + set zero", width=200, callback=safe(self.c.go_center_zero))
            g.bind(b, "go_center_zero", "Slews to (L+R)/2 with gentle gains and zeroes there.")
            b = dpg.add_button(label="Set zero HERE", width=130, callback=safe(self.c.set_zero))
            g.bind(b, "set_zero", "Current position becomes 0 deg. Limits are shifted accordingly.")
        dpg.add_spacer(height=12)
        dpg.add_text("STATE", color=T.DIM)
        self.tags["state"] = dpg.add_text("", wrap=900)
        with dpg.group(horizontal=True):
            self.tags["l"] = dpg.add_input_float(label="left [deg]", default_value=-180, width=110, step=0)
            self.tags["r"] = dpg.add_input_float(label="right [deg]", default_value=180, width=110, step=0)
            b = dpg.add_button(label="Set limits manually", width=160, callback=safe(self._set_limits)); g.bind(b, "capture_limits")

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
