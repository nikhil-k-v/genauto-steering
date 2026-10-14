"""
data/analysis.py — load recordings and compute the metrics stored in meta.json.

Metrics are deliberately plain numbers with units in the key name so they can
be compared across recordings in the Library (item 3).
"""
from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Dict, Optional

import numpy as np

CSV_COLUMNS = ["t_s", "t_teensy_us", "ctrl_state", "flags", "target_deg", "setpoint_deg", "position_deg",
               "velocity_deg_s", "current_A", "torque_cmd_Nm", "error_deg"]


def load_csv(path: Path) -> Dict[str, np.ndarray]:
    path = Path(path)
    cols = {c: [] for c in CSV_COLUMNS}
    with open(path, newline="") as f:
        rd = csv.DictReader(line for line in f if not line.startswith("#"))
        for row in rd:
            for c in CSV_COLUMNS:
                v = row.get(c, "")
                try:
                    cols[c].append(float(v) if v not in ("", None) else math.nan)
                except ValueError:
                    cols[c].append(math.nan)
    return {c: np.asarray(v, dtype=float) for c, v in cols.items()}


def _finite(a: np.ndarray) -> np.ndarray:
    return a[np.isfinite(a)]


def compute_metrics(d: Dict[str, np.ndarray], kind: str = "") -> Dict[str, float]:
    m: Dict[str, float] = {}
    t = d["t_s"]
    if t.size < 2:
        return {"samples": int(t.size)}
    m["samples"] = int(t.size)
    m["duration_s"] = float(t[-1] - t[0])
    dt = np.diff(t)
    m["sample_rate_hz"] = float(1.0 / np.median(dt)) if dt.size and np.median(dt) > 0 else 0.0
    m["max_gap_ms"] = float(np.max(dt) * 1000) if dt.size else 0.0

    err = _finite(d["error_deg"])
    if err.size:
        m["err_rms_deg"] = float(np.sqrt(np.mean(err ** 2)))
        m["err_max_abs_deg"] = float(np.max(np.abs(err)))
        m["err_mean_deg"] = float(np.mean(err))
        m["err_p95_abs_deg"] = float(np.percentile(np.abs(err), 95))
    vel = _finite(d["velocity_deg_s"])
    if vel.size:
        m["vel_max_abs_deg_s"] = float(np.max(np.abs(vel)))
    cur = _finite(d["current_A"])
    if cur.size:
        m["current_max_abs_A"] = float(np.max(np.abs(cur)))
        m["current_rms_A"] = float(np.sqrt(np.mean(cur ** 2)))
    pos = _finite(d["position_deg"])
    if pos.size:
        m["pos_min_deg"], m["pos_max_deg"] = float(pos.min()), float(pos.max())
        m["pos_range_deg"] = float(pos.max() - pos.min())

    # tracking score: 100 % when error is 0; 0 % when rms error = 10 % of the setpoint range
    sp = _finite(d["setpoint_deg"])
    if err.size and sp.size:
        rng = max(float(sp.max() - sp.min()), 1.0)
        m["tracking_score_pct"] = float(max(0.0, 100.0 * (1.0 - m["err_rms_deg"] / (0.1 * rng))))

    if kind == "test_step":
        m.update(step_metrics(d))
    if kind == "test_relay":
        m.update(relay_metrics(d))
    return m


def step_metrics(d: Dict[str, np.ndarray]) -> Dict[str, float]:
    """Rise time (10–90 %), overshoot %, settling time (2 %) for the first step in setpoint."""
    t, sp, pos = d["t_s"], d["setpoint_deg"], d["position_deg"]
    ok = np.isfinite(sp) & np.isfinite(pos)
    t, sp, pos = t[ok], sp[ok], pos[ok]
    if t.size < 10:
        return {}
    dsp = np.diff(sp)
    idx = np.where(np.abs(dsp) > 1.0)[0]
    if idx.size == 0:
        return {}
    i0 = int(idx[0]) + 1
    base, target = float(sp[i0 - 1]), float(sp[i0])
    amp = target - base
    if abs(amp) < 1e-6:
        return {}
    seg_t, seg_p = t[i0:] - t[i0], pos[i0:]
    # stop at the next setpoint change
    nxt = np.where(np.abs(np.diff(sp[i0:])) > 1.0)[0]
    if nxt.size:
        seg_t, seg_p = seg_t[: int(nxt[0]) + 1], seg_p[: int(nxt[0]) + 1]
    frac = (seg_p - base) / amp
    out: Dict[str, float] = {"step_amp_deg": float(amp)}
    i10 = np.argmax(frac >= 0.1) if np.any(frac >= 0.1) else None
    i90 = np.argmax(frac >= 0.9) if np.any(frac >= 0.9) else None
    if i10 is not None and i90 is not None and i90 >= i10:
        out["step_rise_s"] = float(seg_t[i90] - seg_t[i10])
    out["step_overshoot_pct"] = float(max(0.0, (frac.max() - 1.0) * 100.0))
    within = np.abs(frac - 1.0) <= 0.02
    if within.any():
        last_out = np.where(~within)[0]
        i_settle = int(last_out[-1]) + 1 if last_out.size and last_out[-1] + 1 < within.size else 0
        if i_settle < seg_t.size:
            out["step_settle_s"] = float(seg_t[i_settle])
    out["step_ss_err_deg"] = float((seg_p[-max(1, seg_p.size // 10):].mean() - target))
    return out


def relay_metrics(d: Dict[str, np.ndarray]) -> Dict[str, float]:
    """Ultimate gain/period from relay oscillation (Åström–Hägglund)."""
    t, pos, sp, tq = d["t_s"], d["position_deg"], d["setpoint_deg"], d["torque_cmd_Nm"]
    ok = np.isfinite(pos) & np.isfinite(sp)
    t, pos, sp, tq = t[ok], pos[ok], sp[ok], tq[ok]
    if t.size < 50:
        return {}
    y = pos - sp
    # discard the first 20 % (transient)
    k = t.size // 5
    t, y, tq = t[k:], y[k:], tq[k:]
    zc = np.where(np.diff(np.sign(y)) > 0)[0]       # upward zero crossings
    if zc.size < 3:
        return {}
    periods = np.diff(t[zc])
    Tu = float(np.median(periods))
    a = float((np.max(y) - np.min(y)) / 2.0)        # oscillation amplitude (deg)
    h = float(np.nanmax(np.abs(tq))) if np.isfinite(tq).any() else 0.0   # relay amplitude (Nm)
    if a <= 0 or h <= 0:
        return {"relay_Tu_s": Tu}
    Ku = 4.0 * h / (math.pi * math.radians(a))      # Nm/rad
    return {"relay_Tu_s": Tu, "relay_amp_deg": a, "relay_h_Nm": h, "relay_Ku_Nm_per_rad": Ku,
            "relay_periods": float(zc.size - 1)}


def propose_gains(Ku: float, Tu: float) -> Dict[str, Dict[str, float]]:
    """Ziegler–Nichols style proposals from Ku (Nm/rad) and Tu (s).  The motor's
    kp/kd fields are in Nm/rad and Nm/(rad/s); ki is the Teensy integral."""
    return {
        "ZN-PID":      {"kp": 0.6 * Ku,  "ki": 1.2 * Ku / Tu, "kd": 0.075 * Ku * Tu},
        "ZN-PI":       {"kp": 0.45 * Ku, "ki": 0.54 * Ku / Tu, "kd": 0.0},
        "Pessen":      {"kp": 0.7 * Ku,  "ki": 1.75 * Ku / Tu, "kd": 0.105 * Ku * Tu},
        "Steering-conservative": {"kp": 0.33 * Ku, "ki": 0.2 * Ku / Tu, "kd": 0.11 * Ku * Tu},
    }


def trim_csv(path: Path, end_time_s: float) -> int:
    """Permanently drop samples after end_time_s (relative).  Returns kept rows."""
    path = Path(path)
    lines = path.read_text().splitlines()
    header = [l for l in lines if l.startswith("#")]
    body = [l for l in lines if not l.startswith("#")]
    if not body:
        return 0
    cols = body[0].split(",")
    ti = cols.index("t_s")
    kept = [body[0]]
    for l in body[1:]:
        try:
            if float(l.split(",")[ti]) <= end_time_s:
                kept.append(l)
        except (ValueError, IndexError):
            continue
    path.write_text("\n".join(header + kept) + "\n")
    return len(kept) - 1
