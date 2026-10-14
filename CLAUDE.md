# Working in this repo (for humans and coding agents)

Read first: `README.md`, then `docs/ARCHITECTURE.md`, `docs/HEALTH.md`, `docs/SAFETY.md`.

## Invariants — do not break

1. `protocol/protocol.h` is the only wire contract. Change it first, mirror in
   `pc/steering/protocol.py`, run `pytest tests/test_protocol_sync.py`.
2. Only the 1 kHz ISR writes CAN (`can_motor_tick_send`). The main loop queues specials.
3. Safety thresholds live in `firmware/teensy/src/config.h` as named constants. No UI path for them.
4. Every UI control that can move the motor is bound through `GateBinder` to an action in
   `pc/steering/health/gating.py`; every controller method calls `_gate()` first. Add the action there,
   not ad hoc.
5. Every UI callback is wrapped in `ui/safe.safe`. Never block in a callback.
6. A new check = a new health node in `health/model.py` (+ firmware `HN_*` if the Teensy decides it),
   with ok/bad/fix text and affected actions. Regenerate `docs/HEALTH_REFERENCE.md`.
7. Recordings are folders with `meta.json`; the catalog is an index and must stay rebuildable
   (`python -m steering reindex`).
8. Hardware pins/assumptions are unchanged from the original build; document any change in
   `docs/HARDWARE.md` and `config.h` together.

## How to test

* `cd pc && pytest` — protocol sync, end-to-end flows on the simulator, hub.
* `xvfb-run -a python tools/ui_smoke.py --shots docs/screenshots` — scripted UI session.
* `scripts/check_firmware.sh` — host type-check of both firmware targets; `pio run` for real builds.
* `python -m steering ui --sim` — run the app with fault injection (`SimFaults`) to see every node fail.

## Conventions

* Units in names (`_deg`, `_Nm`, `_ms`). Degrees at the PC/UI boundary, radians only inside `can_motor`.
* Firmware events carry a ≤19-char reason; the UI shows them verbatim — write them for a human.
* Prefer editing `config.h` / `model.py` tables over adding code paths.
* Words: every user-facing name lives in `pc/steering/words.py`. Name modes by what the motor does
  ("Position control", never "Hold"); a latched trip is a "safety stop" that is "reset"; buttons say exactly
  what happens ("Move to 0°" moves, "Set 0° at the current angle" sets). A problem is a sentence about the
  physical cause with its number ("Motor current 24 A, close to the cut-out"), node id last - never just
  "blocked"/"FAIL"/"trip". No captions that restate a name; explain purpose in a tooltip instead.
* Every control gets a tooltip (`T.tip`, or the hint in `GateBinder.bind`), shown after `T.TIP_DELAY_S`.
* UI look: status colours are colour-blind safe (blue-green / amber / vermillion) and status marks also differ
  by shape (`T.status_mark`: ● ok, ▲ not ready, ■ fault, ○ no data). Healthy is quiet, broken is loud.
  Plot lines (`ui/lines.py`, `T.SERIES`): solid = measured, dashed = setpoint, dotted = requested; colour =
  source (dark green you, pastel green playback/waveform, orange planner, grey test/calibration) or quantity
  (blue position/speed, vermillion torque/current). Plots sit in a darker well and use DejaVu Sans.
  Use `ui/theme.py` helpers (`T.action(kind=primary|secondary|quiet|danger)`, `T.toggle`, `T.number`,
  `T.heading`, `T.label`, `T.mono_text` for machine text only). No new fonts or colours beyond these.
* Web: `web/index.html` is served by the hub AND published to GitHub Pages (`pc/tools/build_pages.py`), so
  every asset path is relative and every API call goes through `api()` (HUB base URL).
* Diagrams are generated: edit `docs/diagrams/gen.py`, run `python docs/diagrams/gen.py --png /tmp/x` and look
  at every PNG before committing (ports are automatic; pin with `pa=`/`pb=` when a route needs it).
