// =============================================================================
// config.h — every tunable constant for the Teensy steering controller.
//
// Everything a human might want to change while commissioning lives here:
// pins, rates, safety thresholds, calibration behaviour.  Nothing in here is
// changeable from the PC at run time ON PURPOSE (safety limits are a firmware
// property, see docs/SAFETY.md).  Keep units in the names.
// =============================================================================
#pragma once
#include <stdint.h>

// ---- build options ----------------------------------------------------------
#ifndef WIRED_MODE
#define WIRED_MODE 1            // 1 = PC over USB serial, 0 = PC via NRF24 bridge
#endif

// ---- pins (hardware identical to previous build) ----------------------------
#define PIN_IDLE_SWITCH     22  // SPST to GND, INPUT_PULLUP. LOW = ARMED, HIGH = IDLE
#define PIN_OLED_SDA        18  // Wire (I2C0)
#define PIN_OLED_SCL        19
#define PIN_NRF_CE           9
#define PIN_NRF_CSN         10  // SPI0: MOSI 11, MISO 12, SCK 13
#define PIN_LED             13  // on-board LED (shared with SCK; heartbeat only in wired mode)
// CAN3: CRX3 = pin 30, CTX3 = pin 31  (transceiver STBY tied low)

// ---- motor / CAN -------------------------------------------------------------
#define MOTOR_CAN_ID_DEFAULT  0x02
#define CAN_BITRATE           1000000
#define CAN_REPLY_TIMEOUT_MS  200    // no reply for this long while enabled -> TRIP_CAN_LOST
#define CAN_RX_EXPECTED_HZ    1000   // we command at 1 kHz; motor replies to each
#define CAN_RX_LOW_HZ         600    // below this the A4 node goes WARN(BLOCKED)

// BM-18 MIT-style field ranges (datasheet 优宝特 BM-18, 2024).  The motor
// interprets the 12/16-bit fields with these spans — if you change them here
// you are changing the meaning of every number the motor receives.
#define MOTOR_P_MIN_RAD     (-12.566370614f)   // -4*pi
#define MOTOR_P_MAX_RAD     ( 12.566370614f)
#define MOTOR_V_MIN_RAD_S   (-30.0f)
#define MOTOR_V_MAX_RAD_S   ( 30.0f)
#define MOTOR_KP_MIN          0.0f
#define MOTOR_KP_MAX        500.0f
#define MOTOR_KD_MIN          0.0f
#define MOTOR_KD_MAX        100.0f
#define MOTOR_T_MIN_NM      (-18.0f)           // datasheet: -18 .. 18 Nm (NOT +-6 as before)
#define MOTOR_T_MAX_NM      ( 18.0f)

// ---- loop rates --------------------------------------------------------------
#define CONTROL_HZ            1000
#define CONTROL_PERIOD_US     (1000000 / CONTROL_HZ)
#define TELEMETRY_HZ          200
#define HEALTH_HZ             20
#define CONFIG_ECHO_HZ        5
#define DISPLAY_HZ            25
#define ISR_OVERRUN_US        (CONTROL_PERIOD_US * 9 / 10)  // tick took >90% of period
#define ISR_OVERRUN_TRIP      50     // overruns in one health period -> TRIP_ISR_OVERRUN

// ---- link timeouts (what "alive" means) -------------------------------------
#define PC_HEARTBEAT_TIMEOUT_MS   1000
#define PC_CONTROL_LOSS_MS         600   // PC silent this long: TRAJ -> trip, TEST -> end test
#define BRIDGE_TIMEOUT_MS         1000
#define JOYSTICK_TIMEOUT_MS        300
#define SETPOINT_STREAM_TIMEOUT_MS 250   // no setpoint for this long in TRAJ -> HOLD

// ---- control defaults --------------------------------------------------------
#define DEFAULT_KP           30.0f
#define DEFAULT_KD            2.0f
#define DEFAULT_KI            0.0f
#define DEFAULT_TFF_NM        0.0f
#define KI_INTEGRAL_LIMIT_NM  4.0f   // anti-windup clamp on the integral torque
#define KI_LEAK_PER_S         0.2f   // slow leak so the integral never "sticks"

// Software position limit when no calibration has been done.  The calibrated
// end-stops always win when valid (LIMIT_MARGIN_DEG inside the measured stops).
#define POS_LIMIT_DEFAULT_DEG  200.0f
#define LIMIT_MARGIN_DEG         3.0f
#define LIMIT_TRIP_OVERSHOOT_DEG 15.0f   // measured pos this far past a limit -> TRIP_LIMIT

// Setpoint shaping: never let the commanded setpoint jump.
#define SETPOINT_SLEW_DEG_S     2300.0f  // ~40 rad/s, same as before
#define JOY_MAX_RATE_DEG_S       180.0f

// Gain ramp on (re)enable so a stale setpoint never snaps the wheel.
#define GAIN_RAMP_START_FRAC     0.05f
#define GAIN_RAMP_MS             800
#define ENABLE_GRACE_MS          250     // suppress trips right after enable

// ---- safety trips (firmware-only, latched, need CMD_CLEAR_TRIP) --------------
#define VELOCITY_CUTOFF_DEG_S   1430.0f  // ~25 rad/s
#define STALL_ERROR_DEG           28.6f  // 0.5 rad
#define STALL_TIME_MS            500
#define CURRENT_CUTOFF_A          30.0f  // BM-18 peak 40 A, rated 15 A
#define CURRENT_TIME_MS          300

// ---- end-stop auto calibration (docs/OPERATIONS.md#calibration) -------------
// Strategy: torque-mode seek.  Push toward a stop and ramp the torque up
// while the wheel moves slower than CAL_SEEK_VEL_DEG_S (down again when it is
// faster), so the wheel creeps to the stop at a bounded speed with the least
// torque that overcomes friction.  A "stop" is declared when the wheel has not
// moved for CAL_STILL_MS while torque >= CAL_CONFIRM_TORQUE_NM; the confirm
// phase bumps the torque once more to distinguish a real stop from friction.
#define CAL_SEEK_TORQUE_NM        1.0f   // starting / minimum push torque
#define CAL_SEEK_TORQUE_MAX_NM    3.5f   // never exceed while seeking
#define CAL_SEEK_VEL_DEG_S       30.0f   // target creep speed
#define CAL_TORQUE_RAMP_NM_S      1.0f   // ramp rate (both directions)
#define CAL_CONFIRM_TORQUE_NM     2.5f   // torque at which a still wheel = stop
#define CAL_CONFIRM_BUMP_NM       1.0f   // extra push to confirm
#define CAL_STILL_DEG_S           4.0f   // "not moving" threshold
#define CAL_STILL_MS              600
#define CAL_MOVE_MIN_DEG          2.0f   // the bump must move < this to confirm
#define CAL_MAX_SEEK_MS         25000    // give up (TRIP_CALIB_FAILED)
#define CAL_MIN_RANGE_DEG        60.0f   // sanity: a steering wheel has > 60 deg total
#define CAL_CENTER_RATE_DEG_S    40.0f   // slow slew to center
#define CAL_CENTER_KP            25.0f
#define CAL_CENTER_KD             1.5f
#define CAL_SETTLE_MS            800
#define CAL_SETTLE_TOL_DEG        3.0f   // friction may leave it short; the frame offset fixes the rest

// ---- tests (run on the Teensy so timing is exact) ----------------------------
#define TEST_RELAY_TORQUE_NM      2.0f
#define TEST_RELAY_MAX_PERIODS   12

// ---- OLED ---------------------------------------------------------------------
#define OLED_SPLASH_MS         2000
#define OLED_I2C_ADDR          0x3C

// ---- NRF24 (wireless bridge) --------------------------------------------------
#define NRF_CHANNEL            108
#define NRF_ADDR_TEENSY        "STR01"   // bridge -> teensy pipe
#define NRF_ADDR_BRIDGE        "STR02"   // teensy -> bridge pipe
