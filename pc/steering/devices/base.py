"""
devices/base.py — the seam for more hardware (throttle robot, a second
steering Teensy, external sensors).

A Device is anything that (a) produces health nodes, (b) produces timestamped
samples for the recorder, and (c) accepts gated actions.  The steering
Teensy is the first device; it is wired directly through Link/Controller
today and will be refactored behind this interface when the throttle robot
arrives, so nothing here is used by the UI yet — it exists so the throttle
work has a home and does not grow into the steering code.

Contract:
  * `name` is unique and prefixes its health node ids ("T1", "T2" for the
    throttle group).
  * `health()` returns {node_id: (state, reason)} and is called at 10 Hz.
  * `start()/stop()` never block; sample output goes to bus topic
    f"{name}.sample" with dicts {"t": perf_counter, ...}.
  * The recorder subscribes to every registered device and writes
    `<name>.csv` next to data.csv.
"""
from __future__ import annotations

from typing import Dict, Protocol, Tuple

from ..bus import Bus


class Device(Protocol):
    name: str

    def start(self, bus: Bus) -> None: ...
    def stop(self) -> None: ...
    def health(self) -> Dict[str, Tuple[int, str]]: ...
    def columns(self) -> list: ...


class DeviceRegistry:
    def __init__(self, bus: Bus):
        self.bus = bus
        self._devices: Dict[str, Device] = {}

    def add(self, dev: Device):
        self._devices[dev.name] = dev
        dev.start(self.bus)

    def remove(self, name: str):
        d = self._devices.pop(name, None)
        if d:
            d.stop()

    def all(self):
        return list(self._devices.values())

    def health(self) -> Dict[str, Tuple[int, str]]:
        out = {}
        for d in self._devices.values():
            out.update(d.health())
        return out
