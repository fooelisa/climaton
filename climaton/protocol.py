"""Syncleo UDP protocol implementation for Climaton devices."""

import socket
import struct
import time
import datetime
import threading
import logging
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Callable, Optional

_LOGGER = logging.getLogger(__name__)

FRAME_ACK = 0
FRAME_CMD = 1
FRAME_AUX = 2
FRAME_NAK = 0xFF

# Command bytes
CMD_HANDSHAKE = 0x00
CMD_MODE = 0x01
CMD_TARGET_TEMP = 0x02
CMD_TARGET_TIME = 0x03
CMD_ERROR = 0x07
CMD_KEEP_WARM = 0x10
CMD_CURRENT_TEMP = 0x14
CMD_TOTAL_TIME = 0x1A
CMD_TANK = 0x1F
CMD_SMART_MODE = 0x28
CMD_BSS = 0x29
CMD_TURBO = 0x31
CMD_CURRENT_AMPERAGE = 0x33
CMD_CURRENT_POWER = 0x34
CMD_CURRENT_VOLTAGE = 0x35
CMD_SCHEDULE_SET = 0x40
CMD_TIMESYNC = 0x80
CMD_DIAGNOSTICS = 0x8D
CMD_PING = 0xFF


def encode_temp(temp: float) -> bytes:
    """Encode temperature to 2-byte format."""
    integer = int(abs(temp))
    fractional = int((abs(temp) - integer) * 100)
    if temp < 0:
        fractional |= 0x80
    return bytes([integer, fractional])


def decode_temp(data: bytes) -> float:
    """Decode 2-byte temperature."""
    if len(data) < 2:
        return 0.0
    integer = data[0]
    frac = data[1]
    return ((-1 if frac & 0x80 else 1) * (integer + (frac & 0x7F) / 100.0))


def _build_frame(seq: int, frame_type: int, payload: bytes) -> bytes:
    """Build a raw UDP frame."""
    return struct.pack('<BBH', seq & 0xFF, frame_type, len(payload)) + payload


@dataclass
class DeviceState:
    """Current state of a Climaton water heater."""
    mode: int = 0
    target_temperature: float = 0.0
    current_temperature: float = 0.0
    keep_warm: bool = False
    smart_mode: bool = False
    bss: bool = False
    turbo: bool = False
    tank_level: int = 0
    error_code: int = 0
    wifi_connected: bool = False
    mqtt_connected: bool = False
    rssi: int = 0

    MODE_OFF = 0
    MODE_LOW = 1
    MODE_MID = 2
    MODE_TURBO = 3
    MODE_WAITING = 4

    MODE_NAMES = {0: "Off", 1: "Low", 2: "Mid", 3: "Turbo", 4: "Waiting"}

    @property
    def mode_name(self) -> str:
        return self.MODE_NAMES.get(self.mode, f"Unknown({self.mode})")

    @property
    def is_heating(self) -> bool:
        return self.mode in (self.MODE_LOW, self.MODE_MID, self.MODE_TURBO)


class ClimatonConnection:
    """UDP connection to a Climaton/Syncleo device."""

    def __init__(self, host: str, port: int = 41122, token: bytes = b'\x00' * 16):
        self.host = host
        self.port = port
        self.token = token
        self.state = DeviceState()

        self._sock: Optional[socket.socket] = None
        self._seq_out = 0xFF
        self._connected = False
        self._lock = threading.Lock()
        self._listener_thread: Optional[threading.Thread] = None
        self._running = False
        self._on_state_changed: Optional[Callable[[DeviceState], None]] = None
        self._last_ping = 0.0

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self, timeout: float = 10.0) -> bool:
        """Connect to device: handshake + timesync + diagnostics."""
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.settimeout(0.5)
        self._seq_out = 0xFF

        # Send handshake
        self._send_cmd(CMD_HANDSHAKE, self.token)

        # Wait for handshake response
        start = time.time()
        while time.time() - start < timeout:
            result = self._recv_one()
            if result is None:
                continue
            ftype, seq, payload = result
            if ftype == FRAME_CMD and payload and payload[0] == CMD_HANDSHAKE:
                data = payload[1:]
                if len(data) >= 21:
                    resp_token = data[5:21]
                    if resp_token == b'\x00' * 16:
                        _LOGGER.error("Device rejected token (not paired)")
                        self.disconnect()
                        return False
                    self._connected = True
                    _LOGGER.info("Connected to device")

                    # Send timesync + diagnostics
                    ts = int(time.time())
                    offset = int(datetime.datetime.now(
                        datetime.timezone.utc
                    ).astimezone().utcoffset().total_seconds() / 60)
                    self._send_cmd(CMD_TIMESYNC, struct.pack('<iH', ts, offset & 0xFFFF))
                    self._send_cmd(CMD_DIAGNOSTICS, b'\x00')

                    # Collect initial state
                    self._recv_loop(3.0)
                    return True

        _LOGGER.error("Handshake timeout")
        self.disconnect()
        return False

    def disconnect(self):
        """Close the connection."""
        self._running = False
        self._connected = False
        if self._listener_thread and self._listener_thread.is_alive():
            self._listener_thread.join(timeout=3)
        if self._sock:
            self._sock.close()
            self._sock = None

    def start_listening(self, on_state_changed: Optional[Callable[[DeviceState], None]] = None):
        """Start background listener thread with periodic pings."""
        self._on_state_changed = on_state_changed
        self._running = True
        self._listener_thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._listener_thread.start()

    def stop_listening(self):
        """Stop the background listener."""
        self._running = False

    def set_temperature(self, temp: float):
        """Set target temperature (30-75°C)."""
        temp = max(30.0, min(75.0, temp))
        self._send_cmd(CMD_TARGET_TEMP, encode_temp(temp))

    def set_mode(self, mode: int):
        """Set operating mode (0=Off, 1=Low, 2=Mid, 3=Turbo)."""
        self._send_cmd(CMD_MODE, bytes([mode & 0xFF]))

    def set_keep_warm(self, enabled: bool):
        """Enable/disable keep warm."""
        self._send_cmd(CMD_KEEP_WARM, bytes([1 if enabled else 0]))

    def set_smart_mode(self, enabled: bool):
        """Enable/disable smart mode."""
        self._send_cmd(CMD_SMART_MODE, bytes([1 if enabled else 0]))

    def set_bss(self, enabled: bool):
        """Enable/disable BSS (bacteriostatic) mode."""
        self._send_cmd(CMD_BSS, bytes([1 if enabled else 0]))

    def set_turbo(self, enabled: bool):
        """Enable/disable turbo mode."""
        self._send_cmd(CMD_TURBO, bytes([1 if enabled else 0]))

    # --- Internal methods ---

    def _send_cmd(self, cmd: int, payload: bytes = b""):
        """Send a command frame."""
        with self._lock:
            self._seq_out = (self._seq_out + 1) & 0xFF
            data = _build_frame(self._seq_out, FRAME_CMD, bytes([cmd & 0xFF]) + payload)
            if self._sock:
                self._sock.sendto(data, (self.host, self.port))

    def _send_ack(self, seq: int):
        """Send an ACK frame."""
        data = _build_frame(seq, FRAME_ACK, b"")
        if self._sock:
            self._sock.sendto(data, (self.host, self.port))

    def _recv_one(self):
        """Receive one frame. Returns (type, seq, payload) or None."""
        try:
            data, addr = self._sock.recvfrom(4096)
            if len(data) < 4:
                return None
            seq, ftype, length = struct.unpack('<BBH', data[:4])
            payload = data[4:4 + length]

            if ftype == FRAME_CMD:
                self._send_ack(seq)
                self._process_cmd(payload)

            return (ftype, seq, payload)
        except socket.timeout:
            return None
        except OSError:
            return None

    def _recv_loop(self, duration: float):
        """Receive frames for a duration, processing commands."""
        start = time.time()
        while time.time() - start < duration:
            self._recv_one()

    def _listen_loop(self):
        """Background listener with ping keep-alive."""
        while self._running and self._sock:
            self._recv_one()
            now = time.time()
            if now - self._last_ping >= 1.0:
                self._send_cmd(CMD_PING)
                self._last_ping = now

    def _process_cmd(self, payload: bytes):
        """Process a received command and update state."""
        if not payload:
            return
        cmd = payload[0]
        data = payload[1:]
        changed = False

        if cmd == CMD_MODE and data:
            self.state.mode = data[0]
            changed = True
        elif cmd == CMD_TARGET_TEMP and len(data) >= 2:
            self.state.target_temperature = decode_temp(data)
            changed = True
        elif cmd == CMD_CURRENT_TEMP and len(data) >= 2:
            self.state.current_temperature = decode_temp(data)
            changed = True
        elif cmd == CMD_KEEP_WARM and data:
            self.state.keep_warm = bool(data[0])
            changed = True
        elif cmd == CMD_SMART_MODE and data:
            self.state.smart_mode = bool(data[0])
            changed = True
        elif cmd == CMD_BSS and data:
            self.state.bss = bool(data[0])
            changed = True
        elif cmd == CMD_TURBO and data:
            self.state.turbo = bool(data[0])
            changed = True
        elif cmd == CMD_TANK and data:
            self.state.tank_level = data[0]
            changed = True
        elif cmd == CMD_ERROR and data:
            self.state.error_code = data[0]
            changed = True
        elif cmd == CMD_DIAGNOSTICS and data and data[0] == 0 and len(data) >= 3:
            flags = data[1]
            self.state.wifi_connected = bool(flags & 4)
            self.state.mqtt_connected = bool(flags & 8)
            self.state.rssi = data[2] - 256 if data[2] > 127 else data[2]
            changed = True

        if changed and self._on_state_changed:
            self._on_state_changed(self.state)
