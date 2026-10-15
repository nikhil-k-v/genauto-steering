# Wire protocol (v3)

Source of truth: [`protocol/protocol.h`](../protocol/protocol.h). Python mirror:
`pc/steering/protocol.py` (checked by `pc/tests/test_protocol_sync.py`).

## Framing (USB serial)

```
[0xAB][0xCD][LEN][SEQ][payload × LEN][CRC8]
```

* `LEN` 1..32. `SEQ` rolls per sender; the receiver counts gaps as drops (node C3).
* `CRC8` = CRC-8/MAXIM (poly 0x31, reflected 0x8C, init 0) over `LEN SEQ payload` (check value of
  "123456789" is 0xA1).
* The parser resyncs on any byte; a `0xAB` seen while expecting `0xCD` restarts the sync.

## Packets

| Type | Name | Dir | Size | Rate / when |
|---|---|---|---|---|
| 0xA1 | TelemetryPacket | T→PC | 28 | 200 Hz: ctrl_state, flags, t_us, setpoint, position, velocity, current, torque_cmd |
| 0xA2 | HealthPacket | T→PC | 28 | 20 Hz: trip, calib stage, state, 2-bit node states ×13, CAN rates/errors, loop Hz, ages |
| 0xA3 | ConfigEchoPacket | T→PC | 28 | 5 Hz + on change: motor id, zeroed, limits valid, kp kd ki tff, limits |
| 0xA4 | EventPacket | T→PC | 28 | on occurrence: code, arg, 20-char text (trip, state, cmd accepted/**rejected with reason**, calib stage, limits/zero set, test done, warning) |
| 0xA5 | CanScanPacket | T→PC | 18 | once a CMD_CAN_SCAN finishes (~0.3 s; count may be 0) |
| 0xB1 | GainsPacket | PC→T | 20 | on Apply |
| 0xB2 | SetpointPacket | PC→T | 16 | ≤ 200 Hz stream (seq, t_ms, pos, vel_ff, last flag) |
| 0xB3 | ModeRequestPacket | PC→T | 4 | AUTO / HOLD / TRAJ / FREESPIN, sticky |
| 0xC1 | CommandPacket | PC→T | 8 | cmd, u16 arg, float farg — see `CMD_*` |
| 0xC2 | TestStartPacket | PC→T | 16 | step / relay with amplitude, duration, param |
| 0xC3 | HeartbeatPacket | PC→T | 8 | 5 Hz: flags (recording, **UI alive**, server, phone), PC health bits (C/D summary for the OLED) |
| 0xC4 | LimitsPacket | PC→T | 12 | manual limits |

Any well-formed PC packet counts as PC liveness on the Teensy (the setpoint stream is a better
liveness signal than the heartbeat alone); the heartbeat additionally carries the flags.

### Commands

`ENABLE DISABLE SET_ZERO CLEAR_TRIP FREESPIN_ON FREESPIN_OFF CALIB_START CALIB_ABORT CAN_SCAN
HOLD_HERE REQ_CONFIG RESET_COUNTERS CAPTURE_LEFT CAPTURE_RIGHT GO_CENTER_ZERO SET_MOTOR_ID`

Every command is answered by `EV_CMD_ACCEPTED` or `EV_CMD_REJECTED` + reason text (e.g.
`"idle switch is IDLE"`, `"no motor CAN reply"`, `"busy: traj/test/cal"`). The UI shows rejections in
the rail (state line, last event) and the Health page's event list, and writes them to the recording's `events.jsonl`.

### Controller states / trips / calibration stages

See the `CS_*`, `TRIP_*`, `CAL_*` tables in `protocol.h`; names and explanations in
`protocol.py` (`CS_NAMES`, `TRIP_NAMES`, `TRIP_EXPLAIN`, `CAL_NAMES`).

### Health node bits

`HealthPacket.node_states` holds 2 bits per node (`HN_*`): 0 UNKNOWN · 1 OK · 2 BLOCKED · 3 FAIL.
Firmware nodes are M1–M6, S1–S2, T1–T4 and the Teensy's view of the PC link (shown as C5); mapping in
`docs/HEALTH.md`. The heartbeat's `pc_health_bits` relays D1 D2 D3 D5 (bits 0–3) and C1–C4 (bits 4–7) for
the OLED.

## CAN (Teensy ↔ BM-18)

Command (id = motor id, 8 bytes, MIT convention):

```
byte 0-1  position  16 bit   -4π … 4π rad
byte 2-3  velocity  12 bit   -30 … 30 rad/s   (upper 4 bits of byte 3 = kp[11:8])
byte 3-4  kp        12 bit   0 … 500
byte 5-6  kd        12 bit   0 … 100          (lower 4 bits of byte 6 = torque[11:8])
byte 6-7  torque    12 bit   -18 … 18 Nm
```

Special: `FF FF FF FF FF FF FF FC` enter motor mode · `…FD` exit (REST) · `…FE` set zero.

The motor answers **every** frame addressed to its id (in REST it ignores the command but still replies),
and never talks on its own. The Teensy therefore always sends: the command each 1 kHz tick with the motor
on, a zero-gain zero-torque poll at `CAN_REST_POLL_HZ` (100 Hz) with it off, exit-motor-mode once at boot,
and during a scan one ping per tick to ids `first..last` (twice each), then 50 ms of listening.

Reply (8 bytes): `byte 0 = id echo`, bytes 1-2 position, bytes 3-4 velocity (12 bit), bytes 4-5
current/torque (12 bit). The id echo in byte 0 is what the old code once mis-parsed as position.
