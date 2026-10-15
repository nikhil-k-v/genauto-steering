#!/usr/bin/env bash
# Host checks of the Teensy firmware with g++ (no cross toolchain needed):
#  1. syntax/type check of every source file against tiny stub headers;
#  2. firmware/teensy/test/test_can_host.cpp: the real firmware, built as one host
#     program against a simulated clock, USB link and a simulated BM motor on CAN
#     (test/host_sim/), driven through motor off -> on -> scan -> wrong id ->
#     unpowered.  Not a substitute for `pio run` + the hardware checklist.
set -e
cd "$(dirname "$0")/.."
STUBS=firmware/teensy/test/host_stubs
for f in firmware/teensy/src/*.cpp; do
  g++ -std=gnu++17 -fsyntax-only -Wall -Wextra -Wno-unused-parameter -I$STUBS -Iprotocol -Ifirmware/teensy/src "$f"
done
echo "firmware host check OK"
OUT=$(mktemp -d)
trap 'rm -rf "$OUT"' EXIT
g++ -std=gnu++17 -O1 -Wall -Wno-unused-function -Wno-format-truncation \
    -Ifirmware/teensy/test/host_sim -I$STUBS -Iprotocol -Ifirmware/teensy/src \
    firmware/teensy/test/test_can_host.cpp -o "$OUT/test_can_host"
"$OUT/test_can_host"
