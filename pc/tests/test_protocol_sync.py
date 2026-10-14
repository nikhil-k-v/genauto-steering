"""Prove protocol.py and protocol/protocol.h agree (ids, enums, struct sizes, CRC)."""
import ctypes
import re
from pathlib import Path

from steering import protocol as P

HDR = Path(__file__).resolve().parents[2] / "protocol" / "protocol.h"


def _defines():
    out = {}
    for m in re.finditer(r"^#define\s+([A-Z0-9_]+)\s+(\(?[^/\n]+?\)?)\s*(?://.*)?$", HDR.read_text(), re.M):
        name, val = m.group(1), m.group(2).strip()
        if name.startswith(("PKT_", "CS_", "MODE_", "CMD_", "TEST_", "TRIP_", "CAL_", "HN_", "HS_", "EV_", "TF_",
                            "HB_", "BS_", "PROTOCOL_", "FRAME_", "MAX_")):
            try:
                out[name] = eval(val.replace("<<", "<<"), {})
            except Exception:
                pass
    return out


def test_constants_match_header():
    d = _defines()
    assert d, "could not parse protocol.h"
    for name, val in d.items():
        assert hasattr(P, name), f"{name} missing from protocol.py"
        assert getattr(P, name) == val, f"{name}: py={getattr(P, name)} h={val}"


def test_struct_sizes_match_header():
    text = HDR.read_text()
    for m in re.finditer(r"static_assert\(sizeof\((\w+)\)\s*==\s*(\d+)", text):
        cls = getattr(P, m.group(1))
        assert ctypes.sizeof(cls) == int(m.group(2)), m.group(1)


def test_crc_known_vector():
    # CRC-8/MAXIM check value for "123456789" is 0xA1
    assert P.crc8(b"123456789") == 0xA1


def test_frame_roundtrip_and_stats():
    pkt = P.command(P.CMD_ENABLE)
    frame = P.encode(pkt, 7)
    parser = P.FrameParser()
    assert parser.feed(b"\x00\xAB" + frame + b"garbage" + frame[:-1] + b"\x00")[0] == pkt
    assert parser.stats.frames_ok == 1 and parser.stats.crc_errors == 1


def test_sequence_drop_counting():
    parser = P.FrameParser()
    parser.feed(P.encode(b"\x01", 1) + P.encode(b"\x01", 2) + P.encode(b"\x01", 5))
    assert parser.stats.drops == 2
