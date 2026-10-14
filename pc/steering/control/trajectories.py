"""
control/trajectories.py — setpoint sources for the streamer.

A Trajectory is just (t, pos_deg[, vel_deg_s]) arrays sampled at STREAM_HZ.
Generators are a convenience for tuning; the primary source in day-to-day use
is `from_recording()` (play back a recorded wheel motion).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Optional

import numpy as np

STREAM_HZ = 200


@dataclass
class Trajectory:
    name: str
    t: np.ndarray            # seconds, starts at 0
    pos: np.ndarray          # deg
    vel: np.ndarray          # deg/s (feed-forward)
    source_uid: Optional[str] = None   # recording uid when it came from one

    @property
    def duration(self) -> float:
        return float(self.t[-1]) if self.t.size else 0.0

    def clipped(self, lo: float, hi: float) -> "Trajectory":
        return Trajectory(self.name, self.t, np.clip(self.pos, lo, hi), self.vel, self.source_uid)

    def offset(self, start_deg: float, blend_s: float = 0.5) -> "Trajectory":
        """Ramp from start_deg into the first sample so the wheel never jumps."""
        if self.t.size == 0:
            return self
        n = int(blend_s * STREAM_HZ)
        if n < 2:
            return self
        ramp_t = np.arange(n) / STREAM_HZ
        ramp_p = start_deg + (self.pos[0] - start_deg) * (0.5 - 0.5 * np.cos(np.pi * ramp_t / blend_s))
        t = np.concatenate([ramp_t, self.t + blend_s])
        pos = np.concatenate([ramp_p, self.pos])
        vel = np.gradient(pos, 1.0 / STREAM_HZ)
        return Trajectory(self.name, t, pos, vel, self.source_uid)


def _t(duration_s: float) -> np.ndarray:
    return np.arange(0, max(duration_s, 0.0), 1.0 / STREAM_HZ)


def sine(amplitude_deg=20.0, freq_hz=0.5, duration_s=10.0, **_) -> Trajectory:
    t = _t(duration_s)
    w = 2 * np.pi * freq_hz
    return Trajectory("sine", t, amplitude_deg * np.sin(w * t), amplitude_deg * w * np.cos(w * t))


def triangle(amplitude_deg=20.0, freq_hz=0.25, duration_s=10.0, **_) -> Trajectory:
    t = _t(duration_s)
    ph = (t * freq_hz) % 1.0
    pos = amplitude_deg * (4 * np.abs(ph - 0.5) - 1)
    return Trajectory("triangle", t, pos, np.gradient(pos, 1.0 / STREAM_HZ))


def square(amplitude_deg=15.0, freq_hz=0.25, duration_s=10.0, **_) -> Trajectory:
    t = _t(duration_s)
    pos = amplitude_deg * np.sign(np.sin(2 * np.pi * freq_hz * t) + 1e-9)
    return Trajectory("square", t, pos, np.zeros_like(pos))


def chirp(amplitude_deg=15.0, f0_hz=0.1, f1_hz=2.0, duration_s=20.0, **_) -> Trajectory:
    t = _t(duration_s)
    k = (f1_hz - f0_hz) / max(duration_s, 1e-6)
    phase = 2 * np.pi * (f0_hz * t + 0.5 * k * t ** 2)
    pos = amplitude_deg * np.sin(phase)
    return Trajectory("chirp", t, pos, np.gradient(pos, 1.0 / STREAM_HZ))


def step(amplitude_deg=30.0, hold_s=3.0, **_) -> Trajectory:
    t = _t(2 * hold_s)
    pos = np.where(t < hold_s, amplitude_deg, 0.0)
    return Trajectory("step", t, pos, np.zeros_like(pos))


def slew_to(target_deg=0.0, start_deg=0.0, rate_deg_s=30.0, **_) -> Trajectory:
    d = abs(target_deg - start_deg)
    dur = max(d / max(rate_deg_s, 1e-3), 0.05)
    t = _t(dur)
    pos = start_deg + (target_deg - start_deg) * (0.5 - 0.5 * np.cos(np.pi * t / dur))
    return Trajectory("slew", t, pos, np.gradient(pos, 1.0 / STREAM_HZ))


GENERATORS: Dict[str, Callable[..., Trajectory]] = {
    "sine": sine, "triangle": triangle, "square": square, "chirp": chirp, "step": step,
}
GENERATOR_PARAMS: Dict[str, Dict[str, float]] = {
    "sine": {"amplitude_deg": 20.0, "freq_hz": 0.5, "duration_s": 10.0},
    "triangle": {"amplitude_deg": 20.0, "freq_hz": 0.25, "duration_s": 10.0},
    "square": {"amplitude_deg": 15.0, "freq_hz": 0.25, "duration_s": 10.0},
    "chirp": {"amplitude_deg": 15.0, "f0_hz": 0.1, "f1_hz": 2.0, "duration_s": 20.0},
    "step": {"amplitude_deg": 30.0, "hold_s": 3.0},
}


def make(name: str, **params) -> Trajectory:
    return GENERATORS[name](**params)


def from_recording(t_s: np.ndarray, pos_deg: np.ndarray, name: str = "recording",
                   uid: Optional[str] = None, speed: float = 1.0) -> Trajectory:
    """Resample a recorded position trace (any rate) onto the stream grid.
    `speed` > 1 plays faster."""
    ok = np.isfinite(t_s) & np.isfinite(pos_deg)
    t_s, pos_deg = t_s[ok], pos_deg[ok]
    if t_s.size < 2:
        return Trajectory(name, np.zeros(0), np.zeros(0), np.zeros(0), uid)
    t_s = (t_s - t_s[0]) / max(speed, 1e-3)
    grid = _t(float(t_s[-1]))
    pos = np.interp(grid, t_s, pos_deg)
    return Trajectory(name, grid, pos, np.gradient(pos, 1.0 / STREAM_HZ), uid)
