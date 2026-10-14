#pragma once
#include "Arduino.h"
enum CAN_DEV_TABLE { CAN1, CAN2, CAN3 };
enum FLEXCAN_RXQUEUE_TABLE { RX_SIZE_256 = 256 };
enum FLEXCAN_TXQUEUE_TABLE { TX_SIZE_16 = 16 };
struct CAN_message_t { uint32_t id = 0; uint8_t len = 8; uint8_t buf[8] = {0}; struct { bool extended = 0; } flags; };
typedef void (*_MB_ptr)(const CAN_message_t&);
template<CAN_DEV_TABLE B, FLEXCAN_RXQUEUE_TABLE R, FLEXCAN_TXQUEUE_TABLE T> struct FlexCAN_T4 {
  void begin() {} void setBaudRate(uint32_t) {} void setMaxMB(int) {} void enableFIFO() {} void enableFIFOInterrupt() {}
  void onReceive(_MB_ptr) {} void events() {} int write(const CAN_message_t&) { return 1; }
};
