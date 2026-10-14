"""
ui/gate.py - binds widgets to gating actions (item 1B).

    binder.bind(button_tag, "enable")

Every frame `binder.refresh()` asks the controller `can(action)` and:
  * enables/disables the widget,
  * sets its tooltip to the exact blocking reasons,
  * remembers which health nodes are responsible, so the top bar can
    highlight them while the widget is hovered.
"""
from __future__ import annotations

from typing import Dict, List, Set

import dearpygui.dearpygui as dpg

from ..core.controller import Controller


class GateBinder:
    def __init__(self, controller: Controller):
        self.c = controller
        self._bindings: Dict[int, str] = {}
        self._tooltips: Dict[int, int] = {}
        self._tooltip_text: Dict[int, int] = {}
        self._nodes: Dict[int, List[str]] = {}
        self.highlight: Set[str] = set()

    def bind(self, item, action: str, hint: str = ""):
        self._bindings[item] = action
        with dpg.tooltip(item) as tt:
            txt = dpg.add_text(hint or action, wrap=360)
        self._tooltips[item] = tt
        self._tooltip_text[item] = txt
        self._hint = getattr(self, "_hint", {})
        self._hint[item] = hint

    def refresh(self):
        self.highlight = set()
        cache: Dict[str, object] = {}
        for item, action in self._bindings.items():
            if not dpg.does_item_exist(item):
                continue
            r = cache.get(action)
            if r is None:
                r = cache[action] = self.c.can(action)
            dpg.configure_item(item, enabled=r.ok)
            hint = self._hint.get(item, "")
            text = (hint or "") if r.ok else "BLOCKED\n- " + "\n- ".join(r.reasons)
            dpg.set_value(self._tooltip_text[item], text)
            dpg.configure_item(self._tooltips[item], show=bool(text) or not r.ok)
            self._nodes[item] = r.nodes
            if not r.ok and dpg.is_item_hovered(item):
                self.highlight.update(r.nodes)
