# xim4ctl

A from-scratch reverse-engineering of the **XIM4** gaming adapter's Bluetooth configuration
protocol, plus a Python toolkit to read, switch, and author configs on the device programmatically.

The XIM4 is an end-of-life mouse/keyboard-to-controller adapter. Its official Manager app is
delisted and doesn't run cleanly on modern phones, and the device holds only a handful of
on-device config slots. This project talks to the device directly so configs can be managed from
code — an unlimited external library, per-game auto-switching, and (in progress) hardware and web
control surfaces.

No prior public documentation of this protocol existed; everything here was derived from packet
captures and static analysis of the app's native library, and verified against a real device.

## Status

- Wire protocol: **fully mapped** (transport, framing, checksum, command set).
- Config binary format: **fully mapped** (header, up to six fire-mode setting blocks, all input
  encodings, platform/color enums, pagination).
- Verified **end-to-end**: a Linux host connects over RFCOMM, reads and backs up every config,
  switches the active config, and can author configs with a working codec.

## Capabilities

- Connect over Classic Bluetooth RFCOMM (no bonding required to connect).
- Enumerate all configs (name, gameUID, color, platform) — read-only.
- Read and **back up** every config, including all fire-modes.
- **Switch** the active config (`0x29`) — the basis for per-game auto-switching.
- **Author** a config from high-level values (sensitivity, buttons, curve, color, platform, …) and
  write it to the device.

## Repo layout

```
docs/
  PROTOCOL.md        wire protocol: transport, framing, checksum, commands
  CONFIG_FORMAT.md   config binary layout, field offsets, input encodings, enums
  DEVICE_NOTES.md    LED semantics, pairing/connectable window, wedging, capture method
  ROADMAP.md         planned web frontend + hardware controller
tools/
  xim4_frame.py      frame builder + checksum (CRC-32, init 0xFF)
  xim4_config.py     config parser/author (setting block, encodings)
  rfcomm_decode.py   btsnoop -> RFCOMM payload decoder
  ab_diff.py         diff consecutive config writes to map fields
  xim_pi.py          RFCOMM client: connect + handshake + probe
  xim_switch.py      switch active config by index
  xim_backup.py      read-only backup (metadata + active config)
  xim_full_backup.py full backup (activate + read every config; paced, non-destructive)
  crc32table.bin     standard CRC-32 table (poly 0xEDB88320)
```

## Quickstart

Requires Python 3 on a Linux host with a Classic-Bluetooth radio (native `AF_BLUETOOTH` support).

```bash
export XIM4_ADDR="AA:BB:CC:DD:EE:FF"   # your device's Bluetooth address
python3 tools/xim_pi.py                # connect, handshake, query config count
python3 tools/xim_switch.py 3          # activate config index 3
python3 tools/xim_full_backup.py $(date +%s)   # full backup to ~/xim_full_backup_*.json
```

If the connection fails with `Host is down`, the device is outside its connectable window — press
its button, or bond the host for persistent connectivity (see `docs/DEVICE_NOTES.md`).

## Notes and scope

- This is independent interoperability documentation and tooling for a discontinued device you
  own. It contains only original work: a description of the observed protocol and a clean-room
  implementation of it.
- It does **not** include, and does not redistribute, any of the manufacturer's software or data —
  no app binary, no game-support database, no decompiled or repackaged artifacts.
- Not affiliated with, endorsed by, or connected to the device's manufacturer. All trademarks
  belong to their respective owners.
- Provided as-is for interoperability and educational purposes; use with your own hardware.
