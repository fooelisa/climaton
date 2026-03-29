"""Syncleo UDP protocol implementation for Climaton devices."""

import socket
import struct
import time
import datetime
import threading
import logging
from dataclasses import dataclass
from typing import Callable, Optional

_LOGGER = logging.getLogger(__name__)

FRAME_ACK = 0
FRAME_CMD = 1

CMD_HANDSHAKE = 0x00
CMD_MODE = 0x01
CMD_TARGET_TEMP = 0x02
CMD_ERROR = 0x07
CMD_KEEP_WARM = 0x10
CMD_CURRENT_TEMP = 0x14
CMD_TANK = 0x1F
CMD_SMART_MODE = 0x28
CMD_BSS = 0x29
CMD_TURBO = 0x31
CMD_CURRENT_POWER = 0x34
CMD_TIMESYNC = 0x80
CMD_DIAGNOSTICS = 0x8D
CMD_PING = 0xFF


def encode_temp(temp: float) -> bytes:
    integer = int(abs(temp))
    fractional = int((abs(temp) - integer) * 100)
    if temp < 0:
        fractional |= 0x80
    return bytes([integer, fractional])


def decode_temp(data: bytes) -> float:
    if len(data) < 2:
        return 0.0
    integer = data[0]
    frac = data[1]
    return ((-1 if frac & 0x80 else 1) * (integer + (frac & 0x7F) / 100.0))


def _build_frame(seq: int, frame_type: int, payload: bytes) -> bytes:
    return struct.pack('<BBH', seq & 0xFF, frame_type, len(payload)) + payload


@dataclass
class DeviceState:
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

    MODE_NAMES = {0: "off", 1: "low", 2: "mid", 3: "turbo", 4: "waiting"}

    @property
    def mode_name(self) -> str:
        return self.MODE_NAMES.get(self.mode, "unknown")

    @property
    def is_heating(self) -> bool:
        return self.mode in (self.MODE_LOW, self.MODE_MID, self.MODE_TURBO)


class ClimatonConnection:
    """UDP connection to a Climaton/Syncleo device.

    All public methods are serialized with a lock so poll() and write
    commands can never race each other.
    """

    def __init__(self, host: str, port: int = 41122, token: bytes = b'\x00' * 16):
        self.host = host
        self.port = port
        self.token = token
        self.state = DeviceState()
        self._lock = threading.Lock()

    def connect(self, timeout: float = 10.0) -> bool:
        """Connect and read initial state."""
        with self._lock:
            return self._connect(timeout)

    def disconnect(self):
        with self._lock:
            self._disconnect()

    def poll(self) -> bool:
        """Poll device by doing a fresh connect cycle."""
        with self._lock:
            return self._cycle()

    def set_temperature(self, temp: float):
        temp = max(30.0, min(75.0, temp))
        with self._lock:
            self._write_cmd(CMD_TARGET_TEMP, encode_temp(temp))

    def set_mode(self, mode: int):
        with self._lock:
            self._write_cmd(CMD_MODE, bytes([mode & 0xFF]))

    def set_keep_warm(self, enabled: bool):
        with self._lock:
            self._write_cmd(CMD_KEEP_WARM, bytes([1 if enabled else 0]))

    def set_smart_mode(self, enabled: bool):
        with self._lock:
            self._write_cmd(CMD_SMART_MODE, bytes([1 if enabled else 0]))

    def set_bss(self, enabled: bool):
        with self._lock:
            self._write_cmd(CMD_BSS, bytes([1 if enabled else 0]))

    def set_turbo(self, enabled: bool):
        with self._lock:
            self._write_cmd(CMD_TURBO, bytes([1 if enabled else 0]))

    # --- Private methods (must be called with _lock held) ---

    def _write_cmd(self, cmd: int, payload: bytes):
        """Send a write command: connect, send, collect state, disconnect."""
        sock, seq = self._open_and_handshake()
        if sock is None:
            return

        # Send the actual command
        seq = (seq + 1) & 0xFF
        data = _build_frame(seq, FRAME_CMD, bytes([cmd & 0xFF]) + payload)
        sock.sendto(data, (self.host, self.port))

        # Wait for ACK + state update
        self._collect_state(sock, 2.0)
        sock.close()

    def _cycle(self) -> bool:
        """Full connect cycle: handshake, collect state, disconnect."""
        sock, seq = self._open_and_handshake()
        if sock is None:
            return False
        sock.close()
        return True

    def _connect(self, timeout: float) -> bool:
        """Initial connect (same as _cycle but with configurable timeout)."""
        sock, seq = self._open_and_handshake(timeout)
        if sock is None:
            return False
        sock.close()
        return True

    def _disconnect(self):
        pass  # No persistent socket to close anymore

    def _open_and_handshake(self, timeout: float = 10.0):
        """Create socket, do handshake, collect state. Returns (sock, seq) or (None, 0)."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(0.5)
        seq = 0

        # Send handshake
        data = _build_frame(seq, FRAME_CMD, bytes([CMD_HANDSHAKE]) + self.token)
        sock.sendto(data, (self.host, self.port))

        # Wait for handshake response
        start = time.time()
        handshake_ok = False
        while time.time() - start < timeout:
            frame = self._recv_frame(sock)
            if frame is None:
                continue
            ftype, fseq, payload = frame
            if ftype == FRAME_CMD and payload and payload[0] == CMD_HANDSHAKE:
                resp_data = payload[1:]
                if len(resp_data) >= 21:
                    resp_token = resp_data[5:21]
                    if resp_token == b'\x00' * 16:
                        _LOGGER.error("Device rejected token")
                        sock.close()
                        return None, 0
                    handshake_ok = True
                    break

        if not handshake_ok:
            _LOGGER.error("Handshake timeout")
            sock.close()
            return None, 0

        # Send timesync + diagnostics
        ts = int(time.time())
        tz_offset = int(datetime.datetime.now(
            datetime.timezone.utc
        ).astimezone().utcoffset().total_seconds() / 60)

        seq = (seq + 1) & 0xFF
        sock.sendto(
            _build_frame(seq, FRAME_CMD, bytes([CMD_TIMESYNC]) + struct.pack('<iH', ts, tz_offset & 0xFFFF)),
            (self.host, self.port),
        )
        seq = (seq + 1) & 0xFF
        sock.sendto(
            _build_frame(seq, FRAME_CMD, bytes([CMD_DIAGNOSTICS, 0x00]),),
            (self.host, self.port),
        )

        # Collect state dump
        self._collect_state(sock, 3.0)
        return sock, seq

    def _collect_state(self, sock: socket.socket, duration: float):
        """Read frames for `duration` seconds, updating self.state."""
        start = time.time()
        while time.time() - start < duration:
            frame = self._recv_frame(sock)
            if frame is None:
                continue
            ftype, seq, payload = frame
            if ftype == FRAME_CMD and payload:
                self._process_cmd(payload)

    def _recv_frame(self, sock: socket.socket):
        """Receive and ACK one frame. Returns (type, seq, payload) or None."""
        try:
            data, addr = sock.recvfrom(4096)
            if len(data) < 4:
                return None
            seq, ftype, length = struct.unpack('<BBH', data[:4])
            payload = data[4:4 + length]
            if ftype == FRAME_CMD:
                # Send ACK
                ack = _build_frame(seq, FRAME_ACK, b"")
                sock.sendto(ack, (self.host, self.port))
            return (ftype, seq, payload)
        except socket.timeout:
            return None
        except OSError:
            return None

    def _process_cmd(self, payload: bytes):
        if not payload:
            return
        cmd = payload[0]
        data = payload[1:]

        if cmd == CMD_MODE and data:
            self.state.mode = data[0]
        elif cmd == CMD_TARGET_TEMP and len(data) >= 2:
            self.state.target_temperature = decode_temp(data)
        elif cmd == CMD_CURRENT_TEMP and len(data) >= 2:
            self.state.current_temperature = decode_temp(data)
        elif cmd == CMD_KEEP_WARM and data:
            self.state.keep_warm = bool(data[0])
        elif cmd == CMD_SMART_MODE and data:
            self.state.smart_mode = bool(data[0])
        elif cmd == CMD_BSS and data:
            self.state.bss = bool(data[0])
        elif cmd == CMD_TURBO and data:
            self.state.turbo = bool(data[0])
        elif cmd == CMD_TANK and data:
            self.state.tank_level = data[0]
        elif cmd == CMD_ERROR and data:
            self.state.error_code = data[0]
        elif cmd == CMD_DIAGNOSTICS and data and data[0] == 0 and len(data) >= 3:
            flags = data[1]
            self.state.wifi_connected = bool(flags & 4)
            self.state.mqtt_connected = bool(flags & 8)
            self.state.rssi = data[2] - 256 if data[2] > 127 else data[2]
