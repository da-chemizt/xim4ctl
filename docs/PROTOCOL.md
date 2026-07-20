# XIM4 Bluetooth Protocol

Reverse-engineered wire protocol for configuring the XIM4 mouse/keyboard adapter over
Bluetooth. Derived from packet captures of the official Manager app plus static analysis of
the app's native library. Verified end-to-end by driving a real device from a Linux host.

## Transport

- **Classic Bluetooth (BR/EDR)** — not BLE. The newer XIM devices (APEX/MATRIX/NEXUS) use BLE;
  the XIM4 uses Bluetooth 2.1.
- **RFCOMM / Serial Port Profile**, PSM `3`, **DLCI 2** (server channel **1**).
- The app opens the channel with an *insecure* (unauthenticated) RFCOMM socket, so a client can
  connect **without bonding**. See [DEVICE_NOTES.md](DEVICE_NOTES.md) for the connectable-window
  caveat and how to bond for autonomous reconnection.

On Linux, a raw socket is enough (no external library):

```python
import socket
s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
s.connect((XIM4_BDADDR, 1))
```

## Frame format

```
[ checksum : 4 bytes LE ] [ cmd : 2 bytes LE ] [ seq : 2 bytes LE ] [ payload ... ]
```

- **checksum** — CRC of the frame body (`cmd + seq + payload`). See below.
- **cmd** — command id.
- **seq** — transaction counter. The device does not strictly require the client's `seq` to be
  echoed; it tracks its own counter and includes it in responses.
- **payload** — command-specific. Responses echo `cmd` and usually carry a status byte then data.

## Checksum

CRC-32 with a non-standard init. This is why generic CRC-32 identification fails.

| parameter | value |
|---|---|
| polynomial | `0xEDB88320` (standard reflected) |
| **init** | **`0x000000FF`** (not `0xFFFFFFFF`) |
| xorout | `0xFFFFFFFF` |
| byte order (stored) | little-endian |
| covers | the frame body (`cmd + seq + payload`), i.e. everything after the 4 checksum bytes |

Reference implementation:

```python
def gen_crc(body: bytes) -> int:
    crc = 0xFF
    for b in body:
        crc = (TABLE[(crc ^ b) & 0xff] ^ (crc >> 8)) & 0xffffffff
    return (~crc) & 0xffffffff       # TABLE = standard CRC-32 table, poly 0xEDB88320
```

See `tools/xim4_frame.py` for a builder (`build(cmd, seq, payload)`).

## Handshake

The client opens a session by sending a fixed frame containing the app version string; the device
replies with its firmware version. The handshake frame can be replayed verbatim — the body is
constant, so its checksum is valid across sessions.

```
client -> magic + "4.00.20160405"  (app version)
device -> magic + "4.00.20171004"  (firmware version)
```

## Command reference

Quick index (all `cmd` values are little-endian). Each is detailed below.

| cmd | name | summary |
|---|---|---|
| `0x0001` | ping | keepalive; device echoes the frame |
| `0x000a` | read config page | read one page of the active config |
| `0x000b` | setting count | number of fire-modes in the active config |
| `0x000c` | read globals | ~300-byte device/global settings struct |
| `0x000d` | read setting name | composite display name of a setting |
| `0x0014`, `0x001d` | poll | periodic no-op polls (see notes) |
| `0x0015` | write config page | write one page of a config |
| `0x0017` | write translator | opaque per-game aim-translator blob |
| `0x001e` | set parameter | set one small `[field]=[value]` |
| `0x001f` | reorder | reorder the config list |
| `0x0029` | activate config | make a stored config active |
| `0x0032` | enumerate config | read one config's list metadata |
| `0x0033` | config count | number of stored configs |
| `0x003c` | live input poll | current pressed input (mouse/wheel/key), polled ~15 Hz |

Examples below show the **frame body** (`cmd + seq + payload`); a 4-byte checksum precedes each,
and `seq` is a 2-byte counter. Responses echo the same `cmd` and carry the device's own `seq`.

### Session

- **`0x0001` — ping / keepalive.** No payload. The device echoes the frame back verbatim (identical
  body, identical checksum), which is how the checksum was first confirmed to be a pure function of
  the body.
  ```
  req  0100 0002            resp 0100 0002        (echo)
  ```

### Reading the active config

`0x0a` reads pages of the **currently active** config only — it has no "config index" parameter.
To read a specific config, first activate it (`0x29`), then page through it. Config *metadata* for
every config is available read-only via `0x0032`/`0x0033` without changing the active selection.

- **`0x000a` — read config page.** Request `[page:u32]`; response is a 452-byte frame (one 440-byte
  page of the config buffer, see [CONFIG_FORMAT.md](CONFIG_FORMAT.md)). Pages 0..7 cover all
  fire-modes; higher pages read empty.
  ```
  req  0a00 <seq> 00000000        # page 0
  resp 0a00 <seq> <452-byte page>
  ```
- **`0x000b` — setting count.** No payload. Response payload is a u32: the number of fire-modes in
  the active config. Example response payload `17000000` = 23.
- **`0x000c` — read globals.** Request `[index:u32]`; response is a ~300-byte struct of device-level
  / global settings (config-cycle hotkeys, breathe/hot-swap toggles, etc. — not fully mapped).
- **`0x000d` — read setting name.** Response is the setting's composite display string, e.g.
  `R6:S-Hip-X1.7` = game abbreviation, fire-mode (`Hip`), platform (`X1` = Xbox One),
  sensitivity (`1.7`).

### Writing

- **`0x0015` — write config page.** A 452-byte frame, same layout as the `0x0a` response. Byte 8
  (`idx8`) is the page number. Author the config buffer, split it into 440-byte pages, and send one
  `0x15` per page. The device acks each with an 8-byte frame.
- **`0x0017` — write translator.** A 480-byte opaque (encrypted) per-game aim-translator blob. This
  is proprietary data sourced from the game-support database, not something you author by hand;
  treat it as an opaque payload to copy, not to construct.
- **`0x001e` — set parameter.** Payload `[field:u16][value:u16]` — sets a single small setting
  in place without rewriting a whole page. Example `0001 0023` sets field `0x0001` to `0x23`.
  (The field-id table is only partially mapped.)

### Config management

- **`0x0029` — activate config.** Payload `[index:u32]`. Selects which stored config is live. Does
  **not** modify any config data — only the active selector. `index` matches `0x0032` ordering.
  This one command is the whole basis of per-game auto-switching. Example: `2900 <seq> 00000000`
  activates config 0.
- **`0x0033` — config count.** No payload. Response payload is a u32 count of stored configs.
- **`0x0032` — enumerate config.** Request `[index:u32]`; response is a 60-byte metadata record:
  `[ name (ASCII) ][ gameUID:u16 @56 ][ beacon:u8 @58 ][ platform:u8 @59 ]`. Read-only; iterate
  `0..count-1` to list every config without changing the active one.
- **`0x001f` — reorder.** Payload is the full ordering array of config indices, terminated by
  `0xFF` — e.g. `00 01 02 … 16 FF` sends the identity order of 23 configs. Send a permuted array to
  reorder.
### Live input monitoring

- **`0x003c` — live input poll.** The app polls this at ~15 Hz to drive its live input-activity
  readout (the line that lights up when you press a mouse button, roll the wheel, or hit a key on
  the hardware plugged into the device). Request payload is a constant selector (`00 15 22 80` in
  captures); the response is a 28-byte frame whose body begins with the **currently-active input
  code** followed by a mostly-static status block:
  ```
  req   3c00 <seq> 00152280
  resp  3c01 <seq> [input:u16 LE][... status, largely constant ...]
  ```
  The `input` field uses the **exact same 16-bit encoding as config button maps**
  (see [CONFIG_FORMAT.md](CONFIG_FORMAT.md)), so it decodes with the same helper. `0x0000` = nothing
  pressed. Observed on the wire:

  | body[0:2] | code | input |
  |---|---|---|
  | `0000` | — | idle |
  | `0840` | `0x4008` | mouse Back (Mouse4) |
  | `1040` | `0x4010` | mouse Forward (Mouse5) |
  | `04a0` | `0xa004` | wheel up |
  | `08a0` | `0xa008` | wheel down |

  Note the response `cmd` reads back as `0x013c` (high byte set to `0x01`) rather than a plain
  `0x003c` echo. Keyboard presses report in the `0x6xxx`/`0x7xxx` range like any mapped key, though
  the reference captures only exercised mouse inputs. This poll is read-only and optional for a
  control client, but it is a ready-made "what's pressed right now" feed for a live UI or a hardware
  controller's display.

### Polling (partially characterized)

- **`0x0014` and `0x001d`** appear repeatedly as an interleaved pair, each an 8-byte request with no
  payload answered by an 8-byte ack. They carry no data in either direction. The likely purpose is
  the app polling the device for state changes (e.g. detecting on-device button-triggered fire-mode
  switches so the UI can follow). They are not needed to read or write configs and can be ignored by
  a control client.

## Config binary format

The 452-byte `0x0a`/`0x15` payload is one page of a larger, paginated config structure.
See [CONFIG_FORMAT.md](CONFIG_FORMAT.md).
