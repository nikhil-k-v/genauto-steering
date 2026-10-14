// =============================================================================
// main.cpp — Gen Auto steering actuator controller (Teensy 4.1).
//
// Schedules the main-loop services around the 1 kHz control ISR:
//   comms_poll()        every pass   (USB + RF in, dispatch)
//   can_motor_poll()    every pass   (FlexCAN RX queue -> motor sample)
//   telemetry           200 Hz
//   health + OLED       20 / 25 Hz
//   config echo         5 Hz
// Nothing here blocks; the only blocking call in the firmware is the CAN
// scanner, which is only reachable from REST.
// =============================================================================
#include <Arduino.h>
#include "config.h"
#include "can_motor.h"
#include "control.h"
#include "comms.h"
#include "health.h"
#include "display.h"

static elapsedMicros s_telem_t;
static elapsedMillis s_health_t, s_disp_t, s_cfg_t, s_led_t;
static HealthSnapshot s_health = {};

void setup() {
    pinMode(PIN_LED, OUTPUT);
    display_begin();          // shows the logo immediately
    can_motor_begin();
    comms_begin();
    control_begin();          // starts the ISR last, once everything it touches exists
}

void loop() {
    comms_poll();
    can_motor_poll();
    comms_emit_events();

    if (s_telem_t >= (1000000 / TELEMETRY_HZ)) { s_telem_t = 0; comms_emit_telemetry(); }

    if (s_health_t >= (1000 / HEALTH_HZ)) {
        s_health_t = 0;
        health_update(s_health);
        comms_emit_health(s_health);
        if (s_health.isr_overruns >= ISR_OVERRUN_TRIP && control_motor_enabled()) {
            char w[20]; control_command(CMD_DISABLE, 0, 0, w);
        }
    }
    if (s_cfg_t >= (1000 / CONFIG_ECHO_HZ)) { s_cfg_t = 0; comms_emit_config(); }
    if (s_disp_t >= (1000 / DISPLAY_HZ))   { s_disp_t = 0; display_update(s_health); }
#if WIRED_MODE
    if (s_led_t >= 500) { s_led_t = 0; digitalToggleFast(PIN_LED); }
#endif
}
