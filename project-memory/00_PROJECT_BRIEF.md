# Gen Auto steering robot — project brief (v2 software)

**What it is.** A Yobotics BM-series QDD actuator (BM-24 per nkve.dev/pages/genauto: 8/24 N·m; earlier notes
said BM-18 — `MOTOR_MODEL` in config.h) on a universal clamp-on wheel coupling with a floor-constrained
reaction arm, driven by a Teensy 4.1 ("CCM": OLED + take-control/E-stop/power buttons) over CAN,
supervised by a laptop Python (Dear PyGui) app. Vehicle stack: ROS 2 on an NVIDIA AGX Orin (LiDAR,
cameras, GNSS/INS); first maneuver target J-turns, then drifting. Purpose: execute
aggressive / drift steering trajectories from research motion planners, repeatably and safely, and record
evidence of every run. A throttle robot and sensors will join later.

**Repo:** github.com/nikhil-k-v/genauto-steering — `protocol/` (wire contract) · `firmware/teensy` ·
`pc/steering` (link, health, core, control, data, server, ui, sim) · `web/` (browser UI) · `phone/` · `docs/`.

**Hardware (unchanged from v1; the Arduino joystick/RF bridge was dropped).** Teensy 4.1: CAN3 pins 30/31 → transceiver → BM-series motor id 0x02 @ 1 Mbps;
SSD1309 2.42" OLED on I2C 18/19;  **idle switch pin 22 → GND (open = IDLE)**;
USB 2 Mbps to the laptop. BM-18:
24 V, 6/18 Nm rated/peak, 15/40 A, 6:1 planetary, dual absolute encoder, MIT-style CAN frames.

**Control.** Motor FOC 20 kHz (kp, kd in the frame) ⊃ Teensy 1 kHz ISR (slew, gain ramp, leaky
integral, trips; the only CAN writer) ⊃ PC 200 Hz setpoint stream. States: REST HOLD TRAJ JOY TEST
FREESPIN CALIB TRIPPED. Firmware-owned safety constants in `firmware/teensy/src/config.h`.

**Health tree.** Groups **M** motor&CAN · **S** safety · **T** Teensy controller · **C** comms (PC⇄Teensy) ·
**D** data/services; 23 checks, each with reason + affected actions; shown in the app's left rail as the
signal chain (a row that isn't OK names its check, e.g. `M4`), on the web UI and on the OLED. Every UI action is
gated by `health/gating.py` and literally wired to its rail rows (hover → lines); the Teensy answers every command with
ACCEPTED/REJECTED + reason. Transitions logged to `data/logs/health-*.jsonl` and into each recording.

**Data.** `data/recordings/<collection>/<date>/<HHMMSS>_<kind>_<name>/` with `data.csv`, `meta.json`,
`health.jsonl`, `events.jsonl` (+ phone `video.webm`, `imu.csv`). SQLite catalog (rebuildable).
Playbacks are children `<name>_pbNN` of the recording they replay.

**Calibration.** Firmware auto end-stop routine: velocity-regulated torque creep (≤ 3.5 Nm), stop
confirmed by a bump vs friction, both sides, slew to centre, zero with a software offset so centre = 0°.

**Planner path.** Hub `setpoint` stream → `Controller.external_setpoint` (gated like a trajectory; firmware
HOLD fallback after 250 ms). ROS 2 bridge node is the next step.

**Open items (verify on hardware).** Motor model (BM-18 vs BM-24). Torque field range: datasheet says ±18 Nm, old code used ±6 —
`MOTOR_T_*` in config.h; test with Tff = 1 Nm. PlatformIO build not yet run on this code (host
type-check passes). Tune `CAL_*` on the real column.

**Owner preferences.** Laptop app stays a Python desktop GUI (no web GUI in the loop). Safety thresholds
are named constants in firmware, never UI-settable. Web hub is for status/recordings/docs/phones/planner, never in the control loop.
