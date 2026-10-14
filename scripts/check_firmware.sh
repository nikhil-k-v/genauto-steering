#!/usr/bin/env bash
# Host syntax/type check of the Teensy firmware with g++ and tiny stub headers.
# Not a substitute for `pio run`, but catches most mistakes without a toolchain.
set -e
cd "$(dirname "$0")/.."
STUBS=firmware/teensy/test/host_stubs
for f in firmware/teensy/src/*.cpp; do
  g++ -std=gnu++17 -fsyntax-only -Wall -Wextra -Wno-unused-parameter -I$STUBS -Iprotocol -Ifirmware/teensy/src "$f"
done
echo "firmware host check OK"
