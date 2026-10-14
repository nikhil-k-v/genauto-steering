"""Calibrate - end stops and 0°.  The automatic routine runs on the Teensy;
setting them by hand is the fallback.

    ├──────●───────────────────────────────────────────────┤   read-only wheel strip: stops + where the wheel is
    left stop −220°           0°                right stop +220°

    ┌ status, steps, by hand ┐  ┌ live traces: angle and torque while it seeks ┐
"""
from __future__ import annotations

import dearpygui.dearpygui as dpg

from ... import protocol as P
from ... import words as W
from .. import theme as T
from ..liveplot import LivePlot
from ..safe import safe
from ..wheel import WheelStrip

LEFT_W = 430
STEPS = [(P.CAL_SEEK_LEFT, "Find the left stop", "Creeps left with the least torque that moves the wheel."),
         (P.CAL_CONFIRM_LEFT, "Confirm it", "Leans in and bumps once more: a real stop does not give."),
         (P.CAL_SEEK_RIGHT, "Find the right stop", "Same, to the right."),
         (P.CAL_CONFIRM_RIGHT, "Confirm it", "Same check on the right."),
         (P.CAL_GO_CENTER, "Move to the middle", "Drives to halfway between the two stops."),
         (P.CAL_SETTLE, "Settle, set 0° there", "Waits until still, then that angle becomes 0°.")]


class CalibrationPanel:
    def __init__(self, ui):
        self.ui = ui
        self.app = ui.app
        self.c = ui.app.controller
        self.tags = {}
        self.wheel = WheelStrip(ui, "cal", interactive=False)
        self.plot = LivePlot(ui, "cal", speed=False)

    def build(self):
        g = self.ui.gate
        self.wheel.build()
        T.gap(8)
        with dpg.group(horizontal=True, horizontal_spacing=28):
            with dpg.child_window(width=LEFT_W, border=False, tag="cal_left") as lc:
                dpg.bind_item_theme(lc, T.theme("bare"))
                self.tags["now"] = dpg.add_text("", wrap=LEFT_W - 10)
                T.bind_font(self.tags["now"], "label")
                T.gap(8)
                with dpg.group(horizontal=True):
                    b = T.action("Find end stops and set 0°", "primary", safe(self.c.calibrate), 250)
                    g.bind(b, "calibrate", "Runs the six steps below on the Teensy: finds both steering stops by "
                                           "touch (never more than 3.5 N·m), then makes the middle 0°. "
                                           "Recorded as 'autocal'. Keep a hand near the idle switch.")
                    b = T.action("Stop", "secondary", safe(self.c.calib_abort), 90)
                    g.bind(b, "calib_abort", "Stop calibration now and turn the motor off. Nothing is saved.")
                T.gap(10)
                self.tags["steps"] = []
                for i, (code, label, tip) in enumerate(STEPS):
                    with dpg.group(horizontal=True, horizontal_spacing=10):
                        n = dpg.add_text(f"{i + 1}", color=T.FAINT)
                        t = dpg.add_text(label, color=T.FAINT)
                        T.tip(t, tip)
                    self.tags["steps"].append((code, n, t))
                self.tags["detail"] = T.label("", wrap=LEFT_W - 10)

                T.gap(20)
                with dpg.collapsing_header(label="Set them by hand", default_open=False) as ch:
                    T.bind_font(ch, "label")
                    T.tip(ch, "If the automatic routine can't run: free-spin, turn the wheel to each stop and save it.")
                    with dpg.group(horizontal=True):
                        b = T.action("Save as left stop", "secondary", safe(self.c.capture_left), 175)
                        g.bind(b, "capture_limits", "The wheel's current angle becomes the left end stop. "
                                                    "Turn it fully left first (Free-spin lets you turn it by hand).")
                        b = T.action("Save as right stop", "secondary", safe(self.c.capture_right), 175)
                        g.bind(b, "capture_limits", "The wheel's current angle becomes the right end stop.")
                    b = T.action("Move to the middle and set 0° there", "secondary", safe(self.c.go_center_zero), 358)
                    g.bind(b, "go_center_zero", "After saving both stops: drive gently to halfway between them and "
                                                "make that angle 0°. The stops are re-expressed around the new 0°.")
                    b = T.action("Set 0° at the current angle", "secondary", safe(self.c.set_zero), 358)
                    g.bind(b, "set_zero", "Make wherever the wheel is now 0°, without moving it. "
                                          "Saved stops shift with it.")
                    T.gap(6)
                    with dpg.group(horizontal=True, horizontal_spacing=16):
                        self.tags["l"] = T.number("left °", -180, 80, "%.1f",
                                                  tip_text="Left end stop, typed in (relative to the current 0°).")
                        self.tags["r"] = T.number("right °", 180, 80, "%.1f",
                                                  tip_text="Right end stop, typed in (relative to the current 0°).")
                    b = T.action("Use these stops", "secondary", safe(self._set_limits), 175)
                    g.bind(b, "capture_limits", "Send the two typed angles as the end stops.")
            with dpg.child_window(border=False, no_scrollbar=True, tag="cal_right") as rc:
                dpg.bind_item_theme(rc, T.theme("bare"))
                self.plot.build()

    def on_resize(self, w, h):
        self.wheel.on_resize(w)
        body = h - 84
        dpg.configure_item("cal_left", height=body)
        rw = max(400, w - LEFT_W - 28)
        dpg.configure_item("cal_right", width=rw, height=body)
        self.plot.on_resize(rw, body)

    def _set_limits(self):
        self.c.set_limits(dpg.get_value(self.tags["l"]), dpg.get_value(self.tags["r"]))

    def refresh(self):
        self.wheel.refresh()
        self.plot.refresh()
        live = self.c.live
        fw, cfg, t = live.health_fw, live.config, live.telemetry
        if cfg:
            if cfg.limits_valid and cfg.zeroed:
                txt = f"Calibrated: {cfg.limit_right_deg - cfg.limit_left_deg:.0f}° of travel."
            else:
                missing = [w for w, have in (("0°", cfg.zeroed), ("end stops", cfg.limits_valid)) if not have]
                txt = "Not calibrated: no " + " and no ".join(missing) + "."
            dpg.set_value(self.tags["now"], txt)
            dpg.configure_item(self.tags["now"], color=T.INK if cfg.limits_valid and cfg.zeroed else T.WARN)
        if not fw:
            return
        stage = fw.calib_stage
        running = fw.ctrl_state == P.CS_CALIB
        order = [c for c, _, _ in STEPS]
        cur = order.index(stage) if stage in order else (len(order) if stage == P.CAL_DONE else -1)
        for i, (code, n, item) in enumerate(self.tags["steps"]):
            if stage == P.CAL_DONE or i < cur:
                col, font = T.OK, "body"
            elif i == cur and running:
                col, font = T.INK, "label"
            elif i == cur and stage == P.CAL_FAILED:
                col, font = T.BAD, "label"
            else:
                col, font = T.FAINT, "body"
            dpg.configure_item(item, color=col)
            dpg.configure_item(n, color=col)
            T.bind_font(item, font)
        if stage == P.CAL_FAILED:
            why = live.trip_text
            dpg.set_value(self.tags["detail"], f"Failed{': ' + why if why else ''}. Press Reset safety stop, check the "
                                               "wheel can reach both stops, and try again.")
            dpg.configure_item(self.tags["detail"], color=T.BAD)
        elif stage == P.CAL_ABORTED:
            dpg.set_value(self.tags["detail"], "Stopped before it finished. Nothing was saved.")
            dpg.configure_item(self.tags["detail"], color=T.MUTED)
        elif running and t:
            dpg.set_value(self.tags["detail"], f"{W.CAL_STAGE.get(stage, '').capitalize()}: at {W.signed(t.position_deg)}° "
                                               f"pushing {W.signed(t.torque_cmd_Nm, 2)} N·m")
            dpg.configure_item(self.tags["detail"], color=T.MUTED)
        else:
            dpg.set_value(self.tags["detail"], "")
