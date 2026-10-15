// =============================================================================
// can_motor.h — Yobotics BM-series (MIT-style) CAN driver for Teensy 4.1 / CAN3.
//
// Ownership rules (these are what keep CAN alive — see docs/MIGRATION.md):
//   * The 1 kHz control ISR is the ONLY caller of can_motor_tick_send().
//     It sends at most one frame per tick, in this priority:
//       1. a pending "special" frame (enter/exit motor mode, set zero) queued
//          by the main loop,
//       2. the next CAN-scan ping while a scan is running,
//       3. the regular command (motor on) or the motor-off poll (every
//          CONTROL_HZ / CAN_REST_POLL_HZ ticks: zero gains, zero torque).
//   * The main loop is the ONLY caller of can_motor_poll() (dispatches the
//     FlexCAN receive queue -> on_can_rx) and of the queue / scan API.
//   * Nothing else touches CANbus.  Nothing in here blocks.
//
// Why the motor-off poll exists: the BM motor never talks on its own; it
// answers each frame sent to its id (in REST too, without acting on it).  If the
// Teensy is silent while the motor is off it hears nothing, M3/M4 stay at 0 Hz,
// and Position control is refused for "no motor CAN reply" — a deadlock.
// =============================================================================
#pragma once
#include <stdint.h>
#include "config.h"

enum CanSpecial : uint8_t {
    SPECIAL_NONE   = 0,
    SPECIAL_ENTER  = 0xFC,   // enter FOC/motor mode
    SPECIAL_EXIT   = 0xFD,   // exit -> REST (MOSFETs off)
    SPECIAL_ZERO   = 0xFE,   // set current position as mechanical zero
};

// What the ISR wants on the bus this tick (besides specials and scan pings).
enum CanTxKind : uint8_t {
    CAN_TX_NONE = 0,         // nothing
    CAN_TX_POLL = 1,         // motor off: zero-gain poll at CAN_REST_POLL_HZ so the motor keeps answering
    CAN_TX_CMD  = 2,         // motor on: the real command, every tick
};

struct MotorSample {
    volatile float    pos_rad;
    volatile float    vel_rad_s;
    volatile float    cur_A;        // the "torque/current" field of the reply
    volatile uint32_t t_us;         // micros() when received
    volatile uint32_t count;        // total motor replies
    volatile bool     valid;        // at least one reply since boot / since the id changed
};

struct CanCounters {
    volatile uint32_t tx_frames;
    volatile uint32_t tx_failed;      // CANbus.write() returned 0 (mailbox full)
    volatile uint32_t rx_motor;       // replies from MOTOR id
    volatile uint32_t rx_other;       // frames with another id in buf[0]
    volatile uint32_t rx_bad_len;
    volatile uint32_t rx_frozen;      // replies with identical payload many times (while commanded)
    uint8_t           tec, rec;       // FlexCAN error counters
    uint8_t           bus_state;      // 0 active 1 warning 2 passive 3 busoff
};

extern MotorSample  g_motor;
extern CanCounters  g_can;
extern volatile uint8_t g_motor_id;

void can_motor_begin();

// --- main loop only ---
void can_motor_poll();                       // CANbus.events() + error counters
void can_motor_queue_special(CanSpecial s);  // picked up by the next ISR tick
bool can_motor_special_pending();
void can_motor_set_id(uint8_t id);           // REST only (caller checks); forgets the old id's data

// CAN scan, non-blocking: start it, then call can_motor_scan_result() from the
// main loop until it returns true (once, with the ids that answered).
bool can_motor_scan_start(uint8_t first, uint8_t last);   // false if one is already running
bool can_motor_scan_busy();
bool can_motor_scan_result(uint8_t* found /*16*/, uint8_t& n_found);

// --- ISR only ---
// Sends the pending special if any, else a scan ping if scanning, else what
// `kind` asks for.  Returns the special that was sent (or SPECIAL_NONE).
CanSpecial can_motor_tick_send(CanTxKind kind, float p_rad, float v_rad_s,
                               float kp, float kd, float t_Nm);

// --- helpers ---
static inline float deg2rad(float d) { return d * 0.017453292519943295f; }
static inline float rad2deg(float r) { return r * 57.29577951308232f; }
