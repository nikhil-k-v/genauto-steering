"""Health tab - the whole tree, one row per node: state, reason, since, what it
means, what it affects, how to fix.  Plus the transition log and the raw
firmware counters (item 1)."""
from __future__ import annotations

import time
from collections import deque

import dearpygui.dearpygui as dpg

from ... import protocol as P
from ...health.gating import ACTIONS, affected_actions
from ...health.model import GROUPS, NODES, NODE_BY_ID, STATE_NAMES
from .. import theme as T


class HealthPanel:
    def __init__(self, ui):
        self.ui = ui
        self.app = ui.app
        self.c = ui.app.controller
        self.tags = {}
        self.log = deque(maxlen=200)
        self.app.bus.subscribe("health_transition", lambda ch: self.log.appendleft((time.strftime("%H:%M:%S"), ch)))
        self._group = "A"

    def build(self):
        with dpg.group(horizontal=True):
            for g in GROUPS:
                b = dpg.add_button(label=f"{g} | {GROUPS[g].name}", callback=lambda s, a, u: self.select_group(u), user_data=g)
                self.tags[f"g_{g}"] = b
        self.tags["question"] = dpg.add_text("", color=T.DIM)
        with dpg.table(header_row=True, resizable=True, borders_innerH=True, borders_outerH=True, borders_innerV=True,
                       policy=dpg.mvTable_SizingStretchProp, tag="health_table"):
            for lbl, w in (("node", 0.6), ("state", 0.5), ("reason", 1.6), ("since", 0.5), ("affects", 1.2)):
                dpg.add_table_column(label=lbl, init_width_or_weight=w)
            self.rows = {}
            for n in NODES:
                with dpg.table_row(tag=f"hrow_{n.id}"):
                    c0 = dpg.add_text(f"{n.id}  {n.name}")
                    c1 = dpg.add_text("")
                    c2 = dpg.add_text("", wrap=0)
                    c3 = dpg.add_text("")
                    acts = affected_actions(n.id) or list(n.affects)
                    c4 = dpg.add_text(", ".join(ACTIONS[a][0] if a in ACTIONS else a for a in acts) or "-", wrap=0)
                    self.rows[n.id] = (c0, c1, c2, c3)
                    with dpg.tooltip(c0):
                        dpg.add_text(f"OK means: {n.ok_means}\n\nWhen bad: {n.bad_means}\n\nFix: {n.fix}\n\nSource: {'Teensy firmware' if n.source == 'fw' else 'PC'}", wrap=480)
        dpg.add_spacer(height=6)
        with dpg.group(horizontal=True):
            with dpg.child_window(width=560, height=220, border=True):
                dpg.add_text("FIRMWARE COUNTERS", color=T.DIM)
                self.tags["fw"] = dpg.add_text("", wrap=540)
                dpg.add_text("LINK COUNTERS", color=T.DIM)
                self.tags["link"] = dpg.add_text("", wrap=540)
            with dpg.child_window(width=-1, height=220, border=True):
                dpg.add_text("TRANSITIONS (also in data/logs/health-*.jsonl)", color=T.DIM)
                self.tags["log"] = [dpg.add_text("", wrap=0) for _ in range(9)]

    def select_group(self, g):
        self._group = g

    def refresh(self):
        tree = self.c.live.tree
        now = time.time()
        for n in NODES:
            s = tree.nodes[n.id]
            c0, c1, c2, c3 = self.rows[n.id]
            dpg.set_value(c1, STATE_NAMES[s.state])
            dpg.configure_item(c1, color=T.STATE_COLOR[s.state])
            dpg.set_value(c2, s.reason)
            age = now - s.since
            dpg.set_value(c3, f"{age:.0f}s" if age < 120 else f"{age / 60:.0f}m")
            dpg.configure_item(f"hrow_{n.id}", show=(n.group == self._group))
        dpg.set_value(self.tags["question"], f"{GROUPS[self._group].name}: {GROUPS[self._group].question}")
        for g in GROUPS:
            st, _ = tree.group_state(g)
            dpg.bind_item_theme(self.tags[f"g_{g}"], T.theme({P.HS_OK: "btn_ok", P.HS_BLOCKED: "btn_warn", P.HS_FAIL: "btn_bad", P.HS_UNKNOWN: "btn_unknown"}[st]) if g != self._group else T.theme("btn_accent"))
        fw = self.c.live.health_fw
        if fw:
            dpg.set_value(self.tags["fw"], f"ctrl {P.CS_NAMES.get(fw.ctrl_state)} | trip {P.TRIP_NAMES.get(fw.trip_code)} | calib {P.CAL_NAMES.get(fw.calib_stage)}\n"
                                           f"motor replies {fw.can_rx_motor_hz} Hz (last {fw.motor_age_ms} ms) | other ids {fw.can_rx_other_hz} Hz\n"
                                           f"CAN bus state {['active', 'warning', 'passive', 'BUS-OFF'][min(fw.can_bus_state, 3)]} TEC {fw.can_tec} REC {fw.can_rec}\n"
                                           f"loop {fw.loop_hz} Hz | overruns {fw.isr_overruns} | PC hb age {fw.pc_hb_age_ms} ms | bridge age {fw.bridge_age_ms} ms")
        ls = self.app.link.stats
        dpg.set_value(self.tags["link"], f"{'open' if ls.port_open else 'closed'} {ls.port_error}\nbytes {ls.bytes_in} | frames {ls.frames_ok} ({ls.frames_hz:.0f}/s) | crc err {ls.crc_errors} | sync err {ls.sync_errors} | drops {ls.drops} | tx {ls.tx_frames} (err {ls.tx_errors}) | unknown {ls.unknown_packets}")
        for i, line in enumerate(self.tags["log"]):
            if i < len(self.log):
                ts, ch = self.log[i]
                dpg.set_value(line, f"{ts}  {ch['node']} {ch['from']} -> {ch['to']}  {ch['reason']}")
                dpg.configure_item(line, color=T.BAD if ch["to"] == "FAIL" else T.WARN if ch["to"] == "BLOCKED" else T.TEXT)
            else:
                dpg.set_value(line, "")
