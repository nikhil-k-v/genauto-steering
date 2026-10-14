#!/usr/bin/env python3
"""
docs/diagrams/gen.py - generates every diagram in docs/diagrams/*.svg.

Visual language (the legend on each diagram repeats the parts it uses):

  shapes      hardware      square corners, heavy outline
              software      rounded rectangle
              storage       cylinder
              physical      hexagon (things you touch: wheel, switch, supply)
              decision      diamond
              data          parallelogram (a packet, a file, a signal)
              state         pill
  lines       solid = always there, dashed = optional or future
              one head = one-way, two heads = both ways
              the line's label sits in a gap in the line, in the line's colour;
              notes about each direction sit either side of the line, same colour
  colour      the kind of link: USB blue, CAN violet, power red, safety plum,
              Teensy-internal green, laptop data ochre, everything else slate

Every edge gets its own attachment point on a box side (ports are spread
along the side and ordered by where the edge goes), so arrowheads never land
on the same spot.  Fonts are embedded (subset Barlow) so the SVGs look the
same on GitHub, in the web hub and in a browser.

    python docs/diagrams/gen.py            # writes the SVGs next to this file
    python docs/diagrams/gen.py --png      # also renders PNG previews (needs cairosvg + Barlow installed)
"""
from __future__ import annotations

import base64
import io
import math
import sys
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont

OUT = Path(__file__).resolve().parent
FONT_DIR = OUT.parents[1] / "pc" / "steering" / "ui" / "fonts"

BG = "#ffffff"
INK = "#1b2129"
MUTED = "#68717c"
RULE = "#d2d6db"
FILL = "#ffffff"
COL = {"C": "#2b5fae", "M": "#7a5bb5", "S": "#a33a7c", "T": "#1f7a5c", "D": "#a86c0c", "N": "#5c6672", "P": "#c2362d"}
FAMILY = "Barlow, 'Helvetica Neue', Arial, sans-serif"
MONO = "'IBM Plex Mono', Menlo, Consolas, monospace"

# ---- font metrics (real advance widths, so gaps and boxes fit the text) -------------------------------
_FONTS = {}


def _font(face):
    if face not in _FONTS:
        f = TTFont(FONT_DIR / {"reg": "Barlow-Regular.ttf", "semi": "Barlow-SemiBold.ttf",
                               "mono": "IBMPlexMono-Regular.ttf"}[face])
        _FONTS[face] = (f.getBestCmap(), f["hmtx"], f["head"].unitsPerEm)
    return _FONTS[face]


def tw(text: str, size: float, face: str = "reg") -> float:
    cmap, hmtx, upm = _font(face)
    w = 0
    for ch in text:
        g = cmap.get(ord(ch)) or cmap.get(ord("?"))
        w += hmtx[g][0]
    return w * size / upm


def _embedded_fonts() -> str:
    chars = "".join(chr(c) for c in range(0x20, 0x7F)) + "°±×–—’…−·"
    css = []
    for face, file, weight, fam in (("reg", "Barlow-Regular.ttf", 400, "Barlow"), ("semi", "Barlow-SemiBold.ttf", 600, "Barlow"),
                                    ("mono", "IBMPlexMono-Regular.ttf", 400, "IBM Plex Mono")):
        f = TTFont(FONT_DIR / file)
        opts = subset.Options()
        opts.flavor = "woff2"
        opts.layout_features = ["kern"]
        sub = subset.Subsetter(opts)
        sub.populate(text=chars)
        sub.subset(f)
        buf = io.BytesIO()
        f.flavor = "woff2"
        f.save(buf)
        b64 = base64.b64encode(buf.getvalue()).decode()
        css.append(f"@font-face{{font-family:'{fam}';font-weight:{weight};src:url(data:font/woff2;base64,{b64}) format('woff2')}}")
    return "<style>" + "".join(css) + "</style>"


_FONT_CSS = None


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class D:
    def __init__(self, w, h, title, subtitle=""):
        self.w, self.h = w, h
        self.parts = [f'<rect width="{w}" height="{h}" fill="{BG}"/>']
        self.nodes = {}
        self.edges = []
        self.markers = set()
        self.text(32, 44, title, 22, INK, weight=600)
        if subtitle:
            self.text(32, 68, subtitle, 13.5, MUTED)

    # ---- text --------------------------------------------------------------------------------------------
    def text(self, x, y, s, size=13, color=INK, anchor="start", weight=400, mono=False, lh=None):
        lh = lh or size + 4
        for i, line in enumerate(s.split("\n")):
            fam = MONO if mono else FAMILY
            keep = ' xml:space="preserve"' if mono else ""
            self.parts.append(f'<text x="{x:.1f}" y="{y + i * lh:.1f}" fill="{color}" font-family="{fam}" '
                              f'font-size="{size}" font-weight="{weight}" text-anchor="{anchor}"{keep}>{esc(line)}</text>')

    # ---- nodes -------------------------------------------------------------------------------------------
    def node(self, key, kind, x, y, w, h, label, sub="", group="N", mono_sub=False):
        c = COL[group]
        cx, cy = x + w / 2, y + h / 2
        sw = 1.6
        if kind == "hw":
            self.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{FILL}" stroke="{c}" stroke-width="2.6"/>')
        elif kind == "sw":
            self.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{FILL}" stroke="{c}" stroke-width="{sw}"/>')
        elif kind == "state":
            self.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{h / 2}" fill="{FILL}" stroke="{c}" stroke-width="{sw}"/>')
        elif kind == "store":
            ry = 8
            self.parts.append(f'<path d="M{x},{y + ry} a{w / 2},{ry} 0 0 0 {w},0 v{h - 2 * ry} a{w / 2},{ry} 0 0 1 -{w},0 z" '
                              f'fill="{FILL}" stroke="{c}" stroke-width="{sw}"/>')
            self.parts.append(f'<ellipse cx="{cx}" cy="{y + ry}" rx="{w / 2}" ry="{ry}" fill="{FILL}" stroke="{c}" stroke-width="{sw}"/>')
            cy += 5
        elif kind == "phys":
            dx = min(16, h / 2)
            pts = f"{x + dx},{y} {x + w - dx},{y} {x + w},{cy} {x + w - dx},{y + h} {x + dx},{y + h} {x},{cy}"
            self.parts.append(f'<polygon points="{pts}" fill="{FILL}" stroke="{c}" stroke-width="{sw}"/>')
        elif kind == "decision":
            pts = f"{cx},{y} {x + w},{cy} {cx},{y + h} {x},{cy}"
            self.parts.append(f'<polygon points="{pts}" fill="{FILL}" stroke="{c}" stroke-width="{sw}"/>')
        elif kind == "data":
            s = 14
            pts = f"{x + s},{y} {x + w},{y} {x + w - s},{y + h} {x},{y + h}"
            self.parts.append(f'<polygon points="{pts}" fill="{FILL}" stroke="{c}" stroke-width="{sw}"/>')
        elif kind == "group":
            self.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="{c}" fill-opacity="0.045" '
                              f'stroke="{c}" stroke-opacity="0.55" stroke-width="1.2" stroke-dasharray="5 4"/>')
            self.text(x + 16, y + 24, label, 14, c, weight=600)
            self.nodes[key] = (x, y, w, h, kind)
            return
        lines = label.split("\n")
        subs = sub.split("\n") if sub else []
        lh1, lh2 = 18, 16
        total = len(lines) * lh1 + len(subs) * lh2
        y0 = cy - total / 2 + 13
        for i, l in enumerate(lines):
            self.text(cx, y0 + i * lh1, l, 15 if kind != "decision" else 14, INK, "middle", 600)
        if mono_sub:            # code-like detail: a left-aligned block, centred as a block
            bw = max(tw(l, 11.5, "mono") for l in subs)
            for j, l in enumerate(subs):
                self.text(cx - bw / 2, y0 + len(lines) * lh1 + j * lh2 + 1, l, 11.5, MUTED, "start", 400, mono=True)
        else:
            for j, l in enumerate(subs):
                self.text(cx, y0 + len(lines) * lh1 + j * lh2 + 1, l, 12.5, MUTED, "middle", 400)
        self.nodes[key] = (x, y, w, h, kind)

    def note(self, x, y, s, size=13):
        self.text(x, y, s, size, MUTED)

    # ---- edges -------------------------------------------------------------------------------------------
    def edge(self, a, b, label="", sa="r", sb="l", kind="uni", color="N", dashed=False, via=None, at=0.5,
             la="", lb="", pa=None, pb=None, seg=None):
        """a -> b.  kind uni | bi | none.  color: group letter or hex.
        la / lb: what flows a->b / b->a, written either side of the line.
        pa / pb: pin the attachment offset (px from the side's centre) instead of auto ports.
        seg: which segment carries the label (default: the longest)."""
        self.edges.append(dict(a=a, b=b, label=label, sa=sa, sb=sb, kind=kind, color=COL.get(color, color),
                               dashed=dashed, via=[list(p) for p in (via or [])], at=at, la=la, lb=lb, pa=pa, pb=pb, seg=seg))

    def _side_point(self, key, side, t):
        x, y, w, h, kind = self.nodes[key]
        cx, cy = x + w / 2, y + h / 2
        if kind == "decision":
            if side in "lr":
                dx = (w / 2) * (1 - min(abs(t) / (h / 2), 0.95))
                return (cx + dx if side == "r" else cx - dx, cy + t)
            dy = (h / 2) * (1 - min(abs(t) / (w / 2), 0.95))
            return (cx + t, cy - dy if side == "t" else cy + dy)
        if kind == "phys" and side in "lr":
            dx = min(16, h / 2) * min(abs(t) / (h / 2), 1)
            return (x + dx if side == "l" else x + w - dx, cy + t)
        if kind == "data" and side in "lr":
            s = 14
            yy = cy + t
            return ((x + s * (y + h - yy) / h) if side == "l" else (x + w - s * (yy - y) / h), yy)
        if kind == "store" and side in "tb":
            return (cx + t, y if side == "t" else y + h)
        return {"l": (x, cy + t), "r": (x + w, cy + t), "t": (cx + t, y), "b": (cx + t, y + h)}[side]

    def _assign_ports(self):
        ends = {}
        for i, e in enumerate(self.edges):
            ends.setdefault((e["a"], e["sa"]), []).append((i, "a"))
            ends.setdefault((e["b"], e["sb"]), []).append((i, "b"))
        for (key, side), lst in ends.items():
            x, y, w, h, kind = self.nodes[key]
            L = h if side in "lr" else w
            auto = []
            for i, end in lst:
                e = self.edges[i]
                pin = e["pa"] if end == "a" else e["pb"]
                if pin is not None:
                    e["ta" if end == "a" else "tb"] = pin
                    continue
                if end == "a":
                    nb = e["via"][0] if e["via"] else self._centre(e["b"])
                else:
                    nb = e["via"][-1] if e["via"] else self._centre(e["a"])
                auto.append((nb[1] if side in "lr" else nb[0], i, end))
            auto.sort()
            n = len(auto)
            if not n:
                continue
            limit = 0.62 if kind in ("decision", "state") else 0.8
            spacing = min(L * limit / max(n, 1), 30)
            for j, (_, i, end) in enumerate(auto):
                self.edges[i]["ta" if end == "a" else "tb"] = (j - (n - 1) / 2) * spacing

    def _centre(self, key):
        x, y, w, h, _ = self.nodes[key]
        return (x + w / 2, y + h / 2)

    def _route(self, e):
        p = self._side_point(e["a"], e["sa"], e["ta"])
        q = self._side_point(e["b"], e["sb"], e["tb"])
        via = [list(v) for v in e["via"]]
        if len(via) == 1 and (e["sa"] in "lr") == (e["sb"] in "lr"):
            v = via[0]
            via = [[v[0], p[1]], [v[0], q[1]]] if e["sa"] in "lr" else [[p[0], v[1]], [q[0], v[1]]]
        if via:
            if e["sa"] in "lr":
                via[0][1] = p[1]
            else:
                via[0][0] = p[0]
            if e["sb"] in "lr":
                via[-1][1] = q[1]
            else:
                via[-1][0] = q[0]
        else:
            ha, hb = e["sa"] in "lr", e["sb"] in "lr"
            if ha and hb and abs(p[1] - q[1]) > 0.5:
                mx = (p[0] + q[0]) / 2
                via = [[mx, p[1]], [mx, q[1]]]
            elif not ha and not hb and abs(p[0] - q[0]) > 0.5:
                my = (p[1] + q[1]) / 2
                via = [[p[0], my], [q[0], my]]
            elif ha and not hb:
                via = [[q[0], p[1]]]
            elif hb and not ha:
                via = [[p[0], q[1]]]
        return [tuple(p)] + [tuple(v) for v in via] + [tuple(q)]

    def _marker(self, color):
        k = color[1:]
        if k not in self.markers:
            self.markers.add(k)
        return f"m{k}", f"r{k}"

    def _path(self, pts, color, dashed, start=False, end=False):
        d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        m_end, m_start = self._marker(color)
        dash = ' stroke-dasharray="7 5"' if dashed else ""
        ms = f' marker-start="url(#{m_start})"' if start else ""
        me = f' marker-end="url(#{m_end})"' if end else ""
        self.parts.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round"{dash}{ms}{me}/>')

    def _draw_edge(self, e):
        pts = self._route(e)
        color, dashed = e["color"], e["dashed"]
        start, end = e["kind"] == "bi", e["kind"] in ("uni", "bi")
        lab = e["label"]
        segs = [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
        si = e["seg"] if e["seg"] is not None else max(range(len(segs)), key=lambda i: math.dist(*segs[i]))
        (x1, y1), (x2, y2) = segs[si]
        L = math.dist((x1, y1), (x2, y2))
        horiz = abs(y2 - y1) < abs(x2 - x1)
        size, lh = 12.5, 15
        lines = lab.split("\n") if lab else []
        lw = max((tw(l, size) for l in lines), default=0)
        lhgt = len(lines) * lh
        gap = (lw + 16) if horiz else (lhgt + 12)
        ux, uy = ((x2 - x1) / L, (y2 - y1) / L) if L else (1, 0)
        # label centre along the chosen segment, kept clear of the ends (arrowheads)
        margin = 16
        c = L * e["at"]
        if lab and L - 2 * margin > gap:
            c = min(max(c, margin + gap / 2), L - margin - gap / 2)
            g0 = (x1 + ux * (c - gap / 2), y1 + uy * (c - gap / 2))
            g1 = (x1 + ux * (c + gap / 2), y1 + uy * (c + gap / 2))
            self._path(pts[:si + 1] + [g0], color, dashed, start=start)
            self._path([g1] + pts[si + 1:], color, dashed, end=end)
            lx, ly = x1 + ux * c, y1 + uy * c
            in_gap = True
        else:
            self._path(pts, color, dashed, start=start, end=end)
            lx, ly = x1 + ux * c, y1 + uy * c
            in_gap = False
        if lines:
            if in_gap:
                ty = ly - lhgt / 2 + 11
                for i, l in enumerate(lines):
                    self.text(lx, ty + i * lh, l, size, color, "middle", 500)
            else:                       # too short for a gap: write beside the line
                if horiz:
                    for i, l in enumerate(lines):
                        self.text(lx, ly - 8 - (len(lines) - 1 - i) * lh, l, size, color, "middle", 500)
                else:
                    for i, l in enumerate(lines):
                        self.text(lx + 8, ly - lhgt / 2 + 11 + i * lh, l, size, color, "start", 500)
        # direction notes either side of the line, same colour
        nsize = 11.5
        if e["la"] or e["lb"]:
            half = (lhgt / 2 if in_gap else 0)
            if horiz:
                if e["la"]:
                    self.text(lx, ly - max(half, 4) - 7, e["la"], nsize, color, "middle")
                if e["lb"]:
                    self.text(lx, ly + max(half, 4) + 16, e["lb"], nsize, color, "middle")
            else:
                wa = max((tw(l, size) for l in lines), default=0) / 2 if in_gap else 0
                if e["la"]:
                    self.text(lx - max(wa, 4) - 10, ly + 4, e["la"], nsize, color, "end")
                if e["lb"]:
                    self.text(lx + max(wa, 4) + 10, ly + 4, e["lb"], nsize, color, "start")

    # ---- legend ------------------------------------------------------------------------------------------
    def legend(self, x, y, items):
        cx = x
        for kind, txt in items:
            bx, by = cx, y
            s = f'fill="{FILL}" stroke="{MUTED}" stroke-width="1.4"'
            if kind == "hw":
                self.parts.append(f'<rect x="{bx}" y="{by}" width="22" height="15" fill="{FILL}" stroke="{MUTED}" stroke-width="2.4"/>')
            elif kind == "sw":
                self.parts.append(f'<rect x="{bx}" y="{by}" width="22" height="15" rx="5" {s}/>')
            elif kind == "store":
                self.parts.append(f'<path d="M{bx},{by + 4} v8 a11,3.5 0 0 0 22,0 v-8" {s}/><ellipse cx="{bx + 11}" cy="{by + 4}" rx="11" ry="3.5" {s}/>')
            elif kind == "phys":
                self.parts.append(f'<polygon points="{bx + 5},{by} {bx + 17},{by} {bx + 22},{by + 7.5} {bx + 17},{by + 15} {bx + 5},{by + 15} {bx},{by + 7.5}" {s}/>')
            elif kind == "decision":
                self.parts.append(f'<polygon points="{bx + 11},{by - 1} {bx + 23},{by + 7.5} {bx + 11},{by + 16} {bx - 1},{by + 7.5}" {s}/>')
            elif kind == "data":
                self.parts.append(f'<polygon points="{bx + 5},{by} {bx + 22},{by} {bx + 17},{by + 15} {bx},{by + 15}" {s}/>')
            elif kind == "state":
                self.parts.append(f'<rect x="{bx}" y="{by}" width="22" height="15" rx="7.5" {s}/>')
            elif kind in ("line", "dash", "bi"):
                dash = ' stroke-dasharray="5 4"' if kind == "dash" else ""
                self.parts.append(f'<line x1="{bx + (4 if kind == "bi" else 0)}" y1="{by + 7.5}" x2="{bx + 18}" y2="{by + 7.5}" stroke="{MUTED}" stroke-width="2"{dash}/>'
                                  f'<polygon points="{bx + 24},{by + 7.5} {bx + 16},{by + 3.5} {bx + 16},{by + 11.5}" fill="{MUTED}"/>')
                if kind == "bi":
                    self.parts.append(f'<polygon points="{bx - 2},{by + 7.5} {bx + 6},{by + 3.5} {bx + 6},{by + 11.5}" fill="{MUTED}"/>')
            self.text(bx + 32, by + 12, txt, 12.5, MUTED)
            cx += 32 + tw(txt, 12.5) + 28

    def colours(self, x, y, items):
        cx = x
        for g, txt in items:
            self.parts.append(f'<line x1="{cx}" y1="{y + 7.5}" x2="{cx + 22}" y2="{y + 7.5}" stroke="{COL[g]}" stroke-width="2.6"/>')
            self.text(cx + 30, y + 12, txt, 12.5, COL[g], weight=500)
            cx += 30 + tw(txt, 12.5) + 26

    # ---- output ------------------------------------------------------------------------------------------
    def save(self, name):
        global _FONT_CSS
        if _FONT_CSS is None:
            _FONT_CSS = _embedded_fonts()
        self._assign_ports()
        for e in self.edges:
            self._draw_edge(e)
        defs = []
        for k in sorted(self.markers):
            defs.append(f'<marker id="m{k}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="9" markerHeight="9" '
                        f'markerUnits="userSpaceOnUse" orient="auto"><path d="M0,0.8 L10,5 L0,9.2 z" fill="#{k}"/></marker>'
                        f'<marker id="r{k}" viewBox="0 0 10 10" refX="1" refY="5" markerWidth="9" markerHeight="9" '
                        f'markerUnits="userSpaceOnUse" orient="auto"><path d="M10,0.8 L0,5 L10,9.2 z" fill="#{k}"/></marker>')
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" viewBox="0 0 {self.w} {self.h}" '
               f'font-family="{FAMILY}">{_FONT_CSS}<defs>{"".join(defs)}</defs>' + "".join(self.parts) + "</svg>")
        out = OUT / f"{name}.svg"
        out.write_text(svg)
        return out


SHAPES = [("hw", "hardware"), ("sw", "software"), ("store", "storage"), ("phys", "physical"),
          ("bi", "both ways"), ("line", "one way"), ("dash", "optional or future")]
LINKS = [("C", "USB"), ("M", "CAN"), ("P", "power"), ("S", "safety"), ("T", "Teensy internal"), ("D", "laptop data")]


# =========================================================================================================
def system_overview():
    d = D(1500, 660, "System overview", "The components, the links between them, and what crosses each link.")
    d.legend(32, 92, SHAPES)
    d.colours(32, 120, LINKS)
    d.node("laptop", "hw", 40, 200, 290, 130, "Laptop", "Python app (Dear PyGui)\nweb hub (FastAPI)\nchecks: C, D", "D")
    d.node("teensy", "hw", 640, 200, 300, 130, "Teensy 4.1 (CCM)", "1 kHz control interrupt\nhealth, OLED\nchecks: T, S", "T")
    d.node("motor", "hw", 1180, 200, 280, 130, "BM-24 actuator", "FOC board, 20 kHz\ndual absolute encoder, id 0x02\nchecks: M", "M")
    d.edge("laptop", "teensy", "USB serial, 2 Mbps", kind="bi", color="C",
           la="to Teensy: setpoints 200 Hz, heartbeat 5 Hz", lb="to laptop: telemetry 200 Hz, health 20 Hz")
    d.edge("teensy", "motor", "CAN, 1 Mbps", kind="bi", color="M",
           la="to motor: p, v, kp, kd, torque at 1 kHz", lb="to Teensy: id, p, v, current")
    d.node("switch", "phys", 650, 440, 220, 64, "Idle switch", "pin 22 to GND, open = idle", "S")
    d.edge("switch", "teensy", "armed / idle", "t", "b", color="S", pb=-60)
    d.node("oled", "hw", 960, 420, 170, 56, "OLED 2.42 in", "I2C, pins 18 / 19", "T")
    d.edge("teensy", "oled", "status", "b", "t", color="T", pa=90, pb=0, via=[(880, 380), (1045, 380)])
    d.node("wheel", "phys", 1200, 420, 240, 64, "Steering wheel", "clamp-on coupling, braced arm", "N")
    d.edge("motor", "wheel", "torque", "b", "t", color="N")
    d.node("psu", "phys", 1200, 540, 240, 60, "24 V supply", "15 A, 40 A peak", "P")
    d.edge("psu", "motor", "24 V", "r", "r", color="P", via=[(1478, 570), (1478, 265)])
    d.node("phone", "hw", 40, 440, 220, 64, "Phone (browser)", "camera, IMU, clock sync", "D")
    d.edge("phone", "laptop", "Wi-Fi", "t", "b", kind="bi", color="D", pb=-35,
           la="video, IMU", lb="telemetry, health")
    d.node("planner", "hw", 40, 548, 220, 60, "Planner (future)", "ROS 2 on AGX Orin", "D")
    d.edge("planner", "laptop", "setpoints 200 Hz", "r", "b", color="D", dashed=True, pb=100, via=[(290, 578)])
    return d.save("01_system_overview")


def software_map():
    d = D(1500, 800, "Software map", "Who calls whom inside the laptop app and the Teensy firmware.")
    d.legend(32, 92, [("sw", "module"), ("store", "storage"), ("data", "config"), ("hw", "hardware"), ("line", "call or data"), ("bi", "both ways"), ("dash", "optional")])
    d.colours(32, 120, [("D", "inside the laptop app"), ("C", "USB"), ("T", "inside the firmware"), ("M", "CAN")])
    d.node("gL", "group", 40, 160, 940, 600, "Laptop app", "", "D")
    d.node("ui", "sw", 70, 210, 230, 80, "UI", "ui/app.py, rail.py, panels/", "D")
    d.node("ctrl", "sw", 370, 210, 230, 80, "Controller", "core/controller.py\nevery action is gated", "D")
    d.node("gate", "sw", 680, 210, 270, 80, "Gating and health model", "health/gating.py, model.py", "D")
    d.node("stream", "sw", 370, 360, 230, 70, "Streamer", "control/streamer.py, 200 Hz", "D")
    d.node("eval", "sw", 680, 360, 270, 70, "Health evaluator", "health/evaluator.py, 10 Hz", "D")
    d.node("link", "sw", 70, 500, 230, 76, "Link", "link.py: framing, heartbeat\nreconnect, counters", "C")
    d.node("bus", "sw", 370, 500, 230, 76, "Bus", "bus.py: publish / subscribe", "D")
    d.node("rec", "sw", 680, 500, 270, 76, "Recorder", "data/recorder.py", "D")
    d.node("hub", "sw", 70, 650, 230, 84, "Web hub", "server/hub.py\nbrowser, phone, planner", "D")
    d.node("cat", "store", 370, 650, 230, 84, "Catalog", "catalog.sqlite", "D")
    d.node("files", "store", 680, 650, 270, 84, "Recording folders", "data.csv, meta.json,\nhealth.jsonl, events.jsonl", "D")
    d.edge("ui", "ctrl", "actions", color="D", pa=-22, pb=-22)
    d.edge("ctrl", "gate", "allowed?", color="D")
    d.edge("ctrl", "stream", "start / stop", "b", "t", color="D")
    d.edge("stream", "link", "setpoints", "l", "t", color="C", pb=-20, via=[(165, 395)])
    d.edge("ctrl", "link", "commands", "l", "t", color="C", pa=4, pb=55, via=[(325, 254), (325, 462), (240, 462)], seg=1, at=0.62)
    d.edge("link", "bus", "packets", color="D")
    d.edge("bus", "eval", "", "t", "b", color="D", via=[(560, 460), (815, 460)])
    d.edge("bus", "rec", "", color="D")
    d.edge("eval", "gate", "health tree", "t", "b", color="D")
    d.edge("gate", "ui", "enabled + reasons", "t", "t", color="D", via=[(815, 186), (185, 186)])
    d.edge("rec", "files", "", "b", "t", color="D")
    d.edge("rec", "cat", "index", "b", "t", color="D", via=[(760, 615), (485, 615)])
    d.edge("bus", "hub", "", "b", "t", color="D", pa=-60, via=[(425, 610), (185, 610)])
    d.edge("hub", "ctrl", "", "r", "l", color="D", dashed=True, pb=26, via=[(350, 692), (350, 276)])
    d.node("gT", "group", 1010, 160, 460, 600, "Teensy firmware", "", "T")
    d.node("comms", "sw", 1040, 210, 180, 80, "comms", "USB frames, dispatch", "C")
    d.node("fctl", "sw", 1270, 210, 170, 80, "control", "1 kHz: states, trips,\ncalibration, tests", "T")
    d.node("fh", "sw", 1040, 360, 180, 70, "health", "13 checks, 20 Hz", "T")
    d.node("can", "sw", 1270, 360, 170, 70, "can_motor", "MIT pack / unpack", "M")
    d.node("disp", "sw", 1040, 500, 180, 70, "display", "OLED", "T")
    d.node("cfg", "data", 1270, 500, 170, 70, "config.h", "pins, rates, trips", "T")
    d.node("motor", "hw", 1270, 650, 170, 84, "BM-24", "CAN id 0x02", "M")
    d.edge("comms", "fctl", "commands", color="T")
    d.edge("fctl", "can", "", "b", "t", kind="bi", color="M", la="frame / tick", lb="reply")
    d.edge("fh", "comms", "health", "t", "b", color="C")
    d.edge("fctl", "fh", "counters", "l", "r", color="T", pa=24, via=[(1245, 274), (1245, 395)], seg=1)
    d.edge("fh", "disp", "", "b", "t", color="T")
    d.edge("can", "motor", "CAN", "r", "r", kind="bi", color="M", via=[(1458, 395), (1458, 692)])
    d.edge("link", "comms", "USB 2 Mbps", "l", "t", kind="bi", color="C", pb=80, via=[(54, 538), (54, 146), (1210, 146)], seg=2, at=0.8)
    d.note(40, 784, "Everything the UI can do goes UI to Controller to Gating to Link. The web hub and other devices (dashed) enter at the same Controller, with the same gating.")
    return d.save("02_software_map")


def control_cascade():
    d = D(1500, 590, "Control cascade", "Three nested loops. One CAN frame per millisecond, one current loop at 20 kHz.")
    d.legend(32, 92, [("sw", "computation"), ("hw", "hardware loop"), ("data", "packet"), ("decision", "safety check"), ("line", "flow")])
    d.node("gPC", "group", 40, 140, 420, 400, "Laptop, 200 Hz", "", "D")
    d.node("src", "data", 66, 196, 180, 70, "Setpoint source", "waveform, recording,\nslider, planner", "D")
    d.node("clip", "sw", 270, 196, 170, 70, "Clip and blend in", "end stops, 0.6 s blend", "D")
    d.node("spk", "data", 150, 340, 220, 64, "SetpointPacket", "seq, position, velocity", "C")
    d.edge("src", "clip", "", color="D")
    d.edge("clip", "spk", "", "b", "t", color="D")
    d.node("gT", "group", 500, 140, 560, 400, "Teensy, 1 kHz interrupt", "", "T")
    d.node("mode", "sw", 526, 196, 150, 64, "Mode", "hold, follow, test", "T")
    d.node("slew", "sw", 700, 196, 150, 64, "Slew limit", "2300 °/s", "T")
    d.node("ramp", "sw", 876, 196, 160, 64, "Gain ramp", "5% to 100% in 0.8 s", "T")
    d.node("integ", "sw", 876, 306, 160, 64, "Integral and Tff", "leaky, clamp 4 Nm", "T")
    d.node("safe", "decision", 520, 286, 260, 140, "Trip?", "speed, stall, current,\nswitch, CAN, laptop,\nend stop", "S")
    d.node("pack", "data", 790, 440, 240, 60, "MIT frame", "p, v, kp, kd, torque", "M")
    d.edge("spk", "mode", "", "r", "l", color="C", via=[(490, 372), (490, 228)])
    d.edge("mode", "slew", "", color="T")
    d.edge("slew", "ramp", "", color="T")
    d.edge("ramp", "integ", "", "b", "t", color="T")
    d.edge("integ", "pack", "", "b", "t", color="T")
    d.edge("safe", "pack", "rest if tripped", "b", "l", color="S")
    d.node("gM", "group", 1100, 140, 370, 400, "Motor, 20 kHz", "", "M")
    d.node("foc", "hw", 1126, 196, 318, 84, "FOC current loop", "torque = kp (p* - p) + kd (v* - v) + t_ff", "M")
    d.node("rep", "data", 1150, 350, 270, 60, "Reply", "id, p, v, current", "M")
    d.edge("pack", "foc", "CAN, 1 kHz", "r", "l", color="M", via=[(1080, 470), (1080, 238)], seg=1)
    d.edge("foc", "rep", "", "b", "t", color="M")
    d.edge("rep", "safe", "position, speed, current", "b", "b", color="M", pa=60, via=[(1345, 522), (650, 522)], at=0.55)
    d.edge("rep", "src", "telemetry, 200 Hz", "b", "b", color="C", pa=-60, via=[(1225, 560), (156, 560)], at=0.5)
    return d.save("03_control_cascade")


def state_machine():
    d = D(1400, 660, "Controller states", "What the Teensy is doing (CS_* in protocol.h) and what moves it between states.")
    d.legend(32, 92, [("state", "state"), ("line", "command or event"), ("dash", "automatic")])
    d.node("REST", "state", 80, 150, 240, 64, "Resting", "motor off, wheel free", "T")
    d.node("TRIPPED", "state", 1080, 150, 240, 64, "Tripped", "latched until Clear trip", "S")
    d.node("HOLD", "state", 80, 310, 1240, 64, "Holding", "motor on, servo to the setpoint: the home state while enabled", "T")
    d.edge("REST", "HOLD", "Enable", "b", "t", color="T", pa=-60, pb=-560)
    d.edge("HOLD", "REST", "Disable", "t", "b", color="T", pa=-480, pb=60)
    d.edge("TRIPPED", "REST", "Clear trip", "l", "r", color="S")
    d.edge("HOLD", "TRIPPED", "any trip", "t", "b", color="S", pa=580, pb=0)
    kids = [("FOLLOW", "Following", 80, "setpoint stream, 200 Hz", "stream arrives", "stale or Hold", True),
            ("TEST", "Testing", 400, "step or relay test", "test start", "done", False),
            ("FREESPIN", "Free-spin", 720, "zero torque, backdrivable", "Free-spin", "Hold", False),
            ("CALIB", "Calibrating", 1040, "end stops and zero", "Find end stops", "done", False)]
    for key, name, x, sub, enter, leave, auto in kids:
        d.node(key, "state", x, 500, 280, 64, name, sub, "T")
        cx = x + 140 - 700
        d.edge("HOLD", key, enter, "b", "t", color="T", dashed=auto, pa=cx - 60, pb=-60, at=0.3)
        d.edge(key, "HOLD", leave, "t", "b", color="T", dashed=(key == "TEST"), pa=60, pb=cx + 60, at=0.3)
    d.note(80, 610, "Also from Resting: Free-spin, Find end stops.  Every energised state trips on overspeed, stall, overcurrent, switch opened,")
    d.note(80, 630, "motor CAN lost, past an end stop, calibration failed, interrupt overrun, or the laptop going silent while following.  Disable always goes to Resting.")
    return d.save("04_state_machine")


def health_tree():
    d = D(1500, 610, "Health checks", "23 checks in five groups. The app's rail, the Health page, the OLED and the logs all use these ids.")
    d.legend(32, 92, [("sw", "decided by the Teensy"), ("data", "decided by the laptop"), ("line", "checked after")])
    groups = [
        ("C", "C  Laptop to Teensy link", [("C1", "serial port open"), ("C2", "bytes arriving"), ("C3", "frames decode"), ("C4", "telemetry fresh"), ("C5", "Teensy hears laptop"), ("C6", "firmware health fresh")], "data"),
        ("S", "S  Safety", [("S1", "idle switch"), ("S2", "no trip latched")], "sw"),
        ("M", "M  Motor and CAN", [("M1", "CAN controller"), ("M2", "CAN transmit"), ("M3", "bus activity"), ("M4", "motor replies"), ("M5", "data sane"), ("M6", "current")], "sw"),
        ("T", "T  Teensy", [("T1", "loop timing"), ("T2", "zeroed, end stops"), ("T3", "calibration"), ("T4", "OLED (optional)")], "sw"),
        ("D", "D  Data and services", [("D1", "recorder"), ("D2", "store"), ("D3", "web hub (optional)"), ("D4", "phone (optional)"), ("D5", "UI loop")], "data"),
    ]
    x = 40
    for g, name, nodes, kind in groups:
        w = 274
        d.node(f"g{g}", "group", x, 140, w, 420, name, "", g)
        prev = None
        for i, (nid, lbl) in enumerate(nodes):
            y = 182 + i * 62
            d.node(nid, kind, x + 22, y, w - 44, 42, f"{nid}  {lbl}", "", g)
            if prev:
                d.edge(prev, nid, "", "b", "t", color=g)
            prev = nid
        x += w + 18
    d.note(40, 590, "When something is wrong read left to right: can we talk (C), is anything stopping torque (S), is the motor alive (M), is the controller ready (T), will it be recorded (D).")
    return d.save("05_health_tree")


def root_cause():
    d = D(1700, 940, "Root cause: the motor does not move", "Follow the rail top to bottom. The first row that is not green is where to look.")
    d.legend(32, 92, [("decision", "question"), ("sw", "what to do"), ("line", "answer")])
    cols = [
        ("C", "USB row green?", "C1 to C6", [("C1 red", "pick the Teensy port, re-plug USB"), ("C2 red", "Teensy not running this firmware:\nreset or flash"),
                                             ("C3 red", "frames don't decode:\nprotocol version, cable"), ("C5 red", "Teensy can't hear the laptop")]),
        ("S", "Safety row green?", "S1, S2", [("S1 amber", "close the idle switch"), ("S2 red", "read the trip reason in the rail,\nfix the cause, Clear trip")]),
        ("M", "CAN and Motor rows green?", "M1 to M6", [("M1 red", "bus-off: transceiver, termination,\nwiring"), ("M2 red", "nobody acknowledges:\nmotor unpowered"),
                                                        ("M4 amber", "no reply: 24 V, CAN id\n(Settings, Scan the bus)"), ("M5 red", "frozen data: encoder, power-cycle")]),
        ("T", "Teensy row green?", "T1 to T4", [("T2 amber", "not zeroed: Calibrate page"), ("T3 amber", "calibration running:\nwait or Abort"),
                                                 ("T1 red", "loop overruns: OLED / I2C,\nreport it")]),
    ]
    x = 40
    prev = None
    for g, q, ids, answers in cols:
        qk = f"q{g}"
        d.node(qk, "decision", x + 30, 140, 300, 104, q, ids, g)
        if prev:
            d.edge(prev, qk, "yes", color="N")
        gk = f"a{g}"
        d.node(gk, "group", x, 300, 360, 46 + len(answers) * 88, "The first one that isn't green:", "", g)
        for i, (lbl, txt) in enumerate(answers):
            d.node(f"{g}{i}", "sw", x + 20, 340 + i * 88, 320, 74, lbl, txt, g)
        d.edge(qk, gk, "no", "b", "t", color=g)
        prev = qk
        x += 410
    d.node("qState", "decision", 600, 770, 320, 104, "What state does the rail show?", "", "T")
    d.edge("qT", "qState", "all green", "r", "t", color="N", via=[(1682, 192), (1682, 730), (760, 730)], seg=2, at=0.3)
    d.node("e1", "sw", 80, 784, 420, 76, "Resting", "press Hold. If it drops back, the last event\nin the rail says why", "T")
    d.node("e2", "sw", 1020, 760, 420, 66, "Holding, but no motion", "gains too low for the friction: raise Kp, add Ki", "T")
    d.node("e3", "sw", 1020, 840, 420, 66, "Free-spin", "zero torque by design: press Hold", "T")
    d.edge("qState", "e1", "", "l", "r", color="T")
    d.edge("qState", "e2", "", "r", "l", color="T", via=[(970, 793)])
    d.edge("qState", "e3", "", "r", "l", color="T", via=[(970, 873)])
    return d.save("06_root_cause")


def data_lineage():
    d = D(1500, 620, "Recordings and lineage", "What creates a recording, how playbacks link to their source, and where the files go.")
    d.legend(32, 92, [("phys", "your action"), ("data", "recording"), ("store", "storage"), ("line", "creates")])
    d.node("hand", "phys", 40, 170, 230, 70, "Free-spin and Record", "turn the wheel by hand", "N")
    d.node("r0", "data", 330, 170, 260, 70, "hand-motion", "kind: freespin", "D")
    d.edge("hand", "r0", "", color="D")
    d.node("pb1", "data", 770, 130, 280, 64, "hand-motion_pb01", "kind: playback, parent: hand-motion", "D")
    d.node("pb2", "data", 770, 216, 280, 64, "hand-motion_pb02", "played at half speed", "D")
    d.edge("r0", "pb1", "Play on motor", "r", "l", color="D", via=[(626, 195), (626, 162)], seg=2)
    d.edge("r0", "pb2", "Play at ×0.5", "r", "l", color="D", via=[(626, 215), (626, 248)], seg=2)
    d.node("gen", "phys", 40, 300, 230, 60, "Run a waveform", "sine, chirp, step", "N")
    d.node("r1", "data", 330, 300, 260, 60, "sine", "kind: trajectory", "D")
    d.edge("gen", "r1", "", color="D")
    d.node("tst", "phys", 40, 384, 230, 60, "Step or relay test", "", "N")
    d.node("r2", "data", 330, 384, 260, 60, "step", "kind: test_step, with rise and overshoot", "D")
    d.edge("tst", "r2", "", color="D")
    d.node("cal", "phys", 40, 468, 230, 60, "Find end stops", "", "N")
    d.node("r3", "data", 330, 468, 260, 60, "autocal", "kind: calibration", "D")
    d.edge("cal", "r3", "", color="D")
    d.node("folder", "store", 1110, 140, 360, 250, "One folder per recording",
           "<collection>/<date>/<time>_<kind>_<name>/\n\ndata.csv       samples, 200 Hz\nmeta.json      gains, end stops, results, parent\n"
           "health.jsonl   checks, 1 Hz and every change\nevents.jsonl   firmware events, laptop actions\nvideo.webm     phone (optional)\nimu.csv        phone (optional)", "D", mono_sub=True)
    d.edge("pb1", "folder", "", color="D", via=[(1074, 162)])
    d.edge("pb2", "folder", "", color="D", via=[(1090, 248)])
    d.node("cat", "store", 1110, 450, 360, 90, "Catalog", "names, kinds, parents, pins, tags\nrebuild: python -m steering reindex", "D")
    d.edge("folder", "cat", "", "b", "t", kind="bi", color="D")
    d.note(40, 590, "Every recording carries its own evidence: what was asked (target), what the Teensy sent (setpoint), what happened (position), and the health and events during it.")
    return d.save("07_data_lineage")


def electrical():
    d = D(1500, 600, "Electrical", "Power, signals and pins. The hardware is unchanged from the original build.")
    d.legend(32, 92, [("hw", "board"), ("phys", "physical"), ("line", "signal"), ("bi", "bus")])
    d.colours(32, 120, [("P", "24 V power"), ("M", "CAN"), ("C", "USB"), ("T", "I2C"), ("S", "switch")])
    d.node("psu", "phys", 40, 190, 230, 84, "24 V supply", "15 A, 40 A peak\nfuse for 40 A transients", "P")
    d.node("motor", "hw", 350, 170, 310, 124, "BM-24 actuator", "XT30: minus left, plus right\nCAN JST: CAN_L away from notch\nboard limit 35 A for 200 ms", "M")
    d.edge("psu", "motor", "24 V", color="P")
    d.node("xcvr", "hw", 760, 190, 220, 84, "CAN transceiver", "3.3 V, STBY to GND\n120 ohm at both ends", "M")
    d.edge("motor", "xcvr", "CAN_H, CAN_L", kind="bi", color="M")
    d.node("teensy", "hw", 1080, 150, 380, 220, "Teensy 4.1 (CCM)",
           "pin 30, 31   CAN RX / TX, transceiver\npin 18, 19   I2C SDA / SCL, OLED 0x3C\npin 22       idle switch to GND\npin 13       LED heartbeat\nUSB          laptop", "T", mono_sub=True)
    d.edge("xcvr", "teensy", "CRX3 / CTX3", kind="bi", color="M", pb=-28)
    d.node("oled", "hw", 1090, 450, 170, 64, "OLED 2.42 in", "SSD1309, I2C", "T")
    d.edge("teensy", "oled", "I2C", "b", "t", color="T", pa=-95)
    d.node("sw", "phys", 1290, 450, 170, 64, "Idle switch", "open = idle", "S")
    d.edge("sw", "teensy", "pin 22", "t", "b", color="S", pb=105)
    d.node("usb", "hw", 760, 450, 220, 64, "Laptop USB", "5 V and data", "C")
    d.edge("usb", "teensy", "USB serial", "r", "l", kind="bi", color="C", pb=60, via=[(1030, 482)])
    d.note(40, 360, "Not sensed by the Teensy: bus voltage (motor power is inferred from CAN replies, check M4) and motor temperature.")
    d.note(40, 384, "Fail-safe: a broken switch wire reads idle (pull-up). A lost CAN reply trips to Resting within 200 ms.")
    return d.save("08_electrical")


def calibration():
    d = D(1500, 400, "Finding the end stops", "Runs on the Teensy. Limits are the CAL_* constants in config.h.")
    d.legend(32, 92, [("sw", "stage"), ("decision", "check"), ("line", "next"), ("dash", "retry")])
    stages = [("s1", "Find left stop", "creep at 30 °/s\ntorque ramps 1 to 3.5 Nm"), ("c1", "Real stop?", "still 0.6 s,\nbump 1 Nm"),
              ("s2", "Find right stop", "same, other way"), ("c2", "Real stop?", "and range over 60°"),
              ("go", "Move to centre", "(L + R) / 2 at 40 °/s\nKp 25, Kd 1.5"), ("set", "Settle and zero", "within 3°, still 0.8 s\nzero there")]
    x = 40
    for key, lbl, sub in stages:
        kind = "decision" if key.startswith("c") else "sw"
        d.node(key, kind, x, 150, 214, 110, lbl, sub, "T")
        x += 244
    for a, b in (("s1", "c1"), ("c1", "s2"), ("s2", "c2"), ("c2", "go"), ("go", "set")):
        d.edge(a, b, "yes" if a.startswith("c") else "", color="T")
    d.edge("c1", "s1", "moved: keep going", "b", "b", color="T", dashed=True, via=[(391, 310), (147, 310)])
    d.edge("c2", "s2", "moved", "b", "b", color="T", dashed=True, via=[(879, 310), (635, 310)])
    d.note(40, 360, "Outcome: end stops valid, zero set, holding at 0°. A 25 s timeout per stop or a range under 60° trips (calibration failed). End-stop trips are off while calibrating.")
    return d.save("09_calibration")


def main():
    outs = [f() for f in (system_overview, software_map, control_cascade, state_machine, health_tree, root_cause,
                          data_lineage, electrical, calibration)]
    print("\n".join(str(o) for o in outs))
    if "--png" in sys.argv:
        import cairosvg
        dest = Path(sys.argv[sys.argv.index("--png") + 1]) if len(sys.argv) > sys.argv.index("--png") + 1 else OUT
        dest.mkdir(parents=True, exist_ok=True)
        for o in outs:
            cairosvg.svg2png(url=str(o), write_to=str(dest / o.with_suffix(".png").name), scale=1.0)
        print("png previews written to", dest)


if __name__ == "__main__":
    main()
