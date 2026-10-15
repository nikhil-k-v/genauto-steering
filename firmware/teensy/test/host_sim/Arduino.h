// Host simulation of the Teensy core for test/test_can_host.cpp: a controllable
// clock, a Serial that the test can feed and drain, an IntervalTimer the test
// fires by hand, and the idle-switch pin.  Built as ONE translation unit
// together with every firmware .cpp (see scripts/check_firmware.sh).
#pragma once
#include <stdint.h>
#include <string.h>
#include <stdio.h>
#include <math.h>
#include <stdlib.h>
#include <deque>
#include <vector>
#define PROGMEM
#define pgm_read_byte(p) (*(const uint8_t*)(p))
#define INPUT_PULLUP 2
#define OUTPUT 1
#define LOW 0
#define HIGH 1
#define PI 3.14159265358979f
#define F(x) x

inline uint64_t host_now_us = 0;          // the test advances this
inline int      host_switch_level = LOW;  // LOW = idle switch off (armed)
inline uint32_t millis() { return (uint32_t)(host_now_us / 1000); }
inline uint32_t micros() { return (uint32_t)host_now_us; }
// Time passes while firmware code blocks, so a busy-wait shows up as a stall.
inline void delay(uint32_t ms) { host_now_us += 1000ull * ms; }
inline void delayMicroseconds(uint32_t us) { host_now_us += us; }
inline void yield() { host_now_us += 10; }
inline void pinMode(int, int) {}
inline int digitalRead(int) { return host_switch_level; }
inline int digitalReadFast(int) { return host_switch_level; }
inline void digitalToggleFast(int) {}
inline int analogRead(int) { return 512; }
inline void noInterrupts() {}
inline void interrupts() {}
template<class T> T constrain(T x, T a, T b) { return x < a ? a : (x > b ? b : x); }

struct HardwareSerial {
  std::deque<uint8_t> in;                  // PC -> Teensy
  std::vector<uint8_t> out;                // Teensy -> PC
  void begin(long) {}
  int available() { return (int)in.size(); }
  int read() { if (in.empty()) return -1; int b = in.front(); in.pop_front(); return b; }
  size_t write(const uint8_t* p, size_t n) { out.insert(out.end(), p, p + n); return n; }
};
inline HardwareSerial Serial;

inline void (*host_timer_fn)() = nullptr;
struct IntervalTimer { bool begin(void (*f)(), uint32_t) { host_timer_fn = f; return true; } void priority(uint8_t) {} };

// elapsedMillis / elapsedMicros count from the simulated clock like the real ones
struct elapsedMillis {
  uint32_t t0 = millis();
  operator uint32_t() const { return millis() - t0; }
  elapsedMillis& operator=(uint32_t x) { t0 = millis() - x; return *this; }
};
struct elapsedMicros {
  uint32_t t0 = micros();
  operator uint32_t() const { return micros() - t0; }
  elapsedMicros& operator=(uint32_t x) { t0 = micros() - x; return *this; }
};
#define IMXRT_FLEXCAN3_ADDRESS ((uintptr_t)host_can_regs)
inline uint32_t host_can_regs[64];
