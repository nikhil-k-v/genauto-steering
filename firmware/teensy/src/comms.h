// =============================================================================
// comms.h — USB serial transport + packet dispatch.
//
// Every packet is wrapped in the protocol.h frame.  comms_poll() is called
// from the main loop; it parses whatever is pending (bounded work per call)
// and dispatches to control/health.  Emitters are called at their rates by
// main.cpp.
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
uint32_t comms_frames_rx();                // for debugging
