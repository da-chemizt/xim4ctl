# xim4ctl — web UI

Browser UI to manage an unlimited library of XIM4 configs and drive the device over
RFCOMM. A backend owns the (single, serialized) Bluetooth connection; the config
library is external storage that sidesteps the adapter's on-device slot limit.

```
browser ──REST/WebSocket──► backend (FastAPI) ──RFCOMM / 0x15,0x29,0x0a,0x3c──► XIM4
                               │
                               └── library.json  (configs + title→config map)
```

## Features

- **Config library** — every config as a card with its real game cover, platform tag
  (blue = PlayStation, green = Xbox, grey = PC), shell-LED colour, and an amber glow on
  the one that's active on the device.
- **Tabbed editor** — Mouse (sensitivity, Y/X ratio, boost, ballistic curve, translator),
  Keyboard (stick key bindings), Joystick (deadzone, fire-mode activation), and Buttons
  (17 slots × primary/secondary), per fire-mode. Button rows show the real, platform-aware
  glyph and label (a PS4 config shows R2/L2/✕/○/□/△; Xbox shows RT/LT/A/B/X/Y).
- **Real game artwork + per-game action labels** pulled from the XIM game database — the
  live feed reads e.g. `LMB → RT (Fire)`, `Mouse5 → ○ (…)`.
- **Live activity feed** — a right-rail, chat-log style `input → output (function)` view,
  polling the device's `0x3c` input line (see limitation below).
- **Press-to-assign** — a “listen” button on every input picker captures the next input
  you press on the device (mouse / keyboard / controller).
- **Self-healing Bluetooth** — auto-trusts the XIM4 and busts a wedged/half-open ACL link
  (the `[Errno 16]` state) automatically; a manual “⟳ Reconnect” button is offered when idle.
- **Dark / light theme** toggle (follows the OS by default, remembers your choice).

## Layout

- `backend/xim_codec.py` — full config parse + template-based surgical author (patches only
  mapped offsets; unchanged fields round-trip byte-for-byte). Input-code encodings incl.
  the controller class (`0x2000` DualShock/Xbox buttons).
- `backend/xim_device.py` — serialized RFCOMM driver: handshake, connectable-window retries,
  self-heal (`bluetoothctl` trust/disconnect), `0x3c` live-input poll, `0x29` switch,
  `0x0a` read, `0x15` write.
- `backend/library.py` — config library persistence + `0x0032` metadata + title→config map.
- `backend/app.py` — REST + WebSocket; a dedicated thread polls `0x3c` and broadcasts presses.
- `frontend/` — single-page UI (`index.html`, `app.js`, `style.css`) + generated `assets/`.

## Artwork & labels (generated locally — not in the repo)

The game covers, XIM button/platform icons, and per-game action labels are **extracted from
the vendor game database (`.ximmr`)**, which is copyrighted and not redistributed. Generate
them into `frontend/assets/` yourself:

```sh
# 1. fetch your own copy of the game DB (reads the vendor manifest, verifies MD5)
python3 ../tools/fetch_gamedb.py                     # -> XIMR-*.ximmr

# 2. extract per-game action labels  (-> work/re-actions/action_labels.json)
python3 ../tools/extract_action_labels.py XIMR-*.ximmr work/re-actions

# 3. build the frontend asset set + manifest (covers, icons, labels)
python3 ../tools/build_assets.py XIMR-*.ximmr frontend/assets
```

The UI works without these (cards fall back to a colour tag, the feed to generic action
hints); the assets just make it look and read like the official app.

## Run (Docker, on the host with the BR/EDR radio — e.g. a Raspberry Pi)

```sh
mkdir -p data
# optional: seed the library so it's populated without a device sync first
cp /path/to/xim_full_backup_*.json data/seed_backup.json
docker compose up -d --build
```

Open `http://<host>:8477/`. The container uses host networking + `NET_ADMIN` for the RFCOMM
socket and mounts `/var/run/dbus` so its `bluetoothctl` can trust/recover the host adapter —
so it self-pairs; no host-side setup needed.

To run without Docker: `pip install -r backend/requirements.txt` then
`cd backend && uvicorn app:app --host 0.0.0.0 --port 8477`.

## API

| method | path | purpose |
|---|---|---|
| GET  | `/api/status` | device connection, active slot, feed telemetry |
| GET  | `/api/configs` · `/api/config/{i}` | library list · parsed config |
| POST | `/api/switch/{i}` | make config active (`0x29`) |
| POST | `/api/sync` · `/api/sync/{i}` | read config(s) from device into the library |
| PUT  | `/api/config/{i}` · `/api/config/{i}/library` | author edits → device (`0x15`) · library only |
| POST | `/api/capture` | press-to-assign: read the next input pressed |
| POST | `/api/feed` · `/api/poll` | live-feed on/off · single `0x3c` poll |
| POST | `/api/recover` | bust a wedged BT link and reconnect |
| WS   | `/ws` | live log, status, and input-activity events |

## Limitation — the live activity feed and rapid presses

The activity feed reads the device's `0x3c` line, which reports the **currently-held input
state** (a level), not press *events*. The frame carries no press counter. Measured directly
at ~90 Hz with no software in the path, the XIM4 **holds the pressed level continuously during
fast mashing** and only returns to idle when the input is fully released (~0.5 s). So:

- Deliberate presses (≈ up to ~2/sec, with a clean release) register individually.
- Rapid mashing without a full release reads as **one long press** — there is no release edge
  for any poller to detect, and no counter to fall back on. This is an adapter-side limit, not
  a polling-rate one; the feed already polls at the radio's ceiling (~85 Hz).

The feed is therefore an accurate live indicator for normal-speed play, and cosmetic for
machine-gun mashing.
