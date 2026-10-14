// =============================================================================
// health.h — firmware side of the health tree (docs/HEALTH.md).
//
// Every HN_* node is evaluated from counters at HEALTH_HZ and packed into a
// HealthPacket.  The same packed word drives the OLED group letters, so what
// the PC shows and what the Teensy shows can never disagree.
// =============================================================================
#pragma once
#include <stdint.h>
#include "protocol.h"

struct HealthSnapshot {
    uint32_t node_states;        // 2 bits per HN_*
    uint16_t can_rx_motor_hz, can_rx_other_hz, loop_hz;
    uint8_t  isr_overruns;       // since last snapshot
    uint16_t pc_hb_age_ms, bridge_age_ms, motor_age_ms;
};

void health_update(HealthSnapshot& out);     // call at HEALTH_HZ from main loop
void health_fill_packet(HealthPacket& p, const HealthSnapshot& s);
void health_set_oled_ok(bool ok);
void health_set_pc_bits(uint16_t bits);      // from HeartbeatPacket (for OLED D/F groups)
uint16_t health_pc_bits();

static inline uint8_t health_node(uint32_t states, uint8_t node) { return (states >> (2 * node)) & 0x3; }

// Group letter -> worst node state, and the index of the first non-OK node
// (1-based within the group) so the OLED can print e.g. "A4".
struct HealthGroup { char letter; uint8_t state; uint8_t first_bad; };
void health_groups(const HealthSnapshot& s, HealthGroup out[6]);
