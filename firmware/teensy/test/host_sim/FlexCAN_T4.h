// Host simulation of FlexCAN_T4 with one Yobotics BM motor on the bus.
// The motor answers frames addressed to its id (in REST only if answers_in_rest:
// the datasheet suggests it may only answer in motor mode), acts on 0xFC/0xFD/0xFE
// specials, applies command frames only in motor mode, and is silent otherwise.
// Replies reach the firmware's onReceive callback straight away, as the FlexCAN
// interrupt delivers them when events() is not used.
#pragma once
#include "Arduino.h"
enum CAN_DEV_TABLE { CAN1, CAN2, CAN3 };
enum FLEXCAN_RXQUEUE_TABLE { RX_SIZE_256 = 256 };
enum FLEXCAN_TXQUEUE_TABLE { TX_SIZE_16 = 16 };
struct CAN_message_t { uint32_t id = 0; uint8_t len = 8; uint8_t buf[8] = {0}; struct { bool extended = 0; } flags; };
typedef void (*_MB_ptr)(const CAN_message_t&);

struct HostMotor {
  uint8_t  id = 2;
  bool     powered = true;
  bool     motor_mode = false;
  bool     answers_in_rest = true;
  float    pos_rad = 0.4f;          // where the wheel sits
  float    zero_rad = 0.0f;
  uint32_t frames_seen = 0, replies = 0, enters = 0, exits = 0;
  uint32_t cmds_in_rest = 0;        // command frames received in REST (ignored)
};
inline HostMotor host_motor;
inline std::deque<CAN_message_t> host_can_rx;   // frames waiting for events()
inline std::vector<uint32_t> host_can_tx_ids;   // every id written, in order

inline void host_motor_reply() {
  HostMotor& m = host_motor;
  CAN_message_t r; r.id = 0; r.len = 8;
  const float p = m.pos_rad - m.zero_rad;
  float x = p < -12.566f ? -12.566f : (p > 12.566f ? 12.566f : p);
  const uint16_t P = (uint16_t)((x + 12.566370614f) * 65535.f / 25.132741228f + 0.5f);
  const uint16_t V = 2048, T = 2048;  // ~0 rad/s, ~0 A
  r.buf[0] = m.id; r.buf[1] = P >> 8; r.buf[2] = P & 0xFF;
  r.buf[3] = V >> 4; r.buf[4] = ((V & 0xF) << 4) | (T >> 8); r.buf[5] = T & 0xFF;
  host_can_rx.push_back(r); m.replies++;
}

template<CAN_DEV_TABLE B, FLEXCAN_RXQUEUE_TABLE R, FLEXCAN_TXQUEUE_TABLE T> struct FlexCAN_T4 {
  _MB_ptr cb = nullptr;
  void begin() {} void setBaudRate(uint32_t) {} void setMaxMB(int) {} void enableFIFO() {} void enableFIFOInterrupt() {}
  void onReceive(_MB_ptr f) { cb = f; }
  uint64_t events() {
    if (!host_can_rx.empty() && cb) { CAN_message_t m = host_can_rx.front(); host_can_rx.pop_front(); cb(m); }
    return 0;
  }
  int write(const CAN_message_t& f) {
    host_can_tx_ids.push_back(f.id);
    HostMotor& m = host_motor;
    if (!m.powered || f.id != m.id) return 1;
    m.frames_seen++;
    bool special = true;
    for (int i = 0; i < 7; i++) if (f.buf[i] != 0xFF) special = false;
    if (special && f.buf[7] == 0xFC) { m.motor_mode = true; m.enters++; }
    else if (special && f.buf[7] == 0xFD) { m.motor_mode = false; m.exits++; }
    else if (special && f.buf[7] == 0xFE) { m.zero_rad = m.pos_rad; }
    else if (!m.motor_mode) m.cmds_in_rest++;
    if (!m.motor_mode && !m.answers_in_rest && !special) return 1;
    host_motor_reply();
    if (cb) { CAN_message_t r = host_can_rx.back(); host_can_rx.pop_back(); cb(r); }   // the RX interrupt
    return 1;
  }
};
