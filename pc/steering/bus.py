"""
bus.py — tiny thread-safe pub/sub used by every PC component.

Topics are strings ("telemetry", "health", "event", "link", "recording", ...).
Subscribers get called on the publisher's thread, so handlers must be quick and
must not touch Dear PyGui directly (the UI drains the bus from its own frame
callback through `Bus.latest()` / a queue).  This is also the seam where the
server hub and future devices (throttle robot, phone) plug in: they are just
more subscribers/publishers.
"""
from __future__ import annotations

import logging
import threading
from collections import defaultdict
from typing import Any, Callable, Dict, List

log = logging.getLogger(__name__)


class Bus:
    def __init__(self):
        self._subs: Dict[str, List[Callable[[Any], None]]] = defaultdict(list)
        self._latest: Dict[str, Any] = {}
        self._lock = threading.RLock()

    def subscribe(self, topic: str, fn: Callable[[Any], None]) -> Callable[[], None]:
        with self._lock:
            self._subs[topic].append(fn)

        def unsubscribe():
            with self._lock:
                if fn in self._subs[topic]:
                    self._subs[topic].remove(fn)
        return unsubscribe

    def publish(self, topic: str, payload: Any = None):
        with self._lock:
            self._latest[topic] = payload
            subs = list(self._subs.get(topic, ()))
        for fn in subs:
            try:
                fn(payload)
            except Exception:                       # a bad subscriber must never kill the publisher
                log.exception("bus subscriber for %r raised", topic)

    def latest(self, topic: str, default: Any = None) -> Any:
        with self._lock:
            return self._latest.get(topic, default)
