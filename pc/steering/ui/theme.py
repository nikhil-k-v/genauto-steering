"""ui/theme.py - colours, fonts, DPG themes.  One palette, used everywhere."""
from __future__ import annotations

import dearpygui.dearpygui as dpg

from .. import protocol as P

BG       = (15, 18, 24)
PANEL    = (24, 28, 38)
BORDER   = (50, 56, 70)
TEXT     = (220, 224, 232)
DIM      = (130, 138, 152)
ACCENT   = (80, 150, 255)
OK       = (78, 202, 122)
WARN     = (240, 164, 78)
BAD      = (232, 85, 85)
UNKNOWN  = (90, 98, 120)
PURPLE   = (167, 139, 250)

SERIES = {
    "setpoint": (255, 180, 50), "target": (255, 120, 180), "position": (80, 180, 255), "error": (220, 70, 70),
    "velocity": (140, 220, 100), "current": (200, 140, 255), "torque": (255, 120, 180), "cursor": (255, 230, 80),
}

STATE_COLOR = {P.HS_OK: OK, P.HS_BLOCKED: WARN, P.HS_FAIL: BAD, P.HS_UNKNOWN: UNKNOWN}
CS_COLOR = {P.CS_REST: DIM, P.CS_HOLD: OK, P.CS_TRAJ: ACCENT, P.CS_JOY: PURPLE, P.CS_TEST: PURPLE,
            P.CS_FREESPIN: WARN, P.CS_CALIB: WARN, P.CS_TRIPPED: BAD}

_themes = {}


def build():
    with dpg.theme() as global_theme:
        with dpg.theme_component(dpg.mvAll):
            dpg.add_theme_color(dpg.mvThemeCol_WindowBg, BG)
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg, PANEL)
            dpg.add_theme_color(dpg.mvThemeCol_Border, BORDER)
            dpg.add_theme_color(dpg.mvThemeCol_FrameBg, (32, 37, 50))
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgHovered, (42, 48, 64))
            dpg.add_theme_color(dpg.mvThemeCol_Button, (45, 52, 72))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (60, 70, 96))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, ACCENT)
            dpg.add_theme_color(dpg.mvThemeCol_Header, (40, 46, 62))
            dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, (52, 60, 80))
            dpg.add_theme_color(dpg.mvThemeCol_Tab, (34, 40, 54))
            dpg.add_theme_color(dpg.mvThemeCol_TabActive, (52, 72, 110))
            dpg.add_theme_color(dpg.mvThemeCol_TabHovered, (62, 82, 120))
            dpg.add_theme_color(dpg.mvThemeCol_Text, TEXT)
            dpg.add_theme_color(dpg.mvThemeCol_TextDisabled, DIM)
            dpg.add_theme_color(dpg.mvThemeCol_TitleBgActive, (30, 36, 50))
            dpg.add_theme_color(dpg.mvThemeCol_ScrollbarBg, (20, 24, 32))
            dpg.add_theme_color(dpg.mvThemeCol_ScrollbarGrab, (70, 78, 100))
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 4)
            dpg.add_theme_style(dpg.mvStyleVar_WindowRounding, 0)
            dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 6)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 6, 4)
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 8, 6)
            dpg.add_theme_style(dpg.mvStyleVar_ScrollbarSize, 10)
            dpg.add_theme_color(dpg.mvPlotCol_PlotBg, (18, 21, 28), category=dpg.mvThemeCat_Plots)
            dpg.add_theme_color(dpg.mvPlotCol_FrameBg, PANEL, category=dpg.mvThemeCat_Plots)
            dpg.add_theme_color(dpg.mvPlotCol_PlotBorder, BORDER, category=dpg.mvThemeCat_Plots)
            dpg.add_theme_color(dpg.mvPlotCol_LegendBg, (24, 28, 38, 200), category=dpg.mvThemeCat_Plots)
    dpg.bind_theme(global_theme)

    for name, col in SERIES.items():
        with dpg.theme() as t:
            with dpg.theme_component(dpg.mvLineSeries):
                dpg.add_theme_color(dpg.mvPlotCol_Line, col, category=dpg.mvThemeCat_Plots)
                dpg.add_theme_style(dpg.mvPlotStyleVar_LineWeight, 2.5 if name == "cursor" else 1.6,
                                    category=dpg.mvThemeCat_Plots)
            with dpg.theme_component(dpg.mvInfLineSeries):
                dpg.add_theme_color(dpg.mvPlotCol_Line, col, category=dpg.mvThemeCat_Plots)
                dpg.add_theme_style(dpg.mvPlotStyleVar_LineWeight, 2.5, category=dpg.mvThemeCat_Plots)
        _themes[f"series_{name}"] = t

    for name, col in (("ok", OK), ("warn", WARN), ("bad", BAD), ("unknown", UNKNOWN), ("accent", ACCENT), ("dim", (45, 52, 72))):
        with dpg.theme() as t:
            with dpg.theme_component(dpg.mvButton):
                dpg.add_theme_color(dpg.mvThemeCol_Button, col)
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, tuple(min(255, c + 25) for c in col))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, tuple(min(255, c + 45) for c in col))
                dpg.add_theme_color(dpg.mvThemeCol_Text, (10, 12, 16) if name in ("ok", "warn") else TEXT)
        _themes[f"btn_{name}"] = t

    with dpg.theme() as t:        # disabled look for gated controls
        with dpg.theme_component(dpg.mvButton, enabled_state=False):
            dpg.add_theme_color(dpg.mvThemeCol_Button, (34, 38, 48))
            dpg.add_theme_color(dpg.mvThemeCol_Text, (90, 96, 110))
        with dpg.theme_component(dpg.mvSliderFloat, enabled_state=False):
            dpg.add_theme_color(dpg.mvThemeCol_FrameBg, (28, 31, 40))
            dpg.add_theme_color(dpg.mvThemeCol_SliderGrab, (60, 64, 76))
            dpg.add_theme_color(dpg.mvThemeCol_Text, (90, 96, 110))
    dpg.bind_theme(global_theme)
    _themes["disabled"] = t


def theme(name: str):
    return _themes[name]


def series_theme(name: str):
    return _themes[f"series_{name}"]
