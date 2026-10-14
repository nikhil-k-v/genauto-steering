#include <Arduino.h>
#include <Wire.h>
#include <U8g2lib.h>
#include <math.h>
#include "display.h"
#include "config.h"
#include "control.h"
#include "can_motor.h"

static U8G2_SSD1309_128X64_NONAME0_F_HW_I2C u8g2(U8G2_R0, U8X8_PIN_NONE);
static uint32_t s_boot_ms = 0;
static bool     s_ok = false;

#include "logo_bits.inc"     // logo_bits[] 64x48, XBM, from the original build
static constexpr int LOGO_W = 64, LOGO_H = 48;

bool display_begin() {
    Wire.begin();
    Wire.beginTransmission(OLED_I2C_ADDR);
    s_ok = (Wire.endTransmission() == 0);
    if (s_ok) {
        u8g2.begin();
        u8g2.clearBuffer();
        u8g2.drawXBMP((128 - LOGO_W) / 2, (64 - LOGO_H) / 2, LOGO_W, LOGO_H, logo_bits);
        u8g2.sendBuffer();
    }
    s_boot_ms = millis();
    health_set_oled_ok(s_ok);
    return s_ok;
}

static const char* state_name(uint8_t cs) {
    switch (cs) {
    case CS_REST: return "REST"; case CS_HOLD: return "HOLD"; case CS_TRAJ: return "TRAJ";
    case CS_TEST: return "TEST"; case CS_FREESPIN: return "FREE";
    case CS_CALIB: return "CAL"; case CS_TRIPPED: return "TRIP"; default: return "?";
    }
}
static const char* trip_name(uint8_t t) {
    switch (t) {
    case TRIP_VELOCITY: return "OVERSPEED"; case TRIP_STALL: return "STALL";
    case TRIP_OVERCURRENT: return "OVERCURR"; case TRIP_SWITCH_OPENED: return "SW OPENED";
    case TRIP_PC_LINK_LOST: return "PC LOST"; case TRIP_CAN_LOST: return "CAN LOST";
    case TRIP_LIMIT: return "PAST STOP"; case TRIP_CALIB_FAILED: return "CAL FAIL";
    case TRIP_PC_SHUTDOWN: return "PC EXIT"; case TRIP_ISR_OVERRUN: return "LOOP SLOW";
    default: return "";
    }
}
static const char* cal_name(uint8_t c) {
    switch (c) {
    case CAL_SEEK_LEFT: return "SEEK L"; case CAL_CONFIRM_LEFT: return "CONF L";
    case CAL_SEEK_RIGHT: return "SEEK R"; case CAL_CONFIRM_RIGHT: return "CONF R";
    case CAL_GO_CENTER: return "CENTER"; case CAL_SETTLE: return "SETTLE";
    case CAL_DONE: return "CAL OK"; case CAL_ABORTED: return "CAL ABRT"; case CAL_FAILED: return "CAL FAIL";
    default: return "";
    }
}

static void draw_groups(const HealthSnapshot& s) {
    HealthGroup g[HEALTH_GROUPS]; health_groups(s, g);
    const bool blink = (millis() / 250) & 1;
    u8g2.setFont(u8g2_font_5x8_tr);
    for (int i = 0; i < HEALTH_GROUPS; i++) {
        const int x = i * 26, w = 24, h = 11;
        char txt[4];
        if (g[i].state == HS_OK)            snprintf(txt, sizeof txt, "%c", g[i].letter);
        else if (g[i].state == HS_UNKNOWN)  snprintf(txt, sizeof txt, "%c?", g[i].letter);
        else                                snprintf(txt, sizeof txt, "%c%u", g[i].letter, g[i].first_bad);
        if (g[i].state == HS_OK) {
            u8g2.setDrawColor(1); u8g2.drawBox(x, 0, w, h); u8g2.setDrawColor(0);
        } else {
            u8g2.setDrawColor(1);
            if (!(g[i].state == HS_FAIL && blink)) u8g2.drawFrame(x, 0, w, h);
        }
        const int tw = u8g2.getStrWidth(txt);
        u8g2.drawStr(x + (w - tw) / 2, 8, txt);
        u8g2.setDrawColor(1);
    }
}

static void draw_dial(float pos_deg, float sp_deg, bool enabled) {
    const int cx = 96, cy = 44, r = 18;
    u8g2.drawCircle(cx, cy, r);
    float lo, hi;
    if (g_ctl.limits_valid) { lo = g_ctl.limit_left_deg; hi = g_ctl.limit_right_deg; }
    else { lo = -POS_LIMIT_DEFAULT_DEG; hi = POS_LIMIT_DEFAULT_DEG; }
    auto ang = [&](float deg) { return deg2rad(deg) * 0.5f - PI / 2; };   // 1 wheel deg = 0.5 dial deg
    // limit ticks
    const float lims[2] = { lo, hi };
    for (int i = 0; i < 2; i++) {
        const float a = ang(lims[i]);
        u8g2.drawLine(cx + cosf(a) * (r - 4), cy + sinf(a) * (r - 4), cx + cosf(a) * (r + 2), cy + sinf(a) * (r + 2));
    }
    // setpoint tick (hollow) and position needle (solid)
    if (enabled) { const float a = ang(sp_deg); u8g2.drawDisc(cx + cosf(a) * r, cy + sinf(a) * r, 2); }
    const float a = ang(pos_deg);
    u8g2.drawLine(cx, cy, cx + cosf(a) * (r - 2), cy + sinf(a) * (r - 2));
    u8g2.drawDisc(cx, cy, 2);
}

void display_update(const HealthSnapshot& s) {
    if (!s_ok) return;
    if (millis() - s_boot_ms < OLED_SPLASH_MS) return;    // splash stays up

    const float pos = control_pos_deg();
    const bool enabled = control_motor_enabled();

    u8g2.clearBuffer();
    u8g2.setDrawColor(1);
    draw_groups(s);

    // left column
    u8g2.setFont(u8g2_font_7x13B_tr);
    u8g2.drawStr(0, 26, state_name(g_ctl.cs));
    u8g2.setFont(u8g2_font_5x8_tr);
    char line[24];
    if (g_ctl.cs == CS_TRIPPED)      snprintf(line, sizeof line, "%s", trip_name(g_ctl.trip));
    else if (g_ctl.cs == CS_CALIB)   snprintf(line, sizeof line, "%s", cal_name(g_ctl.calib));
    else if (g_ctl.cs == CS_FREESPIN) snprintf(line, sizeof line, "zero torque");
    else                             snprintf(line, sizeof line, "%s%s", g_ctl.zeroed ? "Z " : "nz ", g_ctl.limits_valid ? "LIM" : "nolim");
    u8g2.drawStr(0, 36, line);
    snprintf(line, sizeof line, "SW:%s", g_ctl.switch_armed ? "ARM" : "IDLE");
    u8g2.drawStr(0, 45, line);
    snprintf(line, sizeof line, "P%.0f D%.1f I%.1f", (double)g_ctl.kp, (double)g_ctl.kd, (double)g_ctl.ki);
    u8g2.drawStr(0, 54, line);

    // dial + numbers
    draw_dial(pos, g_ctl.sp_cmd_deg, enabled);
    snprintf(line, sizeof line, "%+.1f", (double)pos);
    u8g2.drawStr(66, 20, line);

    // bottom status: motor Hz / loop Hz / pc age
    if (s.pc_hb_age_ms == 0xFFFF) snprintf(line, sizeof line, "M%u L%u PC--", s.can_rx_motor_hz, s.loop_hz);
    else                          snprintf(line, sizeof line, "M%u L%u PC%u", s.can_rx_motor_hz, s.loop_hz, s.pc_hb_age_ms);
    u8g2.drawStr(0, 63, line);
    u8g2.sendBuffer();
}
