"""
ui/gate.py - binds widgets to gating actions.

    binder.bind(button, "enable", hint)

Every frame `binder.refresh()` asks the controller `can(action)` once per
action and:
  * enables/disables the widget,
  * sets its tooltip to the exact blocking reasons,
  * caches the GateResult so the overlay can draw the dependency lines
    (control -> status tiles) with the right colours.
"""
from __future__ import annotations

from typing import Dict

import dearpygui.dearpygui as dpg

from ..core.controller import Controller
from ..health.gating import GateResult
from . import theme as T


class GateBinder:
    def __init__(self, controller: Controller):
        self.c = controller
        self.bindings: Dict[int, str] = {}
        self._tooltips: Dict[int, int] = {}
        self._tooltip_text: Dict[int, int] = {}
        self._hint: Dict[int, str] = {}
        self._cache: Dict[str, GateResult] = {}

    def bind(self, item, action: str, hint: str = ""):
        self.bindings[item] = action
        with dpg.tooltip(item) as tt:
            txt = dpg.add_text(hint or action, wrap=380)
            T.bind_font(txt, "small")
        self._tooltips[item] = tt
        self._tooltip_text[item] = txt
        self._hint[item] = hint

    def result(self, action: str) -> GateResult:
        r = self._cache.get(action)
        if r is None:
            r = self._cache[action] = self.c.can(action)
        return r

    def refresh(self):
        self._cache = {}
        for item, action in self.bindings.items():
            if not dpg.does_item_exist(item):
                continue
            r = self.result(action)
            dpg.configure_item(item, enabled=r.ok)
            hint = self._hint.get(item, "")
            text = hint if r.ok else ("BLOCKED by:\n- " + "\n- ".join(r.reasons) + ("\n\n" + hint if hint else ""))
            dpg.set_value(self._tooltip_text[item], text)
            dpg.configure_item(self._tooltips[item], show=bool(text))
