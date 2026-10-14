// =============================================================================
// protocol.h — THE wire contract between the Teensy (CCM) and the PC.
//
// Single source of truth.  The firmware includes this exact file via
// PlatformIO `build_flags = -I../../protocol`; pc/steering/protocol.py mirrors
// it and pc/tests/test_protocol_sync.py parses this header to prove the two
// agree (packet IDs, enum values, struct sizes).  Change it here first.
//
// Framing (USB serial):
//
//   [SYNC0 0xAB][SYNC1 0xCD][LEN][SEQ][payload LEN bytes][CRC8]
//
//   LEN   = payload length, 1..MAX_PAYLOAD
//   SEQ   = per-sender rolling counter (lets the receiver count drops)
//   CRC8  = CRC-8/MAXIM (poly 0x31, init 0x00) over LEN, SEQ and payload
//
//   payload[0] is always the packet type.  All structs are packed (1-byte
//   aligned), little-endian, and <= 32 bytes.
// =============================================================================
#pragma once
#include <stdint.h>

#define PROTOCOL_VERSION    3

#define FRAME_SYNC0         0xAB
#define FRAME_SYNC1         0xCD
#define FRAME_OVERHEAD      5          // sync0 sync1 len seq crc
#define MAX_PAYLOAD         32

// ---- packet types ----------------------------------------------------------
// Teensy -> PC
#define PKT_TELEMETRY       0xA1   // 200 Hz  motion state
#define PKT_HEALTH          0xA2   // 20 Hz   firmware health tree + counters
#define PKT_CONFIG_ECHO     0xA3   // 5 Hz / on change: active gains, limits, zero
#define PKT_EVENT           0xA4   // on occurrence: trips, rejections, stage changes
#define PKT_CAN_SCAN        0xA5   // reply to CMD_CAN_SCAN
// PC -> Teensy
#define PKT_GAINS           0xB1
#define PKT_SETPOINT        0xB2   // streamed at up to 200 Hz
#define PKT_MODE_REQUEST    0xB3
#define PKT_COMMAND         0xC1
#define PKT_TEST_START      0xC2
#define PKT_HEARTBEAT       0xC3   // 5 Hz, carries PC-side health summary
#define PKT_LIMITS          0xC4

// ---- controller states (HealthPacket.ctrl_state, TelemetryPacket.ctrl_state)
#define CS_REST             0   // motor MOSFETs off, CAN "exit motor mode" sent
#define CS_HOLD             1   // enabled, holding setpoint (slider / hold-here)
#define CS_TRAJ             2   // following PC setpoint stream
#define CS_TEST             3   // step / relay test running on Teensy
#define CS_FREESPIN         4   // enabled, zero gains, zero torque
#define CS_CALIB            5   // end-stop calibration routine running
#define CS_TRIPPED          6   // safety trip latched; needs CMD_CLEAR_TRIP

// ---- requested modes (ModeRequestPacket.mode) ------------------------------
#define MODE_AUTO           0   // follow a fresh setpoint stream, else hold
#define MODE_HOLD           1
#define MODE_TRAJ           2
#define MODE_FREESPIN       3

// ---- commands (CommandPacket.cmd) ------------------------------------------
#define CMD_ENABLE          0x01   // REST -> HOLD (requires zeroed, switch armed, no trip)
#define CMD_DISABLE         0x02   // any -> REST
#define CMD_SET_ZERO        0x03   // current position becomes 0 (motor-side 0xFE)
#define CMD_CLEAR_TRIP      0x04   // TRIPPED -> REST
#define CMD_FREESPIN_ON     0x05
#define CMD_FREESPIN_OFF    0x06
#define CMD_CALIB_START     0x07   // run end-stop auto-calibration
#define CMD_CALIB_ABORT     0x08
#define CMD_CAN_SCAN        0x09   // arg = first id, farg = last id (float, ugh — see docs)
#define CMD_HOLD_HERE       0x0A   // setpoint := current position
#define CMD_REQ_CONFIG      0x0B   // ask for a ConfigEchoPacket now
#define CMD_RESET_COUNTERS  0x0C
#define CMD_CAPTURE_LEFT    0x0D   // manual calibration: current pos = left stop
#define CMD_CAPTURE_RIGHT   0x0E   // manual calibration: current pos = right stop
#define CMD_GO_CENTER_ZERO  0x0F   // move to (L+R)/2 slowly and set zero there
#define CMD_SET_MOTOR_ID    0x10   // arg = CAN id

// ---- tests (TestStartPacket.test_type) -------------------------------------
#define TEST_NONE           0
#define TEST_STEP           1
#define TEST_RELAY          2

// ---- safety trip codes (HealthPacket.trip_code) ----------------------------
#define TRIP_NONE           0
#define TRIP_VELOCITY       1   // |velocity| > VELOCITY_CUTOFF
#define TRIP_STALL          2   // large error for too long
#define TRIP_OVERCURRENT    3   // |current| > CURRENT_CUTOFF for too long
#define TRIP_SWITCH_OPENED  4   // idle switch opened while enabled
#define TRIP_PC_LINK_LOST   5   // PC heartbeat lost while PC was in control
#define TRIP_CAN_LOST       6   // motor replies stopped while enabled
#define TRIP_LIMIT          7   // position beyond calibrated limits + margin
#define TRIP_CALIB_FAILED   8
#define TRIP_PC_SHUTDOWN    9   // PC app exited / crashed and asked for REST
#define TRIP_ISR_OVERRUN    10  // control loop fell behind badly

// ---- calibration stages (HealthPacket.calib_stage) -------------------------
#define CAL_IDLE            0
#define CAL_SEEK_LEFT       1
#define CAL_CONFIRM_LEFT    2
#define CAL_SEEK_RIGHT      3
#define CAL_CONFIRM_RIGHT   4
#define CAL_GO_CENTER       5
#define CAL_SETTLE          6
#define CAL_DONE            7
#define CAL_ABORTED         8
#define CAL_FAILED          9

// ---- firmware health nodes (HealthPacket.node_states, 2 bits each) ---------
// State encoding per node: 0 = UNKNOWN, 1 = OK, 2 = BLOCKED (not broken, but
// prevents something), 3 = FAIL.  Index = bit offset / 2.
// Group letters (docs/HEALTH.md): M motor & CAN, S safety, T Teensy controller,
// C comms (PC link), D data & services (PC side only).
#define HN_CAN_CTRL         0   // FlexCAN not bus-off, error counters sane   (M1)
#define HN_CAN_TX           1   // frames leaving the mailbox                  (M2)
#define HN_CAN_RX_ANY       2   // any frame heard on the bus                  (M3)
#define HN_CAN_MOTOR        3   // replies from MOTOR_ID at expected rate      (M4)
#define HN_MOTOR_DATA       4   // reply values sane / not frozen              (M5)
#define HN_MOTOR_CURRENT    5   // |current| under limit                       (M6)
#define HN_SWITCH           6   // idle switch armed (OK) / idle (BLOCKED)     (S1)
#define HN_TRIP             7   // no latched trip                             (S2)
#define HN_ISR              8   // 1 kHz loop on time                          (T1)
#define HN_CTRL_READY       9   // zeroed + limits + gains valid               (T2)
#define HN_CALIB            10  // calibration not in progress / not failed    (T3)
#define HN_OLED             11  // display initialised                         (T4)
#define HN_PC_LINK          12  // PC packets fresh as seen by Teensy          (C5 on the PC)
#define HN_COUNT            13

#define HS_UNKNOWN          0
#define HS_OK               1
#define HS_BLOCKED          2
#define HS_FAIL             3

// ---- event codes (EventPacket.code) ----------------------------------------
#define EV_BOOT             1
#define EV_TRIP             2    // arg = TRIP_*
#define EV_STATE            3    // arg = new CS_*
#define EV_CMD_ACCEPTED     4    // arg = CMD_*
#define EV_CMD_REJECTED     5    // arg = CMD_* ; text = reason
#define EV_CALIB_STAGE      6    // arg = CAL_*
#define EV_LIMITS_SET       7
#define EV_ZERO_SET         8
#define EV_TEST_DONE        9    // arg = TEST_*
#define EV_WARNING          10   // text

// ---- telemetry flag bits ---------------------------------------------------
#define TF_ENABLED          (1 << 0)
#define TF_ZEROED           (1 << 1)
#define TF_AT_LIMIT         (1 << 2)
#define TF_SWITCH_ARMED     (1 << 3)
#define TF_TEST_RUNNING     (1 << 4)
#define TF_LIMITS_VALID     (1 << 5)
#define TF_FREESPIN         (1 << 6)

// ---- heartbeat flag bits (PC -> Teensy) ------------------------------------
#define HB_RECORDING        (1 << 0)
#define HB_UI_ALIVE         (1 << 1)
#define HB_SERVER_UP        (1 << 2)
#define HB_PHONE_CAPTURE    (1 << 3)

#pragma pack(push, 1)

// Teensy -> PC @ 200 Hz
struct TelemetryPacket {
    uint8_t  type;            // PKT_TELEMETRY
    uint8_t  ctrl_state;      // CS_*
    uint8_t  flags;           // TF_*
    uint8_t  seq_setpoint;    // low byte of last accepted SetpointPacket.seq (latency check)
    uint32_t t_us;            // Teensy micros()
    float    setpoint_deg;
    float    position_deg;
    float    velocity_deg_s;
    float    current_A;
    float    torque_cmd_Nm;   // feed-forward torque sent this tick (integral + tff)
};                            // 28

// Teensy -> PC @ 20 Hz
struct HealthPacket {
    uint8_t  type;            // PKT_HEALTH
    uint8_t  trip_code;       // TRIP_*
    uint8_t  calib_stage;     // CAL_*
    uint8_t  ctrl_state;      // CS_*
    uint32_t t_ms;
    uint32_t node_states;     // 2 bits per HN_* node
    uint16_t can_rx_motor_hz; // reply frames from MOTOR_ID in last second
    uint16_t can_rx_other_hz; // frames from anyone else
    uint8_t  can_tec;         // FlexCAN TX error counter (saturated at 255)
    uint8_t  can_rec;         // FlexCAN RX error counter
    uint8_t  can_bus_state;   // 0 active, 1 warning, 2 passive, 3 bus-off
    uint8_t  isr_overruns;    // since last health packet
    uint16_t loop_hz;         // measured control loop rate
    uint16_t pc_hb_age_ms;    // 0xFFFF = never
    uint16_t reserved;
    uint16_t motor_age_ms;    // ms since last motor reply (0xFFFF = never)
};                            // 28

// Teensy -> PC @ 5 Hz and on change
struct ConfigEchoPacket {
    uint8_t  type;            // PKT_CONFIG_ECHO
    uint8_t  motor_id;
    uint8_t  zeroed;
    uint8_t  limits_valid;
    float    kp;              // sent to motor each tick
    float    kd;
    float    ki;              // Teensy-side integral gain
    float    tff_Nm;
    float    limit_left_deg;
    float    limit_right_deg;
};                            // 28

// Teensy -> PC on occurrence
struct EventPacket {
    uint8_t  type;            // PKT_EVENT
    uint8_t  code;            // EV_*
    uint16_t arg;
    uint32_t t_ms;
    char     text[20];        // NUL-padded reason / detail
};                            // 28

// Teensy -> PC after CMD_CAN_SCAN
struct CanScanPacket {
    uint8_t  type;            // PKT_CAN_SCAN
    uint8_t  count;
    uint8_t  ids[16];
};                            // 18

// PC -> Teensy
struct GainsPacket {
    uint8_t  type;            // PKT_GAINS
    uint8_t  reserved[3];
    float    kp;
    float    kd;
    float    ki;
    float    tff_Nm;
};                            // 20

struct SetpointPacket {
    uint8_t  type;            // PKT_SETPOINT
    uint8_t  flags;           // bit0 = last sample of a trajectory
    uint16_t seq;
    uint32_t t_ms;            // PC time base (for latency estimation)
    float    pos_deg;
    float    vel_ff_deg_s;    // optional velocity feed-forward
};                            // 16

struct ModeRequestPacket {
    uint8_t  type;            // PKT_MODE_REQUEST
    uint8_t  mode;            // MODE_*
    uint8_t  sticky;          // 1 = keep until another request
    uint8_t  reserved;
};                            // 4

struct CommandPacket {
    uint8_t  type;            // PKT_COMMAND
    uint8_t  cmd;             // CMD_*
    uint16_t arg;
    float    farg;
};                            // 8

struct TestStartPacket {
    uint8_t  type;            // PKT_TEST_START
    uint8_t  test_type;       // TEST_*
    uint8_t  reserved[2];
    float    amplitude_deg;
    float    duration_s;
    float    param;           // relay: hysteresis deg ; step: hold time s
};                            // 16

struct HeartbeatPacket {
    uint8_t  type;            // PKT_HEARTBEAT
    uint8_t  flags;           // HB_*
    uint16_t pc_health_bits;  // PC-side node summary (for OLED group D/F)
    uint32_t t_ms;
};                            // 8

struct LimitsPacket {
    uint8_t  type;            // PKT_LIMITS
    uint8_t  reserved[3];
    float    left_deg;
    float    right_deg;
};                            // 12

#pragma pack(pop)

static_assert(sizeof(TelemetryPacket)    == 28, "TelemetryPacket size");
static_assert(sizeof(HealthPacket)       == 28, "HealthPacket size");
static_assert(sizeof(ConfigEchoPacket)   == 28, "ConfigEchoPacket size");
static_assert(sizeof(EventPacket)        == 28, "EventPacket size");
static_assert(sizeof(CanScanPacket)      == 18, "CanScanPacket size");
static_assert(sizeof(GainsPacket)        == 20, "GainsPacket size");
static_assert(sizeof(SetpointPacket)     == 16, "SetpointPacket size");
static_assert(sizeof(ModeRequestPacket)  ==  4, "ModeRequestPacket size");
static_assert(sizeof(CommandPacket)      ==  8, "CommandPacket size");
static_assert(sizeof(TestStartPacket)    == 16, "TestStartPacket size");
static_assert(sizeof(HeartbeatPacket)    ==  8, "HeartbeatPacket size");
static_assert(sizeof(LimitsPacket)       == 12, "LimitsPacket size");

// ---- CRC-8/MAXIM (poly 0x31 reflected = 0x8C) ------------------------------
static inline uint8_t protocol_crc8(const uint8_t* d, uint8_t len) {
    uint8_t crc = 0x00;
    while (len--) {
        uint8_t b = *d++;
        for (uint8_t i = 0; i < 8; i++) {
            uint8_t mix = (crc ^ b) & 0x01;
            crc >>= 1;
            if (mix) crc ^= 0x8C;
            b >>= 1;
        }
    }
    return crc;
}

// ---- tiny streaming frame parser (shared by firmware and tests) -----------
// Usage:  FrameParser p;  for each byte: if (p.push(b)) handle(p.payload, p.len);
struct FrameParser {
    uint8_t  state   = 0;
    uint8_t  len     = 0;
    uint8_t  seq     = 0;
    uint8_t  idx     = 0;
    uint8_t  payload[MAX_PAYLOAD];
    uint32_t frames_ok = 0, crc_errors = 0, sync_errors = 0, drops = 0;
    uint8_t  last_seq = 0;
    bool     have_seq = false;

    bool push(uint8_t b) {
        switch (state) {
        case 0: if (b == FRAME_SYNC0) state = 1; else sync_errors++; return false;
        case 1: if (b == FRAME_SYNC1) state = 2; else { state = (b == FRAME_SYNC0) ? 1 : 0; sync_errors++; } return false;
        case 2: if (b == 0 || b > MAX_PAYLOAD) { state = 0; sync_errors++; return false; }
                len = b; idx = 0; state = 3; return false;
        case 3: seq = b; state = 4; return false;
        case 4: payload[idx++] = b; if (idx >= len) state = 5; return false;
        case 5: {
                state = 0;
                uint8_t hdr[2] = { len, seq };
                uint8_t crc = protocol_crc8(hdr, 2);
                // continue CRC over payload (same algorithm, chained)
                uint8_t c = crc;
                for (uint8_t i = 0; i < len; i++) {
                    uint8_t x = payload[i];
                    for (uint8_t k = 0; k < 8; k++) {
                        uint8_t mix = (c ^ x) & 0x01; c >>= 1; if (mix) c ^= 0x8C; x >>= 1;
                    }
                }
                if (c != b) { crc_errors++; return false; }
                if (have_seq && (uint8_t)(seq - last_seq) != 1) drops += (uint8_t)(seq - last_seq - 1);
                last_seq = seq; have_seq = true; frames_ok++;
                return true;
            }
        }
        state = 0;
        return false;
    }
};

// Encode a frame into `out` (must hold len + FRAME_OVERHEAD). Returns bytes written.
static inline uint8_t protocol_encode(uint8_t* out, const void* payload, uint8_t len, uint8_t seq) {
    out[0] = FRAME_SYNC0; out[1] = FRAME_SYNC1; out[2] = len; out[3] = seq;
    const uint8_t* p = (const uint8_t*)payload;
    for (uint8_t i = 0; i < len; i++) out[4 + i] = p[i];
    out[4 + len] = protocol_crc8(out + 2, (uint8_t)(len + 2));
    return (uint8_t)(len + FRAME_OVERHEAD);
}
