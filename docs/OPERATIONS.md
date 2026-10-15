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
`scripts/check_firmware.sh` type-checks the firmware on the host without a toolchain, then runs the real
firmware against a simulated motor on CAN (motor off → on → scan → wrong id → unpowered).

## 2. First run

1. `python -m steering ui` (or `--sim` to learn the app without hardware).
2. Top of the rail: pick the Teensy port, **Connect**. The USB row turns green and the line from Laptop to
   Teensy goes green. The Motor row says `no reply` (amber) until the motor is powered; power it and the
   CAN and Motor rows go green.
3. Turn the idle switch off: the Safety row says `armed`.
4. **Calibrate → Find end stops and set 0°.** The six steps light up in order (find left, confirm, find right,
   confirm, move to the middle, settle and set 0°). The Teensy row's "Not calibrated" line disappears. A
   recording `autocal` is kept.
5. Rail: **Position control** (the motor now servos to where the wheel is). On **Drive**, drag the green
   setpoint grab ±20°; the blue dot under it is the measured angle. **Move to 0°** (above 0° on the scale)
   drives back to the middle. If the wheel lags or doesn't reach: **Tune**.
6. Hover anything for a second: it says what it does; if it is grey, exactly why, and lines run to the rail
   rows that block it.

## 3. Record a steering motion and play it back

1. Rail: **Free-spin**. On **Drive**, **Record** (it records as a hand motion). Turn the wheel.
2. **Stop recording**, then **Position control** to grip again. The recording appears in **Library** (kind `freespin`).
3. Select it, choose the speed, **Play on motor**. The wheel blends from where it is into the trace, then
   holds at the end. A child `<name>_pb01` recording is created with results; the parent's playback count
   goes up. Compare RMS error and tracking score between playbacks after gain changes.

## 4. Tuning (Tune page)

* **Step test**: 30° / 3 s. Rise, overshoot, settling and steady error are shown and stored.
  Doesn't reach → add Ki (0.05 steps). Overshoots → raise Kd, lower Kp. Slow → raise Kp.
* **Relay auto-tune**: ±2 Nm bang-bang around the current position; Ku/Tu → proposed gains →
  **Use** on *Steering-conservative* → **Send gains** → step-test again.
* "in use: …" next to **Send gains** is what the Teensy reports it is using; "sent, waiting for the Teensy
  to confirm" means the echo hasn't arrived yet.
* **Waveforms** (collapsed): sine, triangle, square, chirp, step streamed at 200 Hz and recorded.
* The live traces on the right are the same as on Drive: watch the response while you test.

## 5. Web hub: browser UI over the Wi-Fi, phone capture, planner

1. Settings → **Run the web hub** (or `python -m steering ui --server`). Settings lists how to reach it:
   *On this laptop* `http://localhost:8765/`, *On the Wi-Fi* `http://<laptop-ip>:8765/`, *By name*
   `http://genauto.local:8765/` (mDNS, needs `zeroconf`), and a *Bookmark* link with a QR code.
2. **The front door is GitHub Pages**: <https://nikhil-k-v.github.io/genauto-steering/>. Docs work there
   with no hub. Enter the laptop's address (or open the bookmark / scan the QR, which carries
   `?hub=<ip>:8765`): on the laptop itself the page talks to the hub directly (browsers allow an https page
   to reach `http://localhost`); on a phone or another computer it opens the laptop's own copy at
   `http://<ip>:8765/`, because browsers block an https page from calling a plain-http device on the LAN.
   The address is remembered, so after the first time the bookmark is one tap.
3. **Browser** (laptop or any device on the Wi-Fi): `http://<laptop>:8765/`, with the same rail as the app.
   *System* (system diagram, connectivity hop by hop, every check), *Recordings* (browse, traces with a
   cursor, results, events, video; pin, rename, tag, hide), *Docs* (these documents with the diagrams).
4. **Phone capture**: open `/phone`, **Arm camera** (and **Arm IMU**; iOS asks for permission). The clock
   must read green (< 50 ms jitter). Any recording started on the laptop (or from the phone's buttons)
   starts the camera; stopping it uploads `video.webm` + `capture.json` into that recording's folder; IMU
   rows stream into `imu.csv`.
5. **Planner**: enable *Allow remote control* in Settings; a client streams
   `{"type":"setpoint","pos_deg":…}` over `/ws` at up to 200 Hz. It is gated like a waveform.

## 6. Debugging checklist

| Symptom | Look at | Likely |
|---|---|---|
| Connect does nothing | C1 reason | wrong port, permissions (Linux: dialout), device grabbed by another app |
| C2 silent | — | Teensy not running this firmware / bootloader / charge-only cable |
| C3 frames stopped, CRC errors | Health → counters | cable/noise; protocol version mismatch (flash both sides from the same commit) |
| C5 red while C4 green | — | Teensy cannot parse what we send (version) or USB TX dead |
| M1 red | — | CAN bus-off: transceiver power, STBY, CAN_H/L swap, termination |
| M4 amber in Motor off ("never replied") | Settings → Scan the CAN bus | motor unpowered, or on another id: the scan lists who answers; Use this id |
| M1/M2 amber "frames not acknowledged" | — | nothing on the bus ACKs the Teensy's poll: motor unpowered, CAN_H/L or termination |
| M4 red while running | Events: "Safety stop: Motor stopped replying on CAN" | power dropout |
| M5 amber "frozen" | — | encoder/driver; power-cycle; run the motor's own `c` calibration via its debug port |
| S2 red ("Safety stop: …") | rail state line | it names the check that stopped the motor, the measured value, and what to check |
| T1 amber/red | Health → counters | ISR starved: OLED I2C? long main-loop work? |
| Position control greyed, all rail rows green | tooltip | the motor is already on, or a safety stop is latched (Reset safety stop first) |
| Slider / Move to 0° greyed | tooltip | needs Position control and 0° set |
| Stream aborts immediately | rail state line, last event | the motor left Position control / Following, or S1/S2/M4/C5 went bad |
| "UI frozen" (D5) | app.log last traceback | a callback blocked; the firmware dropped FOLLOWING/TEST by design |
| Web page on a phone says "not connected" | Settings → Web hub | hub off, phone on another network, or the address changed (scan the QR again) |
| "UI error in …" note bottom-right | app.log | bug; the UI keeps running. Report it with the traceback |

Logs: `data/logs/app.log`, `data/logs/health-*.jsonl`, and per recording `health.jsonl` /
`events.jsonl`. `python -m steering reindex` if the Library and the disk disagree.

## 7. Changing safety thresholds

Edit `firmware/teensy/src/config.h`, reflash. Never add a UI path for them.
