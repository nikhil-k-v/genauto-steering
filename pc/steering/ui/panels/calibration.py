"""Calibrate - end stops and zero.  The automatic routine runs on the Teensy;
setting them by hand is the fallback."""
from __future__ import annotations

import dearpygui.dearpygui as dpg

from ... import protocol as P
from .. import theme as T
from ..safe import safe

STEPS = [(P.CAL_SEEK_LEFT, "Find left stop"), (P.CAL_CONFIRM_LEFT, "Confirm left"),
         (P.CAL_SEEK_RIGHT, "Find right stop"), (P.CAL_CONFIRM_RIGHT, "Confirm right"),
         (P.CAL_GO_CENTER, "Move to centre"), (P.CAL_SETTLE, "Settle and zero")]


class CalibrationPanel:
    def __init__(self, ui):
        self.ui = ui
        self.app = ui.app
        self.c = ui.app.controller
        self.tags = {}

    def build(self):
        g = self.ui.gate
        T.heading("End stops and zero")
        self.tags["now"] = dpg.add_text("", wrap=900)
        T.gap(14)
        T.label("The Teensy turns the wheel slowly left with the least torque that moves it, leans in when it stops, and "
                "bumps once more to be sure it is a real stop. Same on the right. Then it moves to the middle and sets zero "
                "there. Torque never exceeds 3.5 Nm (CAL_* in config.h).", T.MUTED, wrap=760)
        T.gap(6)
        with dpg.group(horizontal=True):
            b = T.action("Find end stops and zero", "primary", safe(self.c.calibrate), 240)
            g.bind(b, "calibrate", "Needs the motor replying, the switch armed, no trip and nothing streaming. Recorded as 'autocal'.")
            b = T.action("Abort", "secondary", safe(self.c.calib_abort), 90)
            g.bind(b, "calib_abort")
        T.gap(10)
        with dpg.group(horizontal=True, horizontal_spacing=26):
            self.tags["steps"] = []
            for i, (code, label) in enumerate(STEPS):
                t = dpg.add_text(f"{i + 1}  {label}", color=T.FAINT)
                self.tags["steps"].append((code, t))
        self.tags["detail"] = T.label("")

        T.gap(26)
        with dpg.collapsing_header(label="Set them by hand") as ch:
            T.bind_font(ch, "label")
            T.label("Free-spin, turn the wheel to the left stop and capture it; same on the right; then centre and zero.", wrap=760)
            with dpg.group(horizontal=True):
                b = T.action("Capture left stop", "secondary", safe(self.c.capture_left), 170); g.bind(b, "capture_limits")
                b = T.action("Capture right stop", "secondary", safe(self.c.capture_right), 170); g.bind(b, "capture_limits")
                b = T.action("Centre and zero", "secondary", safe(self.c.go_center_zero), 170)
                g.bind(b, "go_center_zero", "Moves to the middle of the two stops with gentle gains and sets zero there.")
            with dpg.group(horizontal=True):
                b = T.action("Zero here", "secondary", safe(self.c.set_zero), 170)
                g.bind(b, "set_zero", "The current position becomes 0°. Stops shift with it.")
            T.gap(6)
            with dpg.group(horizontal=True, horizontal_spacing=22):
                self.tags["l"] = T.number("left °", -180, 90, "%.1f")
                self.tags["r"] = T.number("right °", 180, 90, "%.1f")
                b = T.action("Set stops", "secondary", safe(self._set_limits), 120); g.bind(b, "capture_limits")

    def _set_limits(self):
        self.c.set_limits(dpg.get_value(self.tags["l"]), dpg.get_value(self.tags["r"]))

    def refresh(self):
        live = self.c.live
        fw, cfg, t = live.health_fw, live.config, live.telemetry
        if cfg:
            if cfg.limits_valid:
                txt = (f"End stops at {cfg.limit_left_deg:+.1f}° and {cfg.limit_right_deg:+.1f}°, "
                       f"{cfg.limit_right_deg - cfg.limit_left_deg:.0f}° of travel. ").replace("-", "−")
            else:
                txt = "End stops not set. "
            txt += "Zero is set." if cfg.zeroed else "Zero is not set."
            dpg.set_value(self.tags["now"], txt)
            dpg.configure_item(self.tags["now"], color=T.INK if cfg.limits_valid and cfg.zeroed else T.WARN)
        if not fw:
            return
        stage = fw.calib_stage
        running = fw.ctrl_state == P.CS_CALIB
        order = [c for c, _ in STEPS]
        cur = order.index(stage) if stage in order else (len(order) if stage == P.CAL_DONE else -1)
        for i, (code, item) in enumerate(self.tags["steps"]):
            if stage == P.CAL_DONE or i < cur:
                col, font = T.OK, "body"
            elif i == cur and running:
                col, font = T.INK, "label"
            else:
                col, font = T.FAINT, "body"
            dpg.configure_item(item, color=col)
            T.bind_font(item, font)
        if stage == P.CAL_FAILED:
            dpg.set_value(self.tags["detail"], "Failed. The Teensy tripped; see the reason in the rail, clear it, check the wheel can reach both stops.")
            dpg.configure_item(self.tags["detail"], color=T.BAD)
        elif stage == P.CAL_ABORTED:
            dpg.set_value(self.tags["detail"], "Aborted.")
            dpg.configure_item(self.tags["detail"], color=T.MUTED)
        elif running and t:
            dpg.set_value(self.tags["detail"], f"At {t.position_deg:+.1f}° with {t.torque_cmd_Nm:+.2f} Nm.".replace("-", "−"))
            dpg.configure_item(self.tags["detail"], color=T.MUTED)
        else:
            dpg.set_value(self.tags["detail"], "")
