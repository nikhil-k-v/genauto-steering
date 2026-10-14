"""
ui/lines.py - plot-line grammar for Dear PyGui (ImPlot has no dashed lines).

    solid   measured         (position, speed, current)
    dashed  commanded        (the Teensy's setpoint, torque command)
    dotted  requested        (what the laptop/planner asked for, before the slew limit)

Colour says the source (theme.SOURCE_COLOR) - so "setpoint" is always dashed,
and a playback, a waveform, the slider and the planner differ only by colour.

Dashes are made in SCREEN space: the polyline is measured in pixels for the
plot's current zoom and cut into on/off pieces separated by NaN (ImPlot draws
a NaN as a gap).  So dashes keep their length when you zoom, and steep
segments get as many dashes as flat ones.
"""
from __future__ import annotations

from typing import Optional, Sequence, Tuple

import dearpygui.dearpygui as dpg
import numpy as np

from . import theme as T


def dash(x: Sequence[float], y: Sequence[float], sx: float, sy: float,
         pattern: Optional[Tuple[float, float]]) -> Tuple[np.ndarray, np.ndarray]:
    """Cut a polyline into dashes.  sx, sy = pixels per data unit on each axis."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if pattern is None or x.size < 2:
        return x, y
    on, off = pattern
    period = on + off
    d = np.hypot(np.diff(x) * sx, np.diff(y) * sy)
    d = np.where(np.isfinite(d), d, 0.0)
    s = np.concatenate(([0.0], np.cumsum(d)))
    total = float(s[-1])
    if total <= 0 or not np.isfinite(total):
        return x, y
    if total / period > 4000:          # absurd zoom (or limits not settled yet): stretch the pattern
        f = total / period / 4000
        on, off, period = on * f, off * f, period * f
    k = np.arange(0, int(total // period) + 1, dtype=float)
    b_on = k * period
    b_on = b_on[(b_on > 0) & (b_on < total)]
    b_off = k * period + on
    b_off = b_off[b_off < total]
    gap = ~np.isfinite(x) | ~np.isfinite(y)            # existing gaps stay gaps
    keep = (np.mod(s, period) < on) | gap
    xs, ys = np.interp(b_on, s, x), np.interp(b_on, s, y)
    xo, yo = np.interp(b_off, s, x), np.interp(b_off, s, y)
    S = np.concatenate((s[keep], b_on, b_off, b_off + 1e-7))
    X = np.concatenate((x[keep], xs, xo, np.full(b_off.size, np.nan)))
    Y = np.concatenate((y[keep], ys, yo, np.full(b_off.size, np.nan)))
    order = np.argsort(S, kind="stable")
    return X[order], Y[order]


def scale(plot, xaxis, yaxis) -> Tuple[float, float]:
    """Pixels per data unit for a plot's current axis limits (approximate: frame minus axis labels)."""
    try:
        w, h = dpg.get_item_rect_size(plot)
        x0, x1 = dpg.get_axis_limits(xaxis)
        y0, y1 = dpg.get_axis_limits(yaxis)
    except Exception:
        return 1.0, 1.0
    w = max(50.0, w - 60.0)
    h = max(30.0, h - 30.0)
    return w / max(1e-9, x1 - x0), h / max(1e-9, y1 - y0)


def set_line(item, name: str, x, y, sx: float, sy: float):
    """Set a line series' data with the style its SERIES entry asks for."""
    col, style, _ = T.SERIES[name]
    X, Y = dash(x, y, sx, sy, T.DASH[style])
    dpg.set_value(item, [X.tolist(), Y.tolist()])


def legend(dl, entries, width: int):
    """A legend that shows the actual line styles (ImPlot's shows a colour square only).
    entries: [(series_name, label)].  Returns the height used."""
    dpg.delete_item(dl, children_only=True)
    x, y, lh = 0.0, 0.0, 20.0
    for name, text in entries:
        col, style, wt = T.SERIES[name]
        tw = dpg.get_text_size(text, font=T.font("plot_s")) if T.font("plot_s") else None
        tw = tw[0] if tw and tw[0] > 0 else len(text) * 7.0
        need = 30 + tw + 22
        if x + need > width and x > 0:
            x, y = 0.0, y + lh
        cy = y + lh / 2
        pat = T.DASH[style]
        if pat is None:
            dpg.draw_line((x, cy), (x + 24, cy), color=col, thickness=wt, parent=dl)
        else:
            on, off = pat
            xx = x
            while xx < x + 24:
                dpg.draw_line((xx, cy), (min(xx + on, x + 24), cy), color=col, thickness=wt, parent=dl)
                xx += on + off
        it = dpg.draw_text((x + 30, y + 3), text, color=T.MUTED, size=T.FONT_SIZE.get("plot_s", 12), parent=dl)
        T.bind_font(it, "plot_s")
        x += need
    return int(y + lh)
