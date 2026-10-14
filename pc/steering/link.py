"""
link.py — the PC <-> Teensy transport.

* `Transport` is the seam: `SerialTransport` talks to the real Teensy (or the
  Arduino bridge in wireless mode); `tools/sim_teensy.py` provides a
  `SimTransport` that behaves like the firmware so the whole UI can be used
  with no hardware.
* `Link` runs a reader thread that frames bytes, decodes packets and publishes
  them on the bus ("telemetry", "health", "config", "event", "can_scan",
  "bridge", "joystick"), plus a 5 Hz heartbeat.  It never raises into the UI:
  port errors become `link` topic updates and a reconnect loop.
* Everything observable about the link (bytes, frames, CRC errors, ages) is
  exposed in `LinkStats` for the PC-side health nodes D2..D6.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from . import protocol as P
from .bus import Bus

log = logging.getLogger(__name__)


class Transport:
    """Byte-stream transport.  Implementations must be thread-safe for one reader + one writer."""
    name = "none"

    def open(self) -> None: ...
    def close(self) -> None: ...
    def read(self, max_bytes: int, timeout_s: float) -> bytes: return b""
    def write(self, data: bytes) -> None: ...
    @property
    def is_open(self) -> bool: return False


class SerialTransport(Transport):
    def __init__(self, port: str, baud: int = 2_000_000):
        self.port, self.baud = port, baud
        self._ser = None
        self.name = f"serial:{port}"

    def open(self):
        import serial                                # lazy: tests without pyserial
        self._ser = serial.Serial(self.port, self.baud, timeout=0.02, write_timeout=0.2)
        try:
            self._ser.reset_input_buffer()
        except Exception:
            pass

    def close(self):
        if self._ser:
            try:
                self._ser.close()
            finally:
                self._ser = None

    def read(self, max_bytes, timeout_s):
        if not self._ser:
            return b""
        n = self._ser.in_waiting
        return self._ser.read(max(1, min(n, max_bytes)))

    def write(self, data):
        if self._ser:
            self._ser.write(data)

    @property
    def is_open(self):
        return self._ser is not None and self._ser.is_open


def list_serial_ports():
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    out = []
    for p in list_ports.comports():
        label = f"{p.device}  {p.description}"
        score = 0
        desc = (p.description or "").lower() + " " + (p.manufacturer or "").lower()
        if "teensy" in desc:
            score = 3
        elif "arduino" in desc:
            score = 2
        elif "usb" in desc:
            score = 1
        out.append((score, p.device, label))
    out.sort(reverse=True)
    return [(d, l) for _, d, l in out]


def guess_port() -> Optional[str]:
    ports = list_serial_ports()
    return ports[0][0] if ports else None


@dataclass
class LinkStats:
    port_open: bool = False
    port_error: str = ""
    bytes_in: int = 0
    frames_ok: int = 0
    crc_errors: int = 0
    sync_errors: int = 0
    drops: int = 0
    frames_hz: float = 0.0
    telemetry_hz: float = 0.0
    last_byte_t: float = 0.0
    last_frame_t: float = 0.0
    last_telemetry_t: float = 0.0
    last_health_t: float = 0.0
    last_config_t: float = 0.0
    last_bridge_t: float = 0.0
    hb_sent: int = 0
    tx_frames: int = 0
    tx_errors: int = 0
    teensy_pc_hb_age_ms: int = 0xFFFF     # what the Teensy reports about *our* heartbeat (round trip)
    connect_attempts: int = 0
    opened_at: float = 0.0
    unknown_packets: int = 0

    def age(self, which: str, now: Optional[float] = None) -> float:
        now = now or time.monotonic()
        t = getattr(self, f"last_{which}_t", 0.0)
        return 1e9 if t == 0.0 else now - t


class Link:
    HEARTBEAT_HZ = 5

    def __init__(self, bus: Bus, transport: Optional[Transport] = None):
        self.bus = bus
        self.transport = transport
        self.stats = LinkStats()
        self._parser = P.FrameParser()
        self._tx_seq = 0
        self._tx_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._hb_flags = P.HB_UI_ALIVE
        self._pc_health_bits = 0
        self._want_open = False
        self._rate_window = []       # (t, n_frames) for Hz estimates
        self._telemetry_count = 0

    # ---- lifecycle ----------------------------------------------------------------
    def start(self):
        if self._thread:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="link", daemon=True)
        self._thread.start()

    def stop(self, send_rest: bool = True):
        if send_rest and self.transport and self.transport.is_open:
            try:
                self.send(P.command(P.CMD_DISABLE))     # the firmware also trips on heartbeat loss
                time.sleep(0.05)
            except Exception:
                pass
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None
        if self.transport:
            self.transport.close()
        self.stats.port_open = False
        self.bus.publish("link", self.stats)

    def connect(self, transport: Transport):
        """Swap/open a transport.  Safe to call from the UI thread."""
        self.disconnect()
        self.transport = transport
        self._want_open = True
        self.start()

    def disconnect(self):
        self._want_open = False
        if self.transport and self.transport.is_open:
            try:
                self.send(P.command(P.CMD_DISABLE))
            except Exception:
                pass
            self.transport.close()
        self.stats.port_open = False
        self.bus.publish("link", self.stats)

    # ---- sending ------------------------------------------------------------------
    def send(self, payload: bytes) -> bool:
        if not (self.transport and self.transport.is_open):
            return False
        with self._tx_lock:
            frame = P.encode(payload, self._tx_seq)
            self._tx_seq = (self._tx_seq + 1) & 0xFF
            try:
                self.transport.write(frame)
                self.stats.tx_frames += 1
                return True
            except Exception as e:                  # write timeout / unplugged
                self.stats.tx_errors += 1
                self.stats.port_error = f"write: {e}"
                return False

    def set_heartbeat_flags(self, recording: bool = False, server_up: bool = False, phone: bool = False,
                            ui_alive: bool = True):
        self._hb_flags = ((P.HB_UI_ALIVE if ui_alive else 0) | (P.HB_RECORDING if recording else 0)
                          | (P.HB_SERVER_UP if server_up else 0) | (P.HB_PHONE_CAPTURE if phone else 0))

    def set_pc_health_bits(self, bits: int):
        self._pc_health_bits = bits & 0x7FFF

    # ---- reader thread ------------------------------------------------------------
    def _run(self):
        next_hb = 0.0
        backoff = 0.5
        while not self._stop.is_set():
            t = self.transport
            if t is None or not self._want_open:
                time.sleep(0.1)
                continue
            if not t.is_open:
                try:
                    self.stats.connect_attempts += 1
                    t.open()
                    self.stats.port_open = True
                    self.stats.port_error = ""
                    self.stats.opened_at = time.monotonic()
                    self._parser = P.FrameParser()
                    backoff = 0.5
                    log.info("link open: %s", t.name)
                    self.send(P.command(P.CMD_REQ_CONFIG))
                except Exception as e:
                    self.stats.port_open = False
                    self.stats.port_error = f"open: {e}"
                    self.bus.publish("link", self.stats)
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 3.0)
                    continue
                self.bus.publish("link", self.stats)

            try:
                data = t.read(4096, 0.02)
            except Exception as e:
                log.warning("link read failed: %s", e)
                self.stats.port_error = f"read: {e}"
                self.stats.port_open = False
                try:
                    t.close()
                except Exception:
                    pass
                self.bus.publish("link", self.stats)
                continue

            now = time.monotonic()
            if data:
                self.stats.bytes_in += len(data)
                self.stats.last_byte_t = now
                for payload in self._parser.feed(data):
                    self._dispatch(payload, now)
                st = self._parser.stats
                self.stats.frames_ok, self.stats.crc_errors = st.frames_ok, st.crc_errors
                self.stats.sync_errors, self.stats.drops = st.sync_errors, st.drops
            else:
                time.sleep(0.002)

            if now >= next_hb:
                next_hb = now + 1.0 / self.HEARTBEAT_HZ
                self.send(P.heartbeat(self._hb_flags, self._pc_health_bits, int(now * 1000)))
                self.stats.hb_sent += 1
                self._update_rates(now)
                self.bus.publish("link", self.stats)

    def _update_rates(self, now):
        self._rate_window.append((now, self.stats.frames_ok, self._telemetry_count))
        self._rate_window = [w for w in self._rate_window if now - w[0] <= 1.0]
        if len(self._rate_window) >= 2:
            dt = self._rate_window[-1][0] - self._rate_window[0][0]
            if dt > 0:
                self.stats.frames_hz = (self._rate_window[-1][1] - self._rate_window[0][1]) / dt
                self.stats.telemetry_hz = (self._rate_window[-1][2] - self._rate_window[0][2]) / dt

    def _dispatch(self, payload: bytes, now: float):
        pkt = P.decode(payload)
        self.stats.last_frame_t = now
        if pkt is None:
            self.stats.unknown_packets += 1
            return
        k = payload[0]
        if k == P.PKT_TELEMETRY:
            self.stats.last_telemetry_t = now
            self._telemetry_count += 1
            self.bus.publish("telemetry", pkt)
        elif k == P.PKT_HEALTH:
            self.stats.last_health_t = now
            self.stats.teensy_pc_hb_age_ms = pkt.pc_hb_age_ms
            self.bus.publish("health_fw", pkt)
        elif k == P.PKT_CONFIG_ECHO:
            self.stats.last_config_t = now
            self.bus.publish("config", pkt)
        elif k == P.PKT_EVENT:
            self.bus.publish("event", pkt)
        elif k == P.PKT_CAN_SCAN:
            self.bus.publish("can_scan", pkt)
        elif k == P.PKT_BRIDGE_STATUS:
            self.stats.last_bridge_t = now
            self.bus.publish("bridge", pkt)
        elif k == P.PKT_JOYSTICK:
            self.bus.publish("joystick", pkt)
