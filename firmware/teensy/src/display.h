// =============================================================================
// display.h — 2.42" SSD1309 128x64 OLED (I2C) dashboard.
//
// Layout (docs/HEALTH.md#oled):
//   row 0  : six group boxes A..F.  Filled = OK, hollow = blocked/unknown,
//            blinking hollow = FAIL.  A hollow box shows the index of the first
//            bad node in that group ("A4" = motor not replying).
//   left   : controller state, trip / calibration stage, switch, gains
//   right  : position dial with setpoint tick and calibrated limits
//   bottom : motor reply rate, loop rate, PC link age
// =============================================================================
#pragma once
#include "health.h"

bool display_begin();                 // false if the OLED did not ACK
void display_update(const HealthSnapshot& s);   // non-blocking; call at DISPLAY_HZ
