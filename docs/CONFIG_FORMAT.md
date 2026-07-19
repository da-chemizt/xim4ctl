# XIM4 Config Binary Format

A config ("profile") is a fixed binary structure transferred in pages over the wire protocol
(see [PROTOCOL.md](PROTOCOL.md)). Every offset below was confirmed by controlled A/B testing
(change one value in the app, capture the write, diff the bytes) and cross-checked against the
app library's serialization code.

## Pagination

- Full config = **54-byte header** + up to **six 418-byte setting blocks** (fire-modes),
  laid out contiguously (~2562 bytes total).
- It is transferred as **pages**: each `0x0a`/`0x15` frame carries **440 payload bytes** and a
  page number in **frame byte 8** (`idx8`). Frame payload begins at frame offset 12.
- Reassemble the page payloads in order to get the full config buffer. Then:

```
setting N base (in reassembled buffer) = 54 + N * 418     # verified for N = 0..5
```

Because settings straddle page boundaries, a given setting's name can appear at different
frame offsets depending on which page it lands in — the base formula resolves this.

## Config header (buffer offsets; page 0)

| offset | size | field | notes |
|---|---|---|---|
| 0 | 48 | `name` | ASCII, null-padded |
| 50 | 2 | `gameUID` | u16 game identifier; same game/engine shares a value |
| 52 | 1 | `beacon` | shell-LED color, palette index (see enum) |
| 53 | 1 | `platform` | target platform (see enum) |

`pushToTalkKey` also lives in page 0 (an input code, u16) at buffer offset ~364.

## Setting block (offsets relative to the setting base)

| offset | size | field | encoding |
|---|---|---|---|
| `0x00` | 24 | `name` | ASCII, null-padded |
| `0x18` | 2 | `activateKey` | input code — button that activates this fire-mode |
| `0x1c` | 1 | `activateMode` | 0 = hold, 1 = toggle |
| `0x34` | 2 | `mouseSensitivity` | u16, value × 100 (e.g. 150.00 → 15000) |
| `0x36` | 2 | `mouseYXRatio` | u16, value × 100 (e.g. 1.10 → 110) |
| `0x38` | 2 | `mouseBoost` | u16, raw |
| `0x3a` | 1 | `mouseInvert` | 0/1 (invert vertical) |
| `0x3d` | 20 | `ballisticCurve` | 20 bytes, each byte = multiplier × 2 (0.5 steps, 0..127.5) |
| `0x51` | 1 | `mouseLeftStick` | 0/1 (drive left stick instead of right) |
| `0x52` | 1 | `mouseUseTranslator` | 0 = Hip translator, 1 = ADS translator |
| `0x53` | 1 | `turnAssistMode` | 0 = hold, 1 = toggle |
| `0x54` | 2 | `turnAssistKey` | input code |
| `0xa0` | 2 | `keyboardLeftStickUp` | input code |
| `0xa2` | 2 | `keyboardLeftStickLeft` | input code |
| `0xa4` | 2 | `keyboardLeftStickRight` | input code |
| `0xa6` | 2 | `keyboardLeftStickDown` | input code |
| `0xa8` | 2 | `keyboardLeftStickWalk` | input code |
| `0xaa` | 2 | `keyboardRightStickUp` | input code |
| `0xac` | 2 | `keyboardRightStickLeft` | input code |
| `0xae` | 2 | `keyboardRightStickRight` | input code |
| `0xb0` | 2 | `keyboardRightStickDown` | input code |
| `0xcc` | 2 | `joystickDeadZone` | u16, raw |
| `0xce` | 1 | `joystickSwapSticks` | 0/1 |
| `0xf8` | 34 | primary button codes | 17 × u16 input codes (order below) |
| `0x13c` | 34 | secondary button codes | 17 × u16 input codes (same order) |

`inheritSettings` (u8) lets fire-modes 2–5 inherit the primary fire-mode's button layout; the
6th fire-mode is always independent.

### Controller button order

The 17 button-code slots (primary and secondary) are, in order:

```
RT, LT, RS(R3), LS(L3), RB, LB, A, B, X, Y, Up, Down, Right, Left, Start, Back, Guide
```

## Input code encoding

A single 16-bit value encodes any mapped input. `0x0000` = unmapped.

**Keyboard** — the key's position as a bit in a USB-HID usage bitmap:

```
code = 0x6000 | (hid_usage >> 3) << 8 | (1 << (hid_usage & 7))
```

(HID usage ≥ 128 pushes the high nibble into `0x7xxx`.) Examples: `W`→`0x6304`, `A`→`0x6010`,
`Q`→`0x6210`, `Left Shift`→`0x7c02`, `Esc`→`0x6502`, `Up Arrow`→`0x6a04`.

**Mouse button** — `0x4000 | mask`:

| button | code |
|---|---|
| Left | `0x4001` |
| Right | `0x4002` |
| Middle | `0x4004` |
| Back (Mouse4) | `0x4008` |
| Forward (Mouse5) | `0x4010` |

**Mouse wheel** — `0xa000 | direction`: up = `0xa004`, down = `0xa008`.

## Enums

**Platform** (`platform` byte). Xbox = even, PlayStation = odd, newer = lower:

| value | platform |
|---|---|
| 0 | Xbox One |
| 1 | PS4 |
| 2 | Xbox 360 (inferred) |
| 3 | PS3 |
| 4 | PC (inferred) |

The XIM4 only outputs to Xbox-One-class and PS4-class controller protocols; newer consoles
(Series/PS5) are used via backward compatibility, so their configs map onto Xbox One / PS4.

**Beacon** (shell-LED color, `beacon` byte) — palette index. Lower values confirmed; higher
values are approximate:

```
0 red   1 green   2 blue   3 yellow   4 magenta   5 cyan   6 white   7+ darker/mixed
```

## Config list record (`0x0032`, 60 bytes)

Compact per-config metadata, read without changing the active config:

```
[ name (ASCII) ... ] [ gameUID : u16 @56 ] [ beacon : u8 @58 ] [ platform : u8 @59 ]
```

See `tools/xim4_config.py` for a parser/author of the setting block and `tools/ab_diff.py` for
the offset-mapping method.

## Aim translators and the game database

Separate from the human-editable config above, each config also carries a per-game **aim
translator** — the "Smart Translator" that maps mouse motion to a natural stick response for a
specific game (in **Hip** and **ADS** variants). This is what makes a circular mouse motion produce
a circular in-game aim instead of a diagonal-clamped "diamond".

Translators are transferred with `cmd 0x0017` as **472-byte chunks** (`[chunk:u8][pad:3][mode:u16]`
prefix, then payload; a full translator = 12 chunks; `mode` `0x0001` = Hip, `0x0101` = ADS). The
payload is **encrypted** (entropy ≈ 8.0, no compression header, no block structure). The Manager app
contains **no decryption code** — it reads each translator from the game database and sends it to
the device verbatim (`Database::GameHipTranslator` / `Database::GameADSTranslator`). The device
decrypts it internally, so the key lives in the device firmware, not the app.

Practical consequence: you do **not** need to decrypt a translator to use it. The translators are
stored **byte-for-byte** in the game-support database (`.ximmr`), labelled per game/platform/mode.
To author a config with correct per-game aim, copy that game's Hip/ADS translator blobs out of the
database and send them with `0x0017`. Generating a *novel* translator would require breaking the
device-side encryption (a firmware-extraction project, out of scope here).

### Getting the game database

The `.ximmr` is the vendor's copyrighted data and is **not** distributed with this project. Fetch
your own copy from the vendor's server with `tools/fetch_gamedb.py` (it reads the current file URL
and MD5 from the `VersionXR` manifest, downloads, and verifies). The database is a container with a
`XIMR` header, an index region, and the encrypted translator blobs.
