#pragma once
#include "Arduino.h"
#define U8G2_R0 0
#define U8X8_PIN_NONE 255
extern const uint8_t u8g2_font_5x8_tr[], u8g2_font_7x13B_tr[];
struct U8G2 {
  void begin() {} void clearBuffer() {} void sendBuffer() {} void setDrawColor(int) {}
  void drawBox(int,int,int,int) {} void drawFrame(int,int,int,int) {} void setFont(const uint8_t*) {}
  int getStrWidth(const char*) { return 0; } void drawStr(int,int,const char*) {}
  void drawXBMP(int,int,int,int,const uint8_t*) {} void drawCircle(int,int,int) {} void drawDisc(int,int,int) {}
  void drawLine(int,int,int,int) {}
};
struct U8G2_SSD1309_128X64_NONAME0_F_HW_I2C : U8G2 { U8G2_SSD1309_128X64_NONAME0_F_HW_I2C(int, int) {} };
