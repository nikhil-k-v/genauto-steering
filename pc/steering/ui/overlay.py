"""
ui/overlay.py - literal lines between a control and the system rows it depends on.

Hover any gated control: one line per rail row it needs, leaving the control's
left edge and ending on that row.  Green = that row is fine for this action,
red = that row is what blocks it (the row's reason line says why).  The rows
are outlined in the same colour.

Hover a check in the Health tab: lines to every visible control it gates.

Drawn as a bus: one trunk from the control, one branch per row, so lines never
pile on top of each other.  Branch colour = that row's verdict for this action
(green fine, amber/red = blocking, same colour as the row's dot).  Nothing is
drawn when nothing is hovered.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import dearpygui.dearpygui as dpg

from .. import protocol as P
from ..health.gating import required_nodes
from ..health.model import RANK
from . import theme as T
from .rail import row_for_node



class Overlay:
    def __init__(self, ui):
        self.ui = ui
        self.c = ui.app.controller
        self.force = None          # (item, action) drawn as if hovered (screenshots)

    def build(self):
        self.dl = dpg.add_viewport_drawlist(front=True, tag="overlay")

    @staticmethod
    def _rect(item) -> Optional[Tuple[float, float, float, float]]:
        try:
            a, b = dpg.get_item_rect_min(item), dpg.get_item_rect_max(item)
        except Exception:
            return None
        if b[0] - a[0] < 1:
            return None
        return (a[0], a[1], b[0], b[1])

    def _line(self, pts, col):
        dpg.draw_polyline(pts, color=col, thickness=1.6, parent=self.dl)

    def refresh(self, gate, rail, node_rows: Dict[str, int]):
        dpg.delete_item(self.dl, children_only=True)
        rail.highlight = {}
        tree = self.c.live.tree

        hovered = self.force
        if hovered is None:
            for item, action in gate.bindings.items():
                if dpg.does_item_exist(item) and dpg.is_item_hovered(item):
                    hovered = (item, action)
                    break
        if hovered:
            self._control_to_rows(hovered, gate, rail, tree)
            return
        for nid, item in node_rows.items():
            if dpg.does_item_exist(item) and dpg.is_item_hovered(item):
                self._node_to_controls(nid, item, gate, rail, tree)
                return

    # control -> rail rows ------------------------------------------------------------------------
    def _control_to_rows(self, hovered, gate, rail, tree):
        item, action = hovered
        r = self._rect(item)
        if not r:
            return
        res = gate.result(action)
        rows: Dict[str, List[str]] = {}
        for nid in required_nodes(action):
            k = row_for_node(nid)
            if k:
                rows.setdefault(k, []).append(nid)
        stubs = []
        for k, nids in rows.items():
            rr = rail.row_rect(k)
            if not rr:
                continue
            blocking = [n for n in nids if n in res.nodes or tree.nodes[n].state == P.HS_FAIL]
            if blocking and not res.ok:
                col = T.STATE_COLOR[max((tree.nodes[n].state for n in blocking), key=lambda st: RANK[st])]
                if col == T.IDLE:
                    col = T.WARN
            else:
                col = T.OK
            stubs.append((self._row_y(rr), rr, k, col))
        if not stubs:
            return
        self._bus(r, stubs, rail)
        dpg.draw_rectangle((r[0] - 3, r[1] - 3), (r[2] + 3, r[3] + 3), color=T.OK if res.ok else T.BAD,
                           thickness=1.6, rounding=6, parent=self.dl)

    @staticmethod
    def _row_y(rr):
        return (rr[1] + rr[3]) / 2 if (rr[3] - rr[1]) < 34 else rr[1] + 14

    def _bus(self, r, stubs, rail):
        """One trunk from the control, one branch per row.

        Rail controls: the trunk runs down the rail's left margin and each branch
        lands on that row's status dot.  Page controls: the trunk runs in the gap
        between rail and page, branches land on the row's right end.
        """
        edge = rail.right_edge()
        in_rail = r[0] < edge
        cy = (r[1] + r[3]) / 2
        ys = [y for y, *_ in stubs]
        worst = T.BAD if any(c == T.BAD for *_, c in stubs) else T.WARN if any(c == T.WARN for *_, c in stubs) else T.OK
        if in_rail:
            tx = 9.0
            self._line([(r[0], cy), (tx, cy)], worst)
        else:
            tx = edge + 8
            self._line([(r[0], cy), (tx, cy)], worst)
        self._line([(tx, min(ys + [cy])), (tx, max(ys + [cy]))], worst)
        for y, rr, k, col in stubs:
            if in_rail:
                self._line([(tx, y), (rr[0] - 1, y)], col)
            else:
                self._line([(tx, y), (rr[2] + 4, y)], col)
                dpg.draw_circle((rr[2] + 4, y), 3, fill=col, color=col, parent=self.dl)
            rail.highlight[k] = col

    # health check -> controls ----------------------------------------------------------------------
    def _node_to_controls(self, nid, item, gate, rail, tree):
        tr = self._rect(item)
        if not tr:
            return
        col = T.OK if tree.nodes[nid].state == P.HS_OK else T.STATE_COLOR[tree.nodes[nid].state]
        ctrls = []
        for it, action in gate.bindings.items():
            if nid in required_nodes(action) and dpg.does_item_exist(it) and dpg.is_item_visible(it):
                r = self._rect(it)
                if r:
                    ctrls.append(r)
        edge = rail.right_edge()
        tx = edge + 8
        cy = (tr[1] + tr[3]) / 2
        if ctrls:
            ys = [(r[1] + r[3]) / 2 for r in ctrls]
            self._line([(tr[0], cy), (tx, cy)], col)
            self._line([(tx, min(ys + [cy])), (tx, max(ys + [cy]))], col)
            for r, y in zip(ctrls, ys):
                end = r[2] + 4 if r[2] <= edge else r[0] - 4
                self._line([(tx, y), (end, y)], col)
                dpg.draw_rectangle((r[0] - 3, r[1] - 3), (r[2] + 3, r[3] + 3), color=col, thickness=1.6, rounding=6,
                                   parent=self.dl)
        k = row_for_node(nid)
        if k:
            rail.highlight[k] = col
