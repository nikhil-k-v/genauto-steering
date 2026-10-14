"""
ui/safe.py - nothing in the UI is allowed to kill the UI (item 7).

* `safe(fn)` wraps every callback: exceptions are logged with a traceback,
  shown as a toast, pushed to the health evaluator (F5 reason), and swallowed.
* `ActionRefused` is NOT an error: it becomes a yellow toast with the reasons.
* The frame tick is wrapped the same way, so a bug in one panel's refresh
  cannot stop the others (or the heartbeat, which lives on another thread
  anyway).
"""
from __future__ import annotations

import functools
import logging
import time
import traceback
from typing import Callable, List, Optional, Tuple

from ..core.controller import ActionRefused

log = logging.getLogger(__name__)

_toasts: List[Tuple[float, str, str]] = []     # (expires, level, text)
_last_error: str = ""
_evaluator = None


def attach_evaluator(ev):
    global _evaluator
    _evaluator = ev


def toast(text: str, level: str = "info", seconds: float = 4.0):
    _toasts.append((time.monotonic() + seconds, level, text))
    del _toasts[:-6]


def toasts() -> List[Tuple[str, str]]:
    now = time.monotonic()
    _toasts[:] = [t for t in _toasts if t[0] > now]
    return [(lvl, txt) for _, lvl, txt in _toasts]


def last_error() -> str:
    return _last_error


def safe(fn: Callable) -> Callable:
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        global _last_error
        try:
            return fn(*args, **kwargs)
        except ActionRefused as e:
            toast(str(e), "warn")
            return None
        except Exception as e:
            _last_error = f"{type(e).__name__}: {e}"
            log.error("UI callback %s failed:\n%s", getattr(fn, "__name__", fn), traceback.format_exc())
            toast(f"UI error in {getattr(fn, '__name__', 'callback')}: {e}", "bad", 8)
            if _evaluator:
                _evaluator.note_ui_error(_last_error)
            return None
    return wrapper
