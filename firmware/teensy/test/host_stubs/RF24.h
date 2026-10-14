#pragma once
#include "Arduino.h"
enum { RF24_PA_LOW, RF24_2MBPS };
struct RF24 { RF24(int,int) {} bool begin() { return false; } void setChannel(int) {} void setPALevel(int) {} void setDataRate(int) {}
  void setAutoAck(bool) {} void setRetries(int,int) {} void enableDynamicPayloads() {} void openWritingPipe(const uint8_t*) {}
  void openReadingPipe(int,const uint8_t*) {} void startListening() {} void stopListening() {} bool write(const void*, uint8_t) { return true; }
  bool available(uint8_t*) { return false; } uint8_t getDynamicPayloadSize() { return 0; } void read(void*, uint8_t) {} void flush_rx() {} };
