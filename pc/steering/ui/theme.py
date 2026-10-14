"""ui/theme.py - fonts, colours and widget styles.

Every kind of widget looks different on purpose:
  * ACTION BUTTONS  - solid rounded blocks, Poppins, colour = what they do
                      (green = power on, red = stop/danger, amber = free-spin,
                      blue = run something, grey = neutral)
  * TOGGLES         - checkboxes drawn as pill switches (accent when on)
  * INPUTS          - dark inset fields, mono font
  * READOUTS/LOGS   - mono font on a darker panel (telemetry, events, paths)
  * SECTION HEADERS - small Poppins caps + hairline
  * TILES           - small title above, big filled box, Poppins inside
"""
from __future__ import annotations

from pathlib import Path

import dearpygui.dearpygui as dpg

from .. import protocol as P

FONT_DIR = Path(__file__).resolve().parent / "fonts"

BG       = (14, 16, 22)
PANEL    = (22, 25, 34)
PANEL2   = (28, 32, 44)
INSET    = (10, 12, 17)
BORDER   = (48, 54, 70)
TEXT     = (226, 229, 236)
DIM      = (128, 136, 152)
ACCENT   = (74, 140, 255)
OK       = (62, 190, 110)
WARN     = (236, 160, 64)
BAD      = (226, 76, 76)
UNKNOWN  = (84, 90, 108)
PURPLE   = (160, 130, 250)
INK      = (12, 14, 18)      # text on bright fills

SERIES = {
    "setpoint": (255, 180, 50), "target": (255, 120, 180), "position": (80, 180, 255), "error": (220, 70, 70),
    "velocity": (140, 220, 100), "current": (200, 140, 255), "torque": (255, 120, 180), "cursor": (255, 230, 80),
}

STATE_COLOR = {P.HS_OK: OK, P.HS_BLOCKED: WARN, P.HS_FAIL: BAD, P.HS_UNKNOWN: UNKNOWN}
STATE_WORD = {P.HS_OK: "OK", P.HS_BLOCKED: "BLOCKED", P.HS_FAIL: "FAIL", P.HS_UNKNOWN: "UNKNOWN"}
CS_COLOR = {P.CS_REST: UNKNOWN, P.CS_HOLD: OK, P.CS_TRAJ: ACCENT, P.CS_TEST: PURPLE,
            P.CS_FREESPIN: WARN, P.CS_CALIB: WARN, P.CS_TRIPPED: BAD}

_themes: dict = {}
FONTS: dict = {}


def _font(name, file, size):
    p = FONT_DIR / file
    if p.exists():
        FONTS[name] = dpg.add_font(str(p), size)
    return FONTS.get(name)


def build():
    with dpg.font_registry():
        _font("body", "DejaVuSans.ttf", 15)
        _font("small", "DejaVuSans.ttf", 12)
        _font("head", "Poppins-Bold.ttf", 14)
        _font("btn", "Poppins-Medium.ttf", 15)
        _font("tile", "Poppins-Bold.ttf", 20)
        _font("big", "Poppins-Bold.ttf", 28)
        _font("mono", "DejaVuSansMono.ttf", 13)
        _font("mono_b", "DejaVuSansMono-Bold.ttf", 14)
        _font("mono_s", "DejaVuSansMono.ttf", 11)
    if "body" in FONTS:
        dpg.bind_font(FONTS["body"])

    with dpg.theme() as g:
        with dpg.theme_component(dpg.mvAll):
            dpg.add_theme_color(dpg.mvThemeCol_WindowBg, BG)
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg, PANEL)
            dpg.add_theme_color(dpg.mvThemeCol_Border, BORDER)
            dpg.add_theme_color(dpg.mvThemeCol_FrameBg, INSET)
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgHovered, (30, 34, 46))
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgActive, (36, 42, 58))
            dpg.add_theme_color(dpg.mvThemeCol_Button, (52, 58, 76))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (66, 74, 96))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, ACCENT)
            dpg.add_theme_color(dpg.mvThemeCol_Header, (40, 46, 62))
            dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, (52, 60, 80))
            dpg.add_theme_color(dpg.mvThemeCol_HeaderActive, (60, 70, 96))
            dpg.add_theme_color(dpg.mvThemeCol_Tab, (26, 30, 40))
            dpg.add_theme_color(dpg.mvThemeCol_TabActive, (46, 66, 110))
            dpg.add_theme_color(dpg.mvThemeCol_TabHovered, (56, 76, 120))
            dpg.add_theme_color(dpg.mvThemeCol_Text, TEXT)
            dpg.add_theme_color(dpg.mvThemeCol_TextDisabled, DIM)
            dpg.add_theme_color(dpg.mvThemeCol_TitleBgActive, (30, 36, 50))
            dpg.add_theme_color(dpg.mvThemeCol_ScrollbarBg, (16, 18, 24))
            dpg.add_theme_color(dpg.mvThemeCol_ScrollbarGrab, (70, 78, 100))
            dpg.add_theme_color(dpg.mvThemeCol_CheckMark, ACCENT)
            dpg.add_theme_color(dpg.mvThemeCol_SliderGrab, ACCENT)
            dpg.add_theme_color(dpg.mvThemeCol_SliderGrabActive, (120, 170, 255))
            dpg.add_theme_color(dpg.mvThemeCol_Separator, BORDER)
            dpg.add_theme_color(dpg.mvThemeCol_TableHeaderBg, (30, 34, 46))
            dpg.add_theme_color(dpg.mvThemeCol_TableBorderLight, BORDER)
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 4)
            dpg.add_theme_style(dpg.mvStyleVar_WindowRounding, 0)
            dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 8)
            dpg.add_theme_style(dpg.mvStyleVar_TabRounding, 6)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 8, 5)
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 8, 7)
            dpg.add_theme_style(dpg.mvStyleVar_ScrollbarSize, 10)
            dpg.add_theme_style(dpg.mvStyleVar_GrabMinSize, 14)
            dpg.add_theme_color(dpg.mvPlotCol_PlotBg, (16, 18, 24), category=dpg.mvThemeCat_Plots)
            dpg.add_theme_color(dpg.mvPlotCol_FrameBg, PANEL, category=dpg.mvThemeCat_Plots)
            dpg.add_theme_color(dpg.mvPlotCol_PlotBorder, BORDER, category=dpg.mvThemeCat_Plots)
            dpg.add_theme_color(dpg.mvPlotCol_LegendBg, (22, 25, 34, 210), category=dpg.mvThemeCat_Plots)
            dpg.add_theme_color(dpg.mvPlotCol_AxisGrid, (40, 44, 58), category=dpg.mvThemeCat_Plots)
    dpg.bind_theme(g)

    for name, col in SERIES.items():
        with dpg.theme() as t:
            with dpg.theme_component(dpg.mvLineSeries):
                dpg.add_theme_color(dpg.mvPlotCol_Line, col, category=dpg.mvThemeCat_Plots)
                dpg.add_theme_style(dpg.mvPlotStyleVar_LineWeight, 1.7, category=dpg.mvThemeCat_Plots)
            with dpg.theme_component(dpg.mvInfLineSeries):
                dpg.add_theme_color(dpg.mvPlotCol_Line, col, category=dpg.mvThemeCat_Plots)
                dpg.add_theme_style(dpg.mvPlotStyleVar_LineWeight, 2.5, category=dpg.mvThemeCat_Plots)
        _themes[f"series_{name}"] = t

    # ---- action buttons: solid fills, dark text on bright colours ----------------------
    def btn(name, col, text=INK, rounding=6):
        with dpg.theme() as t:
            with dpg.theme_component(dpg.mvButton):
                dpg.add_theme_color(dpg.mvThemeCol_Button, col)
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, tuple(min(255, c + 28) for c in col))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, tuple(min(255, c + 50) for c in col))
                dpg.add_theme_color(dpg.mvThemeCol_Text, text)
                dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, rounding)
                dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 10, 7)
            with dpg.theme_component(dpg.mvButton, enabled_state=False):
                dpg.add_theme_color(dpg.mvThemeCol_Button, (30, 33, 44))
                dpg.add_theme_color(dpg.mvThemeCol_Text, (84, 90, 108))
                dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, rounding)
                dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 10, 7)
        _themes[name] = t
    btn("btn_ok", OK)
    btn("btn_warn", WARN)
    btn("btn_bad", BAD, TEXT)
    btn("btn_accent", ACCENT, TEXT)
    btn("btn_neutral", (58, 66, 88), TEXT)
    btn("btn_ghost", (34, 38, 50), TEXT, rounding=3)      # small utility buttons (pin, open, ...)

    # ---- toggles: pill switches --------------------------------------------------------
    with dpg.theme() as t:
        with dpg.theme_component(dpg.mvCheckbox):
            dpg.add_theme_color(dpg.mvThemeCol_FrameBg, (40, 46, 62))
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgHovered, (52, 60, 80))
            dpg.add_theme_color(dpg.mvThemeCol_CheckMark, (255, 255, 255))
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 12)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 6, 6)
    _themes["toggle"] = t

    # ---- inputs: inset, mono ------------------------------------------------------------
    with dpg.theme() as t:
        for comp in (dpg.mvInputFloat, dpg.mvInputInt, dpg.mvInputText, dpg.mvCombo):
            with dpg.theme_component(comp):
                dpg.add_theme_color(dpg.mvThemeCol_FrameBg, INSET)
                dpg.add_theme_color(dpg.mvThemeCol_Border, (40, 46, 62))
                dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 1)
                dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 3)
    _themes["input"] = t

    # ---- sliders: fat grab ---------------------------------------------------------------
    with dpg.theme() as t:
        with dpg.theme_component(dpg.mvSliderFloat):
            dpg.add_theme_color(dpg.mvThemeCol_FrameBg, (28, 32, 44))
            dpg.add_theme_color(dpg.mvThemeCol_SliderGrab, ACCENT)
            dpg.add_theme_style(dpg.mvStyleVar_GrabMinSize, 22)
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 8)
            dpg.add_theme_style(dpg.mvStyleVar_GrabRounding, 8)
        with dpg.theme_component(dpg.mvSliderFloat, enabled_state=False):
            dpg.add_theme_color(dpg.mvThemeCol_FrameBg, (24, 26, 34))
            dpg.add_theme_color(dpg.mvThemeCol_SliderGrab, (60, 64, 78))
            dpg.add_theme_color(dpg.mvThemeCol_Text, (84, 90, 108))
    _themes["slider"] = t

    # ---- readout / log panels: darker inset -----------------------------------------------
    with dpg.theme() as t:
        with dpg.theme_component(dpg.mvChildWindow):
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg, INSET)
            dpg.add_theme_color(dpg.mvThemeCol_Border, (36, 40, 52))
            dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 4)
    _themes["readout"] = t

    with dpg.theme() as t:
        with dpg.theme_component(dpg.mvChildWindow):
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg, PANEL2)
            dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 8)
    _themes["card"] = t

    with dpg.theme() as t:
        with dpg.theme_component(dpg.mvSelectable):
            dpg.add_theme_color(dpg.mvThemeCol_Header, (46, 66, 110))
            dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, (40, 46, 62))
    _themes["row"] = t


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


# ---- small layout helpers used by every panel ------------------------------------------------
def section(label: str, width: int = -1):
    """Section header: small Poppins caps + hairline."""
    t = dpg.add_text(label.upper(), color=DIM)
    bind_font(t, "head")
    dpg.add_separator()
    return t


def mono_text(text: str = "", color=TEXT, wrap: int = 0, bold: bool = False):
    t = dpg.add_text(text, color=color, wrap=wrap)
    bind_font(t, "mono_b" if bold else "mono")
    return t


def action(label: str, kind: str, callback, width: int = -1, user_data=None):
    b = dpg.add_button(label=label, width=width, callback=callback, user_data=user_data)
    dpg.bind_item_theme(b, theme(f"btn_{kind}"))
    bind_font(b, "btn")
    return b


def toggle(label: str, default: bool, callback=None, user_data=None):
    c = dpg.add_checkbox(label=label, default_value=default, callback=callback, user_data=user_data)
    dpg.bind_item_theme(c, theme("toggle"))
    return c


def number(label: str, default: float, width: int = 90, fmt: str = "%.2f", callback=None):
    i = dpg.add_input_float(label=label, default_value=default, width=width, step=0, format=fmt, callback=callback)
    dpg.bind_item_theme(i, theme("input"))
    bind_font(i, "mono")
    return i


def text_input(default: str = "", width: int = 150, hint: str = "", callback=None, on_enter: bool = False):
    i = dpg.add_input_text(default_value=default, width=width, hint=hint, callback=callback, on_enter=on_enter)
    dpg.bind_item_theme(i, theme("input"))
    bind_font(i, "mono")
    return i
