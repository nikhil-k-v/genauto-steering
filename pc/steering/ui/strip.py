"""
ui/strip.py - the system strip: a live diagram of the components at the top of
the window, each drawn as a TILE (small title above, big coloured body with
the current state inside) and joined by connectors (annotated two-way
arrows for the comm links).

    LAPTOP APP  <==USB==>  CCM / TEENSY  <==CAN==>  MOTOR
        |                      |
    WEB HUB · PHONE         SAFETY

Tile colour = health of the group it stands for (M motor, S safety, T teensy,
C comms, D data).  Click a tile -> Health tab, that group.  Hover -> node list.
The strip also exposes `rect(group)` so the connection overlay can draw lines
from a control to the tiles it depends on.
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

import dearpygui.dearpygui as dpg

from .. import protocol as P
from ..health.model import GROUP_NODES, GROUPS, NODE_BY_ID
from . import theme as T

STRIP_H = 215

Rect = Tuple[float, float, float, float]


def _fill(state: int):
    return {P.HS_OK: (62, 190, 110), P.HS_BLOCKED: (236, 160, 64), P.HS_FAIL: (226, 76, 76),
            P.HS_UNKNOWN: (62, 68, 84)}[state]


def _fill_dim(state: int):
    c = _fill(state)
    return tuple(int(v * 0.55) for v in c)


class SystemStrip:
    def __init__(self, ui):
        self.ui = ui
        self.app = ui.app
        self.c = ui.app.controller
        self.rects: Dict[str, Rect] = {}       # group letter -> body rect (local coords)
        self.hover: Optional[str] = None
        self.highlight: set = set()            # groups to outline (connection overlay)
        self.width = 1200

    def build(self):
        self.dl = dpg.add_drawlist(width=self.width, height=STRIP_H, tag="strip")
        with dpg.item_handler_registry() as h:
            dpg.add_item_clicked_handler(callback=self._click)
        dpg.bind_item_handler_registry(self.dl, h)
        with dpg.window(tag="strip_tip", no_title_bar=True, no_move=True, no_resize=True, autosize=True,
                        no_focus_on_appearing=True, show=False):
            self.tip_title = dpg.add_text("", color=T.TEXT)
            T.bind_font(self.tip_title, "head")
            self.tip_lines = [dpg.add_text("", wrap=440) for _ in range(8)]
            for l in self.tip_lines:
                T.bind_font(l, "mono")
            self.tip_foot = dpg.add_text("", color=T.DIM, wrap=440)
            T.bind_font(self.tip_foot, "small")

    def set_width(self, w: int):
        self.width = max(900, w)
        dpg.configure_item(self.dl, width=self.width)

    def rect(self, group: str) -> Optional[Rect]:
        r = self.rects.get(group)
        if not r:
            return None
        ox, oy = dpg.get_item_rect_min(self.dl)
        return (r[0] + ox, r[1] + oy, r[2] + ox, r[3] + oy)

    # ---- drawing ---------------------------------------------------------------------------
    def _tile(self, group: str, x: float, y: float, w: float, h: float, title: str, big: str, small: str,
              state: int, big_size: int = 24):
        fill = _fill(state)
        outline = (255, 255, 255) if group in self.highlight else (0, 0, 0, 0)
        dpg.draw_text((x, y - 16), title, color=T.DIM, size=12, parent=self.dl)
        dpg.draw_rectangle((x, y), (x + w, y + h), fill=fill, color=fill, rounding=8, parent=self.dl)
        if group in self.highlight:
            dpg.draw_rectangle((x - 3, y - 3), (x + w + 3, y + h + 3), color=outline, thickness=2, rounding=10, parent=self.dl)
        ink = T.INK if state != P.HS_UNKNOWN else (200, 204, 214)
        dpg.draw_text((x + 12, y + 8), big, color=ink, size=big_size, parent=self.dl)
        dpg.draw_text((x + 12, y + h - 22), small, color=tuple(int(v * 0.85) for v in ink) if state != P.HS_UNKNOWN else ink,
                      size=13, parent=self.dl)
        self.rects[group] = (x, y, x + w, y + h)

    def _link(self, x1: float, x2: float, y: float, label: str, sub: str, state: int, group: str):
        col = _fill(state)
        dpg.draw_line((x1, y), (x2, y), color=col, thickness=4, parent=self.dl)
        # two-way arrow heads
        for (xa, d) in ((x1, 1), (x2, -1)):
            dpg.draw_triangle((xa, y), (xa + d * 14, y - 8), (xa + d * 14, y + 8), fill=col, color=col, parent=self.dl)
        mx = (x1 + x2) / 2
        bw, bh = 150, 58
        self._tile(group, mx - bw / 2, y - bh / 2, bw, bh, "", label, sub, state, big_size=20)

    def refresh(self):
        dpg.delete_item(self.dl, children_only=True)
        live, tree = self.c.live, self.c.live.tree
        t, fw, cfg = live.telemetry, live.health_fw, live.config
        ls = self.app.link.stats
        rs = self.app.recorder.status
        W = self.width
        y = 44
        h = 70
        gap = 200
        tile_w = (W - 2 * gap - 40) / 3
        x0 = 20

        gM, _ = tree.group_state("M"); gS, _ = tree.group_state("S"); gT, _ = tree.group_state("T")
        gC, _ = tree.group_state("C"); gD, _ = tree.group_state("D")

        # --- laptop --------------------------------------------------------------------
        big = f"REC {rs['elapsed']:.0f}s" if rs["active"] else "IDLE"
        hub = self.app.server
        small = ("hub on" if hub and hub.status["running"] else "hub off") + \
                f" | ui {tree.nodes['D5'].reason}" + (f" | {rs['samples']} rows" if rs["active"] else "")
        self._tile("D", x0, y, tile_w, h, "LAPTOP APP  (D: recorder, store, hub, phone, ui)", big, small, gD)

        # --- USB link -------------------------------------------------------------------
        x1 = x0 + tile_w
        x2 = x1 + gap
        if ls.port_open and tree.nodes["C4"].state == P.HS_OK:
            lb = f"{ls.telemetry_hz:.0f} Hz"
            sub = f"rt {fw.pc_hb_age_ms if fw else '--'} ms | drop {ls.drops}"
        elif ls.port_open:
            lb, sub = "SILENT", tree.nodes["C2"].reason[:18]
        else:
            lb, sub = "NO LINK", "connect"
        self._link(x1, x2, y + h / 2, lb, sub, gC, "C")
        dpg.draw_text((x1 + gap / 2 - 60, y - 16), "USB 2 Mbps  (C: comms)", color=T.DIM, size=12, parent=self.dl)

        # --- teensy ---------------------------------------------------------------------
        x3 = x2
        cs = live.ctrl_state
        big = P.CS_NAMES.get(cs, "?") if t else "NO DATA"
        small = (f"loop {fw.loop_hz} Hz | " if fw else "") + ("zeroed" if cfg and cfg.zeroed else "not zeroed") + \
                (" | limits" if cfg and cfg.limits_valid else " | no limits")
        self._tile("T", x3, y, tile_w, h, "CCM / TEENSY  (T: loop, zero, calibration, screen)", big, small, gT)

        # --- CAN link --------------------------------------------------------------------
        x4 = x3 + tile_w
        x5 = x4 + gap
        can_state = max((tree.nodes[n].state for n in ("M1", "M2", "M3")), key=lambda s: {P.HS_OK: 0, P.HS_UNKNOWN: 1, P.HS_BLOCKED: 2, P.HS_FAIL: 3}[s])
        if fw:
            lb = f"{fw.can_rx_motor_hz} Hz" if fw.can_rx_motor_hz else ("BUS-OFF" if fw.can_bus_state == 3 else "QUIET")
            sub = f"TEC {fw.can_tec} REC {fw.can_rec}"
        else:
            lb, sub = "--", ""
        self._link(x4, x5, y + h / 2, lb, sub, can_state, "M")
        dpg.draw_text((x4 + gap / 2 - 62, y - 16), "CAN 1 Mbps  (M1-M3: bus)", color=T.DIM, size=12, parent=self.dl)

        # --- motor ------------------------------------------------------------------------
        if t and tree.nodes["M4"].state == P.HS_OK:
            big = f"{t.position_deg:+.1f} deg"
            small = f"{t.current_A:+.1f} A | {t.velocity_deg_s:+.0f} deg/s"
        elif fw and fw.motor_age_ms == 0xFFFF:
            big, small = "NO REPLY", "unpowered / wrong id?"
        else:
            big, small = "--", tree.nodes["M4"].reason[:28]
        self._tile("M", x5, y, tile_w, h, "MOTOR  (M4-M6: replies, data, current)", big, small, gM)

        # --- safety (below teensy) ---------------------------------------------------------
        sy = y + h + 36
        sw, sh = 230, 52
        sx = x3 + 10
        if fw and fw.trip_code:
            big, small = "TRIPPED", P.TRIP_NAMES.get(fw.trip_code, "")[:22]
        elif tree.nodes["S1"].state == P.HS_OK:
            big, small = "ARMED", "switch closed"
        elif tree.nodes["S1"].state == P.HS_BLOCKED:
            big, small = "IDLE", "switch open"
        else:
            big, small = "--", ""
        dpg.draw_line((sx + 30, y + h), (sx + 30, sy), color=_fill_dim(gS), thickness=3, parent=self.dl)
        self._tile("S", sx, sy, sw, sh, "SAFETY  (S: idle switch, trips)", big, small, gS, big_size=18)

        # --- hub / phone (below laptop) -----------------------------------------------------
        hx = x0 + 10
        hub_on = bool(hub and hub.status["running"])
        ph = tree.nodes["D4"]
        big = "HUB ON" if hub_on else "HUB OFF"
        small = ("phone synced" if ph.state == P.HS_OK else "no phone") if hub_on else "web ui / phone / planner"
        st = P.HS_OK if hub_on and ph.state != P.HS_FAIL else (P.HS_FAIL if ph.state == P.HS_FAIL else P.HS_UNKNOWN)
        dpg.draw_line((hx + 30, y + h), (hx + 30, sy), color=_fill_dim(st), thickness=3, parent=self.dl)
        self._tile("D3", hx, sy, sw, sh, "WEB HUB / PHONE  (D3, D4)", big, small, st, big_size=18)

        self._hover()

    # ---- interaction ----------------------------------------------------------------------
    def _group_at(self, mx, my) -> Optional[str]:
        ox, oy = dpg.get_item_rect_min(self.dl)
        lx, ly = mx - ox, my - oy
        for g, (x1, y1, x2, y2) in self.rects.items():
            if x1 <= lx <= x2 and y1 <= ly <= y2:
                return g
        return None

    def _hover(self):
        if not dpg.is_item_hovered(self.dl):
            self.hover = None
            dpg.configure_item("strip_tip", show=False)
            return
        mx, my = dpg.get_mouse_pos(local=False)
        g = self._group_at(mx, my)
        self.hover = g
        if g is None:
            dpg.configure_item("strip_tip", show=False)
            return
        tree = self.c.live.tree
        letter = "D" if g == "D3" else g
        gd = GROUPS[letter]
        dpg.set_value(self.tip_title, f"{gd.name}: {gd.question}")
        nodes = GROUP_NODES[letter]
        if g == "D3":
            nodes = [NODE_BY_ID["D3"], NODE_BY_ID["D4"]]
        for i, line in enumerate(self.tip_lines):
            if i < len(nodes):
                n = nodes[i]
                s = tree.nodes[n.id]
                dpg.set_value(line, f"{n.id:<3} {T.STATE_WORD[s.state]:<8} {n.name:<22} {s.reason}")
                dpg.configure_item(line, color=T.STATE_COLOR[s.state] if s.state != P.HS_OK else T.TEXT)
            else:
                dpg.set_value(line, "")
        dpg.set_value(self.tip_foot, "click for details, fixes and what each node blocks")
        dpg.configure_item("strip_tip", show=True, pos=(min(mx + 14, self.width - 470), my + 18))

    def _click(self, sender, app_data):
        g = self.hover
        if g:
            self.ui.goto_health("D" if g == "D3" else g)
