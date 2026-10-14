#include <Arduino.h>
#include <FlexCAN_T4.h>
#include "can_motor.h"

// TX_SIZE_16 is required (the 1 kHz stream overflows smaller rings when the
// bus hiccups); RX_SIZE_256 absorbs the burst that arrives while the main
// loop is drawing the OLED.
static FlexCAN_T4<CAN3, RX_SIZE_256, TX_SIZE_16> CANbus;

MotorSample g_motor = {};
CanCounters g_can   = {};
volatile uint8_t g_motor_id = MOTOR_CAN_ID_DEFAULT;

static volatile uint8_t  s_pending_special = SPECIAL_NONE;
static volatile uint8_t  s_tx_seq = 0;
static uint8_t           s_last_payload[8];
static uint8_t           s_same_count = 0;
static volatile bool     s_scanning = false;
static volatile bool     s_seen[128];

// ---- MIT-style packing ---------------------------------------------------------
static inline float fclampf(float x, float a, float b) { return x < a ? a : (x > b ? b : x); }

static inline uint16_t f2u(float x, float xmin, float xmax, int bits) {
    x = fclampf(x, xmin, xmax);
    const float scale = (float)((1u << bits) - 1);
    return (uint16_t)((x - xmin) * (scale / (xmax - xmin)) + 0.5f);
}
static inline float u2f(uint16_t u, float xmin, float xmax, int bits) {
    const float scale = (float)((1u << bits) - 1);
    return ((float)u) * (xmax - xmin) / scale + xmin;
}

static void pack_cmd(uint8_t out[8], float p, float v, float kp, float kd, float t) {
    const uint16_t P  = f2u(p,  MOTOR_P_MIN_RAD,   MOTOR_P_MAX_RAD,   16);
    const uint16_t V  = f2u(v,  MOTOR_V_MIN_RAD_S, MOTOR_V_MAX_RAD_S, 12);
    const uint16_t KP = f2u(kp, MOTOR_KP_MIN,      MOTOR_KP_MAX,      12);
    const uint16_t KD = f2u(kd, MOTOR_KD_MIN,      MOTOR_KD_MAX,      12);
    const uint16_t T  = f2u(t,  MOTOR_T_MIN_NM,    MOTOR_T_MAX_NM,    12);
    out[0] = P >> 8;            out[1] = P & 0xFF;
    out[2] = V >> 4;            out[3] = ((V & 0x0F) << 4) | ((KP >> 8) & 0x0F);
    out[4] = KP & 0xFF;         out[5] = KD >> 4;
    out[6] = ((KD & 0x0F) << 4) | ((T >> 8) & 0x0F);
    out[7] = T & 0xFF;
}

// Reply layout (verified on hardware — the datasheet table is off by one):
//   buf[0] = motor id echo
//   buf[1..2] = position (16 bit)
//   buf[3], buf[4]>>4 = velocity (12 bit)
//   buf[4]&0xF, buf[5] = current/torque (12 bit)
static inline void unpack_reply(const uint8_t b[8], float& p, float& v, float& t) {
    const uint16_t P = ((uint16_t)b[1] << 8) | b[2];
    const uint16_t V = ((uint16_t)b[3] << 4) | (b[4] >> 4);
    const uint16_t T = (((uint16_t)b[4] & 0x0F) << 8) | b[5];
    p = u2f(P, MOTOR_P_MIN_RAD,   MOTOR_P_MAX_RAD,   16);
    v = u2f(V, MOTOR_V_MIN_RAD_S, MOTOR_V_MAX_RAD_S, 12);
    t = u2f(T, MOTOR_T_MIN_NM,    MOTOR_T_MAX_NM,    12);
}

// ---- RX (runs from CANbus.events() in main-loop context) -------------------------
static void on_can_rx(const CAN_message_t& m) {
    if (m.len != 8) { g_can.rx_bad_len++; return; }
    const uint8_t id = m.buf[0];
    if (id < 128) s_seen[id] = true;
    if (id != g_motor_id) { g_can.rx_other++; return; }

    // frozen-data detector: identical payload 200x in a row = encoder/driver stuck
    if (memcmp(s_last_payload, m.buf, 8) == 0) { if (s_same_count < 255) s_same_count++; }
    else s_same_count = 0;
    memcpy(s_last_payload, m.buf, 8);
    if (s_same_count > 200) g_can.rx_frozen++;

    float p, v, t;
    unpack_reply(m.buf, p, v, t);
    noInterrupts();                 // the ISR reads these as a set
    g_motor.pos_rad   = p;
    g_motor.vel_rad_s = v;
    g_motor.cur_A     = t;
    g_motor.t_us      = micros();
    g_motor.count++;
    g_motor.valid     = true;
    interrupts();
    g_can.rx_motor++;
}

void can_motor_begin() {
    CANbus.begin();
    CANbus.setBaudRate(CAN_BITRATE);
    CANbus.setMaxMB(16);
    CANbus.enableFIFO();
    CANbus.enableFIFOInterrupt();
    CANbus.onReceive(on_can_rx);
    memset((void*)s_seen, 0, sizeof(s_seen));
}

// Read the FlexCAN3 error registers directly (library-independent, no
// interrupt plumbing).  ECR = error counters, ESR1 = fault confinement.
// Reference: i.MX RT1060 RM, FlexCAN chapter.
#ifndef IMXRT_FLEXCAN3_ADDRESS
#define IMXRT_FLEXCAN3_ADDRESS 0x401D8000
#endif
#define FLEXCAN3_ECR  (*(volatile uint32_t*)(IMXRT_FLEXCAN3_ADDRESS + 0x1C))
#define FLEXCAN3_ESR1 (*(volatile uint32_t*)(IMXRT_FLEXCAN3_ADDRESS + 0x20))

void can_motor_poll() {
    CANbus.events();
    const uint32_t ecr  = FLEXCAN3_ECR;
    const uint32_t esr1 = FLEXCAN3_ESR1;
    g_can.tec = (uint8_t)(ecr & 0xFF);
    g_can.rec = (uint8_t)((ecr >> 8) & 0xFF);
    const uint32_t fltconf = (esr1 >> 4) & 0x3;   // 00 active, 01 passive, 1x bus-off
    g_can.bus_state = (fltconf & 0x2) ? 3 : (fltconf == 1) ? 2
                    : (g_can.tec > 96 || g_can.rec > 96) ? 1 : 0;
}

void can_motor_queue_special(CanSpecial s) { s_pending_special = s; }
bool can_motor_special_pending()           { return s_pending_special != SPECIAL_NONE; }

CanSpecial can_motor_tick_send(bool send_cmd, float p, float v, float kp, float kd, float t) {
    CAN_message_t m;
    m.id = g_motor_id;
    m.len = 8;
    m.flags.extended = 0;

    const uint8_t special = s_pending_special;
    if (special != SPECIAL_NONE) {
        s_pending_special = SPECIAL_NONE;
        for (int i = 0; i < 7; i++) m.buf[i] = 0xFF;
        m.buf[7] = special;
        if (CANbus.write(m)) g_can.tx_frames++; else g_can.tx_failed++;
        return (CanSpecial)special;
    }
    if (!send_cmd || s_scanning) return SPECIAL_NONE;
    pack_cmd(m.buf, p, v, kp, kd, t);
    if (CANbus.write(m)) g_can.tx_frames++; else g_can.tx_failed++;
    return SPECIAL_NONE;
}

// Blocking scan: only legal in REST (the caller checks).  Pings every id with
// a zero-gain, zero-torque command (harmless) and collects who answers.
void can_motor_scan(uint8_t first, uint8_t last, uint8_t* found, uint8_t& n_found) {
    if (first < 1) first = 1;
    if (last > 127) last = 127;
    if (first > last) { uint8_t x = first; first = last; last = x; }
    memset((void*)s_seen, 0, sizeof(s_seen));
    s_scanning = true;
    uint8_t ping[8];
    pack_cmd(ping, 0, 0, 0, 0, 0);
    for (uint8_t id = first; id <= last; id++) {
        CAN_message_t m; m.id = id; m.len = 8; m.flags.extended = 0;
        memcpy(m.buf, ping, 8);
        CANbus.write(m); delayMicroseconds(400);
        CANbus.write(m); delayMicroseconds(400);
        CANbus.events();
    }
    const uint32_t until = millis() + 600;
    while ((int32_t)(millis() - until) < 0) { CANbus.events(); yield(); }
    n_found = 0;
    for (uint8_t id = first; id <= last && n_found < 16; id++) if (s_seen[id]) found[n_found++] = id;
    s_scanning = false;
}
