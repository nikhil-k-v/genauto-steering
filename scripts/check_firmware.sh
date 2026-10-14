#!/usr/bin/env bash
# Host syntax/type check of both firmware targets with g++ and tiny stub headers.
# Not a substitute for `pio run`, but catches most mistakes without a toolchain.
set -e
cd "$(dirname "$0")/.."
STUBS=firmware/teensy/test/host_stubs
for f in firmware/teensy/src/*.cpp; do
  g++ -std=gnu++17 -fsyntax-only -Wall -Wextra -Wno-unused-parameter -DWIRED_MODE=1 -I$STUBS -Iprotocol -Ifirmware/teensy/src "$f"
done
g++ -std=gnu++17 -fsyntax-only -Wall -Wno-unused-parameter -DPC_VIA_BRIDGE=1 -I$STUBS -Iprotocol firmware/arduino_bridge/src/main.cpp
echo "firmware host check OK"
