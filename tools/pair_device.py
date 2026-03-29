#!/usr/bin/env python3
"""
Pairing script - polls the device waiting for pairing mode.
Run this, then press the pairing button on the water heater.
"""

import socket
import struct
import time
import json
import os

import argparse

parser = argparse.ArgumentParser(description="Pair with a Climaton device")
parser.add_argument("host", help="Device IP address")
parser.add_argument("--port", type=int, default=41122, help="UDP port (default: 41122)")
args = parser.parse_args()

DEVICE_IP = args.host
DEVICE_PORT = args.port

def build_cmd_frame(seq, cmd, payload=b""):
    cmd_payload = bytes([cmd & 0xFF]) + payload
    header = struct.pack('<BBH', seq & 0xFF, 1, len(cmd_payload))
    return header + cmd_payload

def build_ack(seq):
    return struct.pack('<BBH', seq & 0xFF, 0, 0)

def send_handshake(sock):
    frame = build_cmd_frame(0, 0x00, b'\x00' * 16)
    sock.sendto(frame, (DEVICE_IP, DEVICE_PORT))
    try:
        data, addr = sock.recvfrom(4096)
        if len(data) >= 26:
            payload = data[5:]  # skip 4-byte header + cmd byte
            protocol = struct.unpack('<H', payload[0:2])[0]
            fw_major, fw_minor, mode = payload[2], payload[3], payload[4]
            token = payload[5:21]
            is_valid = token != b'\x00' * 16
            return token, is_valid, protocol, fw_major, fw_minor, mode
    except socket.timeout:
        pass
    return None, False, 0, 0, 0, 0

def main():
    print("=" * 50)
    print("  CLIMATON PAIRING TOOL")
    print("=" * 50)
    print()
    print(f"Target: {DEVICE_IP}:{DEVICE_PORT}")
    print()
    print(">>> Press the WiFi/pairing button on the EWH50SI <<<")
    print()
    print("Polling every 2 seconds...")
    print()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(3)

    attempt = 0
    while True:
        attempt += 1
        token, valid, proto, fw_maj, fw_min, mode = send_handshake(sock)

        if token is None:
            print(f"  [{attempt:3d}] No response (timeout)")
        elif valid:
            print(f"\n  *** PAIRED SUCCESSFULLY! ***")
            print(f"  Token: {token.hex()}")
            print(f"  Protocol: {proto}, Firmware: {fw_maj}.{fw_min}, Mode: {mode}")

            # Save token
            token_file = os.path.join(os.path.dirname(__file__), "..", "climaton", "token.json")
            token_data = {
                "token": token.hex(),
                "device_ip": DEVICE_IP,
                "device_port": DEVICE_PORT,
                "protocol": proto,
                "firmware": f"{fw_maj}.{fw_min}",
            }
            os.makedirs(os.path.dirname(token_file), exist_ok=True)
            with open(token_file, "w") as f:
                json.dump(token_data, f, indent=2)
            print(f"\n  Token saved to: {os.path.abspath(token_file)}")
            break
        else:
            print(f"  [{attempt:3d}] Device responded but rejected (not in pairing mode yet)")

        time.sleep(2)

    sock.close()

if __name__ == "__main__":
    main()
