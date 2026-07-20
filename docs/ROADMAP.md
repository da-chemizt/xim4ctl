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
- **Aim translators** — a config's editable pages are authored with the codec; the per-game
  translator (the `0x17` blobs) is not authored, it is *carried*. For v1 the backend keeps a small
  **translator store** populated by capturing a game's 12 chunks once from the wire (exact, no
  database parsing). A config in the library records which translator it uses; on push, the backend
  sends the config pages plus the stored translator. Sourcing translators directly from the `.ximmr`
  container is a v2 improvement (needs the container index parsed — see CONFIG_FORMAT.md).
- **Packaging** — Docker container. If deployed on a host without a local BR/EDR radio, the
  container talks to a thin RFCOMM proxy running on the radio-equipped host.

**Milestones:**
1. Read-only — connect, enumerate, render the config library, one-click switch (`0x29`).
2. Editor + write path — author configs and push editable pages (`0x15`), already proven.
3. Translator store — capture-per-game translators, attach on push.
4. Auto-switch — wire in console title detection.

**Deferred (v2):** a `.ximmr` container parser to assemble any game's translator straight from the
database, so translators don't need to be captured first.

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
- A live "what's pressed now" readout is free: poll `0x3c` (~15 Hz) and decode the leading input
  code with the config button-map decoder (see PROTOCOL.md). Useful for confirming a knob/dial
  binding on the ESP32 display, or a live activity indicator in the web UI.
- The write path is per-page; a knob turn maps to one field edit → one page write, which is cheap.
- Respect the device's one-connection-at-a-time and connectable-window behaviour
  (see [DEVICE_NOTES.md](DEVICE_NOTES.md)); persistent bonding on the relay host avoids button
  presses.
