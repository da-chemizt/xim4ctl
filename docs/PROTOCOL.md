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

`cmd` values (little-endian) observed on the wire:

| cmd | direction | meaning |
|---|---|---|
| `0x0001` | both | ping / keepalive (device echoes body) |
| `0x000a` | req/resp | **read config page** of the *active* config. Request `[index:u32]` selects the page/setting slot. Response is a 452-byte frame. |
| `0x000b` | req/resp | small count query |
| `0x000c` | req/resp | read a ~300-byte device settings struct |
| `0x000d` | req/resp | read a setting's display name |
| `0x0015` | req | **write config page** — 452-byte frame, same layout as `0x0a`. Byte 8 (`idx8`) selects the page. |
| `0x0017` | req | write an opaque (encrypted) per-game translator blob (480 bytes). Not human-editable; sourced from the game database, not authored. |
| `0x001e` | req | set a small parameter `[field:u16][value:u16]` |
| `0x001f` | req | reorder — sends the full ordering array of config indices |
| `0x0029` | req/resp | **activate config** `[index:u32]` — selects which stored config is live. The core switch command. |
| `0x0032` | req/resp | **enumerate config list** — request `[index:u32]`, response is a 60-byte record (name + gameUID + color + platform) |
| `0x0033` | req/resp | config count |
| `0x003c` | req/resp | per-game metadata |

### Reading configs

`0x0a` reads pages of the **currently active** config only. To read a specific config, first make
it active with `0x29 [index]`, then read its pages with `0x0a [page]` (`page` 0..7 covers all
settings). Config *metadata* for every config (name, gameUID, color, platform) is available
read-only via `0x0032`/`0x0033` without changing the active config.

### Switching configs

`0x29 [index]` selects the active config. It does not modify any config data — it only changes the
active selector. `index` matches the order returned by `0x0032`. This one command is the whole
basis of per-game auto-switching.

## Config binary format

The 452-byte `0x0a`/`0x15` payload is one page of a larger, paginated config structure.
See [CONFIG_FORMAT.md](CONFIG_FORMAT.md).
