"""ui/theme.py - palette, type scale and widget styles.

Design rules (keep them when adding UI):

  * Colour means status, nothing else.  Green OK, amber blocked, red failed,
    grey unknown/off.  Everything else is ink on paper.  If a thing is coloured,
    it is telling you about the system.
  * Healthy is quiet, broken is loud.  OK shows as a small green mark; a problem
    gets colour, words and the node id.
  * One family for the interface (Barlow, tabular digits), one mono for things
    that are literally machine text (paths, logs, counters).
  * Widgets look like what they are:
        primary   ink fill            the one main action of a panel
        secondary white, ruled        other actions
        quiet     text only           utilities (open folder, clear, pin)
        danger    red fill            stop / destructive - Stop motor only lights up
                                       when there is something to stop
        segment   joined pair         mutually exclusive modes (Hold | Free-spin)
        toggle    checkbox            on/off preferences
        field     white, ruled        numbers and names
"""
from __future__ import annotations

from pathlib import Path

import dearpygui.dearpygui as dpg

from .. import protocol as P
from .. import words as W

FONT_DIR = Path(__file__).resolve().parent / "fonts"

# ---- palette ----------------------------------------------------------------------------------
PAPER   = (244, 245, 246)     # workspace
RAIL    = (230, 233, 236)     # system rail
SURFACE = (255, 255, 255)     # fields, cards
INK     = (27, 33, 41)        # text, primary buttons
MUTED   = (104, 113, 124)     # secondary text
FAINT   = (163, 170, 179)     # disabled text, unknown status
RULE    = (210, 214, 219)     # borders
HOVER   = (236, 239, 242)
SELECT  = (222, 231, 245)     # selected row
WELL    = (236, 239, 243)     # plot data area: a shade darker than the sheet, so plots read as inset

# Status colours, chosen for red-green colour blindness: a blue-leaning green, an amber and a
# vermillion differ in lightness and along the blue-yellow axis, not only red vs green.  Every
# status mark ALSO has its own shape (status_mark): circle ok, triangle not ready, square fault.
OK      = (0, 128, 98)
WARN    = (196, 126, 0)
BAD     = (205, 62, 22)
IDLE    = FAINT

# ---- plot lines -------------------------------------------------------------------------------
# Line STYLE says what kind of quantity it is:   solid = measured   dashed = setpoint the Teensy
# commanded   dotted = what was requested (before the Teensy's slew limit).
# Line COLOUR says where it came from (setpoints) or which quantity it is (measured).
POSITION = (0, 102, 170)      # measured wheel angle and speed: the one blue
SOURCE_COLOR = {
    "user": (0, 112, 74),         # Position control (slider / Move to 0°): dark green
    "playback": (98, 186, 132),   # playing a recording back: pastel green
    "trajectory": (98, 186, 132), # a synthetic waveform: same pastel green
    "planner": (214, 128, 0),     # external planner stream: orange
    "test": (128, 133, 140),      # step / relay test run by the Teensy: grey
    "calib": (128, 133, 140),     # calibration routine: grey
}
TORQUE = (205, 86, 26)        # torque command (dashed) and motor current (solid): vermillion
ERROR = (90, 96, 104)         # tracking error (derived): dark grey
SIGNAL = POSITION             # slider dot, links

SERIES = {
    "position": (POSITION, "solid", 2.2), "velocity": (POSITION, "solid", 1.8),
    "current": (TORQUE, "solid", 1.6), "torque": (TORQUE, "dashed", 1.6), "error": (ERROR, "solid", 1.6),
    "cursor": (INK, "solid", 1.0), "trim": (BAD, "solid", 1.2), "preview": (SOURCE_COLOR["trajectory"], "dashed", 2.0),
}
for _k, _c in SOURCE_COLOR.items():
    SERIES[f"sp_{_k}"] = (_c, "dashed", 2.0)
    SERIES[f"req_{_k}"] = (_c, "dotted", 1.6)
DASH = {"solid": None, "dashed": (8.0, 5.0), "dotted": (2.0, 4.0)}

STATE_COLOR = {P.HS_OK: OK, P.HS_BLOCKED: WARN, P.HS_FAIL: BAD, P.HS_UNKNOWN: IDLE}
STATE_WORD = dict(W.VERDICT)

# controller state, said the way an operator would (words.py)
CS_WORD = dict(W.STATE)
CS_COLOR = {cs: (BAD if cs == P.CS_TRIPPED else INK) for cs in W.STATE}

TIP_DELAY_S = 0.9            # hover this long before a control explains itself
SLIDER_GRAB_PX = 18

_themes: dict = {}
FONTS: dict = {}
FONT_SIZE: dict = {}


def _font(name, file, size):
    p = FONT_DIR / file
    FONT_SIZE[name] = size
    if p.exists():
        FONTS[name] = dpg.add_font(str(p), size)        # glyph ranges load on demand in DPG 2
    return FONTS.get(name)


def build():
    with dpg.font_registry():
        _font("body", "Barlow-Regular.ttf", 17)
        _font("small", "Barlow-Regular.ttf", 15)
        _font("label", "Barlow-Medium.ttf", 17)
        _font("head", "Barlow-SemiBold.ttf", 19)
        _font("state", "Barlow-SemiBold.ttf", 24)
        _font("numeral", "BarlowSemiCondensed-Medium.ttf", 56)
        _font("mono", "IBMPlexMono-Regular.ttf", 14)
        _font("mono_s", "IBMPlexMono-Regular.ttf", 13)
        _font("plot", "DejaVuSans.ttf", 14)              # the original plot font: open digits, tight at small sizes
        _font("plot_s", "DejaVuSans.ttf", 12)
    if "body" in FONTS:
        dpg.bind_font(FONTS["body"])

    with dpg.theme() as g:
        with dpg.theme_component(dpg.mvAll):
            c = dpg.add_theme_color
            c(dpg.mvThemeCol_WindowBg, PAPER)
            c(dpg.mvThemeCol_ChildBg, PAPER)
            c(dpg.mvThemeCol_PopupBg, SURFACE)
            c(dpg.mvThemeCol_Border, RULE)
            c(dpg.mvThemeCol_BorderShadow, (0, 0, 0, 0))
            c(dpg.mvThemeCol_FrameBg, SURFACE)
            c(dpg.mvThemeCol_FrameBgHovered, SURFACE)
            c(dpg.mvThemeCol_FrameBgActive, SURFACE)
            c(dpg.mvThemeCol_Button, SURFACE)
            c(dpg.mvThemeCol_ButtonHovered, HOVER)
            c(dpg.mvThemeCol_ButtonActive, RULE)
            c(dpg.mvThemeCol_Header, SELECT)
            c(dpg.mvThemeCol_HeaderHovered, HOVER)
            c(dpg.mvThemeCol_HeaderActive, SELECT)
            c(dpg.mvThemeCol_Tab, PAPER)
            c(dpg.mvThemeCol_TabHovered, HOVER)
            c(dpg.mvThemeCol_TabActive, SURFACE)
            c(dpg.mvThemeCol_TabUnfocusedActive, SURFACE)
            c(dpg.mvThemeCol_TabSelectedOverline, INK)
            c(dpg.mvThemeCol_TabDimmedSelectedOverline, INK)
            c(dpg.mvThemeCol_Text, INK)
            c(dpg.mvThemeCol_TextDisabled, FAINT)
            c(dpg.mvThemeCol_TextSelectedBg, SELECT)
            c(dpg.mvThemeCol_ScrollbarBg, (0, 0, 0, 0))
            c(dpg.mvThemeCol_ScrollbarGrab, RULE)
            c(dpg.mvThemeCol_ScrollbarGrabHovered, FAINT)
            c(dpg.mvThemeCol_ScrollbarGrabActive, MUTED)
            c(dpg.mvThemeCol_CheckMark, INK)
            c(dpg.mvThemeCol_SliderGrab, SIGNAL)
            c(dpg.mvThemeCol_SliderGrabActive, SIGNAL)
            c(dpg.mvThemeCol_Separator, RULE)
            c(dpg.mvThemeCol_TableHeaderBg, PAPER)
            c(dpg.mvThemeCol_TableBorderLight, RULE)
            c(dpg.mvThemeCol_TableBorderStrong, RULE)
            c(dpg.mvThemeCol_TableRowBg, (0, 0, 0, 0))
            c(dpg.mvThemeCol_TableRowBgAlt, (0, 0, 0, 0))
            c(dpg.mvThemeCol_PlotHistogram, SIGNAL)
            s = dpg.add_theme_style
            s(dpg.mvStyleVar_WindowPadding, 0, 0)
            s(dpg.mvStyleVar_WindowBorderSize, 0)
            s(dpg.mvStyleVar_ChildBorderSize, 1)
            s(dpg.mvStyleVar_PopupBorderSize, 1)
            s(dpg.mvStyleVar_FrameBorderSize, 1)
            s(dpg.mvStyleVar_FrameRounding, 4)
            s(dpg.mvStyleVar_ChildRounding, 6)
            s(dpg.mvStyleVar_PopupRounding, 6)
            s(dpg.mvStyleVar_TabRounding, 4)
            s(dpg.mvStyleVar_GrabRounding, 3)
            s(dpg.mvStyleVar_ScrollbarRounding, 4)
            s(dpg.mvStyleVar_FramePadding, 10, 6)
            s(dpg.mvStyleVar_ItemSpacing, 10, 8)
            s(dpg.mvStyleVar_ItemInnerSpacing, 8, 6)
            s(dpg.mvStyleVar_ScrollbarSize, 8)
            s(dpg.mvStyleVar_GrabMinSize, 16)
            s(dpg.mvStyleVar_TabBorderSize, 0)
            s(dpg.mvStyleVar_TabBarOverlineSize, 2)
            s(dpg.mvStyleVar_TabBarBorderSize, 0)
            pc = lambda k, v: dpg.add_theme_color(k, v, category=dpg.mvThemeCat_Plots)
            pc(dpg.mvPlotCol_PlotBg, WELL)               # inset: the data area is a shade darker
            pc(dpg.mvPlotCol_FrameBg, SURFACE)
            pc(dpg.mvPlotCol_PlotBorder, RULE)
            pc(dpg.mvPlotCol_LegendBg, (255, 255, 255, 230))
            pc(dpg.mvPlotCol_LegendBorder, (0, 0, 0, 0))
            pc(dpg.mvPlotCol_LegendText, MUTED)
            pc(dpg.mvPlotCol_AxisGrid, (255, 255, 255))      # white grid on the darker well
            pc(dpg.mvPlotCol_AxisText, MUTED)
            pc(dpg.mvPlotCol_AxisBg, (0, 0, 0, 0))
            pc(dpg.mvPlotCol_AxisBgHovered, HOVER)
            pc(dpg.mvPlotCol_AxisBgActive, HOVER)
            pc(dpg.mvPlotCol_TitleText, INK)
            pc(dpg.mvPlotCol_Crosshairs, MUTED)
            ps = lambda k, *v: dpg.add_theme_style(k, *v, category=dpg.mvThemeCat_Plots)
            ps(dpg.mvPlotStyleVar_PlotPadding, 12, 10)
            ps(dpg.mvPlotStyleVar_LegendPadding, 6, 4)
        with dpg.theme_component(dpg.mvChildWindow):
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 0, 0)
        with dpg.theme_component(dpg.mvCollapsingHeader):      # a quiet disclosure line, not a bar
            dpg.add_theme_color(dpg.mvThemeCol_Header, (0, 0, 0, 0))
            dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, HOVER)
            dpg.add_theme_color(dpg.mvThemeCol_HeaderActive, HOVER)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 4, 6)
        for comp in (dpg.mvButton, dpg.mvInputFloat, dpg.mvInputInt, dpg.mvInputText, dpg.mvCombo,
                     dpg.mvSliderFloat, dpg.mvCheckbox):
            with dpg.theme_component(comp, enabled_state=False):
                dpg.add_theme_color(dpg.mvThemeCol_Text, FAINT)
                dpg.add_theme_color(dpg.mvThemeCol_Button, PAPER)
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, PAPER)
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, PAPER)
                dpg.add_theme_color(dpg.mvThemeCol_FrameBg, PAPER)
                dpg.add_theme_color(dpg.mvThemeCol_SliderGrab, RULE)
                dpg.add_theme_color(dpg.mvThemeCol_Border, RULE)
    dpg.bind_theme(g)

    for name, (col, style, weight) in SERIES.items():
        with dpg.theme() as t:
            for comp in (dpg.mvLineSeries, dpg.mvInfLineSeries):
                with dpg.theme_component(comp):
                    dpg.add_theme_color(dpg.mvPlotCol_Line, col, category=dpg.mvThemeCat_Plots)
                    dpg.add_theme_style(dpg.mvPlotStyleVar_LineWeight, weight, category=dpg.mvThemeCat_Plots)
        _themes[f"series_{name}"] = t

    # ---- buttons --------------------------------------------------------------------------
    def btn(name, fill, text, border, hover, press, pad=(12, 7), same_when_disabled=False):
        with dpg.theme() as t:
            with dpg.theme_component(dpg.mvButton):
                dpg.add_theme_color(dpg.mvThemeCol_Button, fill)
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, hover)
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, press)
                dpg.add_theme_color(dpg.mvThemeCol_Text, text)
                dpg.add_theme_color(dpg.mvThemeCol_Border, border)
                dpg.add_theme_style(dpg.mvStyleVar_FramePadding, *pad)
            if same_when_disabled:              # the active segment stays ink even though pressing it does nothing
                with dpg.theme_component(dpg.mvButton, enabled_state=False):
                    dpg.add_theme_color(dpg.mvThemeCol_Button, fill)
                    dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, fill)
                    dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, fill)
                    dpg.add_theme_color(dpg.mvThemeCol_Text, text)
                    dpg.add_theme_color(dpg.mvThemeCol_Border, border)
                    dpg.add_theme_style(dpg.mvStyleVar_FramePadding, *pad)
                _themes[name] = t
                return
            with dpg.theme_component(dpg.mvButton, enabled_state=False):
                dpg.add_theme_color(dpg.mvThemeCol_Button, PAPER if name != "btn_quiet" else (0, 0, 0, 0))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, PAPER if name != "btn_quiet" else (0, 0, 0, 0))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, PAPER if name != "btn_quiet" else (0, 0, 0, 0))
                dpg.add_theme_color(dpg.mvThemeCol_Text, FAINT)
                dpg.add_theme_color(dpg.mvThemeCol_Border, RULE if name != "btn_quiet" else (0, 0, 0, 0))
                dpg.add_theme_style(dpg.mvStyleVar_FramePadding, *pad)
        _themes[name] = t
    btn("btn_primary", INK, SURFACE, INK, (52, 60, 72), (70, 80, 94))
    btn("btn_secondary", SURFACE, INK, RULE, HOVER, RULE)
    btn("btn_quiet", (0, 0, 0, 0), MUTED, (0, 0, 0, 0), HOVER, RULE, pad=(6, 5))
    btn("btn_danger", BAD, SURFACE, BAD, (214, 70, 60), (170, 44, 36))
    btn("btn_danger_idle", SURFACE, BAD, RULE, HOVER, RULE)
    btn("seg_on", INK, SURFACE, INK, INK, INK, same_when_disabled=True)
    btn("seg_off", SURFACE, INK, RULE, HOVER, RULE)

    with dpg.theme() as t:
        with dpg.theme_component(dpg.mvCheckbox):
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 3, 3)
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 3)
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgHovered, HOVER)
    _themes["toggle"] = t

    with dpg.theme() as t:                      # the setpoint slider: transparent track (drawn underneath), green grab
        with dpg.theme_component(dpg.mvSliderFloat):
            dpg.add_theme_style(dpg.mvStyleVar_GrabMinSize, SLIDER_GRAB_PX)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 10, 10)
            dpg.add_theme_style(dpg.mvStyleVar_GrabRounding, 4)
            dpg.add_theme_color(dpg.mvThemeCol_FrameBg, (0, 0, 0, 0))
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgHovered, (0, 0, 0, 0))
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgActive, (0, 0, 0, 0))
            dpg.add_theme_color(dpg.mvThemeCol_Border, (0, 0, 0, 0))
            dpg.add_theme_color(dpg.mvThemeCol_SliderGrab, SOURCE_COLOR["user"])
            dpg.add_theme_color(dpg.mvThemeCol_SliderGrabActive, (0, 90, 60))
        with dpg.theme_component(dpg.mvSliderFloat, enabled_state=False):
            dpg.add_theme_style(dpg.mvStyleVar_GrabMinSize, SLIDER_GRAB_PX)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 10, 10)
            dpg.add_theme_color(dpg.mvThemeCol_FrameBg, (0, 0, 0, 0))
            dpg.add_theme_color(dpg.mvThemeCol_Border, (0, 0, 0, 0))
            dpg.add_theme_color(dpg.mvThemeCol_SliderGrab, (0, 0, 0, 0))
            dpg.add_theme_color(dpg.mvThemeCol_Text, (0, 0, 0, 0))
    _themes["slider_big"] = t

    with dpg.theme() as t:                      # the system rail
        with dpg.theme_component(dpg.mvChildWindow):
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg, RAIL)
            dpg.add_theme_style(dpg.mvStyleVar_ChildBorderSize, 0)
            dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 0)
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 20, 18)
    _themes["rail"] = t

    with dpg.theme() as t:                      # white panel with a hairline
        with dpg.theme_component(dpg.mvChildWindow):
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg, SURFACE)
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 14, 12)
    _themes["card"] = t

    with dpg.theme() as t:                      # a page: the white sheet under the active tab
        with dpg.theme_component(dpg.mvChildWindow):
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg, SURFACE)
            dpg.add_theme_style(dpg.mvStyleVar_ChildBorderSize, 0)
            dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 6)
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 24, 18)
    _themes["page"] = t

    with dpg.theme() as t:                      # transparent, no border, no padding
        with dpg.theme_component(dpg.mvChildWindow):
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg, (0, 0, 0, 0))
            dpg.add_theme_style(dpg.mvStyleVar_ChildBorderSize, 0)
    _themes["bare"] = t

    with dpg.theme() as t:
        with dpg.theme_component(dpg.mvSelectable):
            dpg.add_theme_style(dpg.mvStyleVar_SelectableTextAlign, 0, 0.5)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 6, 6)
    _themes["row"] = t

    with dpg.theme() as t:                      # tight tables (results, proposals)
        with dpg.theme_component(dpg.mvAll):
            dpg.add_theme_style(dpg.mvStyleVar_CellPadding, 4, 2)
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 14, 5)
    _themes["compact"] = t

    with dpg.theme() as t:                      # toast
        with dpg.theme_component(dpg.mvWindowAppItem):
            dpg.add_theme_color(dpg.mvThemeCol_WindowBg, SURFACE)
            dpg.add_theme_color(dpg.mvThemeCol_Border, RULE)
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 14, 10)
            dpg.add_theme_style(dpg.mvStyleVar_WindowBorderSize, 1)
            dpg.add_theme_style(dpg.mvStyleVar_WindowRounding, 6)
    _themes["popup"] = t


def theme(name: str):
    return _themes[name]


def series_theme(name: str):
    return _themes[f"series_{name}"]


def font(name: str):
    return FONTS.get(name)


def bind_font(item, name: str):
    f = FONTS.get(name)
    if f is not None:
        dpg.bind_item_font(item, f)


# ---- helpers used by every panel ---------------------------------------------------------------
KIND_ALIAS = {"ok": "primary", "accent": "primary", "neutral": "secondary", "warn": "secondary",
              "ghost": "quiet", "bad": "danger"}


def heading(text: str, note: str = ""):
    """Section heading in sentence case; optional one-line muted note under it."""
    h = dpg.add_text(text)
    bind_font(h, "head")
    if note:
        n = dpg.add_text(note, color=MUTED, wrap=760)
        bind_font(n, "small")
    return h


section = heading


def gap(h: int = 14):
    dpg.add_spacer(height=h)


def label(text: str, color=MUTED, wrap: int = 0):
    t = dpg.add_text(text, color=color, wrap=wrap)
    bind_font(t, "small")
    return t


def mono_text(text: str = "", color=INK, wrap: int = 0, small: bool = False, bold: bool = False):
    t = dpg.add_text(text, color=color, wrap=wrap)
    bind_font(t, "mono_s" if small else "mono")
    return t


def action(text: str, kind: str, callback, width: int = 0, user_data=None, tip_text: str = ""):
    kind = KIND_ALIAS.get(kind, kind)
    b = dpg.add_button(label=text, width=width, callback=callback, user_data=user_data)
    dpg.bind_item_theme(b, theme(f"btn_{kind}"))
    bind_font(b, "label" if kind != "quiet" else "small")
    if tip_text:
        tip(b, tip_text)
    return b


def toggle(text: str, default: bool, callback=None, user_data=None, tip_text: str = ""):
    c = dpg.add_checkbox(label=text, default_value=default, callback=callback, user_data=user_data)
    dpg.bind_item_theme(c, theme("toggle"))
    if tip_text:
        tip(c, tip_text)
    return c


def number(text: str, default: float, width: int = 90, fmt: str = "%.2f", callback=None, tip_text: str = "",
           label_w: int = 0):
    """Numeric field with its label on the left (label reads first)."""
    with dpg.group(horizontal=True):
        lb = label(text, MUTED)
        if label_w:
            sz = dpg.get_text_size(text, font=font("small")) if font("small") else None
            pad = label_w - (sz[0] if sz and sz[0] > 0 else len(text) * 7.2)
            if pad > 0:
                dpg.add_spacer(width=int(pad))
        i = dpg.add_input_float(default_value=default, width=width, step=0, format=fmt, callback=callback)
    if tip_text:
        tip(lb, tip_text)
        tip(i, tip_text)
    return i


def text_input(default: str = "", width: int = 150, hint: str = "", callback=None, on_enter: bool = False):
    return dpg.add_input_text(default_value=default, width=width, hint=hint, callback=callback, on_enter=on_enter)


def card(**kw):
    cw = dpg.child_window(border=True, **kw)
    return cw


def bind_card(item):
    dpg.bind_item_theme(item, theme("card"))


def tip(item, text: str, width: int = 360):
    """Explain what a control is for.  Appears after TIP_DELAY_S of hovering, so it never gets in
    the way of someone who already knows.  Gated controls get theirs from GateBinder instead."""
    with dpg.tooltip(item, delay=TIP_DELAY_S):
        t = dpg.add_text(text, wrap=width)
        bind_font(t, "small")


def status_mark(dl, center, state: int, off: bool = False, r: float = 5.0):
    """Status drawn with shape AND colour (readable without colour vision):
    ok = filled circle, not ready = triangle, fault = square, no data / off = ring."""
    x, y = center
    col = STATE_COLOR[state]
    if off or state == P.HS_UNKNOWN:
        dpg.draw_circle((x, y), r - 0.5, color=FAINT, thickness=1.6, parent=dl)
    elif state == P.HS_OK:
        dpg.draw_circle((x, y), r, fill=col, color=col, parent=dl)
    elif state == P.HS_BLOCKED:
        h = r * 1.15
        dpg.draw_triangle((x, y - h), (x - h, y + h * 0.8), (x + h, y + h * 0.8), fill=col, color=col, parent=dl)
    else:
        dpg.draw_rectangle((x - r, y - r), (x + r, y + r), fill=col, color=col, parent=dl)


def series(name: str, item):
    """Bind a plot line to its colour/weight (style is applied by lines.py when the data is set)."""
    dpg.bind_item_theme(item, _themes[f"series_{name}"])


def plot_font(plot):
    bind_font(plot, "plot")
