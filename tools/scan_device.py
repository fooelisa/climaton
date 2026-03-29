#!/usr/bin/env python3
"""
Scan for Climaton/Syncleo devices on a subnet.

Sends UDP handshake probes to discover devices.
The Syncleo protocol uses a 4-byte header + payload:
  [seq:1][type:1][length:2 LE] + [payload]

A handshake (CMD=0x00) with an empty token (16 zero bytes) should
elicit a response from any Syncleo device.
"""

import argparse
import socket
import struct
import sys
import time

def build_handshake_frame():
    """Build a handshake frame with empty token."""
    # CMD byte 0x00 (handshake) + 16 bytes empty token
    cmd_payload = b'\x00' + b'\x00' * 16

    seq = 0
    frame_type = 1  # FRAME_CMD
    length = len(cmd_payload)

    # Header: seq(1) + type(1) + length(2 LE)
    header = struct.pack('<BBH', seq, frame_type, length)
    return header + cmd_payload

def scan_host(ip, ports, timeout=2):
    """Send handshake probe to a host on given ports."""
    frame = build_handshake_frame()
    results = []

    for port in ports:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(timeout)
            sock.sendto(frame, (ip, port))
            try:
                data, addr = sock.recvfrom(4096)
                results.append((ip, port, data))
                print(f"  [RESPONSE] {ip}:{port} <- {data.hex()} ({len(data)} bytes)")
            except socket.timeout:
                pass
            finally:
                sock.close()
        except Exception as e:
            pass

    return results

def main():
    parser = argparse.ArgumentParser(description="Scan a subnet for Climaton/Syncleo devices")
    parser.add_argument("subnet", help="Subnet to scan, e.g. 192.168.1")
    parser.add_argument("--start", type=int, default=1, help="Start of IP range (default: 1)")
    parser.add_argument("--end", type=int, default=254, help="End of IP range (default: 254)")
    args = parser.parse_args()

    hosts = [f"{args.subnet}.{i}" for i in range(args.start, args.end + 1)]

    # Try a range of common IoT UDP ports
    # The Syncleo mDNS service uses a dynamic port, but devices often
    # use ports in these ranges
    ports = [
        41122,      # Climaton hotspot config port
        6667, 6668, # Common IoT
        8266,       # ESP devices
        5353,       # mDNS
        1900,       # SSDP
        4196, 4197, # Some IoT
        9999, 9998, # Smart home devices
        12416,      # Some water heaters
    ]

    # Also try a broader port range
    ports += list(range(4000, 4020))
    ports += list(range(6000, 6010))
    ports += list(range(8000, 8010))

    print(f"Scanning {len(hosts)} hosts on {len(ports)} UDP ports...")
    print(f"Handshake frame: {build_handshake_frame().hex()}")
    print()

    all_results = []
    for ip in hosts:
        print(f"Probing {ip}...")
        results = scan_host(ip, ports, timeout=1)
        all_results.extend(results)

    print()
    if all_results:
        print(f"Found {len(all_results)} responsive host(s)!")
        for ip, port, data in all_results:
            print(f"  {ip}:{port} -> {data.hex()}")
            if len(data) >= 4:
                seq, ftype, length = struct.unpack('<BBH', data[:4])
                print(f"    seq={seq} type={ftype} length={length}")
                if len(data) > 4:
                    payload = data[4:]
                    print(f"    payload={payload.hex()}")
    else:
        print("No responses received.")
        print("\nThe device may use a port not in our scan range.")
        print("Try: sudo nmap -sU -p- <ip> for a full UDP port scan")

if __name__ == "__main__":
    main()
