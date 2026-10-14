"""
ui/overlay.py - literal lines between a control and the status tiles it depends on.

A viewport-level drawlist sits over everything.  Each frame:
  * if a gated control is hovered: outline it, and draw a line from it to every
    system-strip tile its action depends on - green when that tile's nodes are
    satisfied, red when they are blocking, with the blocking node ids written
    on the line.
  * if a Health-tab node tile is hovered: lines the other way, to every control
    that depends on that node.
Nothing is drawn when nothing is hovered, so the lines never clutter the UI.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import dearpygui.dearpygui as dpg

from .. import protocol as P
from ..health.gating import required_nodes
from ..health.model import NODE_BY_ID
from . import theme as T


class Overlay:
    def __init__(self, ui):
        self.ui = ui
        self.c = ui.app.controller
        self.force = None          # (item, action) to draw as if hovered (screenshots / tutorials)

    def build(self):
        self.dl = dpg.add_viewport_drawlist(front=True, tag="overlay")

    def _rect(self, item) -> Optional[Tuple[float, float, float, float]]:
        try:
            a, b = dpg.get_item_rect_min(item), dpg.get_item_rect_max(item)
        except Exception:
            return None
        return (a[0], a[1], b[0], b[1])

    def refresh(self, gate, strip, node_tiles: Dict[str, int]):
        dpg.delete_item(self.dl, children_only=True)
        strip.highlight = set()
        tree = self.c.live.tree

        # ---- control -> tiles --------------------------------------------------------
        hovered = self.force
        if hovered is None:
            for item, action in gate.bindings.items():
                if dpg.does_item_exist(item) and dpg.is_item_hovered(item):
                    hovered = (item, action)
                    break
        if hovered:
            item, action = hovered
            r = self._rect(item)
            if r:
                res = gate.result(action)
                dpg.draw_rectangle((r[0] - 2, r[1] - 2), (r[2] + 2, r[3] + 2), color=T.BAD if not res.ok else T.OK,
                                   thickness=2, rounding=6, parent=self.dl)
                sx, sy = (r[0] + r[2]) / 2, r[1] - 2
                by_group: Dict[str, List[str]] = {}
                for nid in required_nodes(action):
                    g = "D3" if nid in ("D3", "D4") else nid[0]
                    by_group.setdefault(g, []).append(nid)
                for g, nids in by_group.items():
                    tr = strip.rect(g)
                    if not tr:
                        continue
                    bad = [n for n in nids if tree.nodes[n].state != P.HS_OK]
                    col = T.BAD if (bad and n_blocking(res, nids)) else T.OK
                    tx, ty = (tr[0] + tr[2]) / 2, tr[3]
                    midy = (sy + ty) / 2
                    dpg.draw_polyline([(sx, sy), (sx, midy), (tx, midy), (tx, ty)], color=col, thickness=2, parent=self.dl)
                    dpg.draw_circle((tx, ty), 5, fill=col, color=col, parent=self.dl)
                    if bad:
                        dpg.draw_text((tx + 8, ty + 4), " ".join(bad), color=col, size=13, parent=self.dl)
                    strip.highlight.add(g)
            return

        # ---- node tile -> controls ---------------------------------------------------
        for nid, tile in node_tiles.items():
            if dpg.does_item_exist(tile) and dpg.is_item_hovered(tile):
                tr = self._rect(tile)
                if not tr:
                    return
                sx, sy = (tr[0] + tr[2]) / 2, tr[1]
                n = 0
                for item, action in gate.bindings.items():
                    if nid in required_nodes(action) and dpg.does_item_exist(item) and dpg.is_item_visible(item):
                        r = self._rect(item)
                        if not r:
                            continue
                        tx, ty = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2
                        col = T.OK if tree.nodes[nid].state == P.HS_OK else T.BAD
                        dpg.draw_line((sx, sy), (tx, ty), color=col, thickness=1.5, parent=self.dl)
                        dpg.draw_rectangle((r[0] - 2, r[1] - 2), (r[2] + 2, r[3] + 2), color=col, thickness=2, rounding=6, parent=self.dl)
                        n += 1
                dpg.draw_text((sx + 8, sy - 20), f"{nid} gates {n} visible control(s)", color=T.TEXT, size=13, parent=self.dl)
                strip.highlight.add("D3" if nid in ("D3", "D4") else nid[0])
                return


def n_blocking(res, nids) -> bool:
    return any(n in res.nodes for n in nids)
