#include <Arduino.h>
#include <SPI.h>
#include <RF24.h>
#include <string.h>
#include "comms.h"
#include "config.h"
#include "protocol.h"
#include "control.h"
#include "can_motor.h"
#include "health.h"

static RF24        s_radio(PIN_NRF_CE, PIN_NRF_CSN);
static bool        s_rf_ok = false;
static FrameParser s_usb_parser;
static uint8_t     s_tx_seq = 0;
static uint32_t    s_rf_telem_last_ms = 0;

bool comms_rf_present() { return s_rf_ok; }
uint32_t comms_frames_rx() { return s_usb_parser.frames_ok; }

// ---- send helpers ----------------------------------------------------------------
static void usb_send(const void* payload, uint8_t len) {
    uint8_t buf[MAX_PAYLOAD + FRAME_OVERHEAD];
    const uint8_t n = protocol_encode(buf, payload, len, s_tx_seq++);
    Serial.write(buf, n);
}
static void rf_send(const void* payload, uint8_t len) {
    if (!s_rf_ok) return;
    s_radio.stopListening();
    s_radio.write(payload, len);     // returns false on no-ack; we don't retry (telemetry is periodic)
    s_radio.startListening();
}
static void pc_send(const void* payload, uint8_t len) {
#if WIRED_MODE
    usb_send(payload, len);
#else
    rf_send(payload, len);
#endif
}

static void send_event(uint8_t code, uint16_t arg, const char* text) {
    EventPacket e; memset(&e, 0, sizeof e);
    e.type = PKT_EVENT; e.code = code; e.arg = arg; e.t_ms = millis();
    strncpy(e.text, text, sizeof(e.text) - 1);
    pc_send(&e, sizeof e);
}

void comms_emit_config() {
    ConfigEchoPacket c;
    c.type = PKT_CONFIG_ECHO; c.motor_id = g_motor_id;
    c.zeroed = g_ctl.zeroed; c.limits_valid = g_ctl.limits_valid;
    c.kp = g_ctl.kp; c.kd = g_ctl.kd; c.ki = g_ctl.ki; c.tff_Nm = g_ctl.tff_Nm;
    c.limit_left_deg = g_ctl.limit_left_deg; c.limit_right_deg = g_ctl.limit_right_deg;
    pc_send(&c, sizeof c);
}

// ---- dispatch ----------------------------------------------------------------------
static void handle_command(const CommandPacket& c) {
    char why[20];
    if (!control_command(c.cmd, c.arg, c.farg, why)) { send_event(EV_CMD_REJECTED, c.cmd, why); return; }
    switch (c.cmd) {
    case CMD_CAN_SCAN: {
        uint8_t ids[16], n = 0;
        const uint8_t first = (uint8_t)(c.arg ? c.arg : 1);
        const uint8_t last  = (uint8_t)(c.farg > 0 ? c.farg : 127);
        can_motor_scan(first, last, ids, n);
        CanScanPacket s; memset(&s, 0, sizeof s);
        s.type = PKT_CAN_SCAN; s.count = n; memcpy(s.ids, ids, n);
        pc_send(&s, sizeof s);
        break;
    }
    case CMD_REQ_CONFIG: comms_emit_config(); break;
    case CMD_RESET_COUNTERS:
        g_can.tx_frames = g_can.tx_failed = g_can.rx_motor = g_can.rx_other = g_can.rx_bad_len = g_can.rx_frozen = 0;
        g_ctl.overruns = 0;
        s_usb_parser.crc_errors = s_usb_parser.sync_errors = s_usb_parser.drops = 0;
        break;
    case CMD_SET_ZERO: case CMD_CAPTURE_LEFT: case CMD_CAPTURE_RIGHT: comms_emit_config(); break;
    default: break;
    }
}

static void dispatch(const uint8_t* p, uint8_t len) {
    if (len < 1) return;
    // Any well-formed PC packet proves the PC is alive (the 200 Hz setpoint
    // stream is a far better liveness signal than the 5 Hz heartbeat alone).
    if (p[0] != PKT_JOYSTICK && p[0] != PKT_BRIDGE_STATUS) control_note_pc_heartbeat();
    switch (p[0]) {
    case PKT_GAINS:        if (len == sizeof(GainsPacket)) { auto g = (const GainsPacket*)p; control_set_gains(g->kp, g->kd, g->ki, g->tff_Nm); comms_emit_config(); } break;
    case PKT_SETPOINT:     if (len == sizeof(SetpointPacket)) { auto s = (const SetpointPacket*)p; control_setpoint(s->seq, s->pos_deg, s->vel_ff_deg_s, s->flags); } break;
    case PKT_MODE_REQUEST: if (len == sizeof(ModeRequestPacket)) { auto m = (const ModeRequestPacket*)p; control_request_mode(m->mode, m->sticky); } break;
    case PKT_COMMAND:      if (len == sizeof(CommandPacket)) handle_command(*(const CommandPacket*)p); break;
    case PKT_TEST_START:   if (len == sizeof(TestStartPacket)) { auto t = (const TestStartPacket*)p; char why[20];
                               if (!control_start_test(t->test_type, t->amplitude_deg, t->duration_s, t->param, why)) send_event(EV_CMD_REJECTED, PKT_TEST_START, why); } break;
    case PKT_HEARTBEAT:    if (len == sizeof(HeartbeatPacket)) { auto h = (const HeartbeatPacket*)p; control_note_pc_heartbeat(); health_set_pc_bits(h->pc_health_bits | 0x8000);
                               if (!(h->flags & HB_UI_ALIVE) && (g_ctl.cs == CS_TRAJ || g_ctl.cs == CS_TEST)) { char w[20]; control_command(CMD_DISABLE, 0, 0, w); } } break;
    case PKT_LIMITS:       if (len == sizeof(LimitsPacket)) { auto l = (const LimitsPacket*)p; control_set_limits(l->left_deg, l->right_deg); comms_emit_config(); } break;
    case PKT_JOYSTICK:     if (len == sizeof(JoystickPacket)) { auto j = (const JoystickPacket*)p; control_joystick(j->x, j->y, j->buttons); control_note_bridge(); } break;
    case PKT_BRIDGE_STATUS: control_note_bridge(); break;
    default: break;
    }
}

// ---- transports ----------------------------------------------------------------------
void comms_begin() {
    Serial.begin(2000000);
    s_rf_ok = s_radio.begin();
    if (s_rf_ok) {
        s_radio.setChannel(NRF_CHANNEL);
        s_radio.setPALevel(RF24_PA_LOW);
        s_radio.setDataRate(RF24_2MBPS);
        s_radio.setAutoAck(true);
        s_radio.setRetries(1, 2);
        s_radio.enableDynamicPayloads();
        s_radio.openWritingPipe((const uint8_t*)NRF_ADDR_BRIDGE);
        s_radio.openReadingPipe(1, (const uint8_t*)NRF_ADDR_TEENSY);
        s_radio.startListening();
    }
}

void comms_poll() {
    // USB: bounded work per call so the loop never stalls behind a flood
    int budget = 512;
    while (budget-- && Serial.available()) {
        const uint8_t b = (uint8_t)Serial.read();
        if (s_usb_parser.push(b)) dispatch(s_usb_parser.payload, s_usb_parser.len);
    }
    if (s_rf_ok) {
        uint8_t pipe;
        int n = 8;
        while (n-- && s_radio.available(&pipe)) {
            const uint8_t len = s_radio.getDynamicPayloadSize();
            uint8_t buf[32];
            if (len == 0 || len > 32) { s_radio.flush_rx(); break; }
            s_radio.read(buf, len);
            dispatch(buf, len);
        }
    }
}

void comms_emit_telemetry() {
    TelemetryPacket t;
    t.type = PKT_TELEMETRY; t.ctrl_state = g_ctl.cs; t.flags = control_telemetry_flags();
    t.seq_setpoint = (uint8_t)g_ctl.sp_seq;
    t.t_us = micros();
    t.setpoint_deg = g_ctl.sp_cmd_deg;
    t.position_deg = control_pos_deg();
    t.velocity_deg_s = rad2deg(g_motor.vel_rad_s);
    t.current_A = g_motor.cur_A;
    t.torque_cmd_Nm = g_ctl.torque_cmd_Nm;
    pc_send(&t, sizeof t);
#if WIRED_MODE
    // 20 Hz copy to the bridge so its OLED can draw the dial
    const uint32_t now = millis();
    if (now - s_rf_telem_last_ms >= 50) { s_rf_telem_last_ms = now; rf_send(&t, sizeof t); }
#endif
}

void comms_emit_health(const HealthSnapshot& s) {
    HealthPacket h; health_fill_packet(h, s);
    pc_send(&h, sizeof h);
#if WIRED_MODE
    rf_send(&h, sizeof h);
#endif
}

void comms_emit_events() {
    ControlEvent ev;
    while (control_pop_event(ev)) send_event(ev.code, ev.arg, ev.text);
}
