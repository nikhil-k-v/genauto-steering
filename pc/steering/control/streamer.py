"""
control/streamer.py — streams a Trajectory to the Teensy at STREAM_HZ.

Runs on its own thread with a monotonic schedule (no drift).  Publishes
"stream_target" (so the recorder logs what we asked for) and "stream"
status.  Stops cleanly on completion, on `stop()`, or when the link drops
(the firmware independently falls back to HOLD after SETPOINT_STREAM_TIMEOUT).
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

from .. import protocol as P
from ..bus import Bus
from ..link import Link
from .trajectories import STREAM_HZ, Trajectory

log = logging.getLogger(__name__)


class Streamer:
    def __init__(self, bus: Bus, link: Link):
        self.bus = bus
        self.link = link
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.traj: Optional[Trajectory] = None
        self.index = 0
        self._seq = 0
        self.on_done: Optional[Callable[[bool], None]] = None
        self._abort_check: Optional[Callable[[], Optional[str]]] = None

    @property
    def active(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def progress(self) -> float:
        if not self.traj or self.traj.t.size == 0:
            return 0.0
        return min(1.0, self.index / self.traj.t.size)

    def start(self, traj: Trajectory, abort_check: Optional[Callable[[], Optional[str]]] = None):
        if self.active:
            raise RuntimeError("already streaming")
        self.traj, self.index = traj, 0
        self._abort_check = abort_check
        self._stop.clear()
        self.link.send(P.mode_request(P.MODE_TRAJ, sticky=True))
        self._thread = threading.Thread(target=self._run, name="streamer", daemon=True)
        self._thread.start()
        self.bus.publish("stream", {"active": True, "name": traj.name, "duration": traj.duration})

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)

    def _run(self):
        traj = self.traj
        period = 1.0 / STREAM_HZ
        t_next = time.perf_counter()
        completed = False
        reason = ""
        try:
            n = traj.t.size
            for i in range(n):
                if self._stop.is_set():
                    reason = "stopped"
                    break
                if self._abort_check:
                    why = self._abort_check()
                    if why:
                        reason = why
                        log.warning("stream aborted: %s", why)
                        break
                self.index = i
                pos = float(traj.pos[i])
                vel = float(traj.vel[i])
                self.bus.publish("stream_target", pos)
                if not self.link.send(P.setpoint(self._seq, pos, vel, int(time.monotonic() * 1000), last=(i == n - 1))):
                    reason = "link down"
                    break
                self._seq = (self._seq + 1) & 0xFFFF
                t_next += period
                delay = t_next - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)
                elif delay < -0.05:            # fell way behind (UI stall?) — resync, don't burst
                    t_next = time.perf_counter()
            else:
                completed = True
        finally:
            self.bus.publish("stream_target", None)
            # leave the motor holding wherever it is now; HOLD is the safe resting mode
            self.link.send(P.command(P.CMD_HOLD_HERE))
            self.link.send(P.mode_request(P.MODE_HOLD, sticky=True))
            self.bus.publish("stream", {"active": False, "name": traj.name, "completed": completed, "reason": reason})
            if self.on_done:
                try:
                    self.on_done(completed)
                except Exception:
                    log.exception("on_done failed")
