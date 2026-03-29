#!/usr/bin/env python3
"""
Interactive command tester — exercise all read/write capabilities.
Tests each command and verifies the device responds with updated state.
"""

import sys
import json
import time
sys.path.insert(0, ".")

from climaton.protocol import ClimatonConnection, DeviceState

with open("climaton/token.json") as f:
    cfg = json.load(f)

conn = ClimatonConnection(
    host=cfg["device_ip"],
    port=cfg["device_port"],
    token=bytes.fromhex(cfg["token"]),
)

def print_state(label=""):
    if label:
        print(f"\n--- {label} ---")
    print(f"  Mode:         {conn.state.mode_name} ({conn.state.mode})")
    print(f"  Target temp:  {conn.state.target_temperature}°C")
    print(f"  Current temp: {conn.state.current_temperature}°C")
    print(f"  Keep warm:    {conn.state.keep_warm}")
    print(f"  Smart mode:   {conn.state.smart_mode}")
    print(f"  BSS:          {conn.state.bss}")
    print(f"  Turbo:        {conn.state.turbo}")
    print(f"  Tank level:   {conn.state.tank_level}")
    print(f"  Error:        {conn.state.error_code}")

def reconnect():
    """Fresh connection to get clean state."""
    global conn
    conn.disconnect()
    time.sleep(0.5)
    conn = ClimatonConnection(
        host=cfg["device_ip"],
        port=cfg["device_port"],
        token=bytes.fromhex(cfg["token"]),
    )
    if not conn.connect(timeout=10):
        print("FAILED to reconnect!")
        sys.exit(1)

def wait_for_update(field, expected, timeout=5):
    """Send pings and listen for state update."""
    start = time.time()
    while time.time() - start < timeout:
        conn._send_cmd(0xFF)  # ping
        conn._recv_loop(0.5)
        actual = getattr(conn.state, field)
        if actual == expected:
            return True
    return False

def test_write(label, action, field, expected, restore_action=None):
    """Test a write command: execute, verify, optionally restore."""
    before = getattr(conn.state, field)
    print(f"\n{'='*50}")
    print(f"TEST: {label}")
    print(f"  Before: {field}={before}")
    print(f"  Action: setting to {expected}")

    action()
    ok = wait_for_update(field, expected)
    after = getattr(conn.state, field)

    if ok:
        print(f"  After:  {field}={after} ✓ OK")
    else:
        print(f"  After:  {field}={after} ✗ MISMATCH (expected {expected})")

    if restore_action and before != expected:
        print(f"  Restoring to {before}...")
        restore_action()
        wait_for_update(field, before)
        restored = getattr(conn.state, field)
        print(f"  Restored: {field}={restored}")

    return ok


print("Connecting...")
if not conn.connect(timeout=10):
    print("FAILED to connect!")
    sys.exit(1)

print_state("Initial State")

# Save original values for restoration
orig_mode = conn.state.mode
orig_temp = conn.state.target_temperature
orig_keep_warm = conn.state.keep_warm
orig_smart_mode = conn.state.smart_mode
orig_bss = conn.state.bss

results = []

# --- Test 1: Set temperature ---
# Pick a safe test value different from current
test_temp = 45.0 if orig_temp != 45.0 else 50.0
results.append(test_write(
    f"Set temperature to {test_temp}°C",
    lambda: conn.set_temperature(test_temp),
    "target_temperature", test_temp,
    lambda: conn.set_temperature(orig_temp),
))

# --- Test 2: Set mode to Low ---
test_mode = 1 if orig_mode != 1 else 2
mode_names = {0: "Off", 1: "Low", 2: "Mid", 3: "Turbo"}
results.append(test_write(
    f"Set mode to {mode_names.get(test_mode, test_mode)}",
    lambda: conn.set_mode(test_mode),
    "mode", test_mode,
    lambda: conn.set_mode(orig_mode),
))

# --- Test 3: Toggle keep warm ---
results.append(test_write(
    f"Set keep_warm to {not orig_keep_warm}",
    lambda: conn.set_keep_warm(not orig_keep_warm),
    "keep_warm", not orig_keep_warm,
    lambda: conn.set_keep_warm(orig_keep_warm),
))

# --- Test 4: Toggle smart mode ---
results.append(test_write(
    f"Set smart_mode to {not orig_smart_mode}",
    lambda: conn.set_smart_mode(not orig_smart_mode),
    "smart_mode", not orig_smart_mode,
    lambda: conn.set_smart_mode(orig_smart_mode),
))

# --- Test 5: Toggle BSS ---
results.append(test_write(
    f"Set BSS to {not orig_bss}",
    lambda: conn.set_bss(not orig_bss),
    "bss", not orig_bss,
    lambda: conn.set_bss(orig_bss),
))

# --- Test 6: Set mode to Off and back ---
if orig_mode != 0:
    results.append(test_write(
        "Set mode to Off",
        lambda: conn.set_mode(0),
        "mode", 0,
        lambda: conn.set_mode(orig_mode),
    ))

# --- Final state check ---
reconnect()
print_state("Final State (after reconnect)")

# --- Summary ---
print(f"\n{'='*50}")
print(f"RESULTS: {sum(results)}/{len(results)} tests passed")
print(f"{'='*50}")
for i, ok in enumerate(results):
    print(f"  Test {i+1}: {'✓ PASS' if ok else '✗ FAIL'}")

conn.disconnect()
print("\nDone!")
