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
2. Top of the rail: pick the Teensy port, **Connect**. The USB row turns green and the line from Laptop to
   Teensy goes green. The Motor row says `no reply` (amber) until the motor is powered; power it and the
   CAN and Motor rows go green.
3. Close the idle switch: the Safety row says `armed`.
4. **Calibrate → Find end stops and zero.** The steps light up in order (find left, confirm, find right,
   confirm, centre, settle and zero). The Teensy row's `T2` reason disappears. A recording `autocal` is kept.
5. Rail: **Hold** (the state reads *Holding*). On **Drive**, drag the wheel slider ±20°. If the wheel lags
   or doesn't reach: **Tune**.
6. Anything grey? Hover it: the tooltip says why, and lines run to the rail rows that block it.

## 3. Record a steering motion and play it back

1. Rail: **Free-spin**. On **Drive**, **Record** (it records as a hand motion). Turn the wheel.
2. **Stop recording**, then **Hold** to grip again. The recording appears in **Library** (kind `freespin`).
3. Select it, choose the speed, **Play on motor**. The wheel blends from where it is into the trace, then
   holds at the end. A child `<name>_pb01` recording is created with results; the parent's playback count
   goes up. Compare RMS error and tracking score between playbacks after gain changes.

## 4. Tuning (Tune page)

* **Step test**: 30° / 3 s. Rise, overshoot, settling and steady error are shown and stored.
  Doesn't reach → add Ki (0.05 steps). Overshoots → raise Kd, lower Kp. Slow → raise Kp.
* **Relay auto-tune**: ±2 Nm bang-bang around the current position; Ku/Tu → proposed gains →
  **Use** on *Steering-conservative* → **Apply** → step-test again.
* The line under the gain fields says what the Teensy is actually using; "Waiting for the Teensy to
  confirm" means the echo hasn't arrived yet.
* **Test waveforms** (collapsed): sine, triangle, square, chirp, step streamed at 200 Hz and recorded.

## 5. Web hub: browser UI, phone capture, planner

1. Settings → **Run the hub** (or `python -m steering ui --server`). The URL is shown.
2. **Browser** (laptop or any device on the Wi-Fi): `http://<laptop>:8765/`, with the same rail as the app.
   *System* (system diagram, connectivity hop by hop, every check), *Recordings* (browse, traces with a
   cursor, results, events, video; pin, rename, tag, hide), *Docs* (these documents with the diagrams).
3. **Phone capture**: open `/phone`, **Arm camera** (and **Arm IMU**; iOS asks for permission). The clock
   must read green (< 50 ms jitter). Any recording started on the laptop (or from the phone's buttons)
   starts the camera; stopping it uploads `video.webm` + `capture.json` into that recording's folder; IMU
   rows stream into `imu.csv`.
4. **Planner**: enable *Allow remote control* in Settings; a client streams
   `{"type":"setpoint","pos_deg":…}` over `/ws` at up to 200 Hz. It is gated like a waveform.

## 6. Debugging checklist

| Symptom | Look at | Likely |
|---|---|---|
| Connect does nothing | C1 reason | wrong port, permissions (Linux: dialout), device grabbed by another app |
| C2 silent | — | Teensy not running this firmware / bootloader / charge-only cable |
| C3 frames stopped, CRC errors | Health → counters | cable/noise; protocol version mismatch (flash both sides from the same commit) |
| C5 red while C4 green | — | Teensy cannot parse what we send (version) or USB TX dead |
| M1 red | — | CAN bus-off: transceiver power, STBY, CAN_H/L swap, termination |
| M4 amber in REST | — | motor off / wrong id (Settings → Scan bus) |
| M4 red while running | Events: `TRIP CAN LOST` | power dropout |
| M5 amber "frozen" | — | encoder/driver; power-cycle; run the motor's own `c` calibration via its debug port |
| S2 red | rail state line | the trip explanation tells you what to check |
| T1 amber/red | Health → counters | ISR starved: OLED I2C? long main-loop work? |
| Hold greyed, all rail rows green | tooltip | already holding, or tripped (Clear trip first) |
| Slider greyed | tooltip | needs Holding and zero set |
| Stream aborts immediately | rail state line, last event | state left Holding/Following, S1/S2/M4/C5 failed |
| "D5 UI stalled" | app.log last traceback | a callback blocked; the firmware dropped FOLLOWING/TEST by design |
| "UI error in …" note bottom-right | app.log | bug; the UI keeps running. Report it with the traceback |

Logs: `data/logs/app.log`, `data/logs/health-*.jsonl`, and per recording `health.jsonl` /
`events.jsonl`. `python -m steering reindex` if the Library and the disk disagree.

## 7. Changing safety thresholds

Edit `firmware/teensy/src/config.h`, reflash. Never add a UI path for them.
