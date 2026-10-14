# Health tree reference

Generated from `pc/steering/health/model.py` — edit there.

## Group A — Motor & CAN

*Can the Teensy talk to a powered, sane motor?*

| Node | OK means | When not OK | Fix | Blocks |
|---|---|---|---|---|
| **A1** CAN controller (fw) | FlexCAN3 is error-active with low error counters. | BLOCKED: error counters high (noise, bad termination). FAIL: bus-off - the transceiver is not seeing a valid bus at all. | Check transceiver power and STBY pin, CAN_H/CAN_L wiring, 120 ohm termination at both ends, and that the motor is on the same bus. | Enable motor, Free-spin, Run trajectory, Play back recording, Run tuning test, Auto-calibrate end stops, Go to center & zero |
| **A2** CAN transmit (fw) | Command frames are leaving the mailbox (no TX overflow, TEC low). | Frames are queued but not acknowledged: nobody on the bus ACKs. Usually means A1-level wiring or the motor is unpowered. | Same checks as A1; also confirm TX_SIZE_16 and that nothing else writes CAN from the main loop. | Enable motor, freespin, Auto-calibrate end stops |
| **A3** Bus activity (fw) | The Teensy has received at least one frame recently (from anyone). | Silence on the bus. Either nothing is powered, or RX wiring is broken while TX looks fine. | Power the motor (it only talks when commanded). Swap CAN_H/CAN_L if TX ACKs but RX is dead. | Enable motor, Free-spin, Run trajectory, Play back recording, Run tuning test, Auto-calibrate end stops, Go to center & zero |
| **A4** Motor replies (fw) | Reply frames from the configured motor id arrive at the expected rate (~1 kHz while enabled). | BLOCKED (in REST): the motor has never answered / stopped answering - unpowered, wrong CAN id, or in a fault. FAIL (enabled): replies stopped mid-run (power dropout) -> TRIP_CAN_LOST. | Check the 24 V supply, run the CAN scanner (Settings) to find the real id, power-cycle the motor. | Enable motor, Set zero here, Free-spin, Run trajectory, Play back recording, Run tuning test, Auto-calibrate end stops, Capture end stop, Go to center & zero |
| **A5** Motor data sane (fw) | Position/velocity values decode to finite numbers and change over time. | Replies decode to NaN or the payload is frozen (encoder or driver fault, or wrong reply layout). | Power-cycle the motor; if it persists, re-run the motor's own encoder calibration (datasheet §4.2). | Enable motor, Set zero here, Free-spin, Run trajectory, Play back recording, Run tuning test, Auto-calibrate end stops, Capture end stop, Go to center & zero |
| **A6** Motor current (fw) | |current| is below 70 % of CURRENT_CUTOFF_A. | BLOCKED: running hot (near the cutoff). FAIL: over the cutoff - a trip will follow. | Lower Kp/Ki, check for a jam, verify MOTOR_T_* ranges in config.h match the datasheet. | Run trajectory, Play back recording, Run tuning test |

## Group B — Safety

*Is anything physically or by latch preventing torque?*

| Node | OK means | When not OK | Fix | Blocks |
|---|---|---|---|---|
| **B1** Idle switch (fw) | The physical idle switch (pin 22 -> GND) is closed: motor may be enabled. | Switch open = IDLE. The firmware will not enable, and opening it while enabled trips the motor. | Close the switch. If it reads IDLE with the switch closed, check the wire to pin 22 / GND. | Enable motor, Free-spin, Run trajectory, Play back recording, Run tuning test, Auto-calibrate end stops, Go to center & zero |
| **B2** No trip latched (fw) | No safety trip is latched. | A trip is latched (see the trip name and explanation in the Health panel). The motor is in REST until cleared. | Fix the cause, then Clear Trip. Trips are listed in docs/SAFETY.md. | Enable motor, Free-spin, Run trajectory, Play back recording, Run tuning test, Auto-calibrate end stops, Go to center & zero |

## Group C — Controller

*Is the Teensy control loop ready to do absolute-position work?*

| Node | OK means | When not OK | Fix | Blocks |
|---|---|---|---|---|
| **C1** Control loop timing (fw) | The 1 kHz tick runs on time with no overruns. | Overruns or low loop rate: the ISR is being starved (I2C stall, long main-loop work) or is too expensive. | Check DISPLAY_HZ / OLED wiring; report isr_overruns from the Health panel. | Enable motor, Run trajectory, Play back recording, Run tuning test, Auto-calibrate end stops |
| **C2** Zeroed + limits (fw) | Zero has been set and end-stop limits are valid: absolute positions mean something. | Not zeroed and/or limits unknown. Trajectories, playback and tests are refused because 0 deg is meaningless. | Run Calibrate (auto) or capture L/R stops and Go-Center-Zero in the Calibration panel. | Setpoint slider, Run trajectory, Play back recording, Run tuning test |
| **C3** Calibration (fw) | No calibration running and the last one did not fail. | BLOCKED: calibration in progress (other motion is refused). FAIL: last calibration failed. | Wait for it to finish, or abort. On FAIL read the event text (seek timeout / range too small). | Run trajectory, Play back recording, Run tuning test |
| **C4** Teensy OLED (fw) | The SSD1309 answered on I2C and is being refreshed. | No OLED (not fatal: the UI shows the same information). | Check I2C wiring (18/19) and address 0x3C. | — |

## Group D — PC link

*Is the PC talking to the Teensy, and does the Teensy hear the PC?*

| Node | OK means | When not OK | Fix | Blocks |
|---|---|---|---|---|
| **D1** Serial port (pc) | The serial port is open. | Port not open: not connected, wrong port, or the OS pulled the device. | Pick the Teensy in Connect; re-plug USB; on Linux check dialout group. | Disconnect, Enable motor, Disable motor, Clear trip, Set zero here, Free-spin, Re-grip, Apply gains, Setpoint slider, Hold here, Run trajectory, Play back recording, Run tuning test, Record, Record wheel motion (free-spin), Auto-calibrate end stops, Abort calibration, Capture end stop, Go to center & zero, Joystick mode, CAN scan |
| **D2** Bytes arriving (pc) | Bytes are arriving on the port. | Port open but silent: the Teensy is not running this firmware, is in the bootloader, or the cable is charge-only. | Press the Teensy reset button; flash firmware; try another cable. | Enable motor, Set zero here, Free-spin, Setpoint slider, Run trajectory, Play back recording, Run tuning test, Record wheel motion (free-spin), Auto-calibrate end stops, Capture end stop, Go to center & zero, Joystick mode |
| **D3** Valid frames (pc) | Frames decode with good CRC at a healthy rate and few drops. | Bytes arrive but do not frame: wrong baud/protocol version, or a noisy link with many CRC errors. | Match PROTOCOL_VERSION on both sides; check the USB cable. | Enable motor, Set zero here, Free-spin, Setpoint slider, Run trajectory, Play back recording, Run tuning test, Record wheel motion (free-spin), Auto-calibrate end stops, Capture end stop, Go to center & zero, Joystick mode |
| **D4** Telemetry fresh (pc) | A TelemetryPacket arrived in the last 100 ms. | Frames arrive but no telemetry: firmware stuck before its main loop, or a different device is on the port. | Reset the Teensy; check the port is the Teensy, not the Arduino. | Enable motor, Set zero here, Free-spin, Setpoint slider, Run trajectory, Play back recording, Run tuning test, Record, Record wheel motion (free-spin), Auto-calibrate end stops, Capture end stop, Go to center & zero, Joystick mode |
| **D5** Teensy hears PC (pc) | The Teensy reports our heartbeat as fresh (round trip proven). | We receive, but the Teensy does not hear us: TX side of the USB link is broken or the firmware's parser is rejecting our frames. | Check CRC/version; the firmware refuses control when this is down (TRIP_PC_LINK_LOST). | Enable motor, Disable motor, Clear trip, Set zero here, Free-spin, Re-grip, Apply gains, Setpoint slider, Hold here, Run trajectory, Play back recording, Run tuning test, Record wheel motion (free-spin), Auto-calibrate end stops, Capture end stop, Go to center & zero, Joystick mode, CAN scan |
| **D6** Firmware health fresh (pc) | HealthPackets are arriving (the A/B/C groups are current). | No HealthPacket for > 500 ms: A/B/C are stale and may be wrong. | Usually accompanies D4; same fixes. | Enable motor, Set zero here, Free-spin, Setpoint slider, Run trajectory, Play back recording, Run tuning test, Record wheel motion (free-spin), Auto-calibrate end stops, Capture end stop, Go to center & zero, Joystick mode |

## Group E — Bridge

*Is the Arduino joystick/RF bridge alive?*

| Node | OK means | When not OK | Fix | Blocks |
|---|---|---|---|---|
| **E1** Bridge RF (fw) | The Teensy hears the Arduino bridge over NRF24. | No bridge packets at the Teensy. Joystick mode unavailable; in wireless mode the PC link is down. | Power the Arduino, check NRF24 wiring/channel 108, both radios on the same addresses. | Joystick mode |
| **E2** Bridge USB (pc) | The Arduino bridge is sending BridgeStatus to the PC (only when it is also on USB). | Not seen. Normal when the Arduino is not plugged into the PC. | Plug the Arduino in if you want its status here. | — |

## Group F — Data & services

*Will what happens now be recorded, stored and served?*

| Node | OK means | When not OK | Fix | Blocks |
|---|---|---|---|---|
| **F1** Recorder (pc) | Recorder idle or recording without dropped samples. | FAIL: recording but samples are being dropped (disk slow) or the writer thread died. | Check free disk space; see data/logs/app-*.log. | Run trajectory, Play back recording, Run tuning test |
| **F2** Store (pc) | The data folder is writable and the catalog database opens. | Cannot write to the data folder or the SQLite catalog is locked/corrupt. | Check permissions / free space; delete data/catalog.sqlite-journal if left over from a crash. | Run trajectory, Play back recording, Run tuning test, Record, Record wheel motion (free-spin) |
| **F3** Device hub (pc) | The optional server hub is running (phones / other devices can connect). | Hub not running (BLOCKED, fine unless you want phone capture). | Start it from Settings or `python -m steering ui --server`. | Phone capture |
| **F4** Phone capture (pc) | A phone is connected and time-synced. | No phone connected (BLOCKED) or its clock offset is unstable (FAIL). | Open the hub URL on the phone, allow camera/motion. | Phone capture |
| **F5** UI responsiveness (pc) | The UI frame loop is keeping up (< 100 ms per frame). | UI frames are slow or stalled: a callback is blocking. If it stalls > 1 s the firmware treats the PC as dead. | Look for the last exception in the Health panel log; never block in callbacks. | Run trajectory, Play back recording |

