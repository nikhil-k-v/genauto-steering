# Migration from the previous software (what changed and why)

Previous generations:

* **MotorControlWebGUI** (Apr 2026): single `teensyController.cpp`, ASCII `T,…`/`M,…` serial lines, a
  browser GUI; `arduinoJoystick.cpp`.
* **steering_tuner** (Jul–Oct 2026, built in chat): Teensy `main.cpp` + `protocol.h`, Arduino bridge,
  Dear PyGui `ui.py` + `playback.py` + `controller.py` + `link.py` + `analyzer.py`, CSV logs + ledger,
  XOR-checked frames, A–F watchdog grid.

This repo keeps the hardware (minus the Arduino bridge), the MIT-style CAN driver, the Dear PyGui choice
and the logo splash, and replaces everything else.

## Problems found in the old code and what replaced them

| # | Old behaviour / bug | New |
|---|---|---|
| 1 | A–F "watchdog" bits were six booleans with no definition of what each one measured, why it mattered, or what it disabled. | Health **tree** (`health/model.py`): 23 checks in 5 typed groups (**C** link, **S** safety, **M** motor and CAN, **T** Teensy, **D** data), each with ok/bad/fix text and the actions it blocks; shown in the always-visible **rail** as the signal chain Laptop, USB, Teensy, CAN, Motor (+ Safety, Web hub) where any row that isn't OK names its failing check and reason; the same packed word drives the OLED; generated reference doc. |
| 1A | Nothing was logged about status; after a failure there was only the CSV. | Transition log + snapshots (`logs/health-*.jsonl`), app log with tracebacks, and **every recording carries `health.jsonl` + `events.jsonl`** (firmware events incl. *rejection reasons*, PC actions incl. *blocked* ones) and a `health_summary`. |
| 1B | UI could send anything; the Teensy silently ignored or acted. | `gating.py`: one declarative requirement list per action, evaluated every frame → controls disabled with the exact reasons and **literally wired**: hovering a control draws a trunk-and-branch line to the rail rows it depends on (amber/red = blocking); hovering a check on the Health page draws lines to the controls it gates. The controller refuses with the same reasons; the Teensy answers every command with ACCEPTED/REJECTED + reason. |
| 2 | Mode/PID state was unclear ("sticky" PC override vs joystick vs test); many test widgets. | Explicit firmware `CS_*` state (REST/HOLD/FOLLOWING/TEST/FREESPIN/CALIB/TRIPPED) shown everywhere; `ConfigEchoPacket` echoes the gains **actually in use** (UI shows "pending…" until confirmed); exactly two tests. |
| 3 | Playbacks were unnamed/unlinked; a flat `logs/` dir and a ledger CSV. | `Store` with SQLite catalog + `meta.json` per folder; playbacks are children (`<name>_pbNN`), library sorts by recency / pinned / playback count; health stored with each file. |
| 4 | Nested scroll regions, fixed plot sizes, hard-to-use playback window; everything in one font. | Left rail + six pages (Drive, Library, Tune, Calibrate, Health, Settings); plots sized from the viewport; only lists scroll. A planned light palette where colour means status only; Barlow (tabular figures baked in) for the interface and IBM Plex Mono only for paths, logs and counters; buttons by role (primary ink, secondary ruled, quiet text, danger red), a segmented Hold / Free-spin control, checkboxes for preferences (fonts bundled in `ui/fonts/`). |
| 5 | No date/time structure in file names; everything in one folder. | `recordings/<collection>/<date>/<HHMMSS>_<kind>_<name>/` — user-defined collection + automatic date, nothing deeper. |
| 6 | Zero was "move by hand, click Set Zero"; no limits. | Firmware auto-calibration (velocity-regulated creep, friction-vs-stop confirmation, centre, zero with software offset so centre is exactly 0); manual capture L/R + go-centre-zero; limits enforced with margin and trip. |
| 7 | Several UI exceptions killed the app (and the heartbeat with it). | `ui/safe.py` wraps every callback and the frame loop; link/heartbeat on its own thread; UI stall → `HB_UI_ALIVE` dropped → firmware leaves TRAJ/TEST; `atexit`/signals send DISABLE. |
| 8 | Waveform generators and unused inputs dominated the Trajectory panel; graph meanings unclear. | Hand-recorded motion + playback is the primary flow; generators collapsed under "tuning aids"; every plot axis is labelled with units; `target` vs `setpoint` vs `position` are distinct series (what PC asked / what Teensy commanded / what happened). |
| 9 | No way to add devices without touching the serial path. | `Bus` + `Controller` seam; optional web hub (FastAPI/WS) beside the UI: browser UI (system/connectivity, recordings viewer, data handling, docs with diagrams), phone video/IMU capture into the recording folder, planner setpoint stream; `devices/base.py` interface for the throttle robot. |
| 10 | Teensy OLED showed watchdog letters without detail. | OLED shows the `M S T C D` boxes with the first bad node index (`M4`), state, trip/calib text, dial with limits. The Arduino joystick / NRF24 wireless bridge was removed entirely (firmware, protocol packets, health nodes, docs). |

### Bugs found while reading the old code

* **Torque range mismatch.** `teensyController.cpp` used `T_MIN/T_MAX = ±6 Nm` for the 12-bit torque field; the BM-18 datasheet specifies **±18 Nm**. With ±6 the encoder sent 0xFFF for "6 Nm", which the motor interprets as 18 Nm — every torque feed-forward (and the integral term) was 3× what the code believed. `config.h` now uses ±18. **Verify on hardware** (see below) — if your motor firmware actually uses ±6, change `MOTOR_T_*` in one place.
* **Reentrant CAN write from the ISR** (the main CAN-death bug of steering_tuner) is structurally impossible now: `can_motor_tick_send()` is the only writer and is only called from the ISR; main-loop requests are queued as a pending special.
* **Reply parsing**: id echo in `buf[0]`, position from `buf[1]` — kept from the fix, documented in `can_motor.cpp`.
* **Enable grace / slew / gain ramp** kept; **limit trip is suppressed during calibration** (finding the stops necessarily exceeds the default limits) — caught by the simulator test.
* **PC-loss during a Teensy-run test** used to trip the motor after two missed 5 Hz heartbeats; now any PC packet counts as liveness, the window is 600 ms, and TEST ends gracefully (TRAJ still trips).
* **Frame resync**: an `AB` seen while waiting for `CD` restarts the sync instead of dropping the frame (caught by `test_frame_roundtrip_and_stats`).
* **XOR checksum** replaced by CRC-8 (same cost, catches burst errors); sequence numbers count drops.
* **Protocol v3** (this revision) removes the joystick/bridge packets and the bridge health node; controller states and health node indices were renumbered — flash firmware and PC from the same commit.

## Verify on hardware (first session with the new firmware)

0. Confirm the unit: the project page says 8/24 N·m (BM-24), earlier notes said BM-18. Set
   `MOTOR_MODEL` in `config.h` to match the label on the actuator.

1. Flash the Teensy, connect, motor off: expect the USB row green, the Motor row `no reply` (amber), Safety
   per switch. Power the motor: Motor green, `can_rx_motor_hz` ≈ 0 in REST (the motor only answers commands).
2. Hold (motor must be free to move): state Holding, `can_rx_motor_hz` ≈ 1000, T1 ≈ 1000 Hz, 0 overruns.
3. **Torque scale check**: in HOLD with Kp=Kd=0, set Tff = 1.0 Nm and apply: the wheel should push
   with ~1 Nm (gently). If it pushes ~3× harder, your motor uses ±6 Nm — set `MOTOR_T_MIN/MAX_NM` to ±6.
   Also compare `current_A` against the bench supply current.
4. Calibrate with a hand on the switch; watch the stage line. If seek times out at 3.5 Nm, raise
   `CAL_SEEK_TORQUE_MAX_NM` modestly.
5. Open the switch while HOLD → immediate TRIP SWITCH_OPENED, banner explains, Enable greyed until cleared.
6. Pull USB during a trajectory → wheel goes limp (TRIP PC_LINK_LOST); replug → D reconnects; Clear trip.

## Things intentionally not carried over

* The ledger CSV (replaced by the catalog + metrics in `meta.json`).
* The web GUI (laptop app stays a Python desktop UI; the hub serves phones only).
* Dynamic safety thresholds via the UI (never existed; still intentionally absent).
