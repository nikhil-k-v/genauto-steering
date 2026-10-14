"""
ui/gate.py - binds widgets to gating actions.

    binder.bind(button, "enable", "what it does")
    binder.bind(button, resolver, {"enable": "...", "hold_here": "..."})   # action depends on state

Every frame `binder.refresh()` asks the controller `can(action)` once per
action and:
  * enables/disables the widget,
  * sets its tooltip: what it does, or exactly what blocks it,
  * caches the result so the overlay can draw the dependency lines
    (control -> rail rows) in the right colours.
"""
from __future__ import annotations

from typing import Callable, Dict, Union

import dearpygui.dearpygui as dpg

from ..core.controller import Controller
from ..health.gating import GateResult
from . import theme as T

ActionRef = Union[str, Callable[[], str]]


class GateBinder:
    def __init__(self, controller: Controller):
        self.c = controller
        self._refs: Dict[int, ActionRef] = {}
        self.bindings: Dict[int, str] = {}           # item -> action resolved this frame
        self._tip_head: Dict[int, int] = {}
        self._tip_body: Dict[int, int] = {}
        self._hint: Dict[int, Union[str, dict]] = {}
        self._cache: Dict[str, GateResult] = {}

    def bind(self, item, action: ActionRef, hint: Union[str, dict] = ""):
        self._refs[item] = action
        self.bindings[item] = action() if callable(action) else action
        with dpg.tooltip(item):
            self._tip_head[item] = dpg.add_text("", wrap=360)
            self._tip_body[item] = dpg.add_text("", wrap=360, color=T.BAD)
            T.bind_font(self._tip_body[item], "small")
        self._hint[item] = hint

    def result(self, action: str) -> GateResult:
        r = self._cache.get(action)
        if r is None:
            r = self._cache[action] = self.c.can(action)
        return r

    def refresh(self):
        self._cache = {}
        for item, ref in self._refs.items():
            if not dpg.does_item_exist(item):
                continue
            action = ref() if callable(ref) else ref
            self.bindings[item] = action
            r = self.result(action)
            dpg.configure_item(item, enabled=r.ok)
            hint = self._hint.get(item, "")
            if isinstance(hint, dict):
                hint = hint.get(action, "")
            dpg.set_value(self._tip_head[item], hint)
            dpg.configure_item(self._tip_head[item], show=bool(hint))
            body = "" if r.ok else "Not available:\n" + "\n".join(f"  {x}" for x in r.reasons)
            dpg.set_value(self._tip_body[item], body)
            dpg.configure_item(self._tip_body[item], show=bool(body))
