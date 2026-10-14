// =============================================================================
// comms.h — transports + packet dispatch.
//
//   WIRED_MODE=1 : PC <-> Teensy over USB serial (framed).  NRF24, if fitted,
//                  still carries joystick/bridge-status from the Arduino and a
//                  20 Hz telemetry copy to it (for its OLED).
//   WIRED_MODE=0 : PC <-> Teensy over NRF24 via the Arduino bridge; USB serial
//                  is debug only.
//
// Over USB every packet is wrapped in the protocol.h frame.  Over NRF24 the
// radio provides packet boundaries and CRC, so the bare payload is sent.
// =============================================================================
#pragma once
#include <stdint.h>
#include "health.h"

void comms_begin();
void comms_poll();                         // read + dispatch everything pending (main loop)
void comms_emit_telemetry();
void comms_emit_health(const HealthSnapshot& s);
void comms_emit_config();
void comms_emit_events();                  // drain the control event ring
bool comms_rf_present();
uint32_t comms_frames_rx();                // for debugging
