// =============================================================================
// control.h — controller state machine + 1 kHz control tick.
//
// Threading model:
//   * control_tick() runs from an IntervalTimer ISR at CONTROL_HZ.  It owns the
//     motion math, safety trips, calibration and test state machines, and is
//     the only thing that sends CAN frames (via can_motor_tick_send()).
//   * Everything else (commands, gains, setpoints, joystick) is written by the
//     main loop through the small API below.  Multi-field updates are done
//     under noInterrupts() so the ISR always sees a consistent set.
//   * The ISR never calls Serial, never blocks, never allocates.  It reports
//     through the event ring (control_pop_event) that the main loop drains.
// =============================================================================
#pragma once
#include <stdint.h>
#include "protocol.h"
#include "config.h"

struct ControlEvent { uint8_t code; uint16_t arg; char text[20]; };

struct ControlState {
    // --- state machine ---
    volatile uint8_t  cs;               // CS_*
    volatile uint8_t  trip;             // TRIP_*
    volatile uint8_t  calib;            // CAL_*
    volatile uint8_t  mode_req;         // MODE_* (sticky request from PC)
    volatile bool     zeroed;
    volatile bool     limits_valid;
    volatile bool     switch_armed;     // debounced PIN_IDLE_SWITCH
    volatile bool     left_captured, right_captured;

    // --- gains actually used this tick (after ramp) ---
    volatile float    kp, kd, ki, tff_Nm;      // configured
    volatile float    kp_eff, kd_eff;          // after enable ramp
    volatile float    integral_Nm;
    volatile float    torque_cmd_Nm;           // feed-forward sent this tick

    // --- positions (deg, PC-facing convention) ---
    volatile float    sp_target_deg;    // what the active source wants
    volatile float    sp_cmd_deg;       // slewed + limited, what is sent
    volatile float    vel_ff_deg_s;
    volatile float    pos_offset_deg;   // reported = motor - offset (lets zero sit exactly at the centre)
    volatile float    limit_left_deg;   // negative side
    volatile float    limit_right_deg;  // positive side

    // --- sources ---
    volatile float    joy_rate_deg_s;
    volatile uint32_t joy_last_ms;
    volatile uint32_t sp_last_ms;
    volatile uint16_t sp_seq;
    volatile uint32_t pc_hb_last_ms;    // 0 = never
    volatile uint32_t bridge_last_ms;

    // --- timing ---
    volatile uint32_t enable_ms;
    volatile uint32_t ramp_start_ms;
    volatile uint32_t ticks;
    volatile uint32_t overruns;         // ticks that exceeded ISR_OVERRUN_US
    volatile uint32_t last_tick_us;
    volatile uint32_t tick_cost_us;     // last tick duration

    // --- test ---
    volatile uint8_t  test_type;
    volatile float    test_amp_deg, test_dur_s, test_param;
    volatile uint32_t test_start_ms;
    volatile float    test_base_deg;
    volatile int8_t   relay_sign;
    volatile uint8_t  relay_periods;
};

extern ControlState g_ctl;

void control_begin();            // starts the IntervalTimer
void control_tick();             // ISR body (exposed for tests)

// --- main-loop API ---
bool control_command(uint8_t cmd, uint16_t arg, float farg, char* why /*20*/);  // true = accepted
void control_set_gains(float kp, float kd, float ki, float tff);
void control_set_limits(float left_deg, float right_deg);
void control_setpoint(uint16_t seq, float pos_deg, float vel_ff, uint8_t flags);
void control_joystick(int16_t x, int16_t y, uint8_t buttons);
void control_request_mode(uint8_t mode, bool sticky);
bool control_start_test(uint8_t type, float amp, float dur, float param, char* why);
void control_note_pc_heartbeat();
void control_note_bridge();
bool control_pop_event(ControlEvent& ev);   // drain ISR events
uint8_t control_telemetry_flags();
bool control_motor_enabled();               // cs in {HOLD,TRAJ,JOY,TEST,FREESPIN,CALIB}
float control_pos_deg();                    // motor position in the PC-facing frame
