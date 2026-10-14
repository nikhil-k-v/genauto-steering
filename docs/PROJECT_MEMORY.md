# What to put in the Claude Project ("Gen Auto") knowledge

Project knowledge should hold the *stable, decision-bearing* documents, not the code. Add these
(copies are in `project-memory/`; keep them in sync when the underlying file changes):

| Add | Why |
|---|---|
| `project-memory/00_PROJECT_BRIEF.md` | one-page description of the system, invariants, where things live — orients any new chat |
| `project-memory/BM-18_datasheet_notes.md` | English extraction of the Chinese datasheet (ranges, special frames, reply layout, CLI) |
| `docs/HARDWARE.md` | pinout, electrical system, CAN bus facts |
| `docs/HEALTH.md` + `docs/HEALTH_REFERENCE.md` | the status bar semantics — most debugging questions start here |
| `docs/SAFETY.md` | trips and layers; keeps future changes from weakening safety |
| `docs/PROTOCOL.md` | packet table; lets a chat reason about firmware/PC changes without opening the header |
| `docs/MIGRATION.md` | the bugs found and the "verify on hardware" checklist — until that checklist is done it is the open-items list |
| `CLAUDE.md` | working rules for coding agents |
| the original BM-18 PDF (`电机产品说明书_详细_2.pdf`) | source of truth for motor numbers |

Do **not** add: the code itself (point at the repo instead), screenshots, recordings.

Suggested Project instructions text:

> This project is the Gen Auto vehicle robotics software (steering robot now; throttle robot, sensors
> later). The steering repo is `genauto-steering` (see PROJECT_BRIEF). Hardware is fixed: Teensy 4.1 +
> Yobotics BM-series (BM-24?) over CAN3, laptop Python app + optional web hub. Respect the invariants in
> CLAUDE.md: single wire contract, ISR-only CAN writes, firmware-owned safety constants, gated UI actions,
> health nodes for every check. Prefer small, verified changes; run the simulator tests.

Memory (the account/project memory files Claude keeps): the durable facts are the repo name and layout,
the hardware assumptions, the torque-range question to verify, and that the owner wants safety
thresholds as named firmware constants.
