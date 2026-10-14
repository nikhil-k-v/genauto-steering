#pragma once
#include "Arduino.h"
#include "Wire.h"
struct Adafruit_SSD1306 { Adafruit_SSD1306(int,int,TwoWire*,int) {} bool begin(int,int) { return true; } void clearDisplay() {} void display() {}
  void setTextSize(int) {} void setTextColor(int) {} void setCursor(int,int) {} void print(const char*) {} void print(char) {} void print(int) {}
  void print(unsigned) {} void print(uint8_t) {} void print(long) {} void fillRect(int,int,int,int,int) {} void drawRect(int,int,int,int,int) {}
  void drawPixel(int,int,int) {} void drawCircle(int,int,int,int) {} void drawLine(int,int,int,int,int) {} void fillCircle(int,int,int,int) {} };
