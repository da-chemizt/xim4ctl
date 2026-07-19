# Roadmap

The core is done: the protocol and config format are fully mapped, and a Linux host can read,
switch, and (with the codec) author configs on the device over RFCOMM. Two things build on top.

The reusable core for both is:

- `tools/xim4_frame.py` — frame builder + checksum
- `tools/xim4_config.py` — config parser/author (setting block, encodings)
- an RFCOMM connection to the device (see `tools/xim_pi.py`, `tools/xim_switch.py`)

---

## 1. Web frontend (Docker)

A browser UI to manage an unlimited library of configs and drive the device — replacing the
adapter's tiny on-device slot limit with external storage.

**Architecture**

```
browser UI  ──REST/WebSocket──►  backend service  ──RFCOMM──►  XIM4
                                    │
                                    └── config library (JSON), title→config map
```

- **Backend** — a small Python service that owns the RFCOMM connection to the device (Classic BT,
  so it must run on, or proxy through, a host with a BR/EDR radio). Wraps the existing tools:
  enumerate/read/backup, switch (`0x29`), and author + write (`0x15`) using the codec.
- **Frontend** — config library browser, a config editor exposing the mapped fields (name, color,
  platform, sensitivity, Y/X ratio, boost, deadzone, ballistic curve, per-button mapping, fire-mode
  activation), and a one-click "make active".
- **Auto-switch** — feed it the currently-running game (from console title detection) and have it
  fire `0x29` with the matching config index automatically.
- **Packaging** — Docker container. If deployed on a host without a local BR/EDR radio, the
  container talks to a thin RFCOMM proxy running on the radio-equipped host.

**First milestone:** read-only — connect, enumerate, render the config library, show one-click
switch. Then add the editor + write path (already proven at the protocol level).

---

## 2. Hardware controller (ESP32)

A physical control surface — knobs, dials, display — to adjust config values live (sensitivity,
Y/X ratio, deadzone, ballistic curve, active fire-mode) without a screen or app.

**Chip choice matters.** The XIM4 speaks **Classic Bluetooth (RFCOMM/SPP)**, so the board must
support BR/EDR, not just BLE:

| chip | Bluetooth | direct RFCOMM to device? |
|---|---|---|
| **ESP32-WROOM / WROVER** (original ESP32) | Classic + BLE | yes — SPP client |
| ESP32-S3 | BLE only | no |
| ESP32-C3 / C6 | BLE only | no |
| ESP32-S2 | none (Wi-Fi only) | no |

**Recommended — direct, standalone (ESP32-WROOM/WROVER).** The classic ESP32 opens the RFCOMM
channel to the device itself and runs host-free. Reimplement the checksum and frame builder in
C/C++ (Arduino `BluetoothSerial` provides SPP in master/client mode; or ESP-IDF RFCOMM). Knobs and
dials map to config-field writes; a display shows the active fire-mode and live values.

**Alternative — control surface + relay (BLE-only boards).** If the board is an S3/C-series, it
can't reach the device directly; use it purely as an input/display surface that sends parameter
changes over Wi-Fi to the project-1 backend, which does the RFCOMM write.

**Live-tuning notes**

- Fast, small changes (sensitivity, ratio, deadzone, curve point) are single-field config writes —
  build the setting page and send `0x15`. Fire-mode selection is `0x29`.
- The write path is per-page; a knob turn maps to one field edit → one page write, which is cheap.
- Respect the device's one-connection-at-a-time and connectable-window behaviour
  (see [DEVICE_NOTES.md](DEVICE_NOTES.md)); persistent bonding on the relay host avoids button
  presses.
