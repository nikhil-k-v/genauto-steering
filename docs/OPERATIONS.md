# Operations

## 0. Install

```bash
pip install platformio                                   # once
cd pc && pip install -e ".[server,dev]"
```

## 1. Flash

```bash
python -m steering flash teensy                          # firmware/teensy, env teensy41 (wired)
python -m steering flash teensy --env teensy41_wireless  # PC over the Arduino RF bridge
python -m steering flash arduino                         # env uno (joystick + status)
python -m steering flash arduino --env uno_bridge        # also forwards PC<->Teensy over RF
```

Both OLEDs show the logo for 2 s, then the dashboard. `scripts/check_firmware.sh` type-checks the
firmware on the host without a toolchain (handy before flashing).

## 2. First run

1. `python -m steering ui` (or `--sim` to learn the app without hardware).
2. Top bar: pick the Teensy port, **Connect**. Within a second D1…D6 go green and A4 shows
   `motor never replied` (amber) until the motor is powered. Power the motor: A goes green.
3. Close the idle switch → B1 green.
4. **Calibration → Auto-calibrate end stops + zero.** Watch the stage line (seek L → confirm L → seek R
   → confirm R → centre → settle → Done). C2 goes green. A recording `autocal` is kept.
5. Left panel: **Enable** → state HOLD. Drag the slider ±20°. If the wheel lags/doesn't reach: Tuning.

## 3. Record a steering motion and play it back

1. **Trajectory → Free-spin + Record** (or left panel: Free-spin, then Record). Turn the wheel.
2. **Stop + Re-grip**. The recording appears in **Playback & Library** (kind `freespin`).
3. Select it, choose speed, **Play back on motor**. The wheel blends from where it is into the trace, then
   holds at the end. A child `<name>_pb01` recording is created with metrics; the parent's playback
   count increments. Compare `err_rms_deg`, `tracking_score_pct` between playbacks after gain changes.

## 4. Tuning

* **Step test**: 30° / 3 s. Rise, overshoot, settle, steady-state error are shown and stored.
  Doesn't reach → add Ki (0.05 steps). Overshoots → raise Kd, lower Kp. Slow → raise Kp.
* **Relay auto-tune**: ±2 Nm bang-bang around the current position; Ku/Tu → proposals →
  `use Steering-conservative` → **Apply gains** → step-test again.
* The *active* gains the Teensy is using are echoed under the Apply button; "(pending…)" means the
  echo has not confirmed yet.

## 5. Phone capture (video + IMU)

1. Settings → **run hub** (or `python -m steering ui --server`). Note the URL.
2. On the phone (same Wi-Fi) open it, **Arm camera** (and **Arm IMU** on iOS it asks for permission).
   The page shows the same A–F boxes, state and position; clock sync must be green (< 50 ms jitter).
3. Any recording started on the laptop (or from the phone's buttons) starts the camera; stopping it
   uploads `video.webm` + `capture.json` into that recording's folder; IMU rows stream into `imu.csv`.

## 6. Wireless mode (Arduino bridge)

Flash `teensy41_wireless` and `uno_bridge`, connect the laptop to the **Arduino**. The A–F boxes on the
Arduino OLED come from the Teensy over RF, E1 from the bridge's own view. Joystick: mode AUTO picks
it up whenever packets arrive and the motor is enabled; the Y axis is a rate (±180°/s).

## 7. Debugging checklist

| Symptom | Look at | Likely |
|---|---|---|
| Connect does nothing | D1 reason | wrong port, permissions (Linux: dialout), device grabbed by another app |
| D2 silent | — | Teensy not running this firmware / bootloader / charge-only cable |
| D3 frames stopped, CRC errors | Health → link counters | cable/noise; protocol version mismatch (flash both sides from the same commit) |
| D5 red while D4 green | — | Teensy cannot parse what we send (version) or USB TX dead |
| A1 red | — | CAN bus-off: transceiver power, STBY, CAN_H/L swap, termination |
| A4 amber in REST | — | motor off / wrong id (Settings → Scan bus) |
| A4 red while running | Events: `TRIP CAN LOST` | power dropout |
| A5 amber "frozen" | — | encoder/driver; power-cycle; run the motor's own `c` calibration via its debug port |
| B2 red | banner text | the trip explanation tells you what to check |
| C1 amber/red | fw counters | ISR starved: OLED I2C? long main-loop work? |
| Enable greyed, all boxes green | tooltip | state not REST (already enabled / tripped) |
| Slider greyed | tooltip | needs HOLD + zeroed |
| Stream aborts immediately | Trajectory → stream status; Events | state left HOLD/TRAJ, B1/B2/A4/D5 failed |
| "F5 UI stalled" | app.log last traceback | a callback blocked; the firmware dropped TRAJ/TEST by design |
| UI shows "UI error in …" toast | app.log | bug; the UI keeps running — please report with the traceback |

Logs: `data/logs/app.log`, `data/logs/health-*.jsonl`, and per recording `health.jsonl` /
`events.jsonl`. `python -m steering reindex` if the Library and the disk disagree.

## 8. Changing safety thresholds

Edit `firmware/teensy/src/config.h`, reflash. Never add a UI path for them.
