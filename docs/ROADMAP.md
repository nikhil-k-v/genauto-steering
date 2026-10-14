# Roadmap

## Near term (same hardware)

* **Hardware verification** of the v2 firmware per `MIGRATION.md`; tune `CAL_*` on the real column.
* **Torque-scale self-check**: at enable, command a tiny known torque against the stops and compare
  the reply current; warn (node A7) if the implied scale is off by > 1.5×.
* **Bus-voltage sense** (one resistor divider on an ADC pin) → node A7 "motor power" so "motor off"
  is observed rather than inferred.
* Second phone / multiple capture clients; per-client offsets already stored.

## Throttle robot

* Implement `devices/base.py::Device` for the throttle actuator (its own Teensy or a second CAN id on
  the same bus). Health group **T** (T1 link, T2 motor, T3 pedal limits…), samples written to
  `throttle.csv` beside `data.csv`, actions gated by the same `gating.py`.
* Combined trajectories: a `Trajectory` with multiple channels (steer_deg, throttle_pct); the streamer
  fans out per device at 200 Hz from one clock.
* Hub exposes both devices to the phone page.

## Planner integration (ROS 2 on the AGX Orin)

* Live path exists: hub `setpoint` stream → `Controller.external_setpoint` (gated). Next: a ROS 2 node
  (`genauto_steering_bridge`) subscribing to the planner's steering-angle topic and publishing
  telemetry/health, running on the laptop (or on the Orin, owning the Teensy link directly through
  `steering.link` — the package has no UI dependency).
* `Trajectory` import from planners / logs (CSV, rosbag, JSON with `t, steer_deg[, steer_rate]`),
  with limit clipping and the existing blend-in. First target: the J-turn maneuver from
  "Instructed Reinforcement Learning Control of Safe Autonomous J-Turn Vehicle Maneuvers" (AIM 2021).
* **IMU on the actuator** (BNO08x was stubbed in MotorControlWebGUI): absolute wheel angle independent
  of the encoder for the angle loop on the project page; log it as an extra column and use it to
  detect coupling slip (encoder vs IMU disagreement → new health node).
* Replay of a logged vehicle run with video overlay (phone video already time-aligned).

## UX

* Health panel: click a node → shows the actions it blocks live (already in the table) and a "test this
  link" button where applicable (CAN scan, ping round trip).
* Library: compare two recordings side by side (overlay plots + metric deltas).
* Optional NRF24 telemetry mirroring at full rate for the bridge OLED dial (currently 20 Hz).
