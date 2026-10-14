# Health tree reference

Generated from `pc/steering/health/model.py` — edit there.

## Group M — Motor & CAN

*Can the Teensy talk to a powered, sane motor?*

| Node | OK means | When not OK | Fix | Blocks |
|---|---|---|---|---|
| **M1** CAN controller (fw) | FlexCAN3 is error-active with low error counters. | BLOCKED: error counters high (noise, bad termination). FAIL: bus-off - the transceiver is not seeing a valid bus at all. | Check transceiver power and STBY pin, CAN_H/CAN_L wiring, 120 ohm termination at both ends, and that the motor is on the same bus. | Hold (turn the motor on), Free-spin, Run waveform, Play on motor, Run step or relay test, Find end stops and zero, Centre and zero, External setpoint stream (planner / remote) |
| **M2** CAN transmit (fw) | Command frames are leaving the mailbox (no TX overflow, TEC low). | Frames are queued but not acknowledged: nobody on the bus ACKs. Usually means M1-level wiring or the motor is unpowered. | Same checks as M1; also confirm TX_SIZE_16 and that nothing else writes CAN from the main loop. | Hold (turn the motor on), Free-spin, Find end stops and zero |
| **M3** Bus activity (fw) | The Teensy has received at least one frame recently (from anyone). | Silence on the bus. Either nothing is powered, or RX wiring is broken while TX looks fine. | Power the motor (it only talks when commanded). Swap CAN_H/CAN_L if TX ACKs but RX is dead. | Hold (turn the motor on), Free-spin, Run waveform, Play on motor, Run step or relay test, Find end stops and zero, Centre and zero, External setpoint stream (planner / remote) |
| **M4** Motor replies (fw) | Reply frames from the configured motor id arrive at the expected rate (~1 kHz while enabled). | BLOCKED (in REST): the motor has never answered / stopped answering - unpowered, wrong CAN id, or in a fault. FAIL (enabled): replies stopped mid-run (power dropout) -> TRIP_CAN_LOST. | Check the 24 V supply, run the CAN scanner (Settings) to find the real id, power-cycle the motor. | Hold (turn the motor on), Zero here, Free-spin, Run waveform, Play on motor, Run step or relay test, Find end stops and zero, Capture end stop, Centre and zero, External setpoint stream (planner / remote) |
| **M5** Motor data sane (fw) | Position/velocity values decode to finite numbers and change over time. | Replies decode to NaN or the payload is frozen (encoder or driver fault, or wrong reply layout). | Power-cycle the motor; if it persists, re-run the motor's own encoder calibration (datasheet section 4.2). | Hold (turn the motor on), Zero here, Free-spin, Run waveform, Play on motor, Run step or relay test, Find end stops and zero, Capture end stop, Centre and zero, External setpoint stream (planner / remote) |
| **M6** Motor current (fw) | |current| is below 70 % of CURRENT_CUTOFF_A. | BLOCKED: running hot (near the cutoff). FAIL: over the cutoff - a trip will follow. | Lower Kp/Ki, check for a jam, verify MOTOR_T_* ranges in config.h match the datasheet. | Run waveform, Play on motor, Run step or relay test, External setpoint stream (planner / remote) |

## Group S — Safety

*Is anything physically or by latch preventing torque?*

| Node | OK means | When not OK | Fix | Blocks |
|---|---|---|---|---|
| **S1** Idle switch (fw) | The physical idle switch (pin 22 -> GND) is closed: motor may be enabled. | Switch open = IDLE. The firmware will not enable, and opening it while enabled trips the motor. | Close the switch. If it reads IDLE with the switch closed, check the wire to pin 22 / GND. | Hold (turn the motor on), Free-spin, Run waveform, Play on motor, Run step or relay test, Find end stops and zero, Centre and zero, External setpoint stream (planner / remote) |
| **S2** No trip latched (fw) | No safety trip is latched. | A trip is latched (the rail shows the trip name and explanation). The motor is in REST until cleared. | Fix the cause, then Clear trip. Trips are listed in docs/SAFETY.md. | Hold (turn the motor on), Free-spin, Run waveform, Play on motor, Run step or relay test, Find end stops and zero, Centre and zero, External setpoint stream (planner / remote) |

## Group T — Teensy controller

*Is the control loop on time and ready for absolute-position work?*

| Node | OK means | When not OK | Fix | Blocks |
|---|---|---|---|---|
| **T1** Control loop timing (fw) | The 1 kHz tick runs on time with no overruns. | Overruns or low loop rate: the ISR is being starved (I2C stall, long main-loop work) or is too expensive. | Check DISPLAY_HZ / OLED wiring; report isr_overruns from the Health page counters. | Hold (turn the motor on), Run waveform, Play on motor, Run step or relay test, Find end stops and zero, External setpoint stream (planner / remote) |
| **T2** Zeroed + limits (fw) | Zero has been set and end-stop limits are valid: absolute positions mean something. | Not zeroed and/or limits unknown. Trajectories, playback and tests are refused because 0 deg is meaningless. | Calibrate page: Find end stops and zero, or set them by hand. | Wheel angle slider, Run waveform, Play on motor, Run step or relay test, External setpoint stream (planner / remote) |
| **T3** Calibration (fw) | No calibration running and the last one did not fail. | BLOCKED: calibration in progress (other motion is refused). FAIL: last calibration failed. | Wait for it to finish, or abort. On FAIL read the event text (seek timeout / range too small). | Run waveform, Play on motor, Run step or relay test, External setpoint stream (planner / remote) |
| **T4** CCM screen (fw) | The SSD1309 answered on I2C and is being refreshed. | No OLED (not fatal: the UI shows the same information). | Check I2C wiring (18/19) and address 0x3C. | — |

## Group C — Comms (PC - Teensy)

*Is the PC talking to the Teensy, and does the Teensy hear the PC?*

| Node | OK means | When not OK | Fix | Blocks |
|---|---|---|---|---|
| **C1** Serial port (pc) | The serial port is open. | Port not open: not connected, wrong port, or the OS pulled the device. | Pick the Teensy in Connect; re-plug USB; on Linux check dialout group. | Disconnect, Hold (turn the motor on), Turn the motor off, Clear trip, Zero here, Free-spin, Hold (grip again after free-spin), Apply gains, Wheel angle slider, Hold (stop following, hold here), Run waveform, Play on motor, Run step or relay test, Record, Record a hand motion (free-spin), Find end stops and zero, Abort calibration, Capture end stop, Centre and zero, Scan the CAN bus / set id, External setpoint stream (planner / remote) |
| **C2** Bytes arriving (pc) | Bytes are arriving on the port. | Port open but silent: the Teensy is not running this firmware, is in the bootloader, or the cable is charge-only. | Press the Teensy reset button; flash firmware; try another cable. | Hold (turn the motor on), Zero here, Free-spin, Wheel angle slider, Run waveform, Play on motor, Run step or relay test, Record a hand motion (free-spin), Find end stops and zero, Capture end stop, Centre and zero, External setpoint stream (planner / remote) |
| **C3** Valid frames (pc) | Frames decode with good CRC at a healthy rate and few drops. | Bytes arrive but do not frame: wrong baud/protocol version, or a noisy link with many CRC errors. | Match PROTOCOL_VERSION on both sides; check the USB cable. | Hold (turn the motor on), Zero here, Free-spin, Wheel angle slider, Run waveform, Play on motor, Run step or relay test, Record a hand motion (free-spin), Find end stops and zero, Capture end stop, Centre and zero, External setpoint stream (planner / remote) |
| **C4** Telemetry fresh (pc) | A TelemetryPacket arrived in the last 100 ms. | Frames arrive but no telemetry: firmware stuck before its main loop, or a different device is on the port. | Reset the Teensy; check the port is the Teensy. | Hold (turn the motor on), Zero here, Free-spin, Wheel angle slider, Run waveform, Play on motor, Run step or relay test, Record, Record a hand motion (free-spin), Find end stops and zero, Capture end stop, Centre and zero, External setpoint stream (planner / remote) |
| **C5** Teensy hears PC (pc) | The Teensy reports our packets as fresh (round trip proven). | We receive, but the Teensy does not hear us: TX side of the USB link is broken or the firmware's parser is rejecting our frames. | Check CRC/version; the firmware refuses control when this is down (TRIP_PC_LINK_LOST). | Hold (turn the motor on), Turn the motor off, Clear trip, Zero here, Free-spin, Hold (grip again after free-spin), Apply gains, Wheel angle slider, Hold (stop following, hold here), Run waveform, Play on motor, Run step or relay test, Record a hand motion (free-spin), Find end stops and zero, Capture end stop, Centre and zero, Scan the CAN bus / set id, External setpoint stream (planner / remote) |
| **C6** Firmware health fresh (pc) | HealthPackets are arriving (the M/S/T groups are current). | No HealthPacket for > 500 ms: M/S/T are stale and may be wrong. | Usually accompanies C4; same fixes. | Hold (turn the motor on), Zero here, Free-spin, Wheel angle slider, Run waveform, Play on motor, Run step or relay test, Record a hand motion (free-spin), Find end stops and zero, Capture end stop, Centre and zero, External setpoint stream (planner / remote) |

## Group D — Data & services

*Will what happens now be recorded, stored and served; is the UI responsive?*

| Node | OK means | When not OK | Fix | Blocks |
|---|---|---|---|---|
| **D1** Recorder (pc) | Recorder idle or recording without dropped samples. | FAIL: recording but samples are being dropped (disk slow) or the writer thread died. | Check free disk space; see data/logs/app.log. | Run waveform, Play on motor, Run step or relay test |
| **D2** Store (pc) | The data folder is writable and the catalog database opens. | Cannot write to the data folder or the SQLite catalog is locked/corrupt. | Check permissions / free space; delete data/catalog.sqlite-journal if left over from a crash. | Run waveform, Play on motor, Run step or relay test, Record, Record a hand motion (free-spin) |
| **D3** Web hub (pc) | The web hub is running (browser UI, phones, planner can connect). | Hub not running (BLOCKED; fine unless you want the web UI / phone capture / planner stream). | Start it from Settings or `python -m steering ui --server`. | Phone capture |
| **D4** Phone capture (pc) | A phone is connected and time-synced. | No phone connected (BLOCKED) or its clock offset is unstable (FAIL). | Open the hub URL on the phone, allow camera/motion. | Phone capture |
| **D5** UI responsiveness (pc) | The UI frame loop is keeping up (< 250 ms per frame). | UI frames are slow or stalled: a callback is blocking. If it stalls > 1 s the firmware treats the PC as dead. | Look for the last traceback in data/logs/app.log; never block in callbacks. | Run waveform, Play on motor, External setpoint stream (planner / remote) |

