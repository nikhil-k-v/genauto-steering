# Operations

## 0. Install

```bash
pip install platformio                                   # once
cd pc && pip install -e ".[server,dev]"
```

## 1. Flash

```bash
python -m steering flash          # = pio run -t upload in firmware/teensy
```

The CCM OLED shows the logo for 2 s, then the dashboard (M S T C D boxes, state, dial).
`scripts/check_firmware.sh` type-checks the firmware on the host without a toolchain.

## 2. First run

1. `python -m steering ui` (or `--sim` to learn the app without hardware).
2. Top bar: pick the Teensy port, **Connect**. The system strip's USB link tile goes green (C1…C6) and
   the MOTOR tile shows `NO REPLY` (amber) until the motor is powered. Power the motor: MOTOR goes green.
3. Close the idle switch → SAFETY tile `ARMED`.
4. **Calibration → Auto-calibrate end stops + zero.** Watch the stage line (seek L → confirm L → seek R
   → confirm R → centre → settle → Done). T2 goes green. A recording `autocal` is kept.
5. Left panel: **Enable** → state HOLD. Drag the wheel slider ±20°. If the wheel lags/doesn't reach: Tuning.
6. Anything grey? Hover it — the tooltip lists the blocking checks and lines are drawn to the tiles.

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

## 5. Web hub: browser UI, phone capture, planner

1. Settings → **run hub** (or `python -m steering ui --server`). The URL is shown.
2. **Browser** (laptop or any device on the Wi-Fi): `http://<laptop>:8765/` — *System* (live tiles +
   connectivity check + every node), *Recordings* (browse, traces with cursor, metrics, events, video; pin /
   rename / tag / hide), *Docs* (these documents with the diagrams).
3. **Phone capture**: open `/phone`, **Arm camera** (and **Arm IMU**; iOS asks for permission). Clock sync
   must be green (< 50 ms jitter). Any recording started on the laptop (or from the phone's buttons) starts
   the camera; stopping it uploads `video.webm` + `capture.json` into that recording's folder; IMU rows
   stream into `imu.csv`.
4. **Planner**: enable *allow remote control* in Settings; a client streams
   `{"type":"setpoint","pos_deg":…}` over `/ws` at up to 200 Hz. It is gated like a trajectory.

## 6. Debugging checklist

| Symptom | Look at | Likely |
|---|---|---|
| Connect does nothing | C1 reason | wrong port, permissions (Linux: dialout), device grabbed by another app |
| C2 silent | — | Teensy not running this firmware / bootloader / charge-only cable |
| C3 frames stopped, CRC errors | Health → link counters | cable/noise; protocol version mismatch (flash both sides from the same commit) |
| C5 red while C4 green | — | Teensy cannot parse what we send (version) or USB TX dead |
| M1 red | — | CAN bus-off: transceiver power, STBY, CAN_H/L swap, termination |
| M4 amber in REST | — | motor off / wrong id (Settings → Scan bus) |
| M4 red while running | Events: `TRIP CAN LOST` | power dropout |
| M5 amber "frozen" | — | encoder/driver; power-cycle; run the motor's own `c` calibration via its debug port |
| S2 red | top-right text | the trip explanation tells you what to check |
| T1 amber/red | fw counters | ISR starved: OLED I2C? long main-loop work? |
| Enable greyed, all tiles green | tooltip | state not REST (already enabled / tripped) |
| Slider greyed | tooltip | needs HOLD + zeroed |
| Stream aborts immediately | Trajectory → stream status; Events | state left HOLD/FOLLOWING, S1/S2/M4/C5 failed |
| "D5 UI stalled" | app.log last traceback | a callback blocked; the firmware dropped FOLLOWING/TEST by design |
| UI shows "UI error in …" toast | app.log | bug; the UI keeps running — please report with the traceback |

Logs: `data/logs/app.log`, `data/logs/health-*.jsonl`, and per recording `health.jsonl` /
`events.jsonl`. `python -m steering reindex` if the Library and the disk disagree.

## 7. Changing safety thresholds

Edit `firmware/teensy/src/config.h`, reflash. Never add a UI path for them.
