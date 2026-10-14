"""Health - every check, grouped by what kind of thing it is about.

    Motor and CAN                         │  M4  Motor replies
    Can the Teensy talk to a sane motor?  │  failed: no reply for 500 ms
      ● M1  CAN controller     ok         │
      ● M2  CAN transmit       ok         │  OK means      ...
      ● M4  Motor replies      no reply   │  If not        ...
    ...                                   │  Fix           ...
                                          │  Blocks        Hold, Free-spin, ...
                                          │
                                          │  Counters (mono)   Recent changes (mono)

Hover a check: lines to the controls it gates.  Click: details on the right.
"""
from __future__ import annotations

import time
from collections import deque

import dearpygui.dearpygui as dpg

from ... import protocol as P
from ... import words as W
from ...health.gating import ACTIONS, affected_actions
from ...health.model import GROUPS, GROUP_NODES, NODES, NODE_BY_ID
from .. import theme as T
from ..safe import safe

DETAIL_W = 420
GROUP_TITLE = {"M": "Motor and CAN", "S": "Safety", "T": "Teensy", "C": "Laptop to Teensy link", "D": "Data and services"}


class HealthPanel:
    def __init__(self, ui):
        self.ui = ui
        self.app = ui.app
        self.c = ui.app.controller
        self.tags = {}
        self.rows = {}             # node id -> selectable (for the overlay)
        self._dots = {}
        self._reason = {}
        self.log = deque(maxlen=200)
        self.app.bus.subscribe("health_transition", lambda ch: self.log.appendleft((time.strftime("%H:%M:%S"), ch)))
        self.sel = "M1"

    def build(self):
        with dpg.group(horizontal=True, horizontal_spacing=28):
            with dpg.child_window(tag="hl_list", border=False, width=-DETAIL_W - 28) as lw:
                dpg.bind_item_theme(lw, T.theme("bare"))
                for g in GROUPS:
                    t = dpg.add_text(f"{GROUP_TITLE[g]}")
                    T.bind_font(t, "head")
                    T.label(GROUPS[g].question)
                    T.gap(2)
                    for n in GROUP_NODES[g]:
                        with dpg.group(horizontal=True, horizontal_spacing=8):
                            d = dpg.add_drawlist(width=14, height=30)
                            self._dots[n.id] = d
                            s = dpg.add_selectable(label=f"{n.id}   {n.name}", width=230, callback=safe(self._click), user_data=n.id)
                            T.tip(s, f"{n.ok_means} Click for details; hover to see which controls it affects.")
                            dpg.bind_item_theme(s, T.theme("row"))
                            self.rows[n.id] = s
                            self._reason[n.id] = T.label("")
                    T.gap(14)
            with dpg.child_window(tag="hl_detail", width=DETAIL_W, border=False) as dw:
                dpg.bind_item_theme(dw, T.theme("bare"))
                self.tags["d_title"] = dpg.add_text("")
                T.bind_font(self.tags["d_title"], "head")
                self.tags["d_state"] = dpg.add_text("", wrap=DETAIL_W - 10)
                self.tags["d_src"] = T.label("")
                T.gap(8)
                with dpg.table(header_row=False, policy=dpg.mvTable_SizingFixedFit, borders_innerH=False):
                    dpg.add_table_column(width_fixed=True, init_width_or_weight=78)
                    dpg.add_table_column(width_fixed=True, init_width_or_weight=DETAIL_W - 96)
                    for key, lab in (("ok", "OK means"), ("bad", "If not"), ("fix", "Fix"), ("gates", "Disables")):
                        with dpg.table_row():
                            T.label(lab)
                            self.tags[f"d_{key}"] = dpg.add_text("", wrap=DETAIL_W - 100)
                T.gap(16)
                t = dpg.add_text("Counters"); T.bind_font(t, "label")
                T.tip(t, "Raw numbers from the Teensy (first block) and from the laptop's USB link (second).")
                self.tags["fw"] = T.mono_text("", T.MUTED, small=True)
                self.tags["link"] = T.mono_text("", T.MUTED, small=True)
                T.gap(12)
                t = dpg.add_text("Recent changes"); T.bind_font(t, "label")
                T.tip(t, "Every check that changed state. The full history is in data/logs/health-*.jsonl and in "
                         "each recording's health.jsonl.")
                self.tags["log"] = [T.mono_text("", T.MUTED, small=True) for _ in range(10)]
                T.gap(12)
                t = dpg.add_text("Events"); T.bind_font(t, "label")
                self.tags["events"] = [T.mono_text("", T.MUTED, small=True, wrap=DETAIL_W - 10) for _ in range(8)]

    def _click(self, sender, app_data, nid):
        self.select(nid)

    def select(self, nid):
        if nid in NODE_BY_ID:
            self.sel = nid

    def select_group(self, g):                 # older call sites
        nodes = GROUP_NODES.get(g)
        if nodes:
            self.sel = nodes[0].id

    def on_resize(self, w, h):
        dpg.configure_item("hl_list", height=h + 30)
        dpg.configure_item("hl_detail", height=h + 30)

    def refresh(self):
        tree = self.c.live.tree
        for n in NODES:
            s = tree.nodes[n.id]
            off = n.optional and s.state == P.HS_BLOCKED
            col = T.STATE_COLOR[s.state]
            d = self._dots[n.id]
            dpg.delete_item(d, children_only=True)
            T.status_mark(d, (7, 15), s.state, off)
            word = "off" if off else (s.reason or W.VERDICT[s.state])
            dpg.set_value(self._reason[n.id], word[:80])
            dpg.configure_item(self._reason[n.id], color=T.MUTED if s.state == P.HS_OK or off or s.state == P.HS_UNKNOWN else col)
            dpg.set_value(self.rows[n.id], n.id == self.sel)

        n = NODE_BY_ID[self.sel]
        s = tree.nodes[n.id]
        off = n.optional and s.state == P.HS_BLOCKED
        dpg.set_value(self.tags["d_title"], f"{n.id}  {n.name}")
        verdict = "off (optional)" if off else W.VERDICT[s.state]
        dpg.set_value(self.tags["d_state"], s.reason or verdict)
        dpg.configure_item(self.tags["d_state"], color=T.INK if s.state == P.HS_OK or off else T.STATE_COLOR[s.state])
        dpg.set_value(self.tags["d_src"], f"{verdict.capitalize()}. " +
                      ("Decided by the Teensy" if n.source == "fw" else "Decided by the laptop") +
                      (". Optional: off is fine." if n.optional else "."))
        dpg.set_value(self.tags["d_ok"], n.ok_means)
        dpg.set_value(self.tags["d_bad"], n.bad_means)
        dpg.set_value(self.tags["d_fix"], n.fix)
        acts = affected_actions(n.id) or list(n.affects)
        dpg.set_value(self.tags["d_gates"], ", ".join(ACTIONS[a][0] if a in ACTIONS else a for a in acts) or "nothing directly")

        fw = self.c.live.health_fw
        if fw:
            dpg.set_value(self.tags["fw"], f"loop {fw.loop_hz} Hz   overruns {fw.isr_overruns}   PC packet age {fw.pc_hb_age_ms} ms\n"
                                           f"motor replies {fw.can_rx_motor_hz} Hz (last {fw.motor_age_ms} ms)   other ids {fw.can_rx_other_hz} Hz\n"
                                           f"CAN {['active', 'warning', 'passive', 'bus-off'][min(fw.can_bus_state, 3)]}   TEC {fw.can_tec}   REC {fw.can_rec}")
        ls = self.app.link.stats
        dpg.set_value(self.tags["link"], f"port {'open' if ls.port_open else 'closed'} {ls.port_error}\n"
                                         f"frames {ls.frames_ok} ({ls.frames_hz:.0f}/s)   crc {ls.crc_errors}   sync {ls.sync_errors}   drops {ls.drops}\n"
                                         f"tx {ls.tx_frames} (err {ls.tx_errors})   unknown {ls.unknown_packets}")
        for i, line in enumerate(self.tags["log"]):
            if i < len(self.log):
                ts, ch = self.log[i]
                to = {"OK": "ok", "BLOCKED": "not ready", "FAIL": "fault", "UNKNOWN": "no data"}.get(ch["to"], ch["to"].lower())
                txt = f"{ts}  {ch['node']:<3} {to:<9} {ch['reason']}"
                dpg.set_value(line, txt if len(txt) <= 60 else txt[:59] + "…")
                dpg.configure_item(line, color=T.BAD if ch["to"] == "FAIL" else T.WARN if ch["to"] == "BLOCKED" else T.MUTED)
            else:
                dpg.set_value(line, "")
        ev = self.ui.events
        for i, line in enumerate(self.tags["events"]):
            if i < len(ev):
                ts, lvl, txt = ev[i]
                dpg.set_value(line, f"{ts}  {txt}")
                dpg.configure_item(line, color={"bad": T.BAD, "warn": T.WARN}.get(lvl, T.MUTED))
            else:
                dpg.set_value(line, "")
