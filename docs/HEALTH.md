# Health: what every check means

Every check in the system is a **node** with an id like `M4`. The letter says what *kind* of thing it is
about, the number its position in the chain:

| Letter | Group | Question it answers | Who decides |
|---|---|---|---|
| **M** | Motor & CAN | Can the Teensy talk to a powered, sane motor? | Teensy |
| **S** | Safety | Is anything physically or by latch preventing torque? | Teensy |
| **T** | Teensy controller | Is the loop on time and ready for absolute-position work? | Teensy |
| **C** | Comms (PC ⇄ Teensy) | Is the PC talking to the Teensy *and does the Teensy hear the PC*? | PC |
| **D** | Data & services | Will what happens now be recorded, stored, served; is the UI responsive? | PC |

![health tree](diagrams/05_health_tree.svg)

| State | Colour | Meaning |
|---|---|---|
| OK | green | working |
| BLOCKED | amber | not broken, but prevents some action (switch idle, not zeroed, calibration running). Optional things (hub, phone, OLED) show **OFF** instead |
| FAIL | red | broken or tripped |
| UNKNOWN | grey | nothing observed yet |

Definitions (name, what OK means, what bad means, the fix, which actions it gates) live in one table,
`pc/steering/health/model.py`; [HEALTH_REFERENCE.md](HEALTH_REFERENCE.md) is generated from it.

## Where you see it

* **The rail** (left side of the desktop app, always visible): the signal chain drawn as one line —
  Laptop, USB, Teensy, CAN, Motor — then Safety and Web hub. Each row has a status dot and one live value
  (rate, loop speed, current). The line between components takes the colour of the link it stands for, so
  a break shows where it is. A row that is not OK gets one more line: the id and reason of its worst check
  (`M4  0 Hz, last 6057 ms ago`). Healthy rows stay quiet. Hover a row for its checks; click it to open
  that check on the Health page.
* **Health page**: every check, grouped by kind, with its live reason. Click one to see what OK means,
  what it means when it isn't, the fix, and what it blocks; counters, recent changes and events sit under it.
* **Controls**: every button or slider that can move the motor is bound to an action. When a check blocks it,
  the control is disabled and its tooltip says exactly why. **Hovering a control draws lines from it to the
  rail rows it depends on**: one trunk, one branch per row, green where that row is fine for this action,
  amber or red (the row's own colour) where it is the reason it is blocked.
* **Web hub**: the same rail and checks plus a connectivity list (this page, hub, laptop, Teensy, motor,
  switch, zero, phone), from any browser on the network.
* **CCM OLED**: five boxes `M S T C D`; filled = OK, hollow + index = first bad check (`M4`), blinking = FAIL.

## Root-causing "the motor doesn't move"

![root cause](diagrams/06_root_cause.svg)

Read the rail top to bottom: **USB, Safety, CAN and Motor, Teensy, then the state**. The first row that
isn't green is the layer to fix.

## Where it is logged

| File | Content |
|---|---|
| `data/logs/health-YYYY-MM-DD.jsonl` | every node transition (`from`, `to`, `reason`) + a full snapshot every 10 s |
| `data/logs/app.log` | application log: link open/close, refusals, trips, exceptions with tracebacks |
| `<recording>/health.jsonl` | snapshots at 1 Hz + transitions **during** the recording |
| `<recording>/events.jsonl` | firmware events (trips, rejections, calib stages, state changes) and PC actions (what was pressed, allowed or blocked and why) |
| `catalog.sqlite` → `health_summary`, `health_worst` | worst nodes seen per recording, shown in the Library and the web UI |

## Firmware nodes in detail

| Node | Computed from |
|---|---|
| M1 | FlexCAN3 `ESR1.FLTCONF` (bus-off / passive) and `ECR` TEC/REC (>96 = warning) |
| M2 | `CANbus.write()` failures per health period (>5 = FAIL), TEC > 127 = BLOCKED |
| M3 | any RX frame in the last period |
| M4 | age of last reply from `MOTOR_CAN_ID`; rate vs `CAN_RX_LOW_HZ` while enabled; BLOCKED in REST (the motor only answers commands), FAIL while enabled |
| M5 | NaN decode, or identical payload 200× in a row (frozen) |
| M6 | reply current vs `CURRENT_CUTOFF_A` (70 % = BLOCKED) |
| S1 | debounced pin 22 (20 ms) |
| S2 | `trip != TRIP_NONE` |
| T1 | measured ISR rate vs `CONTROL_HZ`; overruns (tick > 90 % of period) |
| T2 | `zeroed && limits_valid` |
| T3 | calibration stage |
| T4 | OLED ACKed at boot (optional) |
| C5 (Teensy's view) | PC packet age vs `PC_HEARTBEAT_TIMEOUT_MS` |

PC nodes C1–C6, D1–D5: `health/evaluator.py` (thresholds at the top of the file).

## Adding a node

1. `HN_*` in `protocol.h` (+ `HN_COUNT`), mirror in `protocol.py`.
2. Compute it in `health.cpp::health_update` and add it to a group in `health_groups()`.
3. Declare it in `model.py` with ok/bad/fix text and the actions it affects; add it to requirement lists
   in `gating.py` where relevant.
4. `python -m steering docs-health > docs/HEALTH_REFERENCE.md`.
