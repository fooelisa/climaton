# Climaton Protocol Documentation

Reverse-engineered from ClimatOn v1.17.0 APK (com.climaton.app) by CladSwiss AG.

## Architecture Overview

The Climaton system supports three transport layers:
1. **UDP over WiFi** (local, primary target) — mDNS discovery + custom binary protocol
2. **MQTT** (cloud) — via `mqtt.cloud.climaton.app:8883` (TLS)
3. **BLE** (Bluetooth Low Energy) — GATT characteristics

All three carry the same logical commands (mode, temperature, etc.) with transport-specific encoding.

---

## 1. Device Discovery (mDNS / DNS-SD)

**Service type:** `_syncleo._udp`

The device advertises itself via mDNS with TXT records:

| TXT Key    | Description                        | Example          |
|------------|------------------------------------|------------------|
| `macaddr`  | Device MAC address                 | `AABBCCDDEEFF`   |
| `vendor`   | Vendor name                        | `electrolux`     |
| `devtype`  | Device type code (short)           | `2` or `93`      |
| `protocol` | Protocol version (1=plain, 2=encrypted, 3=encrypted+domain) | `2` |
| `pairing`  | Pairing mode (0=normal, 1=pairing) | `0`              |
| `firmware`  | Firmware version string            | `1.2.0`          |
| `curve`    | Elliptic curve ID for key exchange | `1`              |
| `public`   | Device's ECDH public key (hex)     | `04abcd...`      |
| `basetype` | Base device type                   | `2`              |

**Discovery flow:**
1. Browse for `_syncleo._udp` services
2. Resolve service → get hostname + port + TXT records
3. Resolve hostname → get IPv4/IPv6 addresses
4. Create `UdpDiscoveredDevice` with MAC, addresses, vendor, type

---

## 2. UDP Frame Protocol

### Frame Structure

All frames are **little-endian**:

```
Offset  Size  Description
0       1     Sequence number (seq)
1       1     Frame type
2       2     Payload length (uint16 LE)
4       N     Payload (N = length)
```

**Total frame size:** 4 + payload_length

### Frame Types

| Type byte | Enum         | Description               |
|-----------|-------------|---------------------------|
| `0x00`    | FRAME_ACK   | Acknowledge received frame |
| `0x01`    | FRAME_CMD   | Command (data) frame       |
| `0x02`    | FRAME_AUX   | Auxiliary frame             |
| `0xFF`    | FRAME_NAK   | Negative acknowledge        |

### Sequence Numbers

- 1-byte counter, wraps at 255
- Sender starts at `seqOut = -1` (0xFF), incremented before each send
- Receiver starts at `seqIn = 0`
- Each sent frame increments seqOut: `seqOut = (seqOut + 1) & 0xFF`

### Reliability

- Frames are retried every 300ms if no ACK received
- Max 15 retries (60 in extended mode)
- Ping every 1000ms when idle (READY state)
- Min send delay between frames: 50ms

---

## 3. Encryption (Protocol v2+)

When `protocol >= 2`, frames are encrypted with **AES-256-CBC**.

### Key Exchange

1. Device publishes its ECDH public key and curve ID in mDNS TXT records
2. Phone generates its own ECDH keypair for the same curve
3. Shared secret = ECDH(phone_private, device_public)
4. `SHA-256(shared_secret)` → 32 bytes:
   - Bytes 0-15 → `encryptionInKey` (decrypt received frames)
   - Bytes 16-31 → `encryptionOutKey` (encrypt sent frames)

### Frame Encryption

For each frame with `seq` byte:
- `keyOffset = seq & 0x0F`
- `ivOffset = (seq >> 4) & 0x0F`
- **Sending:** key = rotate(encryptionOutKey, keyOffset), iv = rotate(encryptionInKey, ivOffset)
- **Receiving:** key = rotate(encryptionInKey, keyOffset), iv = rotate(encryptionOutKey, ivOffset)
- Cipher: `AES/CBC/PKCS5Padding`
- Plaintext prepended with seq byte for validation

### Handshake Encryption (Protocol v2+)

The handshake itself is encrypted differently:
- Cipher: `AES/CBC/NoPadding`
- Key: `encryptionOutKey`, IV: `encryptionInKey` (no rotation)
- Payload: `[0x00] + [phone_public_key] + [AES_encrypted(token)]`

---

## 4. Handshake (Connection Setup)

**Command byte:** `0x00` (CmdHandshake)

### Request (phone → device)

Payload: 16-byte device token (or all zeros for pairing)

### Response (device → phone)

| Offset | Size | Description                    |
|--------|------|--------------------------------|
| 0-1    | 2    | Protocol version (uint16 LE)   |
| 2      | 1    | Firmware major                 |
| 3      | 1    | Firmware minor                 |
| 4      | 1    | Mode (0=config, 1=control)     |
| 5-20   | 16   | Device token                   |

### Connection Flow

1. Phone discovers device via mDNS
2. If protocol >= 2: ECDH key exchange using mDNS TXT records
3. Phone sends CmdHandshake with saved token (or empty for new pairing)
4. Device responds with protocol version, firmware, mode, and token
5. Phone saves token for future connections
6. Connection state → READY
7. Periodic ping (CmdPing) every 1000ms to keep alive

---

## 5. Command Protocol (UDP)

### Command Frame Format

Within a FRAME_CMD payload:

```
Offset  Size  Description
0       1     Command byte (CMD)
1       N     Command-specific payload
```

### EWH50SI / SmartInverter Command Map

The EWH50SI is device class `boiler`, type `2` or `93`.

| CMD byte | Command                | R/W | Payload                          | Description                     |
|----------|------------------------|-----|----------------------------------|---------------------------------|
| `0x00`   | Handshake              | R/W | 16 bytes token                   | Connection setup                |
| `0x01`   | Mode                   | R/W | 1 byte: mode index               | Set operating mode              |
| `0x02`   | TargetTemperature      | R/W | 2 bytes (see encoding below)     | Set target temperature          |
| `0x03`   | TargetTime             | R/W | varies                           | Timer control                   |
| `0x0D`   | DelayStart             | R/W | varies                           | Delayed start                   |
| `0x10`   | KeepWarm               | R/W | 1 byte (0/1 toggle)              | Keep warm after heating         |
| `0x14`   | CurrentTemperature     | R   | 2 bytes (same encoding)          | Current water temperature       |
| `0x1A`   | TotalTime              | R   | varies                           | Total operation time            |
| `0x1F`   | Tank                   | R   | varies                           | Water tank level                |
| `0x28`   | SmartMode              | R/W | 1 byte (0/1 toggle)              | Smart/auto mode                 |
| `0x29`   | Bss                    | R/W | 1 byte (0/1 toggle)              | BSS (bacteriostatic) mode       |
| `0x2C`   | Statistics             | R   | varies                           | Usage statistics                |
| `0x31`   | Turbo                  | R/W | 1 byte (0/1 toggle or range)     | Turbo heating mode              |
| `0x34`   | CurrentPower           | R   | varies                           | Current power (model-dependent) |
| `0x33`   | CurrentAmperage        | R   | varies                           | Current amperage (model-dependent) |
| `0x35`   | CurrentVoltage         | R   | varies                           | Current voltage (model-dependent) |
| `0x40`   | ScheduleSet            | R/W | varies                           | Set schedule                    |
| `0x41`   | ScheduleRemove         | W   | varies                           | Remove schedule                 |
| `0x42`   | ProgramData            | R   | varies                           | Program/recipe data             |
| `0x07`   | Error                  | R   | varies                           | Device error code               |

### Temperature Encoding (2 bytes)

```
Byte 0: integer part (unsigned)
Byte 1: fractional part
  - Bits 0-6: hundredths (0-99)
  - Bit 7: sign (1 = negative)
```

**Encoding:**
```python
def encode_temp(temp: float) -> bytes:
    integer = int(abs(temp))
    fractional = int((abs(temp) - integer) * 100)
    if temp < 0:
        fractional |= 0x80  # set bit 7
    return bytes([integer, fractional])
```

**Decoding:**
```python
def decode_temp(data: bytes) -> float:
    integer = data[0]
    frac_byte = data[1]
    fractional = (frac_byte & 0x7F) / 100.0
    sign = -1 if (frac_byte & 0x80) else 1
    return sign * (integer + fractional)
```

### Mode Values (for EWH50SI / SmartInverter)

| Mode byte | Name                    |
|-----------|-------------------------|
| `0x00`    | Off (hidden in UI)       |
| `0x01`    | Low                      |
| `0x02`    | Mid                      |
| `0x03`    | Turbo                    |
| `0x04`    | Waiting for heating (hidden) |

### Device Limits (EWH50SI)

| Feature       | Min | Max | Default | Step |
|---------------|-----|-----|---------|------|
| temperature   | 30  | 75  | 55      | 1    |
| keep_warm     | 0   | 1   | 0       | 1 (toggle) |
| smart_mode    | 0   | 1   | 0       | 1 (toggle) |
| bss           | 0   | 1   | 0       | 1 (toggle) |

### Device Features (EWH50SI)

- `program` — Operating program/mode selection
- `temperature` — Target temperature control (30-75°C)
- `current_temperature` — Current water temperature sensor
- `keep_warm` — Keep warm after reaching target
- `water_tank` — Water tank level indicator
- `smart_mode` — Smart/auto operation
- `power_consume` — Power consumption monitoring (listed in device config but not observed in state dumps)
- `schedule` — Scheduling support
- `bss` — Bacteriostatic mode (anti-legionella)

---

## 6. MQTT Protocol (Cloud)

### Broker

- Host: `mqtt.cloud.climaton.app` (or `mqtt.cloud.rusklimat.ru`)
- Port: 8883 (TLS)
- Username: `rusclimate`
- Client ID: `rusclimate_app`
- Topic prefix: `42fb1234ee9d1e4b`

### Topics

Commands are sent/received on MQTT topics matching the command names:

| Topic              | Description           | Payload format    |
|--------------------|-----------------------|-------------------|
| `mode`             | Operating mode        | UTF-8 string of byte value |
| `temperature`      | Target temperature    | UTF-8 string of double |
| `sensor/temperature` | Current temperature | UTF-8 string of double |
| `turbo`            | Turbo mode            | UTF-8 string      |

MQTT payloads are UTF-8 string representations of the values (not binary).

---

## 7. BLE Protocol

### Service/Characteristics

| UUID                                     | Command                |
|------------------------------------------|------------------------|
| `d973f2e1-b19e-11e2-9e96-0800200c9a66` | Mode                   |
| `d973f2e7-b19e-11e2-9e96-0800200c9a66` | Error / Turbo / Night  |
| `d973f2f4-b19e-11e2-9e96-0800200c9a66` | CurrentTemperature     |

BLE payloads use the same binary encoding as UDP.

---

## 8. Cloud Endpoints

| Service        | Host                                           |
|---------------|------------------------------------------------|
| Auth           | `auth-iot.api.climaton.app`                    |
| User           | `user-iot.api.climaton.app`                    |
| Devices CDN    | `device.cdn.climaton.app/v2`                   |
| Firmware       | `firmware.cdn.climaton.app`                    |
| Support        | `support.api.climaton.app`                     |
| History        | `d5d8b3gl73jk2emn9hv2.apigw.yandexcloud.net` |
| Statistics     | `d5dprb4t1bl1fbpjkhhm.apigw.yandexcloud.net` |
| Analytics WS   | `wss://analytics-iot.api.climaton.app/climaton` |
| MQTT broker    | `mqtt.cloud.climaton.app:8883`                 |

### Authentication

- AWS Cognito Identity Pool: `us-east-1:0972b9a6-3e62-4403-9fd5-8baaab2bd5e4`
- Google Sign-In supported

---

## 9. Hotspot/Configuration Mode

Port **41122** (UDP) is used when the device is in AP/hotspot mode for initial WiFi configuration.

The phone connects to the device's WiFi AP, sends WiFi credentials to the gateway address on port 41122.

---

## 10. Pairing / Authentication

The device requires a 16-byte **token** for authentication. Without a valid token, the device
responds to handshakes but returns an all-zeros token (= rejected).

### Pairing Flow
1. Put device into **pairing mode** (physical button on the EWH50SI)
2. Send handshake with empty token (16 zero bytes)
3. Device returns a valid 16-byte token
4. Save this token — use it for all future connections

### Verified Findings
- **Device Port:** `41122` (UDP)
- **Protocol:** 1 (unencrypted)
- **Firmware:** 1.99
- **Post-handshake flow:** Send `CmdTimeSync` (0x80) + `CmdDiagnostics` (0x8D) → device pushes all state
- **Pairing:** Device must be in pairing mode (physical button) to obtain a token

---

---

## 11. SDK / Library Structure

The app is built on the `SyncleoIoT` SDK by CladSwiss:
- Package: `com.syncleoiot.iottransport`
- Transport layers: `udp`, `ble`, `mqtt`, `evo`, `proxy`, `cross`
- Common: `DeviceCommand`, `DeviceConnection`, `DeviceCommandParser`
- App commands: `com.syncleoiot.app.api.commands`
