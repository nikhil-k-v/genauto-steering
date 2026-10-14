# Yobotics (优宝特) BM series — datasheet notes (English extraction)

Source: 电机产品说明书 (BM-18 / BM-24 / BM-48), Jinan 优宝特机器人. Patented dual absolute encoder;
motor + single-stage planetary + integrated FOC driver board with current sensor; fully sealed.

| | BM-18 | BM-24 | BM-48 |
|---|---|---|---|
| Size / mass | φ94 × 47 mm, 550 g | φ94 × 47 mm, 550 g | φ94 × 52 mm, 730 g |
| Housing | 6061 Al | 7075 Al | 7075 Al |
| Rated voltage | 24 V | 24 V | 36 V |
| Rated / peak current | 15 A / 40 A | 15 / 40 A | 15 / 40 A |
| Rated / peak torque | 6 / 18 Nm | 8 / 24 Nm | 16 / 48 Nm |
| Rated / peak speed | 200 / 300 rpm | 200 / 300 rpm | 160 / 240 rpm |
| Gear ratio | 6:1 | 6:1 | 6:1 |
| Position accuracy | < 0.15° | < 0.15° | < 0.15° |
| Shock | 70 Nm instantaneous | 800 N axial | 1000 N axial |
| Motor | 3-phase disc outer-rotor, 21 pole pairs | same | same |
| Control | position or torque, 1 kHz data rate, CAN online firmware update | | |
| Current protection | 35 A / 200 ms auto | 35 A / 200 ms | 40 A / 200 ms |
| Max temperature | 85 °C | | |
| Bearings / life | deep-groove ball, 6000 h | crossed roller, 10000 h | crossed roller, 8000 h |
| Warranty | 6 months | 1 year | 1 year |

**Connectors.** Power XT30 (negative left, positive right as marked; "supply 12–24 V" on the label).
CAN: keyed JST, CAN_L away from the notch, CAN_H toward it. Debug port 1: non-standard USB-shaped
connector exposing GND, TXD(PA2), RXD(PA3), SWCLK, SWDIO, RST. Debug port 2: pads on the driver PCB.

**Motor's own CLI** (via debug port, 921600 baud, ASCII; firmware "HobbyKing Cheetah" v1.9 style):
`m` motor mode · `c` calibrate encoder · `s` setup (CAN ID `i`, master ID `m`, current bandwidth `b`,
current limit `l`, FW current limit `f`, CAN timeout `t`; e.g. `i01` + Enter) · `e` display encoder ·
`z` set zero · `p` print angle · `r`/`t`/`u` Hall min/mid capture. Procedure: calibrate encoder (`c`,
mid-range, power cycle), Hall min (`r` … `u`), Hall mid (`t` … `u`), zero pose (`z` repeatedly, verify with
`p`). Re-run everything if the mechanics are reassembled; only step 5 (zero) to re-zero.

**CAN (MIT-style), 1 Mbps standard frames.**
Command 8 bytes: position 16 b (−4π…4π rad) · velocity 12 b (−30…30 rad/s) · kp 12 b (0…500) ·
kd 12 b (0…100) · torque 12 b (−18…18 Nm).
Specials: `FF FF FF FF FF FF FF FC` enter motor (FOC) mode · `…FD` reset/exit · `…FE` set current angle as
mechanical zero. Reply per command: position (16 b), velocity (12 b), current (12 b) — on hardware the
first byte is the motor id echo and position starts at byte 1.
Examples from the datasheet (position-only commands, kp=... as encoded): `7F FF 00 00 01 00 07 FF` ≈ 1°,
`90 15 …` 90°, `A0 2A …` 180°, `B0 40 …` 270°, `C0 56 …` 360°.

**Two CAN states.** REST (0xFD): MOSFETs off, waiting. MOTOR (0xFC): FOC running, accepts the single
command frame type and answers each one.
