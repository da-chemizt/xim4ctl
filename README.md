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
- Game-support database (`.ximmr`) container format: **fully mapped** (directory, per-game
  resources, box art, button/platform icons, action labels, aim-translator blobs). The translator
  encryption is characterised (ECB, single firmware-held key) but not broken. See
  [docs/XIMR_FORMAT.md](docs/XIMR_FORMAT.md).
- **Web UI** (`webui/`): a browser front-end + backend that owns the RFCOMM link — config library,
  a full editor, one-click switch, live input activity, and per-game auto-switch.

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
  XIMR_FORMAT.md     game-support database (.ximmr) container format spec
  XIMR_UNKNOWNS.md   detailed .ximmr structure reference (platform lists, gains, blobs, trailer)
  TRANSLATOR_CRYPTO.md  aim-translator encryption analysis (ECB, firmware-held key)
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
  fetch_gamedb.py    download your own copy of the game-support database from the vendor
  build_assets.py    extract UI icons + covers + action labels from the .ximmr into the web UI
  extract_covers.py  extract per-game box art from the .ximmr
  extract_action_labels.py  extract per-game button→action labels from the .ximmr
  extract_translators.py    catalogue the (encrypted) aim-translator blobs
  crc32table.bin     standard CRC-32 table (poly 0xEDB88320)
webui/               browser UI + FastAPI backend (Docker); see webui/README.md
```

The per-game aim **translators** are not part of the editable config — they are encrypted blobs the
device decrypts internally, stored in the vendor's game-support database (`.ximmr`). To author a
config with correct per-game aim you copy the game's translator out of that database; get your own
copy with `tools/fetch_gamedb.py`. See [docs/CONFIG_FORMAT.md](docs/CONFIG_FORMAT.md#aim-translators-and-the-game-database).

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

## Web UI

`webui/` is a browser front-end with a FastAPI backend that owns the RFCOMM connection, giving the
device an unlimited external config library with a full editor, one-click config switching, a live
`input → output` activity view, press-to-assign, self-healing Bluetooth, and per-game auto-switch.
It ships as a Docker container for a host with a Classic-Bluetooth radio. The game covers, button
icons, and per-game action labels shown in the UI are **generated locally** from your own copy of
the game database (`.ximmr`) — none of that vendor art or data is included here. See
[webui/README.md](webui/README.md).

## Notes and scope

- This is independent interoperability documentation and tooling for a discontinued device you
  own. It contains only original work: a description of the observed protocol and a clean-room
  implementation of it.
- It does **not** include, and does not redistribute, any of the manufacturer's software or data —
  no app binary, no game-support database, no decompiled or repackaged artifacts.
- Not affiliated with, endorsed by, or connected to the device's manufacturer. All trademarks
  belong to their respective owners.
- Provided as-is for interoperability and educational purposes; use with your own hardware.
