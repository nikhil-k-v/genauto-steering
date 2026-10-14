#!/usr/bin/env python3
"""
docs/diagrams/gen.py - generates every diagram in docs/diagrams/*.svg.

One consistent visual language (see legend() in every diagram):
  * HARDWARE          sharp rectangle, thick border
  * SOFTWARE          rounded rectangle
  * STORAGE           cylinder
  * PHYSICAL / HUMAN  hexagon
  * DECISION          diamond
  * DATA / SIGNAL     parallelogram
  * STATE             pill
  * links: solid = always on, dashed = optional/future; arrowheads show direction,
    two heads = bidirectional; the label on the line says what flows and how fast.
Colours by group letter: M motor, S safety, T teensy, C comms, D data.

    python docs/diagrams/gen.py            # writes the SVGs next to this file
    python docs/diagrams/gen.py --png      # also renders PNG previews (needs cairosvg)
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent

BG = "#0f1218"
INK = "#e6e9f0"
DIM = "#8a92a4"
LINE = "#5a6278"
COL = {"M": "#a78bfa", "S": "#e85555", "T": "#4eca7a", "C": "#4a8cff", "D": "#f0a44e", "N": "#8a92a4", "X": "#ffd166"}
FONT = "DejaVu Sans, Helvetica, Arial, sans-serif"
MONO = "DejaVu Sans Mono, Menlo, Consolas, monospace"


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class D:
    def __init__(self, w, h, title):
        self.w, self.h, self.title = w, h, title
        self.parts = []
        self.nodes = {}
        self.parts.append(f'<rect width="{w}" height="{h}" fill="{BG}"/>')
        self.parts.append(f'<text x="24" y="34" fill="{INK}" font-family="{FONT}" font-size="20" font-weight="700">{esc(title)}</text>')

    # ---- primitives -------------------------------------------------------------------
    def text(self, x, y, s, size=13, color=INK, anchor="start", weight=400, mono=False):
        for i, line in enumerate(s.split("\n")):
            self.parts.append(f'<text x="{x}" y="{y + i * (size + 4)}" fill="{color}" font-family="{MONO if mono else FONT}" '
                              f'font-size="{size}" font-weight="{weight}" text-anchor="{anchor}">{esc(line)}</text>')

    def _label_block(self, cx, cy, label, sub, color, size=14):
        lines = label.split("\n")
        n = len(lines) + (len(sub.split("\n")) if sub else 0)
        y0 = cy - (n - 1) * 9
        for i, l in enumerate(lines):
            self.text(cx, y0 + i * 18 + 5, l, size, INK, "middle", 700)
        if sub:
            for j, l in enumerate(sub.split("\n")):
                self.text(cx, y0 + (len(lines) + j) * 18 + 5, l, 11, color, "middle", 400, mono=True)

    def node(self, key, kind, x, y, w, h, label, sub="", group="N"):
        c = COL[group]
        cx, cy = x + w / 2, y + h / 2
        if kind == "hw":
            self.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="#161a24" stroke="{c}" stroke-width="3"/>')
        elif kind == "sw":
            self.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="#1a1f2c" stroke="{c}" stroke-width="2"/>')
        elif kind == "state":
            self.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{h / 2}" fill="#1a1f2c" stroke="{c}" stroke-width="2"/>')
        elif kind == "store":
            ry = 9
            self.parts.append(f'<path d="M{x},{y + ry} a{w / 2},{ry} 0 0 0 {w},0 v{h - 2 * ry} a{w / 2},{ry} 0 0 1 -{w},0 z" fill="#1a1f2c" stroke="{c}" stroke-width="2"/>')
            self.parts.append(f'<ellipse cx="{cx}" cy="{y + ry}" rx="{w / 2}" ry="{ry}" fill="#1a1f2c" stroke="{c}" stroke-width="2"/>')
            cy += 6
        elif kind == "phys":
            dx = min(18, h / 2)
            pts = f"{x + dx},{y} {x + w - dx},{y} {x + w},{cy} {x + w - dx},{y + h} {x + dx},{y + h} {x},{cy}"
            self.parts.append(f'<polygon points="{pts}" fill="#1a1f2c" stroke="{c}" stroke-width="2"/>')
        elif kind == "decision":
            pts = f"{cx},{y} {x + w},{cy} {cx},{y + h} {x},{cy}"
            self.parts.append(f'<polygon points="{pts}" fill="#1a1f2c" stroke="{c}" stroke-width="2"/>')
        elif kind == "data":
            s = 14
            pts = f"{x + s},{y} {x + w},{y} {x + w - s},{y + h} {x},{y + h}"
            self.parts.append(f'<polygon points="{pts}" fill="#1a1f2c" stroke="{c}" stroke-width="2"/>')
        elif kind == "group":
            self.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="{c}" fill-opacity="0.07" stroke="{c}" stroke-width="1.5" stroke-dasharray="6 4"/>')
            self.text(x + 14, y + 22, label, 13, c, "start", 700)
            self.nodes[key] = (x, y, w, h)
            return
        self._label_block(cx, cy, label, sub, c, 14 if kind != "decision" else 12)
        self.nodes[key] = (x, y, w, h)

    def _edge_pts(self, a, b, side_a, side_b):
        def pt(n, side):
            x, y, w, h = self.nodes[n]
            return {"l": (x, y + h / 2), "r": (x + w, y + h / 2), "t": (x + w / 2, y), "b": (x + w / 2, y + h)}[side]
        return pt(a, side_a), pt(b, side_b)

    def edge(self, a, b, label="", side_a="r", side_b="l", kind="uni", color=LINE, via=None, label_pos=0.5,
             la="", lb="", label_dy=0, off_a=(0, 0), off_b=(0, 0)):
        """kind: uni (a->b), bi (<->), none; la/lb: small per-direction annotations near each end;
        off_a/off_b shift the end points along the node edge so parallel links don't overlap."""
        p, q = self._edge_pts(a, b, side_a, side_b)
        p = (p[0] + off_a[0], p[1] + off_a[1]); q = (q[0] + off_b[0], q[1] + off_b[1])
        pts = [p] + (via or []) + [q]
        dash = ' stroke-dasharray="7 5"' if color == "dashed" else ""
        if color == "dashed":
            color = LINE
        mid = f'marker-end="url(#ah-{color[1:]})"' if kind in ("uni", "bi") else ""
        ms = f'marker-start="url(#ahr-{color[1:]})"' if kind == "bi" else ""
        self._marker(color)
        d = "M" + " L".join(f"{x},{y}" for x, y in pts)
        self.parts.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2.5"{dash} {ms} {mid}/>')
        if label:
            # place at fraction label_pos of the first-or-longest segment
            seg = max(range(len(pts) - 1), key=lambda i: math.dist(pts[i], pts[i + 1]))
            (x1, y1), (x2, y2) = pts[seg], pts[seg + 1]
            lx, ly = x1 + (x2 - x1) * label_pos, y1 + (y2 - y1) * label_pos + label_dy
            lines = label.split("\n")
            w = max(len(l) for l in lines) * 7 + 14
            h = len(lines) * 15 + 8
            self.parts.append(f'<rect x="{lx - w / 2}" y="{ly - h / 2}" width="{w}" height="{h}" rx="5" fill="#0f1218" stroke="{color}" stroke-width="1"/>')
            for i, l in enumerate(lines):
                self.text(lx, ly - h / 2 + 15 + i * 15, l, 11, INK, "middle", 400, mono=True)
        # per-direction annotations: two stacked lines just below (horizontal) or beside (vertical) the link
        vertical = side_a in ("t", "b")
        if vertical:
            ax, ay = p[0] + 14, (p[1] + q[1]) / 2 + 30
        else:
            ax, ay = min(p[0], q[0]) + 10, p[1] + 20
        if la:
            self.text(ax, ay, la, 10, DIM, "start", mono=True)
        if lb:
            self.text(ax, ay + 14, lb, 10, DIM, "start", mono=True)

    _markers = None

    def _marker(self, color):
        if self._markers is None:
            self._markers = set()
        if color in self._markers:
            return
        self._markers.add(color)
        k = color[1:]
        self.parts.insert(1, f'<defs><marker id="ah-{k}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">'
                             f'<path d="M0,0 L10,5 L0,10 z" fill="{color}"/></marker>'
                             f'<marker id="ahr-{k}" viewBox="0 0 10 10" refX="1" refY="5" markerWidth="8" markerHeight="8" orient="auto">'
                             f'<path d="M10,0 L0,5 L10,10 z" fill="{color}"/></marker></defs>')

    def legend(self, x, y, items):
        """items: list of (kind|'line'|'dash'|'bi', text)"""
        self.parts.append(f'<rect x="{x}" y="{y}" width="{len(items) * 150 + 20}" height="38" rx="8" fill="#141821" stroke="{LINE}" stroke-width="1"/>')
        for i, (kind, txt) in enumerate(items):
            bx = x + 14 + i * 150
            by = y + 10
            if kind == "hw":
                self.parts.append(f'<rect x="{bx}" y="{by}" width="22" height="16" fill="#161a24" stroke="{DIM}" stroke-width="2.5"/>')
            elif kind == "sw":
                self.parts.append(f'<rect x="{bx}" y="{by}" width="22" height="16" rx="6" fill="#1a1f2c" stroke="{DIM}" stroke-width="1.5"/>')
            elif kind == "store":
                self.parts.append(f'<ellipse cx="{bx + 11}" cy="{by + 4}" rx="11" ry="4" fill="#1a1f2c" stroke="{DIM}"/><path d="M{bx},{by + 4} v10 a11,4 0 0 0 22,0 v-10" fill="#1a1f2c" stroke="{DIM}"/>')
            elif kind == "phys":
                self.parts.append(f'<polygon points="{bx + 5},{by} {bx + 17},{by} {bx + 22},{by + 8} {bx + 17},{by + 16} {bx + 5},{by + 16} {bx},{by + 8}" fill="#1a1f2c" stroke="{DIM}"/>')
            elif kind == "decision":
                self.parts.append(f'<polygon points="{bx + 11},{by} {bx + 22},{by + 8} {bx + 11},{by + 16} {bx},{by + 8}" fill="#1a1f2c" stroke="{DIM}"/>')
            elif kind == "data":
                self.parts.append(f'<polygon points="{bx + 5},{by} {bx + 22},{by} {bx + 17},{by + 16} {bx},{by + 16}" fill="#1a1f2c" stroke="{DIM}"/>')
            elif kind == "state":
                self.parts.append(f'<rect x="{bx}" y="{by}" width="22" height="16" rx="8" fill="#1a1f2c" stroke="{DIM}" stroke-width="1.5"/>')
            elif kind == "line":
                self.parts.append(f'<line x1="{bx}" y1="{by + 8}" x2="{bx + 22}" y2="{by + 8}" stroke="{DIM}" stroke-width="2.5"/>')
            elif kind == "dash":
                self.parts.append(f'<line x1="{bx}" y1="{by + 8}" x2="{bx + 22}" y2="{by + 8}" stroke="{DIM}" stroke-width="2.5" stroke-dasharray="5 4"/>')
            elif kind == "bi":
                self.parts.append(f'<line x1="{bx + 3}" y1="{by + 8}" x2="{bx + 19}" y2="{by + 8}" stroke="{DIM}" stroke-width="2.5"/>'
                                  f'<polygon points="{bx},{by + 8} {bx + 6},{by + 4} {bx + 6},{by + 12}" fill="{DIM}"/>'
                                  f'<polygon points="{bx + 22},{by + 8} {bx + 16},{by + 4} {bx + 16},{by + 12}" fill="{DIM}"/>')
            self.text(bx + 30, by + 13, txt, 11, DIM)

    def save(self, name):
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" viewBox="0 0 {self.w} {self.h}" '
               f'font-family="{FONT}">' + "".join(self.parts) + "</svg>")
        (OUT / f"{name}.svg").write_text(svg)
        return OUT / f"{name}.svg"


STD_LEGEND = [("hw", "hardware"), ("sw", "software"), ("store", "storage"), ("phys", "physical / human"),
              ("bi", "two-way link"), ("line", "one-way flow"), ("dash", "optional / future")]


# =====================================================================================
def system_overview():
    d = D(1500, 640, "System overview - components, links, and which status group watches each")
    d.legend(24, 50, STD_LEGEND)
    # row 1: laptop <-> teensy <-> motor
    d.node("laptop", "hw", 40, 160, 280, 130, "LAPTOP", "Python app (Dear PyGui)\nweb hub (FastAPI)", "D")
    d.node("teensy", "hw", 640, 160, 280, 130, "CCM / TEENSY 4.1", "1 kHz control ISR\nhealth · OLED", "T")
    d.node("motor", "hw", 1220, 160, 240, 130, "BM-24 ACTUATOR", "FOC board 20 kHz\ndual absolute encoder\nCAN id 0x02", "M")
    d.edge("laptop", "teensy", "USB serial 2 Mbps\nframes [AB CD len seq .. crc8]", kind="bi", color=COL["C"],
           la="-> setpoints 200 Hz, heartbeat 5 Hz", lb="<- telemetry 200 Hz, health 20 Hz", label_dy=-34)
    d.edge("teensy", "motor", "CAN 1 Mbps\n8-byte MIT frames", kind="bi", color=COL["M"],
           la="-> cmd p v kp kd t @1 kHz", lb="<- reply id p v i", label_dy=-34)
    # physical
    d.node("switch", "phys", 650, 400, 260, 70, "IDLE SWITCH", "pin 22 -> GND, open = IDLE", "S")
    d.edge("switch", "teensy", "armed / idle", "t", "b", kind="uni", color=COL["S"], label_dy=0)
    d.node("wheel", "phys", 1210, 400, 260, 70, "STEERING WHEEL", "clamp-on coupling, floor-braced arm", "N")
    d.edge("motor", "wheel", "torque", "b", "t", kind="uni", color=LINE)
    d.node("oled", "hw", 980, 330, 170, 50, "OLED 2.42\"", "I2C 18/19", "T")
    d.edge("teensy", "oled", "", "b", "l", kind="uni", color=COL["T"], via=[(780, 355)])
    d.node("psu", "phys", 1210, 500, 260, 60, "24 V SUPPLY", "15 A rated, 40 A peak", "N")
    d.edge("psu", "wheel", "", "t", "b", kind="none", color=LINE) if False else None
    d.edge("psu", "motor", "24 V", "l", "l", kind="uni", color="#e85555", via=[(1180, 530), (1180, 225)], label_pos=0.5)
    # phone / planner
    d.node("phone", "hw", 40, 400, 280, 70, "PHONE (browser)", "camera · IMU · time sync", "D")
    d.edge("phone", "laptop", "Wi-Fi HTTP + WebSocket", "t", "b", kind="bi", color=COL["D"], la="^ telemetry, health", lb="v video, IMU, time sync", label_dy=-26)
    d.node("planner", "hw", 40, 500, 280, 60, "ROS 2 / AGX ORIN (future)", "steering angle at 200 Hz", "D")
    d.edge("planner", "laptop", "setpoint stream", "r", "r", kind="uni", color="dashed", via=[(420, 530), (420, 225)], label_pos=0.5)
    # status groups note
    d.text(620, 600, "Status groups:  M motor & CAN   S safety   T teensy controller   C comms (PC-Teensy)   D data & services", 12, DIM, "start", mono=True)
    return d.save("01_system_overview")


def software_map():
    d = D(1500, 760, "Software map - who talks to whom (laptop app and Teensy firmware)")
    d.legend(24, 50, STD_LEGEND)
    d.node("gL", "group", 40, 125, 930, 590, "LAPTOP  pc/steering", "", "D")
    d.node("ui", "sw", 70, 160, 220, 80, "UI (Dear PyGui)", "ui/app.py · panels/\nsystem strip · gating lines", "D")
    d.node("ctrl", "sw", 340, 160, 220, 80, "Controller", "core/controller.py\ngated actions", "D")
    d.node("gate", "sw", 640, 160, 290, 80, "Gating + Health model", "health/gating.py · model.py\n24 nodes, 20 actions", "D")
    d.node("stream", "sw", 340, 300, 220, 70, "Streamer", "control/streamer.py @200 Hz", "D")
    d.node("eval", "sw", 640, 300, 290, 70, "Health evaluator", "health/evaluator.py @10 Hz", "D")
    d.node("link", "sw", 70, 440, 220, 70, "Link", "link.py: framing, 5 Hz heartbeat\nreconnect, counters", "C")
    d.node("bus", "sw", 340, 440, 220, 70, "Bus", "bus.py pub/sub\ntelemetry · health · event", "D")
    d.node("rec", "sw", 640, 440, 290, 70, "Recorder", "data/recorder.py\ncsv + health.jsonl + events.jsonl", "D")
    d.node("hub", "sw", 70, 590, 220, 90, "Web hub", "server/hub.py\nFastAPI + WebSocket\nbrowser UI, phone, planner", "D")
    d.node("cat", "store", 340, 590, 220, 90, "catalog.sqlite", "data/store.py index", "D")
    d.node("files", "store", 640, 590, 290, 90, "recordings/<coll>/<date>/..", "data.csv, meta.json,\nhealth.jsonl, events.jsonl, video", "D")
    d.edge("ui", "ctrl", "", kind="uni", color=COL["D"])
    d.edge("ctrl", "gate", "can(action)?", kind="uni", color=COL["D"])
    d.edge("ctrl", "stream", "", "b", "t", kind="uni", color=COL["D"])
    d.edge("stream", "link", "SetpointPacket", "l", "t", kind="uni", color=COL["C"], via=[(180, 335)])
    d.edge("ctrl", "link", "commands", "l", "t", kind="uni", color=COL["C"], via=[(315, 200), (315, 410), (200, 410)], label_pos=0.5)
    d.edge("link", "bus", "packets", kind="uni", color=COL["D"])
    d.edge("bus", "eval", "", "t", "b", kind="uni", color=COL["D"], via=[(450, 400), (785, 400)])
    d.edge("bus", "rec", "", kind="uni", color=COL["D"])
    d.edge("eval", "gate", "tree", "t", "b", kind="uni", color=COL["D"])
    d.edge("gate", "ui", "disable + reasons", "t", "t", kind="uni", color=COL["D"], via=[(785, 145), (180, 145)], label_pos=0.5)
    d.edge("rec", "files", "", "b", "t", kind="uni", color=COL["D"])
    d.edge("rec", "cat", "", "b", "t", kind="uni", color=COL["D"], via=[(785, 555), (450, 555)])
    d.edge("bus", "hub", "", "b", "t", kind="uni", color=COL["D"], via=[(450, 540), (180, 540)])
    d.edge("hub", "ctrl", "remote actions\n(same gating)", "r", "l", kind="uni", color="dashed", via=[(325, 635), (325, 215)], label_pos=0.5)
    # Teensy
    d.node("gT", "group", 1000, 125, 470, 590, "TEENSY  firmware/teensy/src", "", "T")
    d.node("comms", "sw", 1020, 160, 180, 80, "comms", "USB frames\ndispatch", "C")
    d.node("fctl", "sw", 1260, 160, 170, 80, "control", "ISR 1 kHz: states, trips\ncalibration, tests", "T")
    d.node("fh", "sw", 1020, 300, 180, 80, "health", "13 nodes @20 Hz", "T")
    d.node("can", "sw", 1260, 300, 170, 80, "can_motor", "MIT pack/unpack\ncounters, scanner", "M")
    d.node("disp", "sw", 1020, 440, 180, 70, "display", "OLED tiles + dial", "T")
    d.node("cfg", "data", 1300, 440, 150, 70, "config.h", "pins, rates,\ntrips, CAL_*", "T")
    d.node("motor", "hw", 1260, 590, 170, 80, "BM-24", "CAN 0x02", "M")
    d.edge("comms", "fctl", "cmd / setpoint", kind="uni", color=COL["C"])
    d.edge("fctl", "can", "", "r", "r", kind="bi", color=COL["M"], via=[(1450, 200), (1450, 340)], la="", lb="")
    d.text(1265, 262, "v cmd/tick   ^ sample", 10, DIM, "start", mono=True)
    d.edge("fh", "comms", "HealthPacket", "t", "b", kind="uni", color=COL["C"])
    d.edge("fctl", "fh", "counters", "b", "r", kind="uni", color=COL["T"], via=[(1345, 272), (1220, 272), (1220, 340)], label_pos=0.5)
    d.edge("fh", "disp", "", "b", "t", kind="uni", color=COL["T"])
    d.edge("can", "motor", "CAN 1 Mbps", "b", "t", kind="bi", color=COL["M"], via=[(1465, 340), (1465, 630)]) if False else None
    d.edge("can", "motor", "CAN 1 Mbps", "l", "l", kind="bi", color=COL["M"], via=[(1235, 340), (1235, 630)], label_pos=0.5)
    d.edge("link", "comms", "USB 2 Mbps", "l", "t", kind="bi", color=COL["C"], via=[(55, 475), (55, 112), (1110, 112)], label_pos=0.5)
    d.text(40, 745, "Everything the UI can do goes UI -> Controller -> Gating -> Link; the hub and future devices enter at the same Controller.", 12, DIM, mono=True)
    return d.save("02_software_map")


def control_cascade():
    d = D(1500, 520, "Control cascade - three nested loops, one CAN frame per millisecond")
    d.legend(24, 50, [("sw", "software loop"), ("hw", "hardware loop"), ("data", "signal"), ("line", "flow"), ("decision", "safety check")])
    d.node("gPC", "group", 40, 120, 420, 360, "PC  200 Hz", "", "D")
    d.node("src", "data", 70, 170, 160, 70, "setpoint source", "generator · recording\nslider · planner", "D")
    d.node("clip", "sw", 260, 170, 170, 70, "clip + blend-in", "limits, 0.6 s cosine", "D")
    d.node("spk", "data", 160, 300, 200, 60, "SetpointPacket", "seq, pos, vel_ff @200 Hz", "C")
    d.edge("src", "clip", "", kind="uni", color=COL["D"])
    d.edge("clip", "spk", "", "b", "t", kind="uni", color=COL["D"], via=[(345, 280), (260, 280)])
    d.node("gT", "group", 500, 120, 560, 360, "TEENSY  1 kHz ISR", "", "T")
    d.node("mode", "sw", 530, 170, 150, 60, "mode resolve", "HOLD / FOLLOW / ..", "T")
    d.node("slew", "sw", 700, 170, 150, 60, "slew limit", "2300 deg/s", "T")
    d.node("ramp", "sw", 870, 170, 160, 60, "gain ramp", "5% -> 100% / 0.8 s", "T")
    d.node("integ", "sw", 870, 270, 160, 60, "integral + Tff", "leaky, clamp 4 Nm", "T")
    d.node("safe", "decision", 530, 260, 200, 90, "trips?", "overspeed · stall · current\nswitch · CAN · PC · limit", "S")
    d.node("pack", "data", 760, 380, 240, 60, "MIT frame", "p v kp kd t  (8 bytes)", "M")
    d.edge("spk", "mode", "", kind="uni", color=COL["C"])
    d.edge("mode", "slew", "", kind="uni", color=COL["T"])
    d.edge("slew", "ramp", "", kind="uni", color=COL["T"])
    d.edge("ramp", "integ", "", "b", "t", kind="uni", color=COL["T"])
    d.edge("integ", "pack", "", "b", "t", kind="uni", color=COL["T"], via=[(950, 360), (880, 360)])
    d.edge("safe", "pack", "REST (0xFD)\nif tripped", "b", "l", kind="uni", color=COL["S"], via=[(630, 410)])
    d.node("gM", "group", 1100, 120, 370, 360, "MOTOR  20 kHz", "", "M")
    d.node("foc", "hw", 1130, 170, 310, 90, "FOC current loop", "t = kp(p*-p) + kd(v*-v) + t_ff", "M")
    d.node("rep", "data", 1150, 320, 270, 60, "reply", "id, p, v, i  (8 bytes)", "M")
    d.edge("pack", "foc", "CAN 1 kHz", "r", "l", kind="uni", color=COL["M"], via=[(1080, 410), (1080, 215)])
    d.edge("foc", "rep", "", "b", "t", kind="uni", color=COL["M"])
    d.edge("rep", "safe", "position, velocity, current", "l", "l", kind="uni", color=COL["M"], via=[(1100, 350), (1100, 470), (505, 470), (505, 305)], label_pos=0.5)
    d.edge("rep", "src", "telemetry 200 Hz", "b", "b", kind="uni", color=COL["C"], via=[(1285, 460), (150, 460)], label_pos=0.5)
    return d.save("03_control_cascade")


def state_machine():
    d = D(1400, 620, "Firmware controller states (CS_*) and what moves between them")
    d.legend(24, 50, [("state", "state"), ("line", "command / event"), ("dash", "automatic")])
    d.node("REST", "state", 80, 130, 220, 64, "REST", "MOSFETs off, wheel free", "T")
    d.node("TRIPPED", "state", 1100, 130, 220, 64, "TRIPPED", "latched until CLEAR_TRIP", "S")
    d.node("HOLD", "state", 80, 270, 1240, 64, "HOLD", "FOC on, servo to the setpoint (slider / hold-here) - the home state while enabled", "T")
    d.edge("REST", "HOLD", "ENABLE  (switch armed, CAN alive, no trip)", "b", "t", kind="uni", color=COL["T"], off_a=(-50, 0), off_b=(140 - 700, 0), label_dy=0, label_pos=0.5)
    d.edge("HOLD", "REST", "DISABLE", "t", "b", kind="uni", color=COL["T"], off_a=(250 - 700, 0), off_b=(60, 0), label_pos=0.5)
    d.edge("TRIPPED", "REST", "CLEAR_TRIP", "t", "t", kind="uni", color=COL["S"], via=[(1210, 100), (190, 100)], label_pos=0.5)
    d.edge("HOLD", "TRIPPED", "any trip", "t", "b", kind="uni", color=COL["S"], off_a=(510, 0))
    kids = [("FOLLOW", 80, "setpoint stream 200 Hz", "stream fresh (mode AUTO/TRAJ)", "stream stale 250 ms / HOLD_HERE", True),
            ("TEST", 400, "step / relay on the Teensy", "TEST_START (zeroed)", "test done / PC lost", False),
            ("FREESPIN", 720, "zero torque, backdrivable", "FREESPIN_ON", "FREESPIN_OFF (re-grip, gain ramp)", False),
            ("CALIB", 1040, "end stops + zero", "CALIB_START / GO_CENTER_ZERO", "CAL_DONE: zero at centre", False)]
    for name, x, sub, enter, leave, auto in kids:
        d.node(name, "state", x, 440, 280, 64, name, sub, "T")
        cx = x + 140
        d.edge("HOLD", name, enter, "b", "t", kind="uni", color="dashed" if auto else COL["T"], off_a=(cx - 45 - 700, 0), off_b=(-45, 0), label_dy=-30)
        d.edge(name, "HOLD", leave, "t", "b", kind="uni", color=COL["T"] if name != "TEST" else "dashed", off_a=(45, 0), off_b=(cx + 45 - 700, 0), label_dy=30)
    d.text(80, 560, "Also from REST: FREESPIN_ON -> FREESPIN, CALIB_START -> CALIB.  Every enabled state goes to TRIPPED on: overspeed, stall, overcurrent,", 12, DIM, mono=True)
    d.text(80, 580, "switch opened, motor CAN lost, past end stop, calibration failed, ISR overrun, PC lost while FOLLOWING.  DISABLE from any state -> REST.", 12, DIM, mono=True)
    return d.save("04_state_machine")


def health_tree():
    d = D(1500, 560, "Health tree - 24 checks in 5 groups; the UI tiles, the OLED boxes and the logs all use these ids")
    d.legend(24, 50, [("sw", "node (Teensy decides)"), ("data", "node (PC decides)"), ("line", "'checked after'")])
    groups = [
        ("M", "MOTOR & CAN", [("M1", "CAN controller"), ("M2", "CAN transmit"), ("M3", "bus activity"), ("M4", "motor replies"), ("M5", "data sane"), ("M6", "current")], "sw"),
        ("S", "SAFETY", [("S1", "idle switch"), ("S2", "no trip latched")], "sw"),
        ("T", "TEENSY", [("T1", "loop timing"), ("T2", "zeroed + limits"), ("T3", "calibration"), ("T4", "CCM screen")], "sw"),
        ("C", "COMMS", [("C1", "port open"), ("C2", "bytes arriving"), ("C3", "frames decode"), ("C4", "telemetry fresh"), ("C5", "Teensy hears PC"), ("C6", "fw health fresh")], "data"),
        ("D", "DATA", [("D1", "recorder"), ("D2", "store"), ("D3", "web hub"), ("D4", "phone"), ("D5", "UI loop")], "data"),
    ]
    x = 40
    for g, name, nodes, kind in groups:
        w = 280
        d.node(f"g{g}", "group", x, 110, w, 420, f"{g}  {name}", "", g)
        prev = None
        for i, (nid, lbl) in enumerate(nodes):
            y = 150 + i * 60
            d.node(nid, kind, x + 20, y, w - 40, 44, f"{nid}  {lbl}", "", g)
            if prev:
                d.edge(prev, nid, "", "b", "t", kind="uni", color=COL[g])
            prev = nid
        x += w + 15
    d.text(40, 552, "Read left to right when something fails: C (can we talk?) -> S (is anything blocking torque?) -> M (is the motor alive?) -> T (is the controller ready?) -> D (will it be recorded?)", 12, DIM, mono=True)
    return d.save("05_health_tree")


def root_cause():
    d = D(1700, 800, "Root cause: 'the motor does not move' - read the status tiles left to right")
    d.legend(24, 50, [("decision", "question (a tile)"), ("sw", "what to do"), ("line", "answer")])
    cols = [
        ("C", "COMMS tile green?", "C1..C6", [("C1 red", "pick the Teensy port, re-plug USB"), ("C2 red", "Teensy not running this firmware: reset / flash"),
                                            ("C3 red", "frames don't decode: protocol version, cable"), ("C5 red", "Teensy can't hear us: USB TX side / CRC")]),
        ("S", "SAFETY tile green?", "S1 S2", [("S1 amber", "close the idle switch (pin 22)"), ("S2 red", "read the trip name + explanation,\nfix the cause, press Clear trip")]),
        ("M", "MOTOR tile green?", "M1..M6", [("M1 red", "bus-off: transceiver, termination, wiring"), ("M2 red", "nobody ACKs: motor unpowered"),
                                            ("M4 amber", "no reply: 24 V, CAN id (Settings > Scan bus)"), ("M5 red", "frozen / NaN: encoder, power-cycle")]),
        ("T", "TEENSY tile green?", "T1..T4", [("T2 amber", "not zeroed: Calibration tab"), ("T3 amber", "calibration running: wait or abort"),
                                            ("T1 red", "loop overruns: OLED / I2C, report")]),
    ]
    x = 40
    prev = None
    for g, q, ids, answers in cols:
        qk = f"q{g}"
        d.node(qk, "decision", x, 120, 320, 90, q, ids, g)
        if prev:
            d.edge(prev, qk, "yes", kind="uni", color=LINE)
        spine_x = x + 24
        for i, (lbl, txt) in enumerate(answers):
            ak = f"{g}{i}"
            y = 250 + i * 86
            d.node(ak, "sw", x + 40, y, 330, 70, lbl, txt, g)
            d.edge(qk, ak, "", "b", "l", kind="uni", color=COL[g], via=[(x + 160, 228), (spine_x, 228), (spine_x, y + 35)])
        d.text(x + 60, 232, "no:", 11, DIM, mono=True)
        prev = qk
        x += 400
    d.node("qS", "decision", 560, 640, 300, 90, "controller state?", "big text, top left of the app", "T")
    d.edge("qT", "qS", "all green", "r", "t", kind="uni", color=LINE, via=[(1660, 165), (1660, 610), (710, 610)], label_pos=0.5)
    d.node("e1", "sw", 80, 650, 420, 70, "REST", "press Enable; if it bounces back, the Events pane\nshows the Teensy's reason", "T")
    d.node("e2", "sw", 920, 620, 420, 70, "HOLD but no motion", "gains too low for the friction: raise Kp, add Ki\n(the slider only moves HOLD)", "T")
    d.node("e3", "sw", 920, 700, 420, 70, "FREE-SPIN", "zero torque by design -> Re-grip", "T")
    d.edge("qS", "e1", "", "l", "r", kind="uni", color=COL["T"])
    d.edge("qS", "e2", "", "r", "l", kind="uni", color=COL["T"], via=[(900, 685), (900, 655)])
    d.edge("qS", "e3", "", "r", "l", kind="uni", color=COL["T"], via=[(900, 685), (900, 735)])
    return d.save("06_root_cause")


def data_lineage():
    d = D(1500, 560, "Data: recordings, playback lineage and where files live")
    d.legend(24, 50, [("phys", "human action"), ("data", "recording"), ("store", "storage"), ("line", "creates")])
    d.node("hand", "phys", 40, 140, 220, 70, "Free-spin + Record", "turn the wheel by hand", "T")
    d.node("r0", "data", 320, 140, 260, 70, "hand-motion", "kind=freespin", "D")
    d.edge("hand", "r0", "", kind="uni", color=COL["D"])
    d.node("pb1", "data", 660, 100, 260, 60, "hand-motion_pb01", "kind=playback  parent=hand-motion", "D")
    d.node("pb2", "data", 660, 180, 260, 60, "hand-motion_pb02", "x0.5 speed", "D")
    d.edge("r0", "pb1", "Play back", "r", "l", kind="uni", color=COL["D"], via=[(620, 175), (620, 130)])
    d.edge("r0", "pb2", "", "r", "l", kind="uni", color=COL["D"], via=[(620, 175), (620, 210)])
    d.node("gen", "phys", 40, 260, 220, 60, "Run generator", "sine / chirp / step", "T")
    d.node("r1", "data", 320, 260, 260, 60, "sine", "kind=trajectory", "D")
    d.edge("gen", "r1", "", kind="uni", color=COL["D"])
    d.node("tst", "phys", 40, 340, 220, 60, "Step / relay test", "", "T")
    d.node("r2", "data", 320, 340, 260, 60, "step", "kind=test_step: rise, overshoot, settle", "D")
    d.edge("tst", "r2", "", kind="uni", color=COL["D"])
    d.node("cal", "phys", 40, 420, 220, 60, "Auto-calibrate", "", "T")
    d.node("r3", "data", 320, 420, 260, 60, "autocal", "kind=calibration", "D")
    d.edge("cal", "r3", "", kind="uni", color=COL["D"])
    d.node("folder", "store", 1000, 110, 460, 250, "recordings/<collection>/<YYYY-MM-DD>/<HHMMSS>_<kind>_<name>/",
           "data.csv          samples @200 Hz\nmeta.json         gains, limits, metrics, health summary, parent\nhealth.jsonl      snapshots 1 Hz + transitions\nevents.jsonl      firmware events + PC actions\nvideo.webm        phone (optional)\nimu.csv           phone (optional)", "D")
    d.edge("pb1", "folder", "", kind="uni", color=COL["D"])
    d.edge("pb2", "folder", "", kind="uni", color=COL["D"])
    d.node("cat", "store", 1000, 410, 460, 90, "catalog.sqlite", "index: name, kind, parent, pinned, tags, playback_count\nrebuildable: python -m steering reindex", "D")
    d.edge("folder", "cat", "", "b", "t", kind="bi", color=COL["D"])
    d.text(40, 530, "Every recording carries its own evidence: what was commanded (target), what the Teensy sent (setpoint), what happened (position), and the health + events during it.", 12, DIM, mono=True)
    return d.save("07_data_lineage")


def electrical():
    d = D(1500, 560, "Electrical system - power, signals, pins")
    d.legend(24, 50, [("hw", "board"), ("phys", "physical"), ("line", "signal"), ("bi", "bus")])
    d.node("psu", "phys", 40, 150, 220, 80, "24 V DC SUPPLY", "15 A cont, 40 A peak\nfuse for 40 A transients", "N")
    d.node("motor", "hw", 340, 130, 300, 120, "BM-24 ACTUATOR", "XT30: - left, + right\nCAN JST: CAN_L away from notch\nboard protection 35 A / 200 ms", "M")
    d.edge("psu", "motor", "24 V  (red thick)", kind="uni", color="#e85555")
    d.node("xcvr", "hw", 740, 150, 220, 80, "CAN TRANSCEIVER", "3.3 V, STBY -> GND\n120 ohm at both ends", "M")
    d.edge("motor", "xcvr", "CAN_H / CAN_L\n1 Mbps", kind="bi", color=COL["M"])
    d.node("teensy", "hw", 1060, 110, 400, 220, "TEENSY 4.1  (CCM)", "pin 30 CRX3 / 31 CTX3  -> transceiver\npin 18 SDA / 19 SCL   -> OLED 0x3C\npin 22 idle switch     -> GND (INPUT_PULLUP)\npin 13 LED heartbeat\nUSB 2 Mbps             -> laptop", "T")
    d.edge("xcvr", "teensy", "CRX3 30 / CTX3 31", kind="bi", color=COL["M"])
    d.node("oled", "hw", 1100, 400, 160, 60, "OLED 2.42\"", "SSD1309 I2C", "T")
    d.edge("teensy", "oled", "I2C 18/19", "b", "t", kind="uni", color=COL["T"], off_a=(-80, 0))
    d.node("sw", "phys", 1300, 400, 160, 60, "IDLE SWITCH", "SPST, open = IDLE", "S")
    d.edge("sw", "teensy", "pin 22", "t", "b", kind="uni", color=COL["S"], off_b=(120, 0))
    d.node("usb", "hw", 740, 400, 220, 60, "LAPTOP USB", "5 V + data", "C")
    d.edge("usb", "teensy", "USB serial", "r", "l", kind="bi", color=COL["C"], via=[(1000, 430), (1000, 220)])
    d.text(40, 320, "Not sensed by the Teensy: bus voltage (motor power is inferred from CAN replies, node M4); motor temperature.", 12, DIM, mono=True)
    d.text(40, 345, "Fail-safe polarity: a broken switch wire reads IDLE (pull-up); a lost CAN reply trips to REST within 200 ms.", 12, DIM, mono=True)
    return d.save("08_electrical")


def calibration():
    d = D(1500, 360, "End-stop calibration - firmware routine (CAL_* in config.h)")
    d.legend(24, 50, [("sw", "stage"), ("decision", "check"), ("line", "next"), ("dash", "retry")])
    stages = [("s1", "SEEK LEFT", "torque mode, creep at 30 deg/s\nramp 1 -> 3.5 Nm"), ("c1", "CONFIRM LEFT", "still 0.6 s + bump 1 Nm\nmoved > 2 deg? friction"),
              ("s2", "SEEK RIGHT", "same, other way"), ("c2", "CONFIRM RIGHT", "range > 60 deg?"),
              ("go", "GO CENTRE", "(L+R)/2 at 40 deg/s\nKp 25 Kd 1.5"), ("set", "SETTLE + ZERO", "within 3 deg, still 0.8 s\nzero + software offset -> 0 deg exactly")]
    x = 40
    for key, lbl, sub in stages:
        kind = "decision" if key.startswith("c") else "sw"
        d.node(key, kind, x, 130, 220, 100, lbl, sub, "T")
        x += 245
    for a, b in (("s1", "c1"), ("c1", "s2"), ("s2", "c2"), ("c2", "go"), ("go", "set")):
        d.edge(a, b, "", kind="uni", color=COL["T"])
    d.edge("c1", "s1", "moved: keep seeking", "b", "b", kind="uni", color="dashed", via=[(395, 270), (150, 270)], label_pos=0.5)
    d.edge("c2", "s2", "moved", "b", "b", kind="uni", color="dashed", via=[(885, 270), (640, 270)], label_pos=0.5)
    d.text(40, 320, "Outcome: limits_valid, zeroed, state HOLD at 0 deg. Timeouts (25 s per seek) and a range < 60 deg trip to CALIB_FAILED. Limit trips are off during calibration.", 12, DIM, mono=True)
    return d.save("09_calibration")


def main():
    outs = [f() for f in (system_overview, software_map, control_cascade, state_machine, health_tree, root_cause,
                          data_lineage, electrical, calibration)]
    print("\n".join(str(o) for o in outs))
    if "--png" in sys.argv:
        import cairosvg
        for o in outs:
            cairosvg.svg2png(url=str(o), write_to=str(o.with_suffix(".png")), scale=1.3)
        print("png previews written")


if __name__ == "__main__":
    main()
