"""
ui/wheel.py - the wheel strip: setpoint slider, measured position, end stops.

     Setpoint +25.0°            [ Move to 0° ]                Position +25.1°
     ├────────────────────────────────●──▮──────────────────────────────┤
     left stop −220°        −90        0        +90       right stop +220°

  * The green grab is the setpoint you asked for (drag it).  Released, the
    Teensy slews its setpoint toward it, so the wheel never jumps.
  * The blue dot underneath is where the wheel actually is.  When the two
    agree the grab covers the dot.
  * "Move to 0°" sits above 0° on the scale, wherever 0° is.
  * Read-only mode (Calibrate): no slider, just the stops and the dot.

The slider's frame is transparent and drawn on top of a drawlist that holds
the track, so the dot really is under the grab.  Grab geometry copies ImGui's
SliderBehavior (2 px padding, grab centred on the value).
"""
from __future__ import annotations

from typing import Optional

import dearpygui.dearpygui as dpg

from .. import protocol as P
from .. import words as W
from . import theme as T
from .safe import safe, toast

ROW_H = 34          # readouts + Move to 0° button
TRACK_H = 38        # = slider frame height (font 17 + 2 x 10 padding + 1)
LABEL_H = 22
GRAB_PAD = 2.0
DEFAULT_RANGE = 180.0


class WheelStrip:
    def __init__(self, ui, key: str, interactive: bool = True):
        self.ui = ui
        self.c = ui.app.controller
        self.key = key
        self.interactive = interactive
        self.w = 800
        self.rng = (-DEFAULT_RANGE, DEFAULT_RANGE)
        self.stops: Optional[tuple] = None
        self._prev_cs = None
        self._asked = None          # the last angle the operator asked for (slider / Move to 0°)
        self.tags = {}

    def tag(self, n):
        return f"ws_{self.key}_{n}"

    # ---- geometry ------------------------------------------------------------------------------
    def x_of(self, v: float) -> float:
        lo, hi = self.rng
        g = float(T.SLIDER_GRAB_PX)
        usable = self.w - 2 * GRAB_PAD - g
        t = (v - lo) / max(1e-9, hi - lo)
        return GRAB_PAD + g / 2 + t * usable

    # ---- build ------------------------------------------------------------------------------------
    def build(self):
        g = self.ui.gate
        k = self.tag
        h = ROW_H + TRACK_H + LABEL_H + 4
        with dpg.child_window(height=h, border=False, no_scrollbar=True, tag=k("box")) as box:
            dpg.bind_item_theme(box, T.theme("bare"))
            # NB: a drawlist ignores `pos`, so it goes in the normal flow (after a spacer for the readout row);
            # everything else is placed absolutely on top of it.  Draw order = creation order, so the slider
            # (created after the track) draws over the position dot.
            dpg.add_spacer(height=ROW_H)
            self.dl = dpg.add_drawlist(width=self.w, height=TRACK_H + LABEL_H, tag=k("track"))
            self.tags["sp"] = dpg.add_text("", pos=(0, 6), color=T.SOURCE_COLOR["user"])
            T.bind_font(self.tags["sp"], "label")
            T.tip(self.tags["sp"], "The setpoint the Teensy is commanding right now. Its colour says where it comes "
                                   "from: dark green = you (Position control), pastel green = playback or waveform, "
                                   "orange = planner. It slews toward what you ask, so it can lag the slider.")
            self.tags["pos"] = dpg.add_text("", pos=(0, 6), color=T.POSITION)
            T.bind_font(self.tags["pos"], "label")
            T.tip(self.tags["pos"], "Where the wheel actually is, from the motor's encoder (the blue dot on the scale).")
            if self.interactive:
                self.tags["zero"] = T.action("Move to 0°", "secondary", safe(self._move_zero), 120)
                dpg.configure_item(self.tags["zero"], pos=(0, 0))
                g.bind(self.tags["zero"], "move_to_zero",
                       "Drive the wheel to 0°, the middle of the end stops found by calibration. "
                       "The Teensy slews there at its normal rate. This moves the wheel; it does not change where 0° is.")
                self.tags["slider"] = dpg.add_slider_float(default_value=0.0, min_value=-DEFAULT_RANGE,
                                                           max_value=DEFAULT_RANGE, width=self.w, format="",
                                                           pos=(0, ROW_H), callback=safe(self._slide), tag=k("slider"))
                dpg.bind_item_theme(self.tags["slider"], T.theme("slider_big"))
                g.bind(self.tags["slider"], "slider",
                       "Drag to set the angle to hold. The Teensy moves the wheel there at a limited speed, so a fast "
                       "drag can't jerk the wheel.")

    # ---- callbacks ----------------------------------------------------------------------------------
    def _slide(self, sender, value):
        self._asked = value
        r = self.c.slider(value)
        if not r.ok:
            toast(r.tooltip, "warn", 3)

    def _move_zero(self):
        self.c.move_to_zero()
        self._asked = 0.0
        if "slider" in self.tags:
            dpg.set_value(self.tags["slider"], 0.0)

    def set(self, v: float):
        if "slider" in self.tags:
            dpg.set_value(self.tags["slider"], v)
            self._slide(None, v)

    # ---- layout / refresh -----------------------------------------------------------------------------
    def on_resize(self, w: int):
        self.w = max(300, int(w))
        dpg.configure_item(self.tag("box"), width=self.w)
        dpg.configure_item(self.dl, width=self.w)
        if "slider" in self.tags:
            dpg.configure_item(self.tags["slider"], width=self.w)

    def _text_w(self, text, font):
        f = T.font(font)
        sz = dpg.get_text_size(text, font=f) if f else None
        return sz[0] if sz and sz[0] > 0 else len(text) * 8.0

    def refresh(self):
        live = self.c.live
        cfg, t = live.config, live.telemetry
        if cfg and cfg.limits_valid:
            self.stops = (cfg.limit_left_deg, cfg.limit_right_deg)
            self.rng = (cfg.limit_left_deg + 3.0, cfg.limit_right_deg - 3.0)
        else:
            self.stops = None
            self.rng = (-DEFAULT_RANGE, DEFAULT_RANGE)
        cs = live.ctrl_state if t else None
        if self.ui._frame - getattr(self, "_last_frame", -9) > 2:     # page was hidden: resync the slider
            self._prev_cs = None
        self._last_frame = self.ui._frame
        if "slider" in self.tags:
            sl = self.tags["slider"]
            dpg.configure_item(sl, min_value=self.rng[0], max_value=self.rng[1])
            # follow the wheel until position control starts, then the slider is yours
            if cs != P.CS_HOLD:
                self._asked = None
            if t and (cs != P.CS_HOLD or self._prev_cs != P.CS_HOLD) and not dpg.is_item_active(sl):
                dpg.set_value(sl, self._asked if self._asked is not None else
                              (t.setpoint_deg if cs == P.CS_HOLD else t.position_deg))
        self._prev_cs = cs

        # readouts
        src = self.c.setpoint_source() if t else ""
        if t and src:
            dpg.set_value(self.tags["sp"], f"Setpoint {W.signed(t.setpoint_deg)}°")
            dpg.configure_item(self.tags["sp"], color=T.SOURCE_COLOR.get(src, T.INK))
        else:
            dpg.set_value(self.tags["sp"], "Setpoint —" if t else "")
            dpg.configure_item(self.tags["sp"], color=T.FAINT)
        ptxt = f"Position {W.signed(t.position_deg)}°" if t else "Position —"
        dpg.set_value(self.tags["pos"], ptxt)
        dpg.configure_item(self.tags["pos"], pos=(self.w - self._text_w(ptxt, "label"), 6))
        if "zero" in self.tags:
            bw = 120
            x0 = self.x_of(0.0) if self.rng[0] <= 0 <= self.rng[1] else self.w / 2
            sp_w = self._text_w(dpg.get_value(self.tags["sp"]) or "Setpoint +000.0°", "label") + 12
            x = min(max(x0 - bw / 2, sp_w), self.w - self._text_w(ptxt, "label") - bw - 12)
            dpg.configure_item(self.tags["zero"], pos=(int(x), 0))
        self._draw(t)

    def _draw(self, t):
        dl = self.dl
        dpg.delete_item(dl, children_only=True)
        cy = TRACK_H / 2
        lo, hi = self.rng
        x0, x1 = self.x_of(lo), self.x_of(hi)
        # track
        dpg.draw_rectangle((0, 1), (self.w - 1, TRACK_H - 1), color=T.RULE, fill=T.SURFACE, rounding=4, parent=dl)
        dpg.draw_line((x0, cy), (x1, cy), color=T.RULE, thickness=3, parent=dl)
        # ticks every 90° (+ 0°), labels under the track
        fs = T.FONT_SIZE.get("plot_s", 12)
        step = 90 if hi - lo > 200 else 45
        v = (int(lo // step) + 1) * step
        while v < hi:
            x = self.x_of(v)
            major = v == 0
            dpg.draw_line((x, cy - (9 if major else 5)), (x, cy + (9 if major else 5)),
                          color=T.MUTED if major else T.FAINT, thickness=1.6 if major else 1, parent=dl)
            lab = "0°" if v == 0 else f"{W.signed(v, 0)}°"
            tw = self._text_w(lab, "plot_s")
            it = dpg.draw_text((x - tw / 2, TRACK_H + 3), lab, color=T.MUTED, size=fs, parent=dl)
            T.bind_font(it, "plot_s")
            v += step
        # end stops
        if self.stops:
            for side, val in (("left", self.stops[0]), ("right", self.stops[1])):
                x = min(max(self.x_of(val), 2), self.w - 3)
                dpg.draw_line((x, 5), (x, TRACK_H - 5), color=T.INK, thickness=2, parent=dl)
                lab = f"{side} stop {W.signed(val, 0)}°"
                tw = self._text_w(lab, "plot_s")
                lx = 0 if side == "left" else self.w - tw
                it = dpg.draw_text((lx, TRACK_H + 3), lab, color=T.INK, size=fs, parent=dl)
                T.bind_font(it, "plot_s")
        else:
            lab = "End stops unknown: calibrate to set them"
            it = dpg.draw_text((0, TRACK_H + 3), lab, color=T.WARN, size=fs, parent=dl)
            T.bind_font(it, "plot_s")
        # the measured position: under the slider grab
        if t:
            x = min(max(self.x_of(t.position_deg), 6), self.w - 6)
            dpg.draw_circle((x, cy), 6.5, fill=T.POSITION, color=T.SURFACE, thickness=1.5, parent=dl)
