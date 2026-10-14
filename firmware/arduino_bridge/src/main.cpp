// =============================================================================
// Arduino Uno — joystick + NRF24 bridge + 0.96" SSD1306 OLED.
//
// Roles
//   1. Read the joystick at 100 Hz and send JoystickPacket to the Teensy (RF).
//   2. Wireless mode (PC_VIA_BRIDGE=1): forward framed PC packets USB -> RF and
//      RF -> USB.  Wired mode: nothing is forwarded; the PC talks to the Teensy
//      directly, this board only sends joystick + BridgeStatus.
//   3. Sniff TelemetryPacket / HealthPacket from the Teensy to draw the same
//      A..F group boxes and a position dial.
//
// Hardware (unchanged): NRF24 CE=9 CSN=10 (HW SPI), OLED I2C A4/A5 @0x3C,
// joystick X=A2 Y=A1 button=D3 (pull-up).  2 KB SRAM: no String, no floats
// in the display path beyond what the dial needs.
// =============================================================================
#include <Arduino.h>
#include <SPI.h>
#include <RF24.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <string.h>
#include "protocol.h"

#ifndef PC_VIA_BRIDGE
#define PC_VIA_BRIDGE 0
#endif

#define NRF_CE_PIN     9
#define NRF_CSN_PIN   10
#define JOY_X_PIN     A2
#define JOY_Y_PIN     A1
#define JOY_BTN_PIN    3
#define OLED_ADDR   0x3C
#define NRF_CHANNEL  108
#define SPLASH_MS   2000
#define JOY_MS        10
#define DISP_MS       50
#define STATUS_MS    200
#define TEENSY_TIMEOUT_MS 1000
#define PC_TIMEOUT_MS     1000

static RF24 radio(NRF_CE_PIN, NRF_CSN_PIN);
static Adafruit_SSD1306 oled(128, 64, &Wire, -1);
static FrameParser usb_parser;

#include "logo_bits.inc"      // 64x48 XBM (LSB-first rows) — converted on the fly below
static const uint8_t LOGO_W = 64, LOGO_H = 48;

static uint32_t t_joy = 0, t_disp = 0, t_status = 0, t_boot = 0;
static uint32_t last_teensy_ms = 0, last_pc_ms = 0, rf_rx_count = 0, rf_rx_prev = 0;
static uint8_t  rf_rx_hz = 0;
static uint8_t  seq = 0;
static bool     rf_ok = false, oled_ok = false;

// last sniffed Teensy state
static uint8_t  ctrl_state = 0, trip_code = 0;
static uint32_t node_states = 0;
static int16_t  pos_x10 = 0, sp_x10 = 0;
static bool     have_health = false, have_telem = false;
static int16_t  joy_x = 0, joy_y = 0;

// XBM rows are LSB-first; Adafruit drawBitmap wants MSB-first.  Draw pixel by
// pixel (only during the 2 s splash, so speed is irrelevant).
static void draw_xbm(int16_t x0, int16_t y0) {
    const uint8_t bytes_per_row = (LOGO_W + 7) / 8;
    for (uint8_t y = 0; y < LOGO_H; y++)
        for (uint8_t x = 0; x < LOGO_W; x++) {
            const uint8_t b = pgm_read_byte(&logo_bits[y * bytes_per_row + x / 8]);
            if (b & (1 << (x & 7))) oled.drawPixel(x0 + x, y0 + y, SSD1306_WHITE);
        }
}

static void rf_send(const void* p, uint8_t len) {
    if (!rf_ok) return;
    radio.stopListening(); radio.write(p, len); radio.startListening();
}

static void usb_send(const void* p, uint8_t len) {
    uint8_t buf[MAX_PAYLOAD + FRAME_OVERHEAD];
    const uint8_t n = protocol_encode(buf, p, len, seq++);
    Serial.write(buf, n);
}

static void sniff(const uint8_t* p, uint8_t len) {
    if (p[0] == PKT_TELEMETRY && len == sizeof(TelemetryPacket)) {
        TelemetryPacket t; memcpy(&t, p, sizeof t);
        ctrl_state = t.ctrl_state; pos_x10 = (int16_t)(t.position_deg * 10); sp_x10 = (int16_t)(t.setpoint_deg * 10);
        have_telem = true;
    } else if (p[0] == PKT_HEALTH && len == sizeof(HealthPacket)) {
        HealthPacket h; memcpy(&h, p, sizeof h);
        node_states = h.node_states; trip_code = h.trip_code; ctrl_state = h.ctrl_state; have_health = true;
    }
}

static uint8_t node(uint8_t i) { return (node_states >> (2 * i)) & 3; }

// Same grouping as the Teensy (health.cpp) so both OLEDs agree.
static uint8_t group_state(const uint8_t* nodes, uint8_t n, uint8_t& first_bad) {
    uint8_t worst = HS_OK, rank_w = 0; first_bad = 0;
    for (uint8_t i = 0; i < n; i++) {
        const uint8_t st = node(nodes[i]);
        const uint8_t rank = st == HS_FAIL ? 3 : st == HS_BLOCKED ? 2 : st == HS_UNKNOWN ? 1 : 0;
        if (rank > rank_w) { rank_w = rank; worst = st; }
        if (st != HS_OK && !first_bad) first_bad = i + 1;
    }
    return worst;
}

static void draw() {
    static const uint8_t GA[] = { HN_CAN_CTRL, HN_CAN_TX, HN_CAN_RX_ANY, HN_CAN_MOTOR, HN_MOTOR_DATA, HN_MOTOR_CURRENT };
    static const uint8_t GB[] = { HN_SWITCH, HN_TRIP };
    static const uint8_t GC[] = { HN_ISR, HN_CTRL_READY, HN_CALIB, HN_OLED };
    static const uint8_t GD[] = { HN_PC_LINK };
    static const uint8_t GE[] = { HN_BRIDGE_LINK };
    const bool blink = (millis() / 250) & 1;
    const bool teensy_alive = (millis() - last_teensy_ms) < TEENSY_TIMEOUT_MS && last_teensy_ms;

    oled.clearDisplay();
    oled.setTextSize(1);
    for (uint8_t i = 0; i < 6; i++) {
        uint8_t st, fb = 0; char letter = 'A' + i;
        if (!teensy_alive || !have_health) { st = HS_UNKNOWN; }
        else switch (i) {
            case 0: st = group_state(GA, 6, fb); break;
            case 1: st = group_state(GB, 2, fb); break;
            case 2: st = group_state(GC, 4, fb); break;
            case 3: st = group_state(GD, 1, fb); break;
            case 4: st = group_state(GE, 1, fb); break;
            default: st = HS_UNKNOWN; break;   // F is a PC-side group; unknown here
        }
        // the bridge's own view of E (RF to Teensy) overrides what the Teensy says
        if (i == 4) { st = teensy_alive ? HS_OK : HS_FAIL; fb = teensy_alive ? 0 : 1; }
        const int16_t x = i * 21;
        if (st == HS_OK) { oled.fillRect(x, 0, 20, 11, SSD1306_WHITE); oled.setTextColor(SSD1306_BLACK); }
        else { if (!(st == HS_FAIL && blink)) oled.drawRect(x, 0, 20, 11, SSD1306_WHITE); oled.setTextColor(SSD1306_WHITE); }
        oled.setCursor(x + (st == HS_OK ? 7 : 4), 2);
        oled.print(letter);
        if (st == HS_UNKNOWN) oled.print('?'); else if (st != HS_OK) oled.print(fb);
    }
    oled.setTextColor(SSD1306_WHITE);

    // left: state + joystick widget
    static const char* const NAMES[] = { "REST", "HOLD", "TRAJ", "JOY", "TEST", "FREE", "CAL", "TRIP" };
    oled.setCursor(0, 16); oled.setTextSize(2); oled.print(teensy_alive ? NAMES[ctrl_state & 7] : "----");
    oled.setTextSize(1);
    oled.setCursor(0, 34); oled.print(F("RF ")); oled.print(rf_rx_hz); oled.print(F("Hz"));
    oled.setCursor(0, 44); oled.print(F("PC ")); oled.print((millis() - last_pc_ms) < PC_TIMEOUT_MS && last_pc_ms ? F("ok") : F("--"));
    // joystick box 24x24 at (0,40)... keep it small
    oled.drawRect(60, 36, 26, 26, SSD1306_WHITE);
    oled.fillCircle(73 + joy_x / 48, 49 - joy_y / 48, 2, SSD1306_WHITE);

    // right: dial
    const int16_t cx = 108, cy = 44, r = 17;
    oled.drawCircle(cx, cy, r, SSD1306_WHITE);
    if (have_telem) {
        const float a = (pos_x10 / 10.0f) * 0.0087266f - 1.5708f;   // 0.5 dial deg per wheel deg
        oled.drawLine(cx, cy, cx + (int16_t)(cos(a) * (r - 2)), cy + (int16_t)(sin(a) * (r - 2)), SSD1306_WHITE);
        oled.setCursor(92, 16); oled.print(pos_x10 / 10); oled.print('.'); oled.print(abs(pos_x10 % 10));
    }
    oled.display();
}

void setup() {
    Serial.begin(115200);
    pinMode(JOY_BTN_PIN, INPUT_PULLUP);
    Wire.begin();
    oled_ok = oled.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR);
    if (oled_ok) { oled.clearDisplay(); draw_xbm((128 - LOGO_W) / 2, (64 - LOGO_H) / 2); oled.display(); }
    t_boot = millis();

    rf_ok = radio.begin();
    if (rf_ok) {
        radio.setChannel(NRF_CHANNEL);
        radio.setPALevel(RF24_PA_LOW);
        radio.setDataRate(RF24_2MBPS);
        radio.setAutoAck(true);
        radio.setRetries(1, 2);
        radio.enableDynamicPayloads();
        radio.openWritingPipe((const uint8_t*)"STR01");   // -> Teensy
        radio.openReadingPipe(1, (const uint8_t*)"STR02"); // <- Teensy
        radio.startListening();
    }
}

void loop() {
    const uint32_t now = millis();

    // RF in: Teensy -> (sniff) -> PC
    if (rf_ok) {
        uint8_t pipe;
        while (radio.available(&pipe)) {
            uint8_t len = radio.getDynamicPayloadSize();
            uint8_t buf[32];
            if (!len || len > 32) { radio.flush_rx(); break; }
            radio.read(buf, len);
            last_teensy_ms = now; rf_rx_count++;
            sniff(buf, len);
#if PC_VIA_BRIDGE
            usb_send(buf, len);
#endif
        }
    }

    // USB in: PC -> Teensy (only meaningful in wireless mode; we still note liveness)
    while (Serial.available()) {
        if (usb_parser.push((uint8_t)Serial.read())) {
            last_pc_ms = now;
#if PC_VIA_BRIDGE
            rf_send(usb_parser.payload, usb_parser.len);
#endif
        }
    }

    if (now - t_joy >= JOY_MS) {
        t_joy = now;
        joy_x = (int16_t)analogRead(JOY_X_PIN) - 512;
        joy_y = (int16_t)analogRead(JOY_Y_PIN) - 512;
        JoystickPacket j; j.type = PKT_JOYSTICK; j.buttons = digitalRead(JOY_BTN_PIN) == LOW ? 1 : 0;
        j.x = joy_x; j.y = joy_y; j.t_ms = now;
        rf_send(&j, sizeof j);
    }

    if (now - t_status >= STATUS_MS) {
        t_status = now;
        rf_rx_hz = (uint8_t)min((uint32_t)255, (rf_rx_count - rf_rx_prev) * (1000 / STATUS_MS)); rf_rx_prev = rf_rx_count;
        BridgeStatusPacket b; b.type = PKT_BRIDGE_STATUS; b.reserved = 0; b.t_ms = now; b.rf_rx_hz = rf_rx_hz;
        b.bits = ((now - last_teensy_ms) < TEENSY_TIMEOUT_MS && last_teensy_ms ? BS_RF_TEENSY : 0)
               | ((now - last_pc_ms) < PC_TIMEOUT_MS && last_pc_ms ? BS_USB_PC : 0)
               | BS_JOY_PRESENT | (have_telem ? BS_TELEM_SEEN : 0);
        rf_send(&b, sizeof b);
        usb_send(&b, sizeof b);
    }

    if (oled_ok && now - t_boot > SPLASH_MS && now - t_disp >= DISP_MS) { t_disp = now; draw(); }
}
