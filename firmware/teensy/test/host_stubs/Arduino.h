// Minimal host stubs so the firmware can be syntax/type-checked with host g++
// (no cross toolchain needed).  NOT a simulator.  See scripts/check_firmware.sh
#pragma once
#include <stdint.h>
#include <string.h>
#include <stdio.h>
#include <math.h>
#include <stdlib.h>
#define PROGMEM
#define pgm_read_byte(p) (*(const uint8_t*)(p))
#define INPUT_PULLUP 2
#define OUTPUT 1
#define LOW 0
#define HIGH 1
#define PI 3.14159265358979f
#define A1 15
#define A2 16
#define SSD1306_WHITE 1
#define SSD1306_BLACK 0
#define SSD1306_SWITCHCAPVCC 2
#define F(x) x
inline uint32_t millis() { return 0; }
inline uint32_t micros() { return 0; }
inline void delay(uint32_t) {}
inline void delayMicroseconds(uint32_t) {}
inline void yield() {}
inline void pinMode(int, int) {}
inline int digitalRead(int) { return 0; }
inline int digitalReadFast(int) { return 0; }
inline void digitalToggleFast(int) {}
inline int analogRead(int) { return 512; }
inline void noInterrupts() {}
inline void interrupts() {}
template<class T> T constrain(T x, T a, T b) { return x < a ? a : (x > b ? b : x); }
template<class T> T min(T a, T b) { return a < b ? a : b; }
template<class T> T max(T a, T b) { return a > b ? a : b; }
struct HardwareSerial {
  void begin(long) {} int available() { return 0; } int read() { return -1; }
  size_t write(const uint8_t*, size_t n) { return n; } void print(const char*) {} void print(int) {} void print(char) {}
  void print(unsigned) {} void print(long) {} void println(const char*) {} void printf(const char*, ...) {}
};
static HardwareSerial Serial;
struct IntervalTimer { bool begin(void (*)(), uint32_t) { return true; } void priority(uint8_t) {} };
struct elapsedMillis { uint32_t v = 0; operator uint32_t() const { return v; } elapsedMillis& operator=(uint32_t x) { v = x; return *this; } };
struct elapsedMicros { uint32_t v = 0; operator uint32_t() const { return v; } elapsedMicros& operator=(uint32_t x) { v = x; return *this; } };
#define IMXRT_FLEXCAN3_ADDRESS ((uintptr_t)host_can_regs)
static uint32_t host_can_regs[64];
