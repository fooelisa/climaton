# Climaton → Home Assistant

Home Assistant custom integration for water heaters controlled by the [ClimatOn](https://climaton.app/) app (by CladSwiss AG).

Reverse-engineered from the ClimatOn Android app. Uses the local UDP protocol — **no cloud required**.

## Supported Devices

- Electrolux EWH50SI (SmartInverter)
- Likely works with other Climaton/Syncleo-based water heaters and boilers

## Features

- **Water heater entity** — temperature control, operation modes (Off/Low/Mid/Turbo)
- **Sensors** — current temperature, tank level, WiFi signal strength
- **Switches** — keep warm, smart mode, anti-legionella (BSS)
- Fully local control over UDP — no internet dependency
- Polling every 30 seconds

## Installation

### HACS (recommended)

1. Add this repository as a custom repository in HACS
2. Install "Climaton Water Heater"
3. Restart Home Assistant

### Manual

1. Copy `custom_components/climaton/` to your Home Assistant `config/custom_components/` directory
2. Restart Home Assistant

## Setup

### 1. Pair with your device

Before adding the integration, you need to obtain a pairing token from your device.

If you don't know your device's IP, scan your subnet first:

```bash
python tools/scan_device.py 192.168.1
```

Then pair with the device:

```bash
python tools/pair_device.py 192.168.1.100
```

The script will poll the device. Press the **WiFi/pairing button** on your water heater (hold for a few seconds). The script will capture and save the 16-byte token.

### 2. Add the integration

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **Climaton**
3. Enter your device's IP address, port (default: 41122), and the hex token from step 1

## Protocol Documentation

See [docs/protocol.md](docs/protocol.md) for the full reverse-engineered protocol specification, including:

- mDNS discovery (`_syncleo._udp`)
- UDP frame format (4-byte header + payload)
- Handshake and authentication
- Command bytes and payload encoding
- Temperature encoding (2-byte format)
- Encryption details (for protocol v2+ devices)

## Standalone Python Library

The `climaton/` directory contains a standalone Python client:

```python
from climaton.protocol import ClimatonConnection

conn = ClimatonConnection("192.168.1.100", 41122, bytes.fromhex("your_token_here"))
conn.connect()

print(f"Temperature: {conn.state.current_temperature}°C")
print(f"Mode: {conn.state.mode_name}")

conn.set_temperature(55)
conn.set_mode(1)  # Low

conn.disconnect()
```

## License

MIT
