# Health tree reference

Generated from `pc/steering/health/model.py` — edit there.

## Group M — Motor & CAN

*Can the Teensy talk to a powered, sane motor?*

| Node | OK means | When not OK | Fix | Blocks |
|---|---|---|---|---|
| **M1** CAN controller (fw) | FlexCAN3 is error-active with low error counters. | Not ready: error counters high (noise, bad termination). Fault: bus-off, the transceiver sees no valid bus at all. | Check transceiver power and STBY pin, CAN_H/CAN_L wiring, 120 ohm termination at both ends, and that the motor is on the same bus. | Position control (turn the motor on), Free-spin, Run waveform, Play on motor, Run step or relay test, Find end stops and set 0°, Move to the middle of the stops and set 0°, Planner setpoint stream |
| **M2** CAN transmit (fw) | Command frames are leaving the mailbox (no TX overflow, TEC low). | Frames are queued but not acknowledged: nobody on the bus ACKs. Usually means M1-level wiring or the motor is unpowered. | Same checks as M1; also confirm TX_SIZE_16 and that nothing else writes CAN from the main loop. | Position control (turn the motor on), Free-spin, Find end stops and set 0° |
| **M3** CAN receive (fw) | The Teensy has received at least one frame recently (from anyone). | Silence on the bus. Either nothing is powered, or RX wiring is broken while TX looks fine. | Power the motor (it only answers frames sent to it; the Teensy polls it at 100 Hz even with the motor off). Swap CAN_H/CAN_L if TX ACKs but RX is dead. | Position control (turn the motor on), Free-spin, Run waveform, Play on motor, Run step or relay test, Find end stops and set 0°, Move to the middle of the stops and set 0°, Planner setpoint stream |
| **M4** Motor replies (fw) | Reply frames from the configured motor id arrive at the expected rate: ~100 Hz with the motor off (the Teensy polls it), ~1 kHz while on. | Not ready (motor off): the motor has never answered or stopped answering: unpowered, wrong CAN id, or faulted. Position control needs a reply first. Fault (motor on): replies stopped mid-run (power dropout), which causes a safety stop. | Check the 24 V supply, run the CAN scanner (Settings) to find the real id, power-cycle the motor. | Position control (turn the motor on), Set 0° at the current angle, Free-spin, Run waveform, Play on motor, Run step or relay test, Find end stops and set 0°, Save an end stop, Move to the middle of the stops and set 0°, Planner setpoint stream |
| **M5** Motor data sane (fw) | Position/velocity values decode to finite numbers and change over time. | Replies decode to NaN or the payload is frozen (encoder or driver fault, or wrong reply layout). | Power-cycle the motor; if it persists, re-run the motor's own encoder calibration (datasheet section 4.2). | Position control (turn the motor on), Set 0° at the current angle, Free-spin, Run waveform, Play on motor, Run step or relay test, Find end stops and set 0°, Save an end stop, Move to the middle of the stops and set 0°, Planner setpoint stream |
| **M6** Motor current (fw) | |current| is below 70 % of CURRENT_CUTOFF_A. | Not ready: current near the cut-out. Fault: over the cut-out, a safety stop will follow. | Lower Kp/Ki, check for a jam, verify MOTOR_T_* ranges in config.h match the datasheet. | Run waveform, Play on motor, Run step or relay test, Planner setpoint stream |

## Group S — Safety

*Is the idle switch on, or has a safety stop latched?*

| Node | OK means | When not OK | Fix | Blocks |
|---|---|---|---|---|
| **S1** Idle switch (fw) | The idle switch is off (pin 22 pulled to GND): the motor may have torque. | Idle switch on (pin 22 open, or its wire is broken): the motor cannot be turned on, and turning the switch on while the motor runs causes a safety stop. | Turn the idle switch off. If it still reads on, check the wire from pin 22 to GND. | Position control (turn the motor on), Free-spin, Run waveform, Play on motor, Run step or relay test, Find end stops and set 0°, Move to the middle of the stops and set 0°, Planner setpoint stream |
| **S2** No safety stop (fw) | No safety stop is latched. | A safety check stopped the motor (the rail says which one and why). The motor stays off until the stop is reset. | Fix the cause, then press Reset safety stop. Every safety stop is listed in docs/SAFETY.md. | Position control (turn the motor on), Free-spin, Run waveform, Play on motor, Run step or relay test, Find end stops and set 0°, Move to the middle of the stops and set 0°, Planner setpoint stream |

## Group T — Teensy controller

*Is the control loop on time and ready for absolute-position work?*

| Node | OK means | When not OK | Fix | Blocks |
|---|---|---|---|---|
| **T1** Control loop timing (fw) | The 1 kHz tick runs on time with no overruns. | Overruns or low loop rate: the ISR is being starved (I2C stall, long main-loop work) or is too expensive. | Check DISPLAY_HZ / OLED wiring; report isr_overruns from the Health page counters. | Position control (turn the motor on), Run waveform, Play on motor, Run step or relay test, Find end stops and set 0°, Planner setpoint stream |
| **T2** 0° and end stops (fw) | 0° is set and the end stops are known: absolute angles mean something. | 0° or the end stops are missing. Waveforms, playback and tests are refused because an angle like +30° would mean nothing. | Calibrate page: Find end stops and set 0°, or set them by hand. | Setpoint slider, Move to 0°, Run waveform, Play on motor, Run step or relay test, Planner setpoint stream |
| **T3** Calibration (fw) | No calibration running and the last one did not fail. | Not ready: calibration is running (other motion is refused). Fault: the last calibration failed. | Wait for it to finish, or stop it. After a failure, read the reason in the rail (timed out, or range too small). | Run waveform, Play on motor, Run step or relay test, Planner setpoint stream |
| **T4** CCM screen (fw) | The SSD1309 answered on I2C and is being refreshed. | No OLED (not fatal: the UI shows the same information). | Check I2C wiring (18/19) and address 0x3C. | — |

## Group C — Comms (PC - Teensy)

*Is the PC talking to the Teensy, and does the Teensy hear the PC?*

| Node | OK means | When not OK | Fix | Blocks |
|---|---|---|---|---|
| **C1** Serial port (pc) | The serial port is open. | Port not open: not connected, wrong port, or the OS pulled the device. | Pick the Teensy in Connect; re-plug USB; on Linux check dialout group. | Disconnect, Position control (turn the motor on), Stop motor, Reset safety stop, Set 0° at the current angle, Free-spin, Position control (grip again after free-spin), Send gains, Setpoint slider, Move to 0°, Position control (stop following, keep this angle), Run waveform, Play on motor, Run step or relay test, Record, Record a hand motion (free-spin), Find end stops and set 0°, Stop calibration, Save an end stop, Move to the middle of the stops and set 0°, Scan the CAN bus / change the motor id, Planner setpoint stream |
| **C2** Bytes arriving (pc) | Bytes are arriving on the port. | Port open but silent: the Teensy is not running this firmware, is in the bootloader, or the cable is charge-only. | Press the Teensy reset button; flash firmware; try another cable. | Position control (turn the motor on), Set 0° at the current angle, Free-spin, Setpoint slider, Move to 0°, Run waveform, Play on motor, Run step or relay test, Record a hand motion (free-spin), Find end stops and set 0°, Save an end stop, Move to the middle of the stops and set 0°, Planner setpoint stream |
| **C3** Valid frames (pc) | Frames decode with good CRC at a healthy rate and few drops. | Bytes arrive but do not frame: wrong baud/protocol version, or a noisy link with many CRC errors. | Match PROTOCOL_VERSION on both sides; check the USB cable. | Position control (turn the motor on), Set 0° at the current angle, Free-spin, Setpoint slider, Move to 0°, Run waveform, Play on motor, Run step or relay test, Record a hand motion (free-spin), Find end stops and set 0°, Save an end stop, Move to the middle of the stops and set 0°, Planner setpoint stream |
| **C4** Telemetry fresh (pc) | A TelemetryPacket arrived in the last 100 ms. | Frames arrive but no telemetry: firmware stuck before its main loop, or a different device is on the port. | Reset the Teensy; check the port is the Teensy. | Position control (turn the motor on), Set 0° at the current angle, Free-spin, Setpoint slider, Move to 0°, Run waveform, Play on motor, Run step or relay test, Record, Record a hand motion (free-spin), Find end stops and set 0°, Save an end stop, Move to the middle of the stops and set 0°, Planner setpoint stream |
| **C5** Teensy hears PC (pc) | The Teensy reports our packets as fresh (round trip proven). | We receive, but the Teensy does not hear us: TX side of the USB link is broken or the firmware's parser is rejecting our frames. | Check the protocol version on both sides and the cable. While this is down the Teensy refuses commands, and a running stream ends in a safety stop. | Position control (turn the motor on), Stop motor, Reset safety stop, Set 0° at the current angle, Free-spin, Position control (grip again after free-spin), Send gains, Setpoint slider, Move to 0°, Position control (stop following, keep this angle), Run waveform, Play on motor, Run step or relay test, Record a hand motion (free-spin), Find end stops and set 0°, Save an end stop, Move to the middle of the stops and set 0°, Scan the CAN bus / change the motor id, Planner setpoint stream |
| **C6** Firmware health fresh (pc) | HealthPackets are arriving (the M/S/T groups are current). | No HealthPacket for > 500 ms: M/S/T are stale and may be wrong. | Usually accompanies C4; same fixes. | Position control (turn the motor on), Set 0° at the current angle, Free-spin, Setpoint slider, Move to 0°, Run waveform, Play on motor, Run step or relay test, Record a hand motion (free-spin), Find end stops and set 0°, Save an end stop, Move to the middle of the stops and set 0°, Planner setpoint stream |

## Group D — Data & services

*Will what happens now be recorded, stored and served; is the UI responsive?*

| Node | OK means | When not OK | Fix | Blocks |
|---|---|---|---|---|
| **D1** Recorder (pc) | Recorder idle or recording without dropped samples. | FAIL: recording but samples are being dropped (disk slow) or the writer thread died. | Check free disk space; see data/logs/app.log. | Run waveform, Play on motor, Run step or relay test |
| **D2** Store (pc) | The data folder is writable and the catalog database opens. | Cannot write to the data folder or the SQLite catalog is locked/corrupt. | Check permissions / free space; delete data/catalog.sqlite-journal if left over from a crash. | Run waveform, Play on motor, Run step or relay test, Record, Record a hand motion (free-spin) |
| **D3** Web hub (pc) | The web hub is running (browser UI, phones, planner can connect). | Hub off. That is fine unless you want the browser pages, phone capture or the planner stream. | Start it from Settings or `python -m steering ui --server`. | Phone capture |
| **D4** Phone capture (pc) | A phone is connected and time-synced. | No phone connected (not ready), or its clock offset is unstable (fault). | Open the hub URL on the phone, allow camera/motion. | Phone capture |
| **D5** UI responsiveness (pc) | The UI frame loop is keeping up (< 250 ms per frame). | UI frames are slow or frozen: a callback is blocking. Frozen for more than 1 s, the Teensy treats the laptop as gone and stops any stream. | Look for the last traceback in data/logs/app.log; never block in callbacks. | Run waveform, Play on motor, Planner setpoint stream |

