#pragma once
struct TwoWire { void begin() {} void beginTransmission(int) {} int endTransmission() { return 0; } };
static TwoWire Wire;
