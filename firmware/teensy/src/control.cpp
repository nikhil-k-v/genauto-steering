#include <Arduino.h>
#include <string.h>
#include <math.h>
#include "control.h"
#include "can_motor.h"

ControlState g_ctl = {};
static IntervalTimer s_timer;

// ---- ISR -> main-loop event ring --------------------------------------------
static ControlEvent    s_ev[16];
static volatile uint8_t s_ev_head = 0, s_ev_tail = 0;

static void push_event(uint8_t code, uint16_t arg, const char* text = "") {
    uint8_t next = (s_ev_head + 1) & 15;
    if (next == s_ev_tail) return;   // full: drop (counted nowhere; events are advisory)
    ControlEvent& e = s_ev[s_ev_head];
    e.code = code; e.arg = arg;
    strncpy(e.text, text, sizeof(e.text) - 1); e.text[sizeof(e.text) - 1] = 0;
    s_ev_head = next;
}
bool control_pop_event(ControlEvent& ev) {
    if (s_ev_head == s_ev_tail) return false;
    ev = s_ev[s_ev_tail];
    s_ev_tail = (s_ev_tail + 1) & 15;
    return true;
}

// ---- helpers ------------------------------------------------------------------
static inline float clampf(float x, float a, float b) { return x < a ? a : (x > b ? b : x); }
static inline float signf(float x) { return x < 0 ? -1.f : 1.f; }
static inline uint32_t ms_now() { return millis(); }   // safe inside ISR on Teensy 4

static inline void set_state(uint8_t cs) {
    if (g_ctl.cs != cs) { g_ctl.cs = cs; push_event(EV_STATE, cs); }
}

// Limits currently in force (deg).  Calibrated stops win when valid.
static inline void active_limits(float& lo, float& hi) {
    if (g_ctl.limits_valid) {
        lo = g_ctl.limit_left_deg  + LIMIT_MARGIN_DEG;
        hi = g_ctl.limit_right_deg - LIMIT_MARGIN_DEG;
        if (lo > hi) { float m = 0.5f * (lo + hi); lo = hi = m; }
    } else {
        lo = -POS_LIMIT_DEFAULT_DEG; hi = POS_LIMIT_DEFAULT_DEG;
    }
}

// "<value><suffix>" into a 20-byte event text, integers only: no printf/float
// formatting inside the ISR (newlib's float printf may allocate).  The PC shows it
// next to the safety-stop name, e.g. "Motor current too high (31.2 A)".
static void detail_num(char* out, float v, int decimals, const char* suffix) {
    char tmp[12]; int n = 0;
    int32_t scaled = (int32_t)lroundf(fabsf(v) * (decimals ? 10.f : 1.f));
    if (v < 0) out[n++] = '-';
    int k = 0;
    do { tmp[k++] = (char)('0' + scaled % 10); scaled /= 10; } while (scaled && k < 11);
    if (decimals && k == 1) tmp[k++] = '0';
    while (k) { if (decimals && k == 1) out[n++] = '.'; out[n++] = tmp[--k]; }
    for (const char* p = suffix; *p && n < 19; ++p) out[n++] = *p;
    out[n] = 0;
}

static void trip(uint8_t code, const char* why) {
    if (g_ctl.cs == CS_TRIPPED) return;
    g_ctl.trip = code;
    g_ctl.calib = (g_ctl.cs == CS_CALIB) ? CAL_FAILED : g_ctl.calib;
    g_ctl.test_type = TEST_NONE;
    g_ctl.integral_Nm = 0;
    can_motor_queue_special(SPECIAL_EXIT);
    set_state(CS_TRIPPED);
    push_event(EV_TRIP, code, why);
}

static void go_rest(const char* why) {
    g_ctl.test_type = TEST_NONE;
    g_ctl.integral_Nm = 0;
    if (g_ctl.cs == CS_CALIB) { g_ctl.calib = CAL_ABORTED; push_event(EV_CALIB_STAGE, CAL_ABORTED, why); }
    can_motor_queue_special(SPECIAL_EXIT);
    set_state(CS_REST);
}

// Enter motor mode from REST: seed setpoint at the current position, ramp gains.
static void arm_motor(uint8_t cs) {
    const uint32_t now = ms_now();
    g_ctl.enable_ms = now;
    g_ctl.ramp_start_ms = now;
    g_ctl.integral_Nm = 0;
    g_ctl.sp_cmd_deg = g_ctl.sp_target_deg = control_pos_deg();
    can_motor_queue_special(SPECIAL_ENTER);
    set_state(cs);
}

float control_pos_deg() { return rad2deg(g_motor.pos_rad) - g_ctl.pos_offset_deg; }

bool control_motor_enabled() {
    switch (g_ctl.cs) {
    case CS_HOLD: case CS_TRAJ: case CS_TEST: case CS_FREESPIN: case CS_CALIB: return true;
    default: return false;
    }
}

uint8_t control_telemetry_flags() {
    float lo, hi; active_limits(lo, hi);
    const bool at_limit = (g_ctl.sp_cmd_deg <= lo + 0.5f) || (g_ctl.sp_cmd_deg >= hi - 0.5f);
    return (control_motor_enabled()      ? TF_ENABLED      : 0)
         | (g_ctl.zeroed                 ? TF_ZEROED       : 0)
         | (at_limit                     ? TF_AT_LIMIT     : 0)
         | (g_ctl.switch_armed           ? TF_SWITCH_ARMED : 0)
         | (g_ctl.test_type != TEST_NONE ? TF_TEST_RUNNING : 0)
         | (g_ctl.limits_valid           ? TF_LIMITS_VALID : 0)
         | (g_ctl.cs == CS_FREESPIN      ? TF_FREESPIN     : 0);
}

// ---- main-loop API ------------------------------------------------------------
void control_set_gains(float kp, float kd, float ki, float tff) {
    noInterrupts();
    g_ctl.kp = clampf(kp, MOTOR_KP_MIN, MOTOR_KP_MAX);
    g_ctl.kd = clampf(kd, MOTOR_KD_MIN, MOTOR_KD_MAX);
    g_ctl.ki = clampf(ki, 0.f, 50.f);
    g_ctl.tff_Nm = clampf(tff, -6.f, 6.f);
    interrupts();
}

void control_set_limits(float left, float right) {
    if (!(right > left + CAL_MIN_RANGE_DEG)) { push_event(EV_CMD_REJECTED, 0, "stops too close"); return; }
    noInterrupts();
    g_ctl.limit_left_deg = left; g_ctl.limit_right_deg = right;
    g_ctl.limits_valid = true; g_ctl.left_captured = g_ctl.right_captured = true;
    interrupts();
    push_event(EV_LIMITS_SET, 0);
}

void control_setpoint(uint16_t seq, float pos, float vel_ff, uint8_t flags) {
    (void)flags;
    if (!g_ctl.zeroed) return;                 // TRAJ needs a meaningful zero
    noInterrupts();
    g_ctl.sp_target_deg = pos; g_ctl.vel_ff_deg_s = vel_ff;
    g_ctl.sp_seq = seq; g_ctl.sp_last_ms = ms_now();
    interrupts();
}

void control_request_mode(uint8_t mode, bool sticky) {
    g_ctl.mode_req = sticky ? mode : MODE_AUTO;
    push_event(EV_CMD_ACCEPTED, PKT_MODE_REQUEST);
}

void control_note_pc_heartbeat() { g_ctl.pc_hb_last_ms = ms_now() | 1; }

static bool reject(char* why, const char* msg) { strncpy(why, msg, 19); why[19] = 0; return false; }

// Every rejection carries the reason the UI shows the user (item 1B).
bool control_command(uint8_t cmd, uint16_t arg, float farg, char* why) {
    why[0] = 0;
    const bool can_alive = g_motor.valid && (micros() - g_motor.t_us) < CAN_REPLY_TIMEOUT_MS * 1000u;
    switch (cmd) {
    case CMD_ENABLE:
        if (g_ctl.cs == CS_TRIPPED)  return reject(why, "safety stop: reset");
        if (!g_ctl.switch_armed)     return reject(why, "idle switch on");
        if (!can_alive)              return reject(why, "no motor CAN reply");
        if (control_motor_enabled()) return reject(why, "motor already on");
        if (can_motor_scan_busy())   return reject(why, "CAN scan running");
        noInterrupts(); arm_motor(CS_HOLD); interrupts();
        break;
    case CMD_DISABLE:
        // Always accepted: a tripped motor is already resting, the latch stays.
        if (g_ctl.cs != CS_TRIPPED) { noInterrupts(); go_rest("disable"); interrupts(); }
        else can_motor_queue_special(SPECIAL_EXIT);
        break;
    case CMD_CLEAR_TRIP:
        if (g_ctl.cs != CS_TRIPPED)  return reject(why, "no safety stop");
        noInterrupts(); g_ctl.trip = TRIP_NONE; g_ctl.calib = CAL_IDLE; set_state(CS_REST); interrupts();
        break;
    case CMD_SET_ZERO:
        if (!can_alive)              return reject(why, "no motor CAN reply");
        if (g_ctl.cs == CS_TRAJ || g_ctl.cs == CS_TEST || g_ctl.cs == CS_CALIB) return reject(why, "busy, stop it first");
        noInterrupts();
        can_motor_queue_special(SPECIAL_ZERO);
        // limits were measured in the old frame: shift them to the new one
        if (g_ctl.limits_valid) { float p = control_pos_deg(); g_ctl.limit_left_deg -= p; g_ctl.limit_right_deg -= p; }
        g_ctl.pos_offset_deg = 0;
        g_ctl.sp_cmd_deg = g_ctl.sp_target_deg = 0; g_ctl.integral_Nm = 0; g_ctl.zeroed = true;
        g_ctl.enable_ms = ms_now();   // re-arm grace (position jumps to 0)
        interrupts();
        push_event(EV_ZERO_SET, 0);
        break;
    case CMD_FREESPIN_ON:
        if (g_ctl.cs == CS_TRIPPED)  return reject(why, "safety stop: reset");
        if (!g_ctl.switch_armed)     return reject(why, "idle switch on");
        if (!can_alive)              return reject(why, "no motor CAN reply");
        if (g_ctl.cs == CS_TRAJ || g_ctl.cs == CS_TEST || g_ctl.cs == CS_CALIB) return reject(why, "busy, stop it first");
        if (can_motor_scan_busy())   return reject(why, "CAN scan running");
        noInterrupts();
        if (!control_motor_enabled()) arm_motor(CS_FREESPIN); else set_state(CS_FREESPIN);
        g_ctl.integral_Nm = 0;
        interrupts();
        break;
    case CMD_FREESPIN_OFF:
        if (g_ctl.cs != CS_FREESPIN) return reject(why, "not in free-spin");
        noInterrupts();
        g_ctl.sp_cmd_deg = g_ctl.sp_target_deg = control_pos_deg();
        g_ctl.ramp_start_ms = ms_now(); set_state(CS_HOLD);
        interrupts();
        break;
    case CMD_HOLD_HERE:
        if (!control_motor_enabled()) return reject(why, "motor is off");
        noInterrupts();
        g_ctl.sp_target_deg = control_pos_deg(); g_ctl.mode_req = MODE_HOLD;
        if (g_ctl.cs == CS_TRAJ) set_state(CS_HOLD);
        interrupts();
        break;
    case CMD_CALIB_START:
        if (g_ctl.cs == CS_TRIPPED)  return reject(why, "safety stop: reset");
        if (!g_ctl.switch_armed)     return reject(why, "idle switch on");
        if (!can_alive)              return reject(why, "no motor CAN reply");
        if (g_ctl.cs == CS_TRAJ || g_ctl.cs == CS_TEST) return reject(why, "busy, stop it first");
        if (can_motor_scan_busy())   return reject(why, "CAN scan running");
        noInterrupts();
        if (!control_motor_enabled()) arm_motor(CS_CALIB); else set_state(CS_CALIB);
        g_ctl.calib = CAL_SEEK_LEFT; g_ctl.test_start_ms = ms_now();
        g_ctl.torque_cmd_Nm = -CAL_SEEK_TORQUE_NM; g_ctl.left_captured = g_ctl.right_captured = false;
        g_ctl.limits_valid = false;
        interrupts();
        push_event(EV_CALIB_STAGE, CAL_SEEK_LEFT);
        break;
    case CMD_CALIB_ABORT:
        if (g_ctl.cs != CS_CALIB)    return reject(why, "not calibrating");
        noInterrupts(); go_rest("calib abort"); interrupts();
        break;
    case CMD_CAPTURE_LEFT:
    case CMD_CAPTURE_RIGHT: {
        if (!can_alive)              return reject(why, "no motor CAN reply");
        const float p = control_pos_deg();
        noInterrupts();
        if (cmd == CMD_CAPTURE_LEFT) { g_ctl.limit_left_deg = p; g_ctl.left_captured = true; }
        else                         { g_ctl.limit_right_deg = p; g_ctl.right_captured = true; }
        g_ctl.limits_valid = g_ctl.left_captured && g_ctl.right_captured &&
                             (g_ctl.limit_right_deg - g_ctl.limit_left_deg) > CAL_MIN_RANGE_DEG;
        interrupts();
        if (g_ctl.limits_valid) push_event(EV_LIMITS_SET, 0);
        break;
    }
    case CMD_GO_CENTER_ZERO:
        if (g_ctl.cs == CS_TRIPPED)  return reject(why, "safety stop: reset");
        if (!g_ctl.switch_armed)     return reject(why, "idle switch on");
        if (!can_alive)              return reject(why, "no motor CAN reply");
        if (!(g_ctl.left_captured && g_ctl.right_captured)) return reject(why, "save L and R first");
        if (g_ctl.cs == CS_TRAJ || g_ctl.cs == CS_TEST) return reject(why, "busy, stop it first");
        if (can_motor_scan_busy())   return reject(why, "CAN scan running");
        noInterrupts();
        if (!control_motor_enabled()) arm_motor(CS_CALIB); else set_state(CS_CALIB);
        g_ctl.calib = CAL_GO_CENTER; g_ctl.test_start_ms = ms_now();
        g_ctl.sp_cmd_deg = control_pos_deg();
        interrupts();
        push_event(EV_CALIB_STAGE, CAL_GO_CENTER);
        break;
    case CMD_SET_MOTOR_ID:
        if (control_motor_enabled()) return reject(why, "motor must be off");
        if (arg < 1 || arg > 127)    return reject(why, "id out of range");
        if (can_motor_scan_busy())   return reject(why, "CAN scan running");
        can_motor_set_id((uint8_t)arg);
        break;
    case CMD_CAN_SCAN: {
        if (control_motor_enabled()) return reject(why, "motor must be off");
        // arg = first id (0 -> 1), farg = last id (<= 0 -> 127).  The ISR pings;
        // comms_poll_scan() sends the CanScanPacket when it is done (~0.3 s).
        const uint8_t first = (uint8_t)(arg ? (arg > 127 ? 127 : arg) : 1);
        const uint8_t last  = (uint8_t)(farg >= 1.f && farg <= 127.f ? farg : 127);
        if (!can_motor_scan_start(first, last)) return reject(why, "CAN scan running");
        break;
    }
    case CMD_REQ_CONFIG: case CMD_RESET_COUNTERS:
        break;
    default:
        return reject(why, "unknown command");
    }
    (void)farg;
    push_event(EV_CMD_ACCEPTED, cmd);
    return true;
}

bool control_start_test(uint8_t type, float amp, float dur, float param, char* why) {
    why[0] = 0;
    if (!control_motor_enabled() || g_ctl.cs == CS_FREESPIN || g_ctl.cs == CS_CALIB)
        return reject(why, "needs position ctrl");
    if (!g_ctl.zeroed)             return reject(why, "0 deg not set");
    if (type != TEST_STEP && type != TEST_RELAY) return reject(why, "unknown test");
    noInterrupts();
    g_ctl.test_type = type; g_ctl.test_amp_deg = amp; g_ctl.test_dur_s = dur; g_ctl.test_param = param;
    g_ctl.test_start_ms = ms_now(); g_ctl.test_base_deg = g_ctl.sp_cmd_deg;
    g_ctl.relay_sign = 1; g_ctl.relay_periods = 0; g_ctl.integral_Nm = 0;
    set_state(CS_TEST);
    interrupts();
    return true;
}

// ---- the 1 kHz tick -----------------------------------------------------------
static uint8_t s_switch_samples = 0;

static void sample_switch() {
    // LOW = closed to GND = ARMED.  Require 20 consistent samples (20 ms) to change.
    const bool armed_now = digitalReadFast(PIN_IDLE_SWITCH) == LOW;
    if (armed_now == g_ctl.switch_armed) { s_switch_samples = 0; return; }
    if (++s_switch_samples >= 20) { g_ctl.switch_armed = armed_now; s_switch_samples = 0; }
}

static void run_safety(float pos_deg, float vel_deg_s, float cur_A, uint32_t now_ms, bool motor_fresh) {
    static uint32_t stall_start = 0, cur_start = 0;
    if (!control_motor_enabled()) { stall_start = cur_start = 0; return; }

    char why[20];
    if (!g_ctl.switch_armed) { trip(TRIP_SWITCH_OPENED, "pin 22 open"); return; }
    if (!motor_fresh)        { trip(TRIP_CAN_LOST, ""); return; }

    const bool in_grace = (now_ms - g_ctl.enable_ms) < ENABLE_GRACE_MS;
    if (in_grace) { stall_start = cur_start = 0; return; }

    if (fabsf(vel_deg_s) > VELOCITY_CUTOFF_DEG_S) { detail_num(why, vel_deg_s, 0, " deg/s"); trip(TRIP_VELOCITY, why); return; }

    if (fabsf(cur_A) > CURRENT_CUTOFF_A) {
        if (!cur_start) cur_start = now_ms;
        else if (now_ms - cur_start > CURRENT_TIME_MS) { detail_num(why, cur_A, 1, " A"); trip(TRIP_OVERCURRENT, why); return; }
    } else cur_start = 0;

    // Calibration is the act of finding the stops, so the limit trip is off there.
    if (g_ctl.cs != CS_CALIB) {
        float lo, hi; active_limits(lo, hi);
        if (pos_deg < lo - LIMIT_TRIP_OVERSHOOT_DEG || pos_deg > hi + LIMIT_TRIP_OVERSHOOT_DEG) {
            const bool left = pos_deg < lo;
            detail_num(why, left ? lo - pos_deg : pos_deg - hi, 0, left ? " deg past L" : " deg past R");
            trip(TRIP_LIMIT, why); return;
        }
    }

    // stall: only meaningful when we are actively servoing to a setpoint
    if (g_ctl.cs == CS_HOLD || g_ctl.cs == CS_TRAJ) {
        if (fabsf(g_ctl.sp_cmd_deg - pos_deg) > STALL_ERROR_DEG) {
            if (!stall_start) stall_start = now_ms;
            else if (now_ms - stall_start > STALL_TIME_MS) {
                detail_num(why, g_ctl.sp_cmd_deg - pos_deg, 0, " deg off target"); trip(TRIP_STALL, why); return;
            }
        } else stall_start = 0;
    } else stall_start = 0;

    // PC in control and silent?  TRAJ -> trip (the setpoint source died);
    // TEST runs autonomously, so just end it and hold.
    if (g_ctl.pc_hb_last_ms && (now_ms - g_ctl.pc_hb_last_ms) > PC_CONTROL_LOSS_MS) {
        if (g_ctl.cs == CS_TRAJ) { detail_num(why, (float)(now_ms - g_ctl.pc_hb_last_ms), 0, " ms silent"); trip(TRIP_PC_LINK_LOST, why); return; }
        if (g_ctl.cs == CS_TEST) {
            g_ctl.test_type = TEST_NONE; g_ctl.sp_target_deg = g_ctl.sp_cmd_deg;
            push_event(EV_WARNING, 0, "test ended: no PC"); set_state(CS_HOLD);
        }
    }
}

// Resolve which source drives the setpoint while enabled.
static void resolve_mode(uint32_t now_ms) {
    if (g_ctl.cs != CS_HOLD && g_ctl.cs != CS_TRAJ) return;
    const bool sp_fresh  = g_ctl.sp_last_ms  && (now_ms - g_ctl.sp_last_ms)  < SETPOINT_STREAM_TIMEOUT_MS;
    uint8_t want = CS_HOLD;
    switch (g_ctl.mode_req) {
    case MODE_HOLD: want = CS_HOLD; break;
    default:        want = sp_fresh ? CS_TRAJ : CS_HOLD; break;   // AUTO / TRAJ
    }
    if (want != g_ctl.cs) {
        if (want == CS_HOLD) g_ctl.sp_target_deg = g_ctl.sp_cmd_deg;   // freeze where we are
        set_state(want);
    }
}

static void run_calibration(float pos_deg, float vel_deg_s, uint32_t now_ms, float dt,
                            float& kp, float& kd, float& t_Nm) {
    static uint32_t still_ms = 0, stage_ms = 0;
    static float    still_pos = 0;
    static float    center = 0;
    static uint8_t  last_stage = CAL_IDLE;
    if (g_ctl.calib != last_stage) { still_ms = 0; stage_ms = now_ms; last_stage = g_ctl.calib; }

    const bool still = fabsf(vel_deg_s) < CAL_STILL_DEG_S;
    kp = kd = 0; t_Nm = g_ctl.torque_cmd_Nm;

    auto advance = [&](uint8_t s) { g_ctl.calib = s; push_event(EV_CALIB_STAGE, s); };

    switch (g_ctl.calib) {
    case CAL_SEEK_LEFT:
    case CAL_SEEK_RIGHT: {
        const float dir = (g_ctl.calib == CAL_SEEK_LEFT) ? -1.f : 1.f;
        float mag = clampf(fabsf(t_Nm), CAL_SEEK_TORQUE_NM, CAL_SEEK_TORQUE_MAX_NM);
        if (fabsf(vel_deg_s) < CAL_SEEK_VEL_DEG_S) mag += CAL_TORQUE_RAMP_NM_S * dt;   // too slow: lean harder
        else                                        mag -= CAL_TORQUE_RAMP_NM_S * dt;   // too fast: ease off
        mag = clampf(mag, CAL_SEEK_TORQUE_NM, CAL_SEEK_TORQUE_MAX_NM);
        if (still) still_ms += (uint32_t)(dt * 1000.f); else still_ms = 0;
        t_Nm = dir * mag;
        if (still_ms >= CAL_STILL_MS && mag >= CAL_CONFIRM_TORQUE_NM) {
            still_pos = pos_deg;
            t_Nm = dir * fminf(mag + CAL_CONFIRM_BUMP_NM, MOTOR_T_MAX_NM * 0.5f);
            advance(g_ctl.calib == CAL_SEEK_LEFT ? CAL_CONFIRM_LEFT : CAL_CONFIRM_RIGHT);
        }
        if (now_ms - stage_ms > CAL_MAX_SEEK_MS) trip(TRIP_CALIB_FAILED, "no stop found");
        break;
    }
    case CAL_CONFIRM_LEFT:
    case CAL_CONFIRM_RIGHT: {
        const bool left = g_ctl.calib == CAL_CONFIRM_LEFT;
        if (fabsf(pos_deg - still_pos) > CAL_MOVE_MIN_DEG) {
            // it moved under the bump -> that was friction, keep seeking
            g_ctl.torque_cmd_Nm = t_Nm;   // keep the higher torque
            advance(left ? CAL_SEEK_LEFT : CAL_SEEK_RIGHT);
            break;
        }
        if (now_ms - stage_ms >= CAL_STILL_MS) {
            if (left) { g_ctl.limit_left_deg = pos_deg; g_ctl.left_captured = true;
                        g_ctl.torque_cmd_Nm = CAL_SEEK_TORQUE_NM; advance(CAL_SEEK_RIGHT); }
            else      { g_ctl.limit_right_deg = pos_deg; g_ctl.right_captured = true;
                        if (g_ctl.limit_right_deg - g_ctl.limit_left_deg < CAL_MIN_RANGE_DEG) {
                            trip(TRIP_CALIB_FAILED, "range too small"); break;
                        }
                        center = 0.5f * (g_ctl.limit_left_deg + g_ctl.limit_right_deg);
                        g_ctl.sp_cmd_deg = pos_deg; t_Nm = 0;
                        advance(CAL_GO_CENTER); }
        }
        break;
    }
    case CAL_GO_CENTER: {
        center = 0.5f * (g_ctl.limit_left_deg + g_ctl.limit_right_deg);
        const float step = CAL_CENTER_RATE_DEG_S * dt;
        const float err = center - g_ctl.sp_cmd_deg;
        g_ctl.sp_cmd_deg += clampf(err, -step, step);
        kp = CAL_CENTER_KP; kd = CAL_CENTER_KD; t_Nm = 0;
        if (fabsf(err) < 0.01f) advance(CAL_SETTLE);
        if (now_ms - stage_ms > CAL_MAX_SEEK_MS) trip(TRIP_CALIB_FAILED, "middle not reached");
        break;
    }
    case CAL_SETTLE: {
        kp = CAL_CENTER_KP; kd = CAL_CENTER_KD; t_Nm = 0;
        if (fabsf(pos_deg - center) < CAL_SETTLE_TOL_DEG && fabsf(vel_deg_s) < CAL_STILL_DEG_S) {
            if (now_ms - stage_ms >= CAL_SETTLE_MS) {
                // Zero the motor where it settled, then shift our frame so the
                // measured centre is exactly 0 (friction may leave it a degree short).
                can_motor_queue_special(SPECIAL_ZERO);
                g_ctl.pos_offset_deg = center - pos_deg;
                g_ctl.limit_left_deg -= center; g_ctl.limit_right_deg -= center;
                g_ctl.limits_valid = true; g_ctl.zeroed = true;
                g_ctl.sp_cmd_deg = g_ctl.sp_target_deg = 0; g_ctl.integral_Nm = 0;
                g_ctl.enable_ms = now_ms; g_ctl.ramp_start_ms = now_ms;
                push_event(EV_LIMITS_SET, 0); push_event(EV_ZERO_SET, 0);
                advance(CAL_DONE);
                set_state(CS_HOLD);
            }
        } else stage_ms = now_ms;   // not settled: restart the settle timer
        if (now_ms - g_ctl.test_start_ms > 2 * CAL_MAX_SEEK_MS) trip(TRIP_CALIB_FAILED, "did not settle");
        break;
    }
    default: break;
    }
}

static void run_test(uint32_t now_ms, float pos_deg, float& kp, float& kd, float& t_Nm) {
    const float el = (now_ms - g_ctl.test_start_ms) * 0.001f;
    if (g_ctl.test_type == TEST_STEP) {
        g_ctl.sp_target_deg = g_ctl.test_base_deg + ((el < g_ctl.test_dur_s) ? g_ctl.test_amp_deg : 0.f);
        if (el > g_ctl.test_dur_s + fmaxf(g_ctl.test_param, 1.f)) {
            g_ctl.test_type = TEST_NONE; push_event(EV_TEST_DONE, TEST_STEP);
            g_ctl.sp_target_deg = g_ctl.sp_cmd_deg; set_state(CS_HOLD);
        }
    } else if (g_ctl.test_type == TEST_RELAY) {
        // Åström–Hägglund relay around test_base with hysteresis test_param (deg)
        const float e = g_ctl.test_base_deg - pos_deg;
        if (e > g_ctl.test_param && g_ctl.relay_sign < 0) { g_ctl.relay_sign = 1; g_ctl.relay_periods++; }
        if (e < -g_ctl.test_param && g_ctl.relay_sign > 0) g_ctl.relay_sign = -1;
        kp = kd = 0; t_Nm = g_ctl.relay_sign * TEST_RELAY_TORQUE_NM;
        g_ctl.sp_target_deg = g_ctl.test_base_deg;
        if (el > g_ctl.test_dur_s || g_ctl.relay_periods >= TEST_RELAY_MAX_PERIODS) {
            g_ctl.test_type = TEST_NONE; push_event(EV_TEST_DONE, TEST_RELAY);
            g_ctl.sp_cmd_deg = g_ctl.sp_target_deg = pos_deg; g_ctl.ramp_start_ms = now_ms;
            set_state(CS_HOLD);
        }
    }
}

void control_tick() {
    const uint32_t t0 = micros();
    const uint32_t now_ms = ms_now();
    const float dt = 1.0f / CONTROL_HZ;
    g_ctl.ticks++;

    sample_switch();

    // snapshot the motor sample (written by main-loop RX under noInterrupts)
    const float    pos_deg   = control_pos_deg();
    const float    vel_deg_s = rad2deg(g_motor.vel_rad_s);
    const float    cur_A     = g_motor.cur_A;
    const bool     fresh     = g_motor.valid && (t0 - g_motor.t_us) < CAN_REPLY_TIMEOUT_MS * 1000u;

    run_safety(pos_deg, vel_deg_s, cur_A, now_ms, fresh);
    resolve_mode(now_ms);

    float kp = 0, kd = 0, t_Nm = 0, vel_cmd = 0;
    // Motor off / safety stop: keep polling so the motor keeps answering (see can_motor.h).
    CanTxKind tx = CAN_TX_POLL;

    switch (g_ctl.cs) {
    case CS_REST:
    case CS_TRIPPED:
        g_ctl.torque_cmd_Nm = 0;
        break;

    case CS_FREESPIN:
        tx = CAN_TX_CMD; kp = kd = 0; t_Nm = 0;
        g_ctl.sp_cmd_deg = g_ctl.sp_target_deg = pos_deg;   // so re-grip is seamless
        g_ctl.torque_cmd_Nm = 0;
        break;

    case CS_CALIB:
        tx = CAN_TX_CMD;
        run_calibration(pos_deg, vel_deg_s, now_ms, dt, kp, kd, t_Nm);
        g_ctl.torque_cmd_Nm = t_Nm;
        break;

    case CS_TEST:
        tx = CAN_TX_CMD;
        run_test(now_ms, pos_deg, kp, kd, t_Nm);
        if (g_ctl.test_type == TEST_RELAY) { g_ctl.torque_cmd_Nm = t_Nm; break; }
        // step test falls through to the normal servo path
        [[fallthrough]];
    case CS_HOLD:
    case CS_TRAJ: {
        tx = CAN_TX_CMD;

        // 1) limit the target, 2) slew the command toward it
        float lo, hi; active_limits(lo, hi);
        g_ctl.sp_target_deg = clampf(g_ctl.sp_target_deg, lo, hi);
        const float max_step = SETPOINT_SLEW_DEG_S * dt;
        const float d = g_ctl.sp_target_deg - g_ctl.sp_cmd_deg;
        g_ctl.sp_cmd_deg += clampf(d, -max_step, max_step);

        // 3) gain ramp after enable / re-grip
        const uint32_t ramp_el = now_ms - g_ctl.ramp_start_ms;
        const float ramp = ramp_el >= GAIN_RAMP_MS ? 1.f
                         : GAIN_RAMP_START_FRAC + (1.f - GAIN_RAMP_START_FRAC) * (ramp_el / (float)GAIN_RAMP_MS);
        kp = g_ctl.kp_eff = g_ctl.kp * ramp;
        kd = g_ctl.kd_eff = g_ctl.kd * ramp;

        // 4) Teensy-side integral (steering friction) with anti-windup + leak
        const float err_deg = g_ctl.sp_cmd_deg - pos_deg;
        if (g_ctl.ki > 0.f && ramp >= 1.f) {
            g_ctl.integral_Nm += g_ctl.ki * deg2rad(err_deg) * dt;
            g_ctl.integral_Nm -= g_ctl.integral_Nm * KI_LEAK_PER_S * dt;
            g_ctl.integral_Nm = clampf(g_ctl.integral_Nm, -KI_INTEGRAL_LIMIT_NM, KI_INTEGRAL_LIMIT_NM);
        } else g_ctl.integral_Nm = 0;
        t_Nm = g_ctl.integral_Nm + g_ctl.tff_Nm;
        vel_cmd = (g_ctl.cs == CS_TRAJ) ? g_ctl.vel_ff_deg_s : 0.f;
        g_ctl.torque_cmd_Nm = t_Nm;
        break;
    }
    default: break;
    }

    can_motor_tick_send(tx, deg2rad(g_ctl.sp_cmd_deg + g_ctl.pos_offset_deg), deg2rad(vel_cmd), kp, kd, t_Nm);

    const uint32_t cost = micros() - t0;
    g_ctl.tick_cost_us = cost;
    g_ctl.last_tick_us = t0;
    if (cost > ISR_OVERRUN_US) g_ctl.overruns++;
}

void control_begin() {
    pinMode(PIN_IDLE_SWITCH, INPUT_PULLUP);
    g_ctl.cs = CS_REST; g_ctl.trip = TRIP_NONE; g_ctl.calib = CAL_IDLE; g_ctl.mode_req = MODE_AUTO;
    g_ctl.kp = DEFAULT_KP; g_ctl.kd = DEFAULT_KD; g_ctl.ki = DEFAULT_KI; g_ctl.tff_Nm = DEFAULT_TFF_NM;
    g_ctl.switch_armed = digitalReadFast(PIN_IDLE_SWITCH) == LOW;
    // A motor left in motor mode by a Teensy reset goes limp and then to REST.
    can_motor_queue_special(SPECIAL_EXIT);
    s_timer.priority(64);                       // above USB/serial, below FlexCAN
    s_timer.begin(control_tick, CONTROL_PERIOD_US);
    push_event(EV_BOOT, PROTOCOL_VERSION);
}
