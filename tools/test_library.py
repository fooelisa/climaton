#!/usr/bin/env python3
"""Test the climaton library — connect, read state, verify."""

import sys
import json
sys.path.insert(0, ".")

from climaton.protocol import ClimatonConnection

with open("climaton/token.json") as f:
    cfg = json.load(f)

conn = ClimatonConnection(
    host=cfg["device_ip"],
    port=cfg["device_port"],
    token=bytes.fromhex(cfg["token"]),
)

print("Connecting...")
if not conn.connect(timeout=10):
    print("FAILED to connect!")
    sys.exit(1)

print(f"\nDevice State:")
print(f"  Mode:              {conn.state.mode_name} ({conn.state.mode})")
print(f"  Target temp:       {conn.state.target_temperature}°C")
print(f"  Current temp:      {conn.state.current_temperature}°C")
print(f"  Keep warm:         {conn.state.keep_warm}")
print(f"  Smart mode:        {conn.state.smart_mode}")
print(f"  BSS:               {conn.state.bss}")
print(f"  Turbo:             {conn.state.turbo}")
print(f"  Tank level:        {conn.state.tank_level}")
print(f"  Error:             {conn.state.error_code}")
print(f"  WiFi connected:    {conn.state.wifi_connected}")
print(f"  MQTT connected:    {conn.state.mqtt_connected}")
print(f"  RSSI:              {conn.state.rssi} dBm")
print(f"  Is heating:        {conn.state.is_heating}")

conn.disconnect()
print("\nDone!")
