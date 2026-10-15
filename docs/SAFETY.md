# Safety

Principle: **the firmware owns safety; the PC can only make things safer.** All thresholds are named
constants at the top of `firmware/teensy/src/config.h` and are deliberately not settable from the UI.

## Layers

| Layer | Mechanism | Where |
|---|---|---|
| 0 | **Idle switch** (pin 22, pull-up, open = IDLE). Enable refused while idle; opening it while enabled trips. Broken wire = idle. | `control.cpp::sample_switch`, `run_safety` |
| 1 | **Latched trips** → REST (`0xFD`, MOSFETs off) until `CMD_CLEAR_TRIP`: overspeed, stall, overcurrent, switch opened, motor CAN lost, PC lost (TRAJ), past end stop, calibration failed, ISR overrun | `run_safety`, `trip()` |
| 2 | **Motion shaping** that makes a bad command harmless: setpoint slew limit (`SETPOINT_SLEW_DEG_S`), gain ramp after any (re)grip (`GAIN_RAMP_*`), integral clamp + leak, enable grace (`ENABLE_GRACE_MS`), limits with margin (`LIMIT_MARGIN_DEG`) | `control_tick` |
| 3 | **Liveness**: any valid PC packet = alive; TRAJ with PC silent `PC_CONTROL_LOSS_MS` → trip; TEST → ends (HOLD); setpoint stream stale 250 ms → HOLD; heartbeat `HB_UI_ALIVE` dropped when the UI stalls > 1 s → TRAJ/TEST → DISABLE | `comms.cpp::dispatch`, `run_safety`, `resolve_mode` |
| 4 | **Single CAN writer**: only the 1 kHz ISR writes CAN (commands, the motor-off poll, scan pings); specials are queued by the main loop. (The old firmware's reentrant `CAN.write` from the ISR *and* main loop killed CAN entirely.) | `can_motor.cpp` |
| 5 | **PC gating** (`health/gating.py`): nothing is sent unless the health tree allows it; refusals carry reasons | PC |
| 6 | **PC process hygiene**: every UI callback is wrapped (`ui/safe.py`), the link/heartbeat runs on its own thread, `atexit` + SIGINT/SIGTERM send DISABLE, `Link.stop()` sends DISABLE before closing the port | PC |
| 7 | **Calibration bounds**: seek torque ≤ `CAL_SEEK_TORQUE_MAX_NM` (3.5 Nm), creep speed regulated to `CAL_SEEK_VEL_DEG_S`, per-stage timeouts, range sanity | `run_calibration` |
| 8 | Motor-side: BM-18 board current protection 35 A / 200 ms | motor firmware |

## Trip reference

The app calls a latched trip a **safety stop** and names it in plain words (pc/steering/words.py), with
the value the Teensy measured, e.g. "Safety stop: Motor current too high (31.2 A)".

| Trip (code) | Operator sees | Condition | Typical cause | Recovery |
|---|---|---|---|---|
| OVERSPEED | Wheel turned too fast (1502 deg/s) | \|v\| > `VELOCITY_CUTOFF_DEG_S` (1430°/s) | runaway gains, external shove | reset, lower Kp / raise Kd |
| STALL | Wheel stuck: could not reach the setpoint (34 deg off target) | error > `STALL_ERROR_DEG` for `STALL_TIME_MS` while servoing | wheel blocked, gains too low to move it | remove obstruction / raise gains |
| OVERCURRENT | Motor current too high (31.2 A) | \|i\| > `CURRENT_CUTOFF_A` for `CURRENT_TIME_MS` | jam, wrong torque range, too-high gains | check mechanics, gains |
| SWITCH_OPENED | Idle switch turned on while running (pin 22 open) | idle switch opened while enabled | human hit the switch | turn the switch off, reset |
| CAN_LOST | Motor stopped replying on CAN | no motor reply for `CAN_REPLY_TIMEOUT_MS` while enabled | motor power dropout, wiring | fix power/wiring, reset |
| PC_LINK_LOST | Laptop stopped sending setpoints (612 ms silent) | PC silent `PC_CONTROL_LOSS_MS` during TRAJ | UI frozen, USB unplugged | reconnect, reset |
| LIMIT | Wheel went past an end stop (16 deg past L) | measured position `LIMIT_TRIP_OVERSHOOT_DEG` past a calibrated stop | limits wrong, zero slipped, mechanical slip | recalibrate |
| CALIB_FAILED | Calibration failed (no stop found) | seek/centre/settle timeout, range < `CAL_MIN_RANGE_DEG` | wheel can't reach a stop at 3.5 Nm, something in the way | reset, check mechanics, adjust `CAL_*` |
| PC_SHUTDOWN | Laptop app closed | PC app exited and asked for REST | normal exit | re-enable |
| ISR_OVERRUN | Teensy control loop fell behind | ≥ `ISR_OVERRUN_TRIP` overruns in one health period | I2C stall, firmware bug | report (T1 counters) |

Trips are latched: the Teensy stays in TRIPPED (motor resting) until **Reset safety stop**, which only goes to
REST (Motor off) — you then press **Position control** deliberately. `DISABLE` is always accepted (even while tripped).

## What the PC must never do

* Send gains/setpoints without the link round trip proven (C5).
* Start a stream unless the motor is in HOLD, zeroed, limits valid, no trip, switch armed, recorder OK.
* Crash. (`safe()` everywhere; the frame loop itself is wrapped.)
* Exit without sending DISABLE.
