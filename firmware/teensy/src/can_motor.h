// =============================================================================
// can_motor.h — Yobotics BM-18 (MIT-style) CAN driver for Teensy 4.1 / CAN3.
//
// Ownership rules (these are what keep CAN alive — see docs/MIGRATION.md):
//   * The 1 kHz control ISR is the ONLY caller of can_motor_tick_send().
//     It sends exactly one frame per tick: either a pending "special" frame
//     (enter/exit motor mode, set zero) queued by the main loop, or the
//     regular position/velocity/gain/torque command.
//   * The main loop is the ONLY caller of can_motor_poll() (dispatches the
//     FlexCAN receive queue -> on_can_rx) and of the queue_special() API.
//   * Nothing else touches CANbus.
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

struct MotorSample {
    volatile float    pos_rad;
    volatile float    vel_rad_s;
    volatile float    cur_A;        // the "torque/current" field of the reply
    volatile uint32_t t_us;         // micros() when received
    volatile uint32_t count;        // total motor replies
    volatile bool     valid;        // at least one reply since boot
};

struct CanCounters {
    volatile uint32_t tx_frames;
    volatile uint32_t tx_failed;      // CANbus.write() returned 0 (mailbox full)
    volatile uint32_t rx_motor;       // replies from MOTOR id
    volatile uint32_t rx_other;       // frames with another id in buf[0]
    volatile uint32_t rx_bad_len;
    volatile uint32_t rx_frozen;      // replies with identical payload many times
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
void can_motor_scan(uint8_t first, uint8_t last, uint8_t* found, uint8_t& n_found); // blocking ~1 s, REST only

// --- ISR only ---
// Sends the pending special frame if any, else (if `send_cmd`) a command frame.
// Returns the special that was sent (or SPECIAL_NONE).
CanSpecial can_motor_tick_send(bool send_cmd, float p_rad, float v_rad_s,
                               float kp, float kd, float t_Nm);

// --- helpers ---
static inline float deg2rad(float d) { return d * 0.017453292519943295f; }
static inline float rad2deg(float r) { return r * 57.29577951308232f; }
