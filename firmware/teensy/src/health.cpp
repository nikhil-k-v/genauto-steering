#include <Arduino.h>
#include "health.h"
#include "config.h"
#include "control.h"
#include "can_motor.h"

static bool     s_oled_ok = false;
static uint16_t s_pc_bits = 0;
static uint32_t s_last_rx_motor = 0, s_last_rx_other = 0, s_last_ticks = 0, s_last_overruns = 0;
static uint32_t s_last_ms = 0;
static uint16_t s_can_tx_failed_prev = 0;

void health_set_oled_ok(bool ok)        { s_oled_ok = ok; }
void health_set_pc_bits(uint16_t bits)  { s_pc_bits = bits; }
uint16_t health_pc_bits()               { return s_pc_bits; }

static inline void set_node(uint32_t& w, uint8_t node, uint8_t state) {
    w &= ~(0x3u << (2 * node));
    w |= ((uint32_t)(state & 0x3)) << (2 * node);
}

static inline uint16_t age_ms(uint32_t last, uint32_t now) {
    if (!last) return 0xFFFF;
    uint32_t a = now - last;
    return a > 0xFFFE ? 0xFFFE : (uint16_t)a;
}

void health_update(HealthSnapshot& s) {
    const uint32_t now = millis();
    const uint32_t dt_ms = s_last_ms ? (now - s_last_ms) : (1000 / HEALTH_HZ);
    s_last_ms = now;
    const float scale = dt_ms ? 1000.f / (float)dt_ms : 0.f;

    // ---- rates from counters --------------------------------------------------
    const uint32_t rx_motor = g_can.rx_motor, rx_other = g_can.rx_other;
    const uint32_t ticks = g_ctl.ticks, overruns = g_ctl.overruns;
    s.can_rx_motor_hz = (uint16_t)((rx_motor - s_last_rx_motor) * scale);
    s.can_rx_other_hz = (uint16_t)((rx_other - s_last_rx_other) * scale);
    s.loop_hz         = (uint16_t)((ticks - s_last_ticks) * scale);
    const uint32_t ov = overruns - s_last_overruns;
    s.isr_overruns    = ov > 255 ? 255 : (uint8_t)ov;
    s_last_rx_motor = rx_motor; s_last_rx_other = rx_other; s_last_ticks = ticks; s_last_overruns = overruns;

    s.pc_hb_age_ms  = age_ms(g_ctl.pc_hb_last_ms, now);
    s.bridge_age_ms = age_ms(g_ctl.bridge_last_ms, now);
    s.motor_age_ms  = 0xFFFF;
    if (g_motor.valid) { uint32_t a = (micros() - g_motor.t_us) / 1000; s.motor_age_ms = a > 0xFFFE ? 0xFFFE : a; }

    // ---- nodes ----------------------------------------------------------------
    uint32_t w = 0;
    const bool enabled = control_motor_enabled();

    // A1 controller / transceiver / wiring
    set_node(w, HN_CAN_CTRL, g_can.bus_state == 3 ? HS_FAIL : g_can.bus_state >= 1 ? HS_BLOCKED : HS_OK);

    // A2 TX accepted by mailbox.  While REST we still send nothing, so judge by failures.
    const uint16_t txf = (uint16_t)g_can.tx_failed;
    const bool tx_failing = (uint16_t)(txf - s_can_tx_failed_prev) > 5;
    s_can_tx_failed_prev = txf;
    set_node(w, HN_CAN_TX, tx_failing ? HS_FAIL : (g_can.tec > 127 ? HS_BLOCKED : HS_OK));

    // A3 anything on the bus.  Unknown until something is heard at all.
    set_node(w, HN_CAN_RX_ANY, (rx_motor + rx_other) == 0 ? HS_UNKNOWN
                             : (s.can_rx_motor_hz + s.can_rx_other_hz) > 0 ? HS_OK : HS_BLOCKED);

    // A4 motor replies.  When enabled we expect ~1 kHz; in REST the BM-18 is
    // silent (it only answers commands), so "no reply" is BLOCKED (= "motor
    // not powered or not responding; you cannot enable"), not FAIL.
    if (s.motor_age_ms == 0xFFFF)                  set_node(w, HN_CAN_MOTOR, HS_UNKNOWN);
    else if (s.motor_age_ms > CAN_REPLY_TIMEOUT_MS) set_node(w, HN_CAN_MOTOR, enabled ? HS_FAIL : HS_BLOCKED);
    else if (enabled && s.can_rx_motor_hz < CAN_RX_LOW_HZ) set_node(w, HN_CAN_MOTOR, HS_BLOCKED);
    else                                            set_node(w, HN_CAN_MOTOR, HS_OK);

    // A5 reply data sane
    static uint32_t frozen_prev = 0;
    const bool frozen = g_can.rx_frozen != frozen_prev; frozen_prev = g_can.rx_frozen;
    const bool nan = isnan(g_motor.pos_rad) || isnan(g_motor.vel_rad_s);
    set_node(w, HN_MOTOR_DATA, !g_motor.valid ? HS_UNKNOWN : (nan ? HS_FAIL : frozen ? HS_BLOCKED : HS_OK));

    // A6 current
    const float cur = fabsf(g_motor.cur_A);
    set_node(w, HN_MOTOR_CURRENT, !g_motor.valid ? HS_UNKNOWN : cur > CURRENT_CUTOFF_A ? HS_FAIL
                                  : cur > CURRENT_CUTOFF_A * 0.7f ? HS_BLOCKED : HS_OK);

    // B1 switch, B2 trip
    set_node(w, HN_SWITCH, g_ctl.switch_armed ? HS_OK : HS_BLOCKED);
    set_node(w, HN_TRIP,   g_ctl.cs == CS_TRIPPED ? HS_FAIL : HS_OK);

    // C1 loop
    set_node(w, HN_ISR, s.isr_overruns > 10 ? HS_FAIL : (s.loop_hz < CONTROL_HZ * 95 / 100 || s.isr_overruns) ? HS_BLOCKED : HS_OK);

    // C2 ready for absolute-position work
    set_node(w, HN_CTRL_READY, (g_ctl.zeroed && g_ctl.limits_valid) ? HS_OK : HS_BLOCKED);

    // C3 calibration
    set_node(w, HN_CALIB, g_ctl.calib == CAL_FAILED ? HS_FAIL
                        : (g_ctl.cs == CS_CALIB) ? HS_BLOCKED : HS_OK);

    // D1 PC link as seen from here
    set_node(w, HN_PC_LINK, s.pc_hb_age_ms == 0xFFFF ? HS_UNKNOWN : s.pc_hb_age_ms > PC_HEARTBEAT_TIMEOUT_MS ? HS_FAIL : HS_OK);

    // E1 bridge
#if WIRED_MODE
    set_node(w, HN_BRIDGE_LINK, s.bridge_age_ms == 0xFFFF ? HS_UNKNOWN : s.bridge_age_ms > BRIDGE_TIMEOUT_MS ? HS_BLOCKED : HS_OK);
#else
    set_node(w, HN_BRIDGE_LINK, s.bridge_age_ms == 0xFFFF ? HS_UNKNOWN : s.bridge_age_ms > BRIDGE_TIMEOUT_MS ? HS_FAIL : HS_OK);
#endif

    // C4 OLED
    set_node(w, HN_OLED, s_oled_ok ? HS_OK : HS_BLOCKED);

    s.node_states = w;
}

void health_fill_packet(HealthPacket& p, const HealthSnapshot& s) {
    p.type = PKT_HEALTH;
    p.trip_code = g_ctl.trip;
    p.calib_stage = g_ctl.calib;
    p.ctrl_state = g_ctl.cs;
    p.t_ms = millis();
    p.node_states = s.node_states;
    p.can_rx_motor_hz = s.can_rx_motor_hz;
    p.can_rx_other_hz = s.can_rx_other_hz;
    p.can_tec = g_can.tec; p.can_rec = g_can.rec; p.can_bus_state = g_can.bus_state;
    p.isr_overruns = s.isr_overruns;
    p.loop_hz = s.loop_hz;
    p.pc_hb_age_ms = s.pc_hb_age_ms;
    p.bridge_age_ms = s.bridge_age_ms;
    p.motor_age_ms = s.motor_age_ms;
}

// Group membership mirrors docs/HEALTH.md and pc/steering/health/model.py.
static const uint8_t GROUP_A[] = { HN_CAN_CTRL, HN_CAN_TX, HN_CAN_RX_ANY, HN_CAN_MOTOR, HN_MOTOR_DATA, HN_MOTOR_CURRENT };
static const uint8_t GROUP_B[] = { HN_SWITCH, HN_TRIP };
static const uint8_t GROUP_C[] = { HN_ISR, HN_CTRL_READY, HN_CALIB, HN_OLED };
static const uint8_t GROUP_D[] = { HN_PC_LINK };
static const uint8_t GROUP_E[] = { HN_BRIDGE_LINK };

static void group_of(uint32_t w, const uint8_t* nodes, uint8_t n, char letter, HealthGroup& g) {
    g.letter = letter; g.state = HS_OK; g.first_bad = 0;
    for (uint8_t i = 0; i < n; i++) {
        const uint8_t st = health_node(w, nodes[i]);
        // UNKNOWN is shown as BLOCKED-ish (hollow) but never hides a FAIL
        const uint8_t rank = st == HS_FAIL ? 3 : st == HS_BLOCKED ? 2 : st == HS_UNKNOWN ? 1 : 0;
        const uint8_t cur  = g.state == HS_FAIL ? 3 : g.state == HS_BLOCKED ? 2 : g.state == HS_UNKNOWN ? 1 : 0;
        if (rank > cur) { g.state = st; }
        if (st != HS_OK && g.first_bad == 0) g.first_bad = i + 1;
    }
}

void health_groups(const HealthSnapshot& s, HealthGroup out[6]) {
    group_of(s.node_states, GROUP_A, sizeof GROUP_A, 'A', out[0]);
    group_of(s.node_states, GROUP_B, sizeof GROUP_B, 'B', out[1]);
    group_of(s.node_states, GROUP_C, sizeof GROUP_C, 'C', out[2]);
    group_of(s.node_states, GROUP_D, sizeof GROUP_D, 'D', out[3]);
    group_of(s.node_states, GROUP_E, sizeof GROUP_E, 'E', out[4]);
    // F = PC-side data/server group, relayed in the heartbeat: bits 0..3 =
    // recorder, store, server, phone (1 = ok), bit 15 = valid.
    out[5].letter = 'F';
    if (!(s_pc_bits & 0x8000)) { out[5].state = HS_UNKNOWN; out[5].first_bad = 0; }
    else {
        out[5].state = HS_OK; out[5].first_bad = 0;
        for (uint8_t i = 0; i < 4; i++) if (!(s_pc_bits & (1u << i))) { out[5].state = HS_BLOCKED; out[5].first_bad = i + 1; break; }
    }
}
