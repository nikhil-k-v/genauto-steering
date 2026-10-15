// =============================================================================
// test_can_host.cpp — runs the real firmware (all of src/) on the host against a
// simulated BM motor on a simulated CAN bus (test/host_sim/).  Covers the path
// that broke on hardware: the motor must be heard with the motor off, so that
// Position control can be turned on at all, and the CAN scan must work without
// stalling the main loop.
//
//   scripts/check_firmware.sh        (builds and runs this)
// =============================================================================
#include "../src/can_motor.cpp"
#include "../src/control.cpp"
#include "../src/comms.cpp"
#include "../src/health.cpp"
#include "../src/display.cpp"
#include "../src/main.cpp"

const uint8_t u8g2_font_5x8_tr[1] = {0}, u8g2_font_7x13B_tr[1] = {0};

static int g_fail = 0;
#define CHECK(c, ...) do { if (!(c)) { g_fail++; printf("  FAIL %s:%d  %s  -- ", __FILE__, __LINE__, #c); printf(__VA_ARGS__); printf("\n"); } } while (0)

// ---- PC side: what the laptop would see on USB ---------------------------------
struct PcView {
    FrameParser parser;
    HealthPacket health{}; bool have_health = false;
    TelemetryPacket telem{}; uint64_t last_telem_us = 0, max_telem_gap_us = 0;
    std::vector<EventPacket> events;
    std::vector<CanScanPacket> scans;
    ConfigEchoPacket config{};
    void drain() {
        for (uint8_t b : Serial.out) if (parser.push(b)) {
            const uint8_t* p = parser.payload;
            switch (p[0]) {
            case PKT_HEALTH:      memcpy(&health, p, sizeof health); have_health = true; break;
            case PKT_TELEMETRY:   memcpy(&telem, p, sizeof telem);
                                  if (last_telem_us && host_now_us - last_telem_us > max_telem_gap_us) max_telem_gap_us = host_now_us - last_telem_us;
                                  last_telem_us = host_now_us; break;
            case PKT_EVENT:       { EventPacket e; memcpy(&e, p, sizeof e); events.push_back(e); break; }
            case PKT_CAN_SCAN:    { CanScanPacket s; memcpy(&s, p, sizeof s); scans.push_back(s); break; }
            case PKT_CONFIG_ECHO: memcpy(&config, p, sizeof config); break;
            }
        }
        Serial.out.clear();
    }
    int node(int hn) const { return (health.node_states >> (2 * hn)) & 3; }
    const EventPacket* last(uint8_t code, uint16_t arg) const {
        for (auto it = events.rbegin(); it != events.rend(); ++it) if (it->code == code && it->arg == arg) return &*it;
        return nullptr;
    }
};
static PcView pc;
static uint8_t s_pc_seq = 0;

template<class Pk> static void pc_send(const Pk& pk) {
    uint8_t buf[MAX_PAYLOAD + FRAME_OVERHEAD];
    const uint8_t n = protocol_encode(buf, &pk, sizeof pk, s_pc_seq++);
    for (uint8_t i = 0; i < n; i++) Serial.in.push_back(buf[i]);
}
static void command(uint8_t cmd, uint16_t arg = 0, float farg = 0) {
    CommandPacket c{}; c.type = PKT_COMMAND; c.cmd = cmd; c.arg = arg; c.farg = farg; pc_send(c);
}
static void heartbeat() {
    HeartbeatPacket h{}; h.type = PKT_HEARTBEAT; h.flags = HB_UI_ALIVE; h.pc_health_bits = 0xFF; pc_send(h);
}

// Advance simulated time: 1 kHz ISR, main loop a few times per ms, PC heartbeat 5 Hz.
static void run_ms(uint32_t ms) {
    for (uint32_t i = 0; i < ms; i++) {
        for (int k = 0; k < 4; k++) { host_now_us += 250; loop(); }
        if (host_timer_fn) host_timer_fn();
        if (millis() % 200 == 0) heartbeat();
        pc.drain();
    }
}

static const char* hs(int s) { return s == HS_OK ? "OK" : s == HS_BLOCKED ? "BLOCKED" : s == HS_FAIL ? "FAIL" : "UNKNOWN"; }

int main() {
    setup();
    run_ms(600);

    printf("motor off (REST):\n");
    printf("  motor replies %u Hz, M3 %s, M4 %s, rest commands seen by motor %u, exits %u\n",
           pc.health.can_rx_motor_hz, hs(pc.node(HN_CAN_RX_ANY)), hs(pc.node(HN_CAN_MOTOR)),
           host_motor.cmds_in_rest, host_motor.exits);
    CHECK(pc.have_health, "no HealthPacket");
    CHECK(host_motor.exits >= 1, "boot must send exit-motor-mode once");
    CHECK(!host_motor.motor_mode, "motor must stay in REST");
    CHECK(pc.health.can_rx_motor_hz >= CAN_RX_REST_LOW_HZ, "motor not heard with the motor off (%u Hz)", pc.health.can_rx_motor_hz);
    CHECK(pc.node(HN_CAN_RX_ANY) == HS_OK, "M3 %s", hs(pc.node(HN_CAN_RX_ANY)));
    CHECK(pc.node(HN_CAN_MOTOR) == HS_OK, "M4 %s", hs(pc.node(HN_CAN_MOTOR)));
    CHECK(pc.node(HN_MOTOR_DATA) == HS_OK, "M5 %s (still wheel must not read as frozen)", hs(pc.node(HN_MOTOR_DATA)));
    CHECK(fabsf(pc.telem.position_deg - rad2deg(0.4f)) < 0.1f, "position not live in REST: %.2f", pc.telem.position_deg);
    run_ms(3000);   // > 200 identical replies: a still wheel in REST is not "frozen"
    CHECK(pc.node(HN_MOTOR_DATA) == HS_OK, "M5 %s after 3 s still", hs(pc.node(HN_MOTOR_DATA)));

    printf("turn on (Position control):\n");
    command(CMD_ENABLE); run_ms(300);
    const EventPacket* rej = pc.last(EV_CMD_REJECTED, CMD_ENABLE);
    CHECK(!rej, "enable rejected: %s", rej ? rej->text : "");
    CHECK(pc.last(EV_CMD_ACCEPTED, CMD_ENABLE), "enable not accepted");
    CHECK(g_ctl.cs == CS_HOLD, "state %u", g_ctl.cs);
    CHECK(host_motor.motor_mode && host_motor.enters == 1, "enter-motor-mode not sent");
    run_ms(500);
    printf("  state %u, motor replies %u Hz, M4 %s\n", g_ctl.cs, pc.health.can_rx_motor_hz, hs(pc.node(HN_CAN_MOTOR)));
    CHECK(pc.health.can_rx_motor_hz >= CAN_RX_LOW_HZ, "rx %u Hz while on", pc.health.can_rx_motor_hz);
    CHECK(pc.node(HN_CAN_MOTOR) == HS_OK, "M4 %s while on", hs(pc.node(HN_CAN_MOTOR)));

    printf("scan refused while on, then off and scan:\n");
    command(CMD_CAN_SCAN, 1, 127); run_ms(50);
    CHECK(pc.last(EV_CMD_REJECTED, CMD_CAN_SCAN), "scan must be refused with the motor on");
    command(CMD_DISABLE); run_ms(100);
    CHECK(g_ctl.cs == CS_REST && !host_motor.motor_mode, "disable did not rest the motor");
    pc.max_telem_gap_us = 0;
    command(CMD_CAN_SCAN, 1, 127);
    run_ms(150);
    command(CMD_ENABLE); run_ms(5);             // a scan must not be interrupted by motor mode
    CHECK(pc.last(EV_CMD_REJECTED, CMD_ENABLE), "enable must wait for the scan");
    run_ms(450);
    CHECK(pc.scans.size() == 1, "%zu scan results", pc.scans.size());
    if (!pc.scans.empty()) {
        printf("  scan found %u id(s): %u; longest telemetry gap %.1f ms\n", pc.scans[0].count, pc.scans[0].ids[0], pc.max_telem_gap_us / 1000.0);
        CHECK(pc.scans[0].count == 1 && pc.scans[0].ids[0] == 2, "scan result");
    }
    CHECK(pc.max_telem_gap_us < 20000, "main loop stalled during the scan (%.1f ms)", pc.max_telem_gap_us / 1000.0);
    run_ms(300);
    CHECK(pc.node(HN_CAN_MOTOR) == HS_OK, "M4 %s after the scan", hs(pc.node(HN_CAN_MOTOR)));

    printf("wrong motor id: turning on ends in a safety stop, then fixed:\n");
    command(CMD_SET_MOTOR_ID, 5); run_ms(400);
    printf("  id 5: M4 %s, replies %u Hz\n", hs(pc.node(HN_CAN_MOTOR)), pc.health.can_rx_motor_hz);
    CHECK(pc.config.motor_id == 5, "config echo id %u", pc.config.motor_id);
    CHECK(pc.node(HN_CAN_MOTOR) != HS_OK, "M4 must not be OK with the wrong id");
    command(CMD_ENABLE); run_ms(400);
    CHECK(g_ctl.cs == CS_TRIPPED && g_ctl.trip == TRIP_CAN_LOST, "wrong id: state %u trip %u", g_ctl.cs, g_ctl.trip);
    command(CMD_CLEAR_TRIP); command(CMD_SET_MOTOR_ID, 2); run_ms(400);
    CHECK(pc.node(HN_CAN_MOTOR) == HS_OK, "M4 %s after id fixed", hs(pc.node(HN_CAN_MOTOR)));

    printf("motor unpowered: turning on ends in a safety stop:\n");
    host_motor.powered = false; run_ms(400);
    printf("  M4 %s\n", hs(pc.node(HN_CAN_MOTOR)));
    CHECK(pc.node(HN_CAN_MOTOR) == HS_UNKNOWN, "M4 %s with the motor unpowered and off", hs(pc.node(HN_CAN_MOTOR)));
    command(CMD_ENABLE); run_ms(400);
    CHECK(g_ctl.cs == CS_TRIPPED && g_ctl.trip == TRIP_CAN_LOST, "unpowered: state %u trip %u", g_ctl.cs, g_ctl.trip);
    host_motor.powered = true; host_motor.motor_mode = false;
    command(CMD_CLEAR_TRIP); run_ms(300);
    command(CMD_ENABLE); run_ms(300);
    CHECK(g_ctl.cs == CS_HOLD, "re-enable after power returns: state %u", g_ctl.cs);

    printf("motor power lost while on:\n");
    host_motor.powered = false; run_ms(400);
    CHECK(g_ctl.cs == CS_TRIPPED && g_ctl.trip == TRIP_CAN_LOST, "state %u trip %u", g_ctl.cs, g_ctl.trip);
    host_motor.powered = true; host_motor.motor_mode = false; run_ms(400);
    CHECK(pc.node(HN_CAN_MOTOR) == HS_OK, "M4 %s: motor heard again while stopped", hs(pc.node(HN_CAN_MOTOR)));

    printf("motor that only answers in motor mode (datasheet reading):\n");
    command(CMD_CLEAR_TRIP);
    host_motor.answers_in_rest = false; host_motor.pos_rad = -0.25f; run_ms(500);
    printf("  off: replies %u Hz, M4 %s\n", pc.health.can_rx_motor_hz, hs(pc.node(HN_CAN_MOTOR)));
    CHECK(pc.node(HN_CAN_MOTOR) == HS_UNKNOWN, "silent motor off: M4 %s (no data, not a fault)", hs(pc.node(HN_CAN_MOTOR)));
    pc.events.clear();
    command(CMD_ENABLE); run_ms(5);
    CHECK(!pc.last(EV_CMD_REJECTED, CMD_ENABLE), "enable must not need a reply first");
    run_ms(600);
    printf("  on: state %u, replies %u Hz, setpoint %.1f deg vs wheel %.1f deg\n", g_ctl.cs,
           pc.health.can_rx_motor_hz, g_ctl.sp_cmd_deg, control_pos_deg());
    CHECK(g_ctl.cs == CS_HOLD, "state %u trip %u", g_ctl.cs, g_ctl.trip);
    CHECK(pc.health.can_rx_motor_hz >= CAN_RX_LOW_HZ, "rx %u Hz while on", pc.health.can_rx_motor_hz);
    CHECK(fabsf(g_ctl.sp_cmd_deg - rad2deg(-0.25f)) < 0.5f, "setpoint must start at the measured angle (%.1f)", g_ctl.sp_cmd_deg);

    printf(g_fail ? "\n%d check(s) FAILED\n" : "\nfirmware host test OK\n", g_fail);
    return g_fail ? 1 : 0;
}
