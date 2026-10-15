"""
sim.py — a fake Teensy + fake BM-series motor behind the Transport interface.

`python -m steering ui --sim` runs the whole PC application against this with
no hardware.  It speaks the real wire protocol (frames, CRC, packet structs)
and mimics the firmware state machine closely enough that gating, health,
recording, playback, calibration and tests can all be exercised.  Fault
injection knobs (`SimTeensy.faults`) let you see what every health node
looks like when it fails — handy for learning the status bar.

The CAN side is modelled the way the hardware behaves, not short-cut: the motor
answers only frames sent to ITS id (`SimFaults.motor_can_id`), and only if it is
powered and the bus works; the Teensy sends one frame per 1 kHz tick with the
motor on and a zero-gain poll at CAN_REST_POLL_HZ with it off; reply rates,
"motor alive" and the scan all come from those replies, exactly as in
firmware/teensy/src (can_motor.cpp, health.cpp).  A sim that pretends the motor
is alive hides the bugs that bite on the real bench.
"""
from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from . import protocol as P
from .link import Transport


@dataclass
class SimFaults:
    motor_power: bool = True        # False -> no CAN replies (M4 BLOCKED/FAIL), nobody ACKs our frames
    motor_can_id: int = 2           # the id the motor really answers to (Teensy default is 2)
    answers_in_rest: bool = True    # False: the motor only answers once in motor mode
    switch_armed: bool = True       # idle switch
    can_bus_off: bool = False       # M1 FAIL
    frozen_encoder: bool = False    # M5
    heartbeat_deaf: bool = False    # Teensy ignores PC heartbeats (C5)
    isr_overruns: int = 0
    hand_Nm: float = 0.0            # torque a hand puts on the wheel (free-spin recordings, disturbances)


@dataclass
class SimMotor:
    pos: float = 12.0               # deg (power-on offset so "zero" means something)
    vel: float = 0.0
    cur: float = 0.0
    inertia: float = 0.02           # kg m^2 equivalent (deg units scaled below)
    friction_Nm: float = 0.8        # coulomb
    viscous: float = 0.004          # Nm per deg/s
    stop_left: float = -210.0       # hard stops in the motor frame
    stop_right: float = 230.0
    stop_k: float = 8.0             # Nm/deg spring at the stop
    stop_c: float = 0.3             # Nm per deg/s damping in the stop (rubber bump)
    ext_Nm: float = 0.0             # external torque (a hand on the wheel)

    def step(self, dt: float, p_cmd_deg: float, v_cmd: float, kp: float, kd: float, t_ff: float):
        # MIT-style: torque = kp*(p_cmd - p) + kd*(v_cmd - v) + t_ff, gains in Nm/rad
        err_rad = math.radians(p_cmd_deg - self.pos)
        verr_rad = math.radians(v_cmd - self.vel)
        tau = kp * err_rad + kd * verr_rad + t_ff
        tau = max(-18.0, min(18.0, tau))
        motor_tau = tau
        tau += self.ext_Nm
        if self.pos < self.stop_left:
            tau += self.stop_k * (self.stop_left - self.pos) - self.stop_c * self.vel
        if self.pos > self.stop_right:
            tau -= self.stop_k * (self.pos - self.stop_right) + self.stop_c * self.vel
        fric = self.friction_Nm * (1 if self.vel > 0.5 else -1 if self.vel < -0.5 else 0)
        if abs(self.vel) <= 0.5 and abs(tau) < self.friction_Nm:
            tau_net = 0.0
            self.vel = 0.0
        else:
            tau_net = tau - fric - self.viscous * self.vel
        acc = math.degrees(tau_net / self.inertia) * 0.01      # scaled to feel like a steering wheel
        self.vel += acc * dt
        self.pos += self.vel * dt
        self.cur = motor_tau / 1.2                             # ~1.2 Nm/A, motor's own torque only


# firmware/teensy/src/config.h
CAN_REST_POLL_HZ = 100
CAN_RX_LOW_HZ = 600
CAN_REPLY_TIMEOUT_S = 0.2
CAN_SCAN_PASSES = 2
CAN_SCAN_SETTLE_S = 0.05


class SimTeensy:
    def __init__(self, faults: Optional[SimFaults] = None):
        self.f = faults or SimFaults()
        self.m = SimMotor()
        self.cs = P.CS_REST
        self.trip = P.TRIP_NONE
        self.calib = P.CAL_IDLE
        self.mode_req = P.MODE_AUTO
        self.zeroed = False
        self.limits_valid = False
        self.limit_l, self.limit_r = -200.0, 200.0
        self.left_cap = self.right_cap = False
        self.kp, self.kd, self.ki, self.tff = 30.0, 2.0, 0.0, 0.0
        self.sp_target = self.sp_cmd = 0.0
        self.sp_last = 0.0
        self.sp_seq = 0
        self.pc_hb_last = 0.0
        self.enable_t = 0.0
        self.integral = 0.0
        self.torque_cmd = 0.0
        self.test_type = P.TEST_NONE
        self.test_amp = self.test_dur = self.test_param = 0.0
        self.test_t0 = 0.0
        self.test_base = 0.0
        self.relay_sign = 1
        self.events = []
        self.t = 0.0
        self.motor_last_reply = -1.0    # sim time of the last reply from motor_id (-1 = none since boot / id change)
        self.motor_id = 2               # the id the Teensy commands (CMD_SET_MOTOR_ID)
        self.rx_motor = 0               # replies from motor_id
        self.rx_other = 0               # replies from any other id (seen during scans)
        self.tec = 0                    # FlexCAN TX error counter
        self._meas = (12.0, 0.0, 0.0)   # pos/vel/cur in the last reply (motor frame)
        self._poll_div = 0
        self._scan: Optional[dict] = None
        self._hz_prev = (0.0, 0, 0)     # (t, rx_motor, rx_other) at the last health packet
        self._arm_rx = 0
        self._cal_stage_t = 0.0
        self._cal_still = 0.0
        self._cal_torque = 1.0
        self._cal_center = 0.0
        self._zero_offset = 0.0         # motor frame -> reported frame
        self.out_queue: list = []
        self._soft_offset = 0.0
        self._still_pos = 0.0

    # ---- helpers ---------------------------------------------------------------------
    def event(self, code, arg=0, text=""):
        self.events.append((code, arg, text, int(self.t * 1000)))

    def rep_pos(self):
        return self.m.pos - self._zero_offset - self._soft_offset

    def set_state(self, cs):
        if cs != self.cs:
            self.cs = cs
            self.event(P.EV_STATE, cs)

    def do_trip(self, code, why):
        if self.cs == P.CS_TRIPPED:
            return
        self.trip = code
        if self.cs == P.CS_CALIB:
            self.calib = P.CAL_FAILED
        self.test_type = P.TEST_NONE
        self.set_state(P.CS_TRIPPED)
        self.event(P.EV_TRIP, code, why)

    @property
    def enabled(self):
        return self.cs in P.CS_ENABLED

    def arm(self, cs):
        self.enable_t = self.t
        self._arm_rx = self.rx_motor          # waiting for the first reply after turning on
        self.integral = 0.0
        self.sp_cmd = self.sp_target = self.rep_pos()
        self.set_state(cs)

    def limits(self):
        if self.limits_valid:
            return self.limit_l + 3.0, self.limit_r - 3.0
        return -200.0, 200.0

    # ---- command handling --------------------------------------------------------------------
    def command(self, cmd, arg, farg):
        alive = self.motor_fresh
        scanning = self.scan_busy
        def rej(txt):
            self.event(P.EV_CMD_REJECTED, cmd, txt); return False
        if cmd == P.CMD_ENABLE:
            if self.cs == P.CS_TRIPPED: return rej("safety stop: reset")
            if not self.f.switch_armed: return rej("idle switch on")
            if self.enabled: return rej("motor already on")
            if scanning: return rej("CAN scan running")
            self.arm(P.CS_HOLD)
        elif cmd == P.CMD_DISABLE:
            if self.cs == P.CS_TRIPPED: self.event(P.EV_CMD_ACCEPTED, cmd); return True
            self.test_type = P.TEST_NONE
            if self.cs == P.CS_CALIB: self.calib = P.CAL_ABORTED
            self.set_state(P.CS_REST)
        elif cmd == P.CMD_CLEAR_TRIP:
            if self.cs != P.CS_TRIPPED: return rej("no safety stop")
            self.trip = P.TRIP_NONE; self.calib = P.CAL_IDLE; self.set_state(P.CS_REST)
        elif cmd == P.CMD_SET_ZERO:
            if not alive: return rej("no motor CAN reply")
            if self.cs in (P.CS_TRAJ, P.CS_TEST, P.CS_CALIB): return rej("busy, stop it first")
            p = self.rep_pos()
            self._zero_offset = self.m.pos; self._soft_offset = 0.0
            if self.limits_valid: self.limit_l -= p; self.limit_r -= p
            self.sp_cmd = self.sp_target = 0.0; self.integral = 0.0; self.zeroed = True; self.enable_t = self.t
            self.event(P.EV_ZERO_SET)
        elif cmd == P.CMD_FREESPIN_ON:
            if self.cs == P.CS_TRIPPED: return rej("safety stop: reset")
            if not self.f.switch_armed: return rej("idle switch on")
            if self.cs in (P.CS_TRAJ, P.CS_TEST, P.CS_CALIB): return rej("busy, stop it first")
            if scanning: return rej("CAN scan running")
            if not self.enabled: self.arm(P.CS_FREESPIN)
            else: self.set_state(P.CS_FREESPIN)
        elif cmd == P.CMD_FREESPIN_OFF:
            if self.cs != P.CS_FREESPIN: return rej("not in free-spin")
            self.sp_cmd = self.sp_target = self.rep_pos(); self.enable_t = self.t; self.set_state(P.CS_HOLD)
        elif cmd == P.CMD_HOLD_HERE:
            if not self.enabled: return rej("motor is off")
            self.sp_target = self.rep_pos(); self.mode_req = P.MODE_HOLD
            if self.cs == P.CS_TRAJ: self.set_state(P.CS_HOLD)
        elif cmd == P.CMD_CALIB_START:
            if self.cs == P.CS_TRIPPED: return rej("safety stop: reset")
            if not self.f.switch_armed: return rej("idle switch on")
            if self.cs in (P.CS_TRAJ, P.CS_TEST): return rej("busy, stop it first")
            if scanning: return rej("CAN scan running")
            if not self.enabled: self.arm(P.CS_CALIB)
            else: self.set_state(P.CS_CALIB)
            self.calib = P.CAL_SEEK_LEFT; self._cal_stage_t = self.t; self._cal_torque = -1.0
            self.limits_valid = False; self.left_cap = self.right_cap = False
            self.event(P.EV_CALIB_STAGE, P.CAL_SEEK_LEFT)
        elif cmd == P.CMD_CALIB_ABORT:
            if self.cs != P.CS_CALIB: return rej("not calibrating")
            self.calib = P.CAL_ABORTED; self.set_state(P.CS_REST)
        elif cmd in (P.CMD_CAPTURE_LEFT, P.CMD_CAPTURE_RIGHT):
            if not alive: return rej("no motor CAN reply")
            if cmd == P.CMD_CAPTURE_LEFT: self.limit_l = self.rep_pos(); self.left_cap = True
            else: self.limit_r = self.rep_pos(); self.right_cap = True
            self.limits_valid = self.left_cap and self.right_cap and (self.limit_r - self.limit_l) > 60
            if self.limits_valid: self.event(P.EV_LIMITS_SET)
        elif cmd == P.CMD_GO_CENTER_ZERO:
            if self.cs == P.CS_TRIPPED: return rej("safety stop: reset")
            if not self.f.switch_armed: return rej("idle switch on")
            if not (self.left_cap and self.right_cap): return rej("save L and R first")
            if self.cs in (P.CS_TRAJ, P.CS_TEST): return rej("busy, stop it first")
            if scanning: return rej("CAN scan running")
            if not self.enabled: self.arm(P.CS_CALIB)
            else: self.set_state(P.CS_CALIB)
            self.calib = P.CAL_GO_CENTER; self._cal_stage_t = self.t; self.sp_cmd = self.rep_pos()
            self.event(P.EV_CALIB_STAGE, P.CAL_GO_CENTER)
        elif cmd == P.CMD_SET_MOTOR_ID:
            if self.enabled: return rej("motor must be off")
            if not 1 <= arg <= 127: return rej("id out of range")
            if scanning: return rej("CAN scan running")
            self.motor_id = arg
            self.motor_last_reply = -1.0          # replies so far were from the old id
            self.out_queue.append(self.config())
        elif cmd == P.CMD_CAN_SCAN:
            if self.enabled: return rej("motor must be off")
            if scanning: return rej("CAN scan running")
            first = min(127, arg) if arg else 1
            last = int(farg) if 1 <= farg <= 127 else 127
            first, last = min(first, last), max(first, last)
            self._scan = {"first": first, "last": last, "next": first, "pass": 0, "until": None, "seen": set()}
        elif cmd in (P.CMD_REQ_CONFIG, P.CMD_RESET_COUNTERS):
            pass
        else:
            return rej("unknown command")
        self.event(P.EV_CMD_ACCEPTED, cmd)
        return True

    def start_test(self, tt, amp, dur, param):
        if not self.enabled or self.cs in (P.CS_FREESPIN, P.CS_CALIB):
            self.event(P.EV_CMD_REJECTED, P.PKT_TEST_START, "needs position ctrl"); return
        if not self.zeroed:
            self.event(P.EV_CMD_REJECTED, P.PKT_TEST_START, "0 deg not set"); return
        self.test_type, self.test_amp, self.test_dur, self.test_param = tt, amp, dur, param
        self.test_t0 = self.t; self.test_base = self.sp_cmd; self.relay_sign = 1; self.integral = 0.0
        self.set_state(P.CS_TEST)

    # ---- the tick (1 kHz equivalent, run at 1 kHz by the transport thread) ------------------------
    def tick(self, dt):
        self.t += dt
        self.m.ext_Nm = self.f.hand_Nm
        pos, vel = self.rep_pos(), self.m.vel
        # safety
        if self.enabled:
            if not self.f.switch_armed: self.do_trip(P.TRIP_SWITCH_OPENED, "pin 22 open")
            elif not self.motor_fresh and not (self.rx_motor == self._arm_rx and self.t - self.enable_t < CAN_REPLY_TIMEOUT_S):
                self.do_trip(P.TRIP_CAN_LOST, "no reply after on" if self.rx_motor == self._arm_rx else "")
            elif self.t - self.enable_t > 0.25:
                if abs(vel) > 1430: self.do_trip(P.TRIP_VELOCITY, f"{vel:.0f} deg/s")
                lo, hi = self.limits()
                if self.cs != P.CS_CALIB and (pos < lo - 15 or pos > hi + 15): self.do_trip(P.TRIP_LIMIT, f"{(lo - pos) if pos < lo else (pos - hi):.0f} deg past {'L' if pos < lo else 'R'}")
                if self.pc_hb_last and self.t - self.pc_hb_last > 0.6:
                    if self.cs == P.CS_TRAJ: self.do_trip(P.TRIP_PC_LINK_LOST, f"{(self.t - self.pc_hb_last) * 1000:.0f} ms silent")
                    elif self.cs == P.CS_TEST:
                        self.test_type = P.TEST_NONE; self.sp_target = self.sp_cmd
                        self.event(P.EV_WARNING, 0, "test ended: no PC"); self.set_state(P.CS_HOLD)
        # mode resolution
        if self.cs in (P.CS_HOLD, P.CS_TRAJ):
            sp_fresh = self.sp_last and (self.t - self.sp_last) < 0.25
            want = P.CS_TRAJ if (self.mode_req in (P.MODE_TRAJ, P.MODE_AUTO) and sp_fresh) else P.CS_HOLD
            if want != self.cs:
                if want == P.CS_HOLD: self.sp_target = self.sp_cmd
                self.set_state(want)

        kp = kd = t_ff = 0.0
        p_cmd = self.sp_cmd
        if self.cs in (P.CS_REST, P.CS_TRIPPED):
            self.torque_cmd = 0.0
            # free wheel: no torque
            self.m.step(dt, self.m.pos, 0, 0, 0, 0)
        elif self.cs == P.CS_FREESPIN:
            self.sp_cmd = self.sp_target = pos
            self.m.step(dt, self.m.pos, 0, 0, 0, 0)
        elif self.cs == P.CS_CALIB:
            self._calib_tick(dt, pos, vel)
        else:
            if self.cs == P.CS_TEST:
                el = self.t - self.test_t0
                if self.test_type == P.TEST_STEP:
                    self.sp_target = self.test_base + (self.test_amp if el < self.test_dur else 0.0)
                    if el > self.test_dur + max(self.test_param, 1.0):
                        self.test_type = P.TEST_NONE; self.event(P.EV_TEST_DONE, P.TEST_STEP)
                        self.sp_target = self.sp_cmd; self.set_state(P.CS_HOLD)
                elif self.test_type == P.TEST_RELAY:
                    e = self.test_base - pos
                    if e > self.test_param and self.relay_sign < 0: self.relay_sign = 1
                    if e < -self.test_param and self.relay_sign > 0: self.relay_sign = -1
                    self.torque_cmd = self.relay_sign * 2.0
                    self.m.step(dt, self.m.pos, 0, 0, 0, self.torque_cmd)
                    if el > self.test_dur:
                        self.test_type = P.TEST_NONE; self.event(P.EV_TEST_DONE, P.TEST_RELAY)
                        self.sp_cmd = self.sp_target = pos; self.enable_t = self.t; self.set_state(P.CS_HOLD)
                    self._can_tick()
                    return
            lo, hi = self.limits()
            self.sp_target = max(lo, min(hi, self.sp_target))
            step = 2300.0 * dt
            d = self.sp_target - self.sp_cmd
            self.sp_cmd += max(-step, min(step, d))
            ramp = min(1.0, 0.05 + 0.95 * (self.t - self.enable_t) / 0.8)
            kp, kd = self.kp * ramp, self.kd * ramp
            err = self.sp_cmd - pos
            if self.ki > 0 and ramp >= 1.0:
                self.integral += self.ki * math.radians(err) * dt
                self.integral -= self.integral * 0.2 * dt
                self.integral = max(-4.0, min(4.0, self.integral))
            else:
                self.integral = 0.0
            t_ff = self.integral + self.tff
            self.torque_cmd = t_ff
            self.m.step(dt, self.sp_cmd + self._zero_offset + self._soft_offset, 0, kp, kd, t_ff)
        self._can_tick()

    # ---- CAN (firmware can_motor.cpp + the motor's answer) ------------------------------------
    @property
    def motor_fresh(self) -> bool:
        return self.motor_last_reply >= 0 and (self.t - self.motor_last_reply) < CAN_REPLY_TIMEOUT_S

    @property
    def scan_busy(self) -> bool:
        return self._scan is not None

    def _can_send(self, can_id: int):
        """One frame on the bus.  The motor ACKs any frame and answers the ones addressed to it."""
        if self.f.can_bus_off:
            return
        if not self.f.motor_power:                  # nobody on the bus to ACK: TEC climbs to error-passive
            self.tec = min(128, self.tec + 8)
            return
        self.tec = max(0, self.tec - 1)
        if can_id != self.f.motor_can_id:
            return
        if not self.enabled and not self.f.answers_in_rest:
            return
        if self._scan is not None:
            self._scan["seen"].add(can_id)
        if can_id == self.motor_id:
            self.rx_motor += 1
            self.motor_last_reply = self.t
            self._meas = (self.m.pos, self.m.vel, self.m.cur)
        else:
            self.rx_other += 1

    def _can_tick(self):
        """What the 1 kHz ISR puts on the bus this tick: a scan ping, or the command
        (motor on), or every 10th tick a zero-gain poll (motor off)."""
        sc = self._scan
        if sc is not None and sc["until"] is None:
            self._can_send(sc["next"])
            if sc["next"] >= sc["last"]:
                sc["next"] = sc["first"]; sc["pass"] += 1
                if sc["pass"] >= CAN_SCAN_PASSES:
                    sc["until"] = self.t + CAN_SCAN_SETTLE_S
            else:
                sc["next"] += 1
            return
        if sc is not None and self.t >= sc["until"]:
            ids = sorted(sc["seen"])[:16]
            pkt = P.CanScanPacket(type=P.PKT_CAN_SCAN, count=len(ids))
            for i, cid in enumerate(ids):
                pkt.ids[i] = cid
            self.out_queue.append(pkt.to_bytes())
            self._scan = None
        if self.enabled:
            self._poll_div = 0
            self._can_send(self.motor_id)
        else:
            self._poll_div += 1
            if self._poll_div >= 1000 // CAN_REST_POLL_HZ:
                self._poll_div = 0
                self._can_send(self.motor_id)

    def _calib_tick(self, dt, pos, vel):
        still = abs(vel) < 4.0
        st = self.calib
        def adv(s):
            self.calib = s; self._cal_stage_t = self.t; self._cal_still = 0.0; self.event(P.EV_CALIB_STAGE, s)
        if st in (P.CAL_SEEK_LEFT, P.CAL_SEEK_RIGHT):
            d = -1 if st == P.CAL_SEEK_LEFT else 1
            mag = max(1.0, min(3.5, abs(self._cal_torque)))
            mag += 1.0 * dt if abs(vel) < 30.0 else -1.0 * dt
            mag = max(1.0, min(3.5, mag))
            if still: self._cal_still += dt
            else: self._cal_still = 0.0
            self._cal_torque = d * mag
            self.torque_cmd = self._cal_torque
            self.m.step(dt, self.m.pos, 0, 0, 0, self._cal_torque)
            if self._cal_still >= 0.6 and mag >= 2.5:
                self._still_pos = pos; self._cal_torque = d * (mag + 1.0)
                adv(P.CAL_CONFIRM_LEFT if st == P.CAL_SEEK_LEFT else P.CAL_CONFIRM_RIGHT)
            if self.t - self._cal_stage_t > 15: self.do_trip(P.TRIP_CALIB_FAILED, "no stop found")
        elif st in (P.CAL_CONFIRM_LEFT, P.CAL_CONFIRM_RIGHT):
            left = st == P.CAL_CONFIRM_LEFT
            self.m.step(dt, self.m.pos, 0, 0, 0, self._cal_torque)
            if abs(pos - self._still_pos) > 2.0:
                adv(P.CAL_SEEK_LEFT if left else P.CAL_SEEK_RIGHT)
            elif self.t - self._cal_stage_t >= 0.6:
                if left:
                    self.limit_l = pos; self.left_cap = True; self._cal_torque = 1.0; adv(P.CAL_SEEK_RIGHT)
                else:
                    self.limit_r = pos; self.right_cap = True
                    if self.limit_r - self.limit_l < 60: self.do_trip(P.TRIP_CALIB_FAILED, "range too small"); return
                    self._cal_center = 0.5 * (self.limit_l + self.limit_r); self.sp_cmd = pos; adv(P.CAL_GO_CENTER)
        elif st == P.CAL_GO_CENTER:
            self._cal_center = 0.5 * (self.limit_l + self.limit_r)
            step = 40.0 * dt
            e = self._cal_center - self.sp_cmd
            self.sp_cmd += max(-step, min(step, e))
            self.m.step(dt, self.sp_cmd + self._zero_offset + self._soft_offset, 0, 25.0, 1.5, 0)
            if abs(e) < 0.01: adv(P.CAL_SETTLE)
        elif st == P.CAL_SETTLE:
            self.m.step(dt, self.sp_cmd + self._zero_offset + self._soft_offset, 0, 25.0, 1.5, 0)
            if abs(pos - self._cal_center) < 3.0 and abs(vel) < 4.0:
                if self.t - self._cal_stage_t >= 0.8:
                    c = self._cal_center
                    self._zero_offset = self.m.pos; self._soft_offset = c - pos
                    self.limit_l -= c; self.limit_r -= c
                    self.limits_valid = True; self.zeroed = True
                    self.sp_cmd = self.sp_target = 0.0; self.integral = 0.0; self.enable_t = self.t
                    self.event(P.EV_LIMITS_SET); self.event(P.EV_ZERO_SET)
                    adv(P.CAL_DONE); self.set_state(P.CS_HOLD)
            else:
                self._cal_stage_t = self.t

    # ---- packets out ------------------------------------------------------------------------------
    def telemetry(self) -> bytes:
        f = ((P.TF_ENABLED if self.enabled else 0) | (P.TF_ZEROED if self.zeroed else 0)
             | (P.TF_SWITCH_ARMED if self.f.switch_armed else 0) | (P.TF_TEST_RUNNING if self.test_type else 0)
             | (P.TF_LIMITS_VALID if self.limits_valid else 0) | (P.TF_FREESPIN if self.cs == P.CS_FREESPIN else 0))
        # what the Teensy knows is the last reply (nothing before the motor has answered)
        mpos, mvel, mcur = self._meas if self.motor_last_reply >= 0 else (self._zero_offset + self._soft_offset, 0.0, 0.0)
        pos = mpos - self._zero_offset - self._soft_offset
        if self.f.frozen_encoder:
            pos = 0.0
        return P.TelemetryPacket(type=P.PKT_TELEMETRY, ctrl_state=self.cs, flags=f, seq_setpoint=self.sp_seq & 0xFF,
                                 t_us=int(self.t * 1e6) & 0xFFFFFFFF, setpoint_deg=self.sp_cmd, position_deg=pos,
                                 velocity_deg_s=mvel, current_A=mcur, torque_cmd_Nm=self.torque_cmd).to_bytes()

    def health(self) -> bytes:
        w = 0
        def setn(i, s): nonlocal w; w |= (s & 3) << (2 * i)
        # rates over the health period, from the counters (health.cpp)
        t0, m0, o0 = self._hz_prev
        span = max(1e-3, self.t - t0)
        hz_m, hz_o = int((self.rx_motor - m0) / span), int((self.rx_other - o0) / span)
        self._hz_prev = (self.t, self.rx_motor, self.rx_other)
        valid = self.motor_last_reply >= 0
        age = 0xFFFF if not valid else min(0xFFFE, int((self.t - self.motor_last_reply) * 1000))
        bus_state = 3 if self.f.can_bus_off else 2 if self.tec >= 128 else 1 if self.tec > 96 else 0
        setn(P.HN_CAN_CTRL, P.HS_FAIL if bus_state == 3 else P.HS_BLOCKED if bus_state else P.HS_OK)
        setn(P.HN_CAN_TX, P.HS_BLOCKED if self.tec > 127 else P.HS_OK)
        setn(P.HN_CAN_RX_ANY, P.HS_OK if (hz_m + hz_o) else P.HS_BLOCKED if self.enabled else P.HS_UNKNOWN)
        if age == 0xFFFF or age > CAN_REPLY_TIMEOUT_S * 1000: m4 = P.HS_FAIL if self.enabled else P.HS_UNKNOWN
        elif self.enabled and hz_m < CAN_RX_LOW_HZ: m4 = P.HS_BLOCKED
        else: m4 = P.HS_OK
        setn(P.HN_CAN_MOTOR, m4)
        setn(P.HN_MOTOR_DATA, P.HS_UNKNOWN if not valid else P.HS_BLOCKED if self.f.frozen_encoder else P.HS_OK)
        setn(P.HN_MOTOR_CURRENT, P.HS_UNKNOWN if not valid else P.HS_OK if abs(self._meas[2]) < 21 else P.HS_BLOCKED)
        setn(P.HN_SWITCH, P.HS_OK if self.f.switch_armed else P.HS_BLOCKED)
        setn(P.HN_TRIP, P.HS_FAIL if self.cs == P.CS_TRIPPED else P.HS_OK)
        setn(P.HN_ISR, P.HS_FAIL if self.f.isr_overruns > 10 else P.HS_BLOCKED if self.f.isr_overruns else P.HS_OK)
        setn(P.HN_CTRL_READY, P.HS_OK if (self.zeroed and self.limits_valid) else P.HS_BLOCKED)
        setn(P.HN_CALIB, P.HS_FAIL if self.calib == P.CAL_FAILED else P.HS_BLOCKED if self.cs == P.CS_CALIB else P.HS_OK)
        hb_age = 0xFFFF if not self.pc_hb_last else min(0xFFFE, int((self.t - self.pc_hb_last) * 1000))
        setn(P.HN_PC_LINK, P.HS_UNKNOWN if hb_age == 0xFFFF else P.HS_FAIL if hb_age > 1000 else P.HS_OK)
        setn(P.HN_OLED, P.HS_OK)
        return P.HealthPacket(type=P.PKT_HEALTH, trip_code=self.trip, calib_stage=self.calib, ctrl_state=self.cs,
                              t_ms=int(self.t * 1000) & 0xFFFFFFFF, node_states=w,
                              can_rx_motor_hz=hz_m, can_rx_other_hz=hz_o,
                              can_tec=self.tec, can_rec=0, can_bus_state=bus_state,
                              isr_overruns=self.f.isr_overruns, loop_hz=1000, pc_hb_age_ms=hb_age,
                              reserved=0, motor_age_ms=age).to_bytes()

    def config(self) -> bytes:
        return P.ConfigEchoPacket(type=P.PKT_CONFIG_ECHO, motor_id=self.motor_id, zeroed=int(self.zeroed),
                                  limits_valid=int(self.limits_valid), kp=self.kp, kd=self.kd, ki=self.ki,
                                  tff_Nm=self.tff, limit_left_deg=self.limit_l, limit_right_deg=self.limit_r).to_bytes()

    def handle(self, payload: bytes):
        pkt = P.decode(payload)
        if pkt is None:
            return
        k = payload[0]
        if not self.f.heartbeat_deaf:
            self.pc_hb_last = self.t
        if k == P.PKT_HEARTBEAT:
            if not (pkt.flags & P.HB_UI_ALIVE) and self.cs in (P.CS_TRAJ, P.CS_TEST):
                self.command(P.CMD_DISABLE, 0, 0)
        elif k == P.PKT_GAINS:
            self.kp, self.kd, self.ki, self.tff = pkt.kp, pkt.kd, pkt.ki, pkt.tff_Nm
            self.out_queue.append(self.config())
        elif k == P.PKT_SETPOINT:
            if self.zeroed:
                self.sp_target = pkt.pos_deg; self.sp_seq = pkt.seq; self.sp_last = self.t
        elif k == P.PKT_MODE_REQUEST:
            self.mode_req = pkt.mode if pkt.sticky else P.MODE_AUTO
        elif k == P.PKT_COMMAND:
            self.command(pkt.cmd, pkt.arg, pkt.farg)
            if pkt.cmd in (P.CMD_REQ_CONFIG, P.CMD_SET_ZERO, P.CMD_CAPTURE_LEFT, P.CMD_CAPTURE_RIGHT):
                self.out_queue.append(self.config())
        elif k == P.PKT_TEST_START:
            self.start_test(pkt.test_type, pkt.amplitude_deg, pkt.duration_s, pkt.param)
        elif k == P.PKT_LIMITS:
            if pkt.right_deg > pkt.left_deg + 60:
                self.limit_l, self.limit_r = pkt.left_deg, pkt.right_deg
                self.limits_valid = self.left_cap = self.right_cap = True
                self.event(P.EV_LIMITS_SET)
            self.out_queue.append(self.config())



class SimTransport(Transport):
    """Runs a SimTeensy on a thread; the Link reads/writes bytes as with a serial port."""
    name = "sim:teensy"

    def __init__(self, faults: Optional[SimFaults] = None, realtime: float = 1.0):
        self.sim = SimTeensy(faults)
        self._rx = bytearray()            # bytes for the PC to read
        self._lock = threading.Lock()
        self._parser = P.FrameParser()
        self._seq = 0
        self._open = False
        self._thread: Optional[threading.Thread] = None
        self.realtime = realtime

    def open(self):
        self._open = True
        self._thread = threading.Thread(target=self._run, name="sim", daemon=True)
        self._thread.start()

    def close(self):
        self._open = False
        if self._thread:
            self._thread.join(timeout=1.0)

    @property
    def is_open(self):
        return self._open

    def write(self, data: bytes):
        with self._lock:
            for payload in self._parser.feed(data):
                self.sim.handle(payload)

    def read(self, max_bytes, timeout_s):
        t_end = time.monotonic() + timeout_s
        while True:
            with self._lock:
                if self._rx:
                    out = bytes(self._rx[:max_bytes]); del self._rx[:max_bytes]
                    return out
            if time.monotonic() >= t_end:
                return b""
            time.sleep(0.002)

    def _emit(self, payload: bytes):
        self._rx += P.encode(payload, self._seq)
        self._seq = (self._seq + 1) & 0xFF

    def _run(self):
        dt = 0.001
        next_t = time.perf_counter()
        n = 0
        while self._open:
            with self._lock:
                self.sim.tick(dt)
                n += 1
                if n % 5 == 0: self._emit(self.sim.telemetry())
                if n % 50 == 0: self._emit(self.sim.health())
                if n % 200 == 0: self._emit(self.sim.config())
                for ev in self.sim.events:
                    e = P.EventPacket(type=P.PKT_EVENT, code=ev[0], arg=ev[1], t_ms=ev[3])
                    e.text = ev[2].encode()[:19]
                    self._emit(e.to_bytes())
                self.sim.events.clear()
                for q in self.sim.out_queue:
                    self._emit(q)
                self.sim.out_queue.clear()
            next_t += dt / self.realtime
            delay = next_t - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            elif delay < -0.1:
                next_t = time.perf_counter()
