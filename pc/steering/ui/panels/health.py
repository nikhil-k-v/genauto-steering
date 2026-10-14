"""Health tab - every node as a TILE (small title above, big coloured box with
the state word and the live reason inside).  Hover a tile: it explains itself
and draws lines to every visible control it gates.  Grouped by letter:
M motor, S safety, T teensy, C comms, D data."""
from __future__ import annotations

import time
from collections import deque

import dearpygui.dearpygui as dpg

from ... import protocol as P
from ...health.gating import ACTIONS, affected_actions
from ...health.model import GROUPS, GROUP_NODES, NODES, STATE_NAMES
from .. import theme as T

TILE_W, TILE_H = 196, 74


class HealthPanel:
    def __init__(self, ui):
        self.ui = ui
        self.app = ui.app
        self.c = ui.app.controller
        self.tags = {}
        self.tiles = {}            # node id -> child_window item (for the overlay)
        self._tile_parts = {}      # node id -> (state_text, reason_text)
        self._themes = {}
        self.log = deque(maxlen=200)
        self.app.bus.subscribe("health_transition", lambda ch: self.log.appendleft((time.strftime("%H:%M:%S"), ch)))
        self._group = "M"

    def _tile_theme(self, state: int):
        if state not in self._themes:
            col = T.STATE_COLOR[state]
            with dpg.theme() as t:
                with dpg.theme_component(dpg.mvChildWindow):
                    dpg.add_theme_color(dpg.mvThemeCol_ChildBg, col)
                    dpg.add_theme_color(dpg.mvThemeCol_Border, col)
                    dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 8)
            self._themes[state] = t
        return self._themes[state]

    def build(self):
        head = dpg.add_text("Each tile is one check. Colour = state. Hover a tile to see what it means, how to fix it, and lines to the controls it gates.", color=T.DIM, wrap=1200)
        T.bind_font(head, "small")
        for g, gd in GROUPS.items():
            dpg.add_spacer(height=4)
            with dpg.group(horizontal=True):
                t = dpg.add_text(f"{g}  {gd.name.upper()}", color=T.TEXT)
                T.bind_font(t, "head")
                q = dpg.add_text(f"  {gd.question}", color=T.DIM)
                T.bind_font(q, "small")
            with dpg.group(horizontal=True):
                for n in GROUP_NODES[g]:
                    with dpg.group():
                        title = dpg.add_text(f"{n.id}  {n.name}", color=T.DIM)
                        T.bind_font(title, "small")
                        with dpg.child_window(width=TILE_W, height=TILE_H, border=True, no_scrollbar=True) as tile:
                            st = dpg.add_text("UNKNOWN", color=T.INK)
                            T.bind_font(st, "tile")
                            rs = dpg.add_text("", color=T.INK, wrap=TILE_W - 16)
                            T.bind_font(rs, "mono_s")
                        self.tiles[n.id] = tile
                        self._tile_parts[n.id] = (st, rs)
                        with dpg.tooltip(tile):
                            acts = affected_actions(n.id) or list(n.affects)
                            blocks = ", ".join(ACTIONS[a][0] if a in ACTIONS else a for a in acts) or "nothing directly"
                            tt = dpg.add_text(f"{n.id} {n.name}  ({'Teensy decides' if n.source == 'fw' else 'PC decides'})", color=T.TEXT)
                            T.bind_font(tt, "head")
                            dpg.add_text(f"OK means: {n.ok_means}", wrap=460)
                            dpg.add_text(f"When not OK: {n.bad_means}", wrap=460, color=T.WARN)
                            dpg.add_text(f"Fix: {n.fix}", wrap=460, color=T.OK)
                            dpg.add_text(f"Gates: {blocks}", wrap=460, color=T.DIM)
        dpg.add_spacer(height=8)
        with dpg.group(horizontal=True):
            with dpg.child_window(width=600, height=190, border=True) as cw:
                dpg.bind_item_theme(cw, T.theme("readout"))
                T.section("Firmware counters")
                self.tags["fw"] = T.mono_text("", wrap=580)
                T.section("Link counters")
                self.tags["link"] = T.mono_text("", wrap=580)
            with dpg.child_window(width=-1, height=190, border=True) as cw2:
                dpg.bind_item_theme(cw2, T.theme("readout"))
                T.section("Transitions (also data/logs/health-*.jsonl)")
                self.tags["log"] = [T.mono_text("", wrap=0) for _ in range(8)]
                for l in self.tags["log"]:
                    T.bind_font(l, "mono_s")

    def select_group(self, g):
        self._group = g

    def on_resize(self, w, h):
        tw = max(140, min(TILE_W, (w - 40) // 6 - 8))
        for nid, tile in self.tiles.items():
            dpg.configure_item(tile, width=tw)
            dpg.configure_item(self._tile_parts[nid][1], wrap=tw - 16)

    def refresh(self):
        tree = self.c.live.tree
        for n in NODES:
            s = tree.nodes[n.id]
            st, rs = self._tile_parts[n.id]
            word = STATE_NAMES[s.state]
            if n.optional and s.state == P.HS_BLOCKED:
                word = "OFF"
            dpg.set_value(st, word)
            dpg.set_value(rs, s.reason[:60])
            dpg.bind_item_theme(self.tiles[n.id], self._tile_theme(s.state))
            ink = T.INK if s.state != P.HS_UNKNOWN else (200, 204, 214)
            dpg.configure_item(st, color=ink); dpg.configure_item(rs, color=ink)
        fw = self.c.live.health_fw
        if fw:
            dpg.set_value(self.tags["fw"], f"ctrl {P.CS_NAMES.get(fw.ctrl_state)} | trip {P.TRIP_NAMES.get(fw.trip_code)} | calib {P.CAL_NAMES.get(fw.calib_stage)}\n"
                                           f"motor replies {fw.can_rx_motor_hz} Hz (last {fw.motor_age_ms} ms) | other ids {fw.can_rx_other_hz} Hz\n"
                                           f"CAN {['active', 'warning', 'passive', 'BUS-OFF'][min(fw.can_bus_state, 3)]} TEC {fw.can_tec} REC {fw.can_rec}\n"
                                           f"loop {fw.loop_hz} Hz | overruns {fw.isr_overruns} | PC packet age {fw.pc_hb_age_ms} ms")
        ls = self.app.link.stats
        dpg.set_value(self.tags["link"], f"{'open' if ls.port_open else 'closed'} {ls.port_error}\nbytes {ls.bytes_in} | frames {ls.frames_ok} ({ls.frames_hz:.0f}/s) | crc err {ls.crc_errors} | sync err {ls.sync_errors} | drops {ls.drops}\ntx {ls.tx_frames} (err {ls.tx_errors}) | unknown {ls.unknown_packets}")
        for i, line in enumerate(self.tags["log"]):
            if i < len(self.log):
                ts, ch = self.log[i]
                dpg.set_value(line, f"{ts}  {ch['node']} {ch['from']} -> {ch['to']}  {ch['reason']}")
                dpg.configure_item(line, color=T.BAD if ch["to"] == "FAIL" else T.WARN if ch["to"] == "BLOCKED" else T.TEXT)
            else:
                dpg.set_value(line, "")
