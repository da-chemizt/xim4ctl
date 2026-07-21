#!/usr/bin/env python3
"""XIM4 config codec — full parse + template-based surgical author.

A config is a fixed 8-page image on the wire. Each page is a 452-byte frame:

    [ crc:4 ][ cmd:2 ][ seq:2 ][ idx4:4 ][ payload:440 ]

On a 0x0a read the idx4 slot carries a constant framing marker; on a 0x15 write it
carries the page number. The logical config buffer is the 440-byte payloads
concatenated (8 * 440 = 3520 bytes):

    buffer[0:48]   name (ASCII, null-padded)
    buffer[50:52]  gameUID (u16)
    buffer[52]     beacon (shell-LED palette index)
    buffer[53]     platform (enum)
    buffer[~364]   pushToTalkKey (input code, u16)

    setting N base = 54 + N*418   (up to 6 fire-modes)

Authoring is *surgical*: we start from the device's real pages, patch only the
mapped field offsets in the reassembled buffer, and re-page. Unmapped bytes are
carried through verbatim, so a no-op edit round-trips byte-for-byte and we never
fabricate structure we don't understand.
"""
import struct

# ---- frame / paging geometry ------------------------------------------------
FRAME      = 452
FRAME_HDR  = 12       # crc4 + cmd2 + seq2 + idx4
PAYLOAD    = 440      # per-page payload bytes
N_PAGES    = 8        # device always returns/accepts an 8-page image
HEADER_LEN = 54       # config header before the first setting
SET_BASE   = 54
SET_STRIDE = 418
N_SETTINGS = 6        # XIM4 fire-modes

# ---- CRC-32 (poly 0xEDB88320, init 0x000000FF, xorout 0xFFFFFFFF) -----------
def _make_table():
    t = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = (0xEDB88320 ^ (c >> 1)) if (c & 1) else (c >> 1)
        t.append(c & 0xffffffff)
    return t
_TBL = _make_table()

def gen_crc(body: bytes) -> int:
    crc = 0xFF
    for b in body:
        crc = (_TBL[(crc ^ b) & 0xff] ^ (crc >> 8)) & 0xffffffff
    return (~crc) & 0xffffffff

def build_frame(cmd: int, seq: int, payload: bytes = b"") -> bytes:
    body = struct.pack("<HH", cmd & 0xffff, seq & 0xffff) + payload
    return struct.pack("<I", gen_crc(body)) + body

# ---- input-code encoding ----------------------------------------------------
# USB HID usage IDs (Keyboard/Keypad page 0x07)
HID = {**{c: 0x04 + i for i, c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ")},
       **{str((i + 1) % 10): 0x1E + i for i in range(10)},
       "Enter": 0x28, "Esc": 0x29, "Backspace": 0x2A, "Tab": 0x2B, "Space": 0x2C,
       "Minus": 0x2D, "Equal": 0x2E, "LBracket": 0x2F, "RBracket": 0x30,
       "Backslash": 0x31, "Semicolon": 0x33, "Quote": 0x34, "Grave": 0x35,
       "Comma": 0x36, "Period": 0x37, "Slash": 0x38, "CapsLock": 0x39,
       **{f"F{i+1}": 0x3A + i for i in range(12)},
       "Pause": 0x48, "Insert": 0x49, "Home": 0x4A, "PageUp": 0x4B, "Delete": 0x4C,
       "End": 0x4D, "PageDown": 0x4E, "Right": 0x4F, "Left": 0x50, "Down": 0x51, "Up": 0x52,
       "LCtrl": 0xE0, "LShift": 0xE1, "LAlt": 0xE2, "LGui": 0xE3,
       "RCtrl": 0xE4, "RShift": 0xE5, "RAlt": 0xE6}
_HID_REV = {v: k for k, v in HID.items()}
MOUSE = {"LMB": 0x4001, "RMB": 0x4002, "MMB": 0x4004, "Mouse4": 0x4008, "Mouse5": 0x4010}
WHEEL = {"WheelUp": 0xa004, "WheelDown": 0xa008}
_MW_REV = {v: k for k, v in {**MOUSE, **WHEEL}.items()}

# Controller-button INPUTS (the XIM's auth/passthrough controller). Codes CONFIRMED by
# live 0x3c capture from a DualShock 4 (+ a config sample):
#   analog class (0xa000, shared with the wheel — triggers have a range): L2=0xa001, R2=0xa002
#   button page 0 (0x20xx): Start=0x2010, Back=0x2020
#   button page 1 (0x21xx): L1=0x2101, R1=0x2102, Home/PS=0x2104,
#                           A/✕=0x2110, B/○=0x2120, X/□=0x2140, Y/△=0x2180
# L3/R3, d-pad and Touchpad weren't captured yet -> they show as "Ctrl:0xNNN" until pressed.
CTRL = {0xa001: "Pad L2", 0xa002: "Pad R2",
        # button page 0 (0x20xx) — bits 0..7, all confirmed by live DS4 capture
        0x2001: "Pad Up", 0x2002: "Pad Down", 0x2004: "Pad Left", 0x2008: "Pad Right",
        0x2010: "Pad Start", 0x2020: "Pad Back", 0x2040: "Pad L3", 0x2080: "Pad R3",
        # button page 1 (0x21xx) — 0x2108 (bit 3, Touchpad?) still un-captured
        0x2101: "Pad L1", 0x2102: "Pad R1", 0x2104: "Pad Home",
        0x2110: "Pad A", 0x2120: "Pad B", 0x2140: "Pad X", 0x2180: "Pad Y"}
CTRL_REV = {v: k for k, v in CTRL.items()}

def encode_input(name):
    """name(str)/None -> u16 input code. None or '' -> 0 (unmapped)."""
    if not name:
        return 0
    if name in MOUSE:
        return MOUSE[name]
    if name in WHEEL:
        return WHEEL[name]
    if name in CTRL_REV:
        return CTRL_REV[name]
    if name.startswith("Ctrl:"):
        return 0x2000 | (int(name[5:], 0) & 0xfff)
    if name in HID:
        u = HID[name]
        return 0x6000 | ((u >> 3) << 8) | (1 << (u & 7))
    if name.startswith("HID:"):
        u = int(name[4:], 0)
        return 0x6000 | ((u >> 3) << 8) | (1 << (u & 7))
    if name.startswith("raw:"):
        return int(name[4:], 0) & 0xffff
    raise ValueError(f"unknown input name: {name!r}")

def decode_input(c):
    """u16 -> canonical name string, or None if unmapped."""
    if c == 0:
        return None
    if c in _MW_REV:
        return _MW_REV[c]
    if c in CTRL:
        return CTRL[c]
    if (c >> 12) == 2:                        # controller class, unnamed mask
        return f"Ctrl:0x{c & 0xfff:03x}"
    if 0x6000 <= c < 0x8000:                 # keyboard HID bitmap
        byte = (c >> 8) - 0x60
        bit = c & 0xff
        if bit and (bit & (bit - 1)) == 0:   # exactly one bit set
            usage = byte * 8 + (bit.bit_length() - 1)
            return _HID_REV.get(usage, f"HID:{usage:#x}")
    return f"raw:{c:#06x}"

# ---- enums ------------------------------------------------------------------
BEACON = {0: "red", 1: "green", 2: "blue", 3: "yellow", 4: "magenta", 5: "cyan",
          6: "white", 7: "darkgreen", 8: "purple", 9: "orange", 10: "red2",
          11: "bluishpurple", 12: "kiwi", 13: "eggyolk", 14: "lightblue"}
BEACON_REV = {v: k for k, v in BEACON.items()}
PLATFORM = {0: "Xbox One", 1: "PS4", 2: "Xbox 360", 3: "PS3", 4: "PC"}
PLATFORM_REV = {v: k for k, v in PLATFORM.items()}

BTN_ORDER = ["RT", "LT", "RS", "LS", "RB", "LB", "A", "B", "X", "Y",
             "Up", "Down", "Right", "Left", "Start", "Back", "Guide"]

# setting-relative offsets
S = {
    "name": 0x00, "activateKey": 0x18, "activateMode": 0x1c,
    "sensitivity": 0x34, "yxRatio": 0x36, "boost": 0x38, "invert": 0x3a,
    "curve": 0x3d, "leftStick": 0x51, "useTranslator": 0x52,
    "turnAssistMode": 0x53, "turnAssistKey": 0x54,
    "kbLU": 0xa0, "kbLL": 0xa2, "kbLR": 0xa4, "kbLD": 0xa6, "kbLWalk": 0xa8,
    "kbRU": 0xaa, "kbRL": 0xac, "kbRR": 0xae, "kbRD": 0xb0,
    "deadzone": 0xcc, "swapSticks": 0xce,
    "primary": 0xf8, "secondary": 0x13c,
}
# config-header (buffer) offsets
H = {"name": 0x00, "gameUID": 0x32, "beacon": 0x34, "platform": 0x35, "pushToTalkKey": 364}

_STICK_KEYS = [("kbLU", "leftUp"), ("kbLL", "leftLeft"), ("kbLR", "leftRight"),
               ("kbLD", "leftDown"), ("kbLWalk", "leftWalk"),
               ("kbRU", "rightUp"), ("kbRL", "rightLeft"), ("kbRR", "rightRight"),
               ("kbRD", "rightDown")]


# ---- paging -----------------------------------------------------------------
def pages_to_buffer(pages) -> bytearray:
    """Concatenate the 440-byte payloads of the (8) frames into the config buffer."""
    buf = bytearray()
    for p in pages:
        if len(p) < FRAME_HDR + PAYLOAD:
            p = p.ljust(FRAME_HDR + PAYLOAD, b"\x00")
        buf += p[FRAME_HDR:FRAME_HDR + PAYLOAD]
    return buf

def buffer_to_pages(buf: bytes, cmd: int = 0x15, seq0: int = 0x0200) -> list:
    """Split the config buffer into 0x15 write frames (idx4 = page number)."""
    buf = bytes(buf)
    total = N_PAGES * PAYLOAD
    buf = buf[:total].ljust(total, b"\x00")
    pages = []
    for i in range(N_PAGES):
        chunk = buf[i * PAYLOAD:(i + 1) * PAYLOAD]
        pages.append(build_frame(cmd, seq0 + i, struct.pack("<I", i) + chunk))
    return pages


# ---- parse ------------------------------------------------------------------
def _u16(buf, off):
    return struct.unpack_from("<H", buf, off)[0]

def _str(buf, off, n):
    return buf[off:off + n].split(b"\x00")[0].decode("latin1")

def _setting_present(buf, base):
    """A fire-mode counts as present if it has a name or any button mapped."""
    if buf[base:base + 24].split(b"\x00")[0]:
        return True
    for i in range(17):
        if _u16(buf, base + S["primary"] + i * 2):
            return True
    return _u16(buf, base + S["activateKey"]) != 0

def parse_setting(buf, base) -> dict:
    def code(off):
        return decode_input(_u16(buf, base + off))
    d = {
        "name": _str(buf, base + S["name"], 24),
        "activateKey": code(S["activateKey"]),
        "activateMode": buf[base + S["activateMode"]],
        "sensitivity": _u16(buf, base + S["sensitivity"]) / 100.0,
        "yxRatio": _u16(buf, base + S["yxRatio"]) / 100.0,
        "boost": _u16(buf, base + S["boost"]),
        "invert": buf[base + S["invert"]],
        "curve": [b / 2.0 for b in buf[base + S["curve"]:base + S["curve"] + 20]],
        "leftStick": buf[base + S["leftStick"]],
        "useTranslator": buf[base + S["useTranslator"]],
        "turnAssistMode": buf[base + S["turnAssistMode"]],
        "turnAssistKey": code(S["turnAssistKey"]),
        "deadzone": _u16(buf, base + S["deadzone"]),
        "swapSticks": buf[base + S["swapSticks"]],
        "keyboardSticks": {name: code(S[key]) for key, name in _STICK_KEYS},
        "primary": {},
        "secondary": {},
    }
    for i, b in enumerate(BTN_ORDER):
        pc = code(S["primary"] + i * 2)
        sc = code(S["secondary"] + i * 2)
        if pc:
            d["primary"][b] = pc
        if sc:
            d["secondary"][b] = sc
    return d

def parse_config(pages) -> dict:
    """pages: list of 452-byte frames (bytes). Returns the editable config dict."""
    buf = pages_to_buffer(pages)
    cfg = {
        "name": _str(buf, H["name"], 48),
        "gameUID": _u16(buf, H["gameUID"]),
        "beacon": BEACON.get(buf[H["beacon"]], f"idx{buf[H['beacon']]}"),
        "beaconIndex": buf[H["beacon"]],
        "platform": PLATFORM.get(buf[H["platform"]], f"idx{buf[H['platform']]}"),
        "platformIndex": buf[H["platform"]],
        "pushToTalkKey": decode_input(_u16(buf, H["pushToTalkKey"])),
        "settings": [],
    }
    for n in range(N_SETTINGS):
        base = SET_BASE + n * SET_STRIDE
        if base + SET_STRIDE > len(buf):
            break
        s = parse_setting(buf, base)
        s["index"] = n
        s["present"] = _setting_present(buf, base)
        cfg["settings"].append(s)
    return cfg


# ---- author (surgical patch) ------------------------------------------------
def _set_u16(buf, off, val):
    struct.pack_into("<H", buf, off, int(val) & 0xffff)

def _set_str(buf, off, n, val):
    # Write the string plus a single null terminator, preserving any bytes that
    # live after it in the fixed field (the device stores a second null-separated
    # label in some name fields — zero-padding the whole field would wipe it).
    raw = (val or "").encode("latin1")[:n]
    buf[off:off + len(raw)] = raw
    if len(raw) < n:
        buf[off + len(raw)] = 0

def author_setting(buf, base, s: dict):
    """Patch one setting block in-place from a (possibly partial) setting dict."""
    if s is None:
        return
    def put_code(off, name):
        _set_u16(buf, base + off, encode_input(name))

    if "name" in s:            _set_str(buf, base + S["name"], 24, s["name"])
    if "activateKey" in s:     put_code(S["activateKey"], s["activateKey"])
    if "activateMode" in s:    buf[base + S["activateMode"]] = int(s["activateMode"]) & 0xff
    if "sensitivity" in s:     _set_u16(buf, base + S["sensitivity"], round(float(s["sensitivity"]) * 100))
    if "yxRatio" in s:         _set_u16(buf, base + S["yxRatio"], round(float(s["yxRatio"]) * 100))
    if "boost" in s:           _set_u16(buf, base + S["boost"], s["boost"])
    if "invert" in s:          buf[base + S["invert"]] = int(s["invert"]) & 0xff
    if "leftStick" in s:       buf[base + S["leftStick"]] = int(s["leftStick"]) & 0xff
    if "useTranslator" in s:   buf[base + S["useTranslator"]] = int(s["useTranslator"]) & 0xff
    if "turnAssistMode" in s:  buf[base + S["turnAssistMode"]] = int(s["turnAssistMode"]) & 0xff
    if "turnAssistKey" in s:   put_code(S["turnAssistKey"], s["turnAssistKey"])
    if "deadzone" in s:        _set_u16(buf, base + S["deadzone"], s["deadzone"])
    if "swapSticks" in s:      buf[base + S["swapSticks"]] = int(s["swapSticks"]) & 0xff
    if "curve" in s:
        cv = s["curve"]
        for i in range(20):
            buf[base + S["curve"] + i] = int(round(float(cv[i]) * 2)) & 0xff
    if "keyboardSticks" in s:
        for key, name in _STICK_KEYS:
            if name in s["keyboardSticks"]:
                put_code(S[key], s["keyboardSticks"][name])
    for arr in ("primary", "secondary"):
        if arr in s:
            for i, b in enumerate(BTN_ORDER):
                if b in s[arr]:
                    put_code(S[arr] + i * 2, s[arr][b])

def author_config(template_pages, edits: dict, cmd: int = 0x15, seq0: int = 0x0200) -> list:
    """Return 0x15 write frames. `template_pages` are the device's real pages;
    `edits` is a (partial) config dict — only present keys are patched."""
    buf = pages_to_buffer(template_pages)
    if "name" in edits:          _set_str(buf, H["name"], 48, edits["name"])
    if "gameUID" in edits:       _set_u16(buf, H["gameUID"], edits["gameUID"])
    if "beaconIndex" in edits:   buf[H["beacon"]] = int(edits["beaconIndex"]) & 0xff
    elif "beacon" in edits:      buf[H["beacon"]] = BEACON_REV.get(edits["beacon"], buf[H["beacon"]])
    if "platformIndex" in edits: buf[H["platform"]] = int(edits["platformIndex"]) & 0xff
    elif "platform" in edits:    buf[H["platform"]] = PLATFORM_REV.get(edits["platform"], buf[H["platform"]])
    if "pushToTalkKey" in edits: _set_u16(buf, H["pushToTalkKey"], encode_input(edits["pushToTalkKey"]))
    for s in edits.get("settings", []):
        base = SET_BASE + s["index"] * SET_STRIDE
        author_setting(buf, base, s)
    return buffer_to_pages(buf, cmd=cmd, seq0=seq0)
