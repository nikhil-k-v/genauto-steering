"""
ui/rail.py - the system rail on the left of the window.

    ┌──────────────────────┐
    │ [port      ][Connect]│
    │                      │
    │ Holding              │   controller state, in words
    │ Holding the angle.   │   what it means / why it tripped
    │ +25.5°               │   the wheel, big
    │ target +25.0°        │
    │                      │
    │ [ Hold ][Free-spin ] │   mode (segmented: one is always the current one)
    │ [     Stop motor   ] │   red only when there is something to stop
    │                      │
    │ ● Laptop             │   the signal chain, drawn as one line:
    │ │ USB        399 Hz  │   the line is coloured by the link it stands for,
    │ ● Teensy    1000 Hz  │   so a break shows exactly where it is
    │ │ CAN       1000 Hz  │
    │ ● Motor      −0.2 A  │
    │   M5 encoder frozen  │   <- only rows that are not OK get a reason line
    │                      │
    │ ● Safety      armed  │
    │ ○ Web hub       off  │
    │                      │
    │ 16:21 state → HOLD   │   last event
    └──────────────────────┘

Hover a chain row: its checks.  Click: Health tab at that row.
`row_rect(key)` / `row_for_node(nid)` let the overlay draw lines from a
control to the rows it depends on.
"""
from __future__ import annotations

import time
from typing import Dict, Optional, Tuple

import dearpygui.dearpygui as dpg

from .. import protocol as P
from ..health.model import NODE_BY_ID, RANK
from ..link import list_serial_ports
from . import theme as T
from .safe import safe, toast

RAIL_W = 300
PAD = 20
INNER = RAIL_W - 2 * PAD

Rect = Tuple[float, float, float, float]

# key, label, nodes, kind  (None = gap; "link" rows sit on the line between two components)
ROWS = [
    ("laptop", "Laptop", ("D1", "D2", "D5"), "node"),
    ("usb", "USB", ("C1", "C2", "C3", "C4", "C5", "C6"), "link"),
    ("teensy", "Teensy", ("T1", "T2", "T3", "T4"), "node"),
    ("can", "CAN", ("M1", "M2", "M3"), "link"),
    ("motor", "Motor", ("M4", "M5", "M6"), "node"),
    None,
    ("safety", "Safety", ("S1", "S2"), "node"),
    ("hub", "Web hub", ("D3", "D4"), "node"),
]
ROW_OF: Dict[str, str] = {nid: r[0] for r in ROWS if r for nid in r[2]}
ROW_DEF = {r[0]: r for r in ROWS if r}

STATE_LINE = {
    P.CS_REST: "Motor off. The wheel turns freely.",
    P.CS_HOLD: "Holding the commanded angle.",
    P.CS_TRAJ: "Following a stream from the laptop.",
    P.CS_TEST: "Running a tuning test on the Teensy.",
    P.CS_FREESPIN: "No torque. Turn the wheel by hand.",
    P.CS_CALIB: "Finding the end stops.",
    P.CS_TRIPPED: "Tripped.",
}


def row_for_node(nid: str) -> Optional[str]:
    return ROW_OF.get(nid)


def row_state(tree, nodes) -> Tuple[int, Optional[str], bool]:
    """(state, worst node id or None, all-optional-off)."""
    worst, wid, off = P.HS_OK, None, False
    for nid in nodes:
        s = tree.nodes[nid].state
        if NODE_BY_ID[nid].optional and s == P.HS_BLOCKED:
            if nid == nodes[0]:
                off = True
            continue
        if RANK[s] > RANK[worst]:
            worst, wid = s, nid
    return worst, wid, off


class Rail:
    def __init__(self, ui):
        self.ui = ui
        self.app = ui.app
        self.c = ui.app.controller
        self.rects: Dict[str, Rect] = {}
        self.highlight: Dict[str, tuple] = {}     # row key -> colour (overlay)
        self.hover: Optional[str] = None
        self.tags: Dict[str, int] = {}
        self._chain_h = 300

    # ---- build ----------------------------------------------------------------------------------
    def build(self, parent):
        g, c = self.ui.gate, self.c
        with dpg.child_window(tag="rail", width=RAIL_W, border=False, parent=parent, no_scrollbar=True, pos=(0, 0),
                              always_use_window_padding=True) as rail:
            dpg.bind_item_theme(rail, T.theme("rail"))
            with dpg.group(horizontal=True, horizontal_spacing=6):
                ports = list_serial_ports()
                items = ["sim"] + [p[0] for p in ports]
                default = "sim" if self.ui.sim else (self.app.settings.last_port or (items[1] if len(items) > 1 else "sim"))
                self.tags["port"] = dpg.add_combo(items, default_value=default, width=INNER - 112)
                with dpg.item_handler_registry() as h:
                    dpg.add_item_clicked_handler(callback=safe(self._refresh_ports))
                dpg.bind_item_handler_registry(self.tags["port"], h)
                self.tags["connect"] = T.action("Connect", "secondary", safe(self._connect), 106)

            T.gap(22)
            self.tags["state"] = dpg.add_text("Not connected")
            T.bind_font(self.tags["state"], "state")
            self.tags["state_line"] = dpg.add_text("Choose a port and connect.", color=T.MUTED, wrap=INNER)
            T.bind_font(self.tags["state_line"], "small")
            T.gap(4)
            self.tags["angle"] = dpg.add_text("—")
            T.bind_font(self.tags["angle"], "numeral")
            self.tags["target"] = dpg.add_text("", color=T.MUTED)
            T.bind_font(self.tags["target"], "small")

            T.gap(16)
            seg_w = (INNER - 2) // 2
            with dpg.group(horizontal=True, horizontal_spacing=2, tag="seg"):
                self.tags["hold"] = dpg.add_button(label="Hold", width=seg_w, callback=safe(self._hold))
                self.tags["free"] = dpg.add_button(label="Free-spin", width=seg_w, callback=safe(c.freespin_on))
            for k in ("hold", "free"):
                T.bind_font(self.tags[k], "label")
            g.bind(self.tags["hold"], self._hold_action, {
                "enable": "Turn the motor on and hold the wheel where it is.",
                "freespin_off": "Grip the wheel again where it is now.",
                "hold_here": "Stop following and hold the wheel where it is now."})
            g.bind(self.tags["free"], "freespin_on", "No torque: turn the wheel by hand. Press Record to capture the motion.")
            self.tags["clear"] = T.action("Clear trip", "primary", safe(c.clear_trip), INNER)
            g.bind(self.tags["clear"], "clear_trip", "Unlatch the trip. The motor stays off until you press Hold.")
            dpg.configure_item(self.tags["clear"], show=False)
            self.tags["stop"] = T.action("Stop motor", "danger_idle", safe(lambda: c.emergency_rest("button")), INNER)
            with dpg.tooltip(self.tags["stop"]):
                T.label("Always available. Stops any stream or recording and turns the motor off.", T.INK)

            T.gap(26)
            self.dl = dpg.add_drawlist(width=INNER, height=self._chain_h, tag="chain")
            with dpg.item_handler_registry() as h:
                dpg.add_item_clicked_handler(callback=safe(self._click))
            dpg.bind_item_handler_registry(self.dl, h)

            T.gap(18)
            self.tags["event"] = T.mono_text("", T.MUTED, wrap=INNER, small=True)

        with dpg.window(tag="rail_tip", no_title_bar=True, no_move=True, no_resize=True, autosize=True,
                        no_focus_on_appearing=True, show=False) as tip:
            dpg.bind_item_theme(tip, T.theme("popup"))
            self.tip_title = dpg.add_text("")
            T.bind_font(self.tip_title, "label")
            self.tip_lines = [dpg.add_text("", wrap=420) for _ in range(6)]
            for l in self.tip_lines:
                T.bind_font(l, "small")
            self.tip_foot = T.label("Click to open in Health.", T.MUTED)

    # ---- actions ---------------------------------------------------------------------------------
    def _hold_action(self) -> str:
        cs = self.c.live.ctrl_state
        if cs == P.CS_REST or self.c.live.telemetry is None:
            return "enable"
        if cs == P.CS_FREESPIN:
            return "freespin_off"
        return "hold_here"

    def _hold(self):
        a = self._hold_action()
        {"enable": self.c.enable, "freespin_off": self.c.freespin_off, "hold_here": self.c.hold_here}[a]()

    def _refresh_ports(self, *_):
        dpg.configure_item(self.tags["port"], items=["sim"] + [p[0] for p in list_serial_ports()])

    def _connect(self):
        port = dpg.get_value(self.tags["port"])
        if self.app.link.stats.port_open:
            self.app.link.disconnect()
            return
        if port == "sim":
            from ..sim import SimTransport
            self.app.link.connect(SimTransport())
        else:
            self.app.connect_port(port)
        toast(f"Connecting to {port}")

    # ---- geometry for the overlay ----------------------------------------------------------------------
    def row_rect(self, key: str) -> Optional[Rect]:
        r = self.rects.get(key)
        if not r:
            return None
        ox, oy = dpg.get_item_rect_min(self.dl)
        return (r[0] + ox, r[1] + oy, r[2] + ox, r[3] + oy)

    def right_edge(self) -> float:
        return float(RAIL_W)            # the rail is pinned to the window's left edge

    # ---- per frame ---------------------------------------------------------------------------------------
    def refresh(self):
        self._head()
        self._controls()
        self._chain()
        self._hover_tip()

    def _head(self):
        live = self.c.live
        t, fw = live.telemetry, live.health_fw
        cs = live.ctrl_state
        if not t:
            port_open = self.app.link.stats.port_open
            dpg.set_value(self.tags["state"], "Waiting for the Teensy" if port_open else "Not connected")
            dpg.configure_item(self.tags["state"], color=T.INK)
            dpg.set_value(self.tags["state_line"], "No telemetry yet. See USB below." if port_open else "Choose a port and connect.")
            dpg.configure_item(self.tags["state_line"], color=T.MUTED)
            dpg.set_value(self.tags["angle"], "—")
            dpg.set_value(self.tags["target"], "")
        else:
            dpg.set_value(self.tags["state"], T.CS_WORD.get(cs, "?"))
            dpg.configure_item(self.tags["state"], color=T.CS_COLOR.get(cs, T.INK))
            line, col = STATE_LINE.get(cs, ""), T.MUTED
            if fw and fw.trip_code:
                line, col = f"{P.TRIP_NAMES.get(fw.trip_code, '?').replace('_', ' ').capitalize()}: " + \
                    P.TRIP_EXPLAIN.get(fw.trip_code, ""), T.BAD
            elif cs == P.CS_TRAJ and self.c.streamer.active:
                s = self.app.bus.latest("stream") or {}
                line = f"Following {s.get('name', 'stream')}, {self.c.streamer.progress * 100:.0f}% done."
            elif cs == P.CS_CALIB and fw:
                line = f"Finding the end stops: {P.CAL_NAMES.get(fw.calib_stage, '?').lower()}."
            elif live.last_rejection and time.monotonic() - live.last_rejection_t < 6:
                line, col = live.last_rejection, T.WARN
            dpg.set_value(self.tags["state_line"], line)
            dpg.configure_item(self.tags["state_line"], color=col)
            dpg.set_value(self.tags["angle"], f"{t.position_deg:+.1f}°".replace("-", "−"))
            energized = cs in P.CS_ENABLED and cs != P.CS_FREESPIN
            dpg.set_value(self.tags["target"], f"target {t.setpoint_deg:+.1f}°".replace("-", "−") if energized else "")
        dpg.set_item_label(self.tags["connect"], "Disconnect" if self.app.link.stats.port_open else "Connect")

    def _controls(self):
        live = self.c.live
        cs = live.ctrl_state if live.telemetry else None
        tripped = cs == P.CS_TRIPPED
        dpg.configure_item("seg", show=not tripped)
        dpg.configure_item(self.tags["clear"], show=tripped)
        dpg.bind_item_theme(self.tags["hold"], T.theme("seg_on" if cs == P.CS_HOLD else "seg_off"))
        dpg.bind_item_theme(self.tags["free"], T.theme("seg_on" if cs == P.CS_FREESPIN else "seg_off"))
        live_motor = (cs in P.CS_ENABLED) or self.c.streamer.active
        dpg.bind_item_theme(self.tags["stop"], T.theme("btn_danger" if live_motor else "btn_danger_idle"))
        ev = self.ui.events[0] if self.ui.events else None
        if ev:
            ts, lvl, txt = ev
            dpg.set_value(self.tags["event"], f"{ts[:5]}  {txt}")
            dpg.configure_item(self.tags["event"], color={"bad": T.BAD, "warn": T.WARN}.get(lvl, T.MUTED))

    # ---- the chain ---------------------------------------------------------------------------------------
    def _text(self, pos, text, font, color):
        it = dpg.draw_text(pos, text, color=color, size=T.FONT_SIZE.get(font, 15), parent=self.dl)
        T.bind_font(it, font)
        return it

    def _w(self, text, font) -> float:
        sz = dpg.get_text_size(text, font=T.font(font)) if T.font(font) else None
        return sz[0] if sz else len(text) * 7.5

    def _fit(self, text, font, width) -> str:
        if self._w(text, font) <= width:
            return text
        while text and self._w(text + "…", font) > width:
            text = text[:-1]
        return text.rstrip() + "…"

    def _values(self) -> Dict[str, str]:
        live, tree = self.c.live, self.c.live.tree
        t, fw = live.telemetry, live.health_fw
        ls, rs = self.app.link.stats, self.app.recorder.status
        hub = self.app.server
        v = {}
        v["laptop"] = f"recording {int(rs['elapsed']) // 60}:{int(rs['elapsed']) % 60:02d}" if rs["active"] else ""
        if not ls.port_open:
            v["usb"] = "closed"
        elif tree.nodes["C4"].state == P.HS_OK:
            v["usb"] = f"{ls.telemetry_hz:.0f} Hz"
        else:
            v["usb"] = "silent"
        v["teensy"] = f"loop {fw.loop_hz} Hz" if fw else ""
        if fw:
            v["can"] = "bus-off" if fw.can_bus_state == 3 else (f"{fw.can_rx_motor_hz} Hz" if fw.can_rx_motor_hz else "quiet")
        else:
            v["can"] = ""
        if t and tree.nodes["M4"].state == P.HS_OK:
            v["motor"] = f"{t.current_A:+.1f} A".replace("-", "−")
        elif fw and fw.motor_age_ms == 0xFFFF:
            v["motor"] = "no reply"
        else:
            v["motor"] = ""
        s1 = tree.nodes["S1"].state
        v["safety"] = "tripped" if fw and fw.trip_code else ("armed" if s1 == P.HS_OK else "switch open" if s1 == P.HS_BLOCKED else "")
        on = bool(hub and hub.status["running"])
        if on:
            n = hub.status.get("clients", 0)
            v["hub"] = f"{n} client" + ("" if n == 1 else "s")
        else:
            v["hub"] = "off"
        return v

    def _chain(self):
        dpg.delete_item(self.dl, children_only=True)
        tree = self.c.live.tree
        vals = self._values()
        y = 0.0
        xl, xt = 6.0, 24.0
        layout = []          # (key, y_top, h, state, wid, off)
        for r in ROWS:
            if r is None:
                y += 20
                continue
            key, label, nodes, kind = r
            st, wid, off = row_state(tree, nodes)
            base = 30 if kind == "node" else 26
            h = base + (20 if wid else 0)
            layout.append((key, y, h, st, wid, off, kind, label))
            y += h
        total = y + 4
        if abs(total - self._chain_h) > 1:
            self._chain_h = total
            dpg.configure_item(self.dl, height=int(total))
        self.rects = {}

        # highlight bands (overlay) under everything
        for key, y0, h, st, wid, off, kind, label in layout:
            self.rects[key] = (xl - 6, y0, INNER, y0 + h)
            if key in self.highlight or key == self.hover:
                dpg.draw_rectangle((xt - 6, y0 + 1), (INNER + 4, y0 + h - 1), fill=(255, 255, 255, 190),
                                   color=(0, 0, 0, 0), rounding=4, parent=self.dl)

        # the line: segment between consecutive chain components, coloured by the link row between
        chain = [e for e in layout if e[0] in ("laptop", "usb", "teensy", "can", "motor")]
        dot_y = {e[0]: e[1] + 14 for e in chain if e[6] == "node"}
        for a, link, b in (("laptop", "usb", "teensy"), ("teensy", "can", "motor")):
            e = next(x for x in chain if x[0] == link)
            col = T.STATE_COLOR[e[3]]
            y1, y2 = dot_y[a] + 6, dot_y[b] - 6
            if e[3] == P.HS_UNKNOWN:
                yy = y1
                while yy < y2:
                    dpg.draw_line((xl, yy), (xl, min(yy + 3, y2)), color=col, thickness=2, parent=self.dl)
                    yy += 7
            else:
                dpg.draw_line((xl, y1), (xl, y2), color=col, thickness=2, parent=self.dl)

        for key, y0, h, st, wid, off, kind, label in layout:
            col = T.STATE_COLOR[st]
            if kind == "node":
                cy = y0 + 14
                if off or st == P.HS_UNKNOWN:
                    dpg.draw_circle((xl, cy), 4.5, color=T.FAINT, thickness=1.6, parent=self.dl)
                else:
                    dpg.draw_circle((xl, cy), 5, fill=col, color=col, parent=self.dl)
                self._text((xt, y0 + 4), label, "label", T.INK)
                vf = "small"
                vy = y0 + 6
            else:
                self._text((xt, y0 + 4), label, "small", T.MUTED)
                vf = "small"
                vy = y0 + 4
            v = vals.get(key, "")
            if v:
                self._text((INNER - self._w(v, vf), vy), v, vf, T.MUTED)
            if wid:
                n = tree.nodes[wid]
                txt = self._fit(f"{wid}  {n.reason or NODE_BY_ID[wid].name}", "small", INNER - xt)
                self._text((xt, y0 + h - 22), txt, "small", col)

    # ---- hover / click -------------------------------------------------------------------------------------
    def _row_at(self) -> Optional[str]:
        if not dpg.is_item_hovered(self.dl):
            return None
        mx, my = dpg.get_mouse_pos(local=False)
        ox, oy = dpg.get_item_rect_min(self.dl)
        for k, (x1, y1, x2, y2) in self.rects.items():
            if y1 <= my - oy <= y2:
                return k
        return None

    def _hover_tip(self):
        self.hover = self._row_at()
        if not self.hover:
            dpg.configure_item("rail_tip", show=False)
            return
        key, label, nodes, kind = ROW_DEF[self.hover]
        tree = self.c.live.tree
        dpg.set_value(self.tip_title, label)
        for i, line in enumerate(self.tip_lines):
            if i < len(nodes):
                nid = nodes[i]
                nd, s = NODE_BY_ID[nid], tree.nodes[nid]
                word = "off" if nd.optional and s.state == P.HS_BLOCKED else T.STATE_WORD[s.state]
                dpg.set_value(line, f"{nid}  {nd.name}: {word}" + (f", {s.reason}" if s.reason and s.state != P.HS_OK else ""))
                dpg.configure_item(line, show=True, color=T.INK if s.state == P.HS_OK or nd.optional else T.STATE_COLOR[s.state])
            else:
                dpg.configure_item(line, show=False)
        mx, my = dpg.get_mouse_pos(local=False)
        dpg.configure_item("rail_tip", show=True, pos=(RAIL_W - 8, my + 12))

    def _click(self, *_):
        if self.hover:
            self.ui.goto_health(ROW_DEF[self.hover][2][0])
