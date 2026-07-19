#!/usr/bin/env python3
"""XIM4 FULL backup — for each config: activate (0x29), wait, read all pages (0x0a). Paced.
Non-destructive (0x29 only selects active; 0x0a only reads). Restores original active at end."""
import socket, struct, sys, time, json, os

ADDR = os.environ.get("XIM4_ADDR", "AA:BB:CC:DD:EE:FF")  # set XIM4_ADDR to your XIM4 bdaddr
CH = 1
TS = sys.argv[1] if len(sys.argv) > 1 else "full"
PACE = 5.0  # seconds between config switches

def make_table():
    t = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = (0xEDB88320 ^ (c >> 1)) if (c & 1) else (c >> 1)
        t.append(c & 0xffffffff)
    return t
TBL = make_table()
def gen_crc(body):
    crc = 0xFF
    for b in body:
        crc = (TBL[(crc ^ b) & 0xff] ^ (crc >> 8)) & 0xffffffff
    return (~crc) & 0xffffffff
def build(cmd, seq, payload=b""):
    body = struct.pack("<HH", cmd, seq) + payload
    return struct.pack("<I", gen_crc(body)) + body
HANDSHAKE = bytes.fromhex("4b72fc2b00000100342e30302e32303136303430350000000000000000000000aca6121074420a00")
assert build(0x29, 0x44, struct.pack("<I", 0)) == bytes.fromhex("1ec844ab2900440000000000")

_seq = [0x0100]
def xact(s, cmd, payload=b"", window=1.2):
    _seq[0] = (_seq[0] + 1) & 0xffff
    s.send(build(cmd, _seq[0], payload))
    s.settimeout(window); data = b""
    try:
        while True:
            c = s.recv(2048)
            if not c: break
            data += c
    except socket.timeout:
        pass
    return data

def name_of(hexs):
    f = bytes.fromhex(hexs) if isinstance(hexs, str) else hexs
    return f[12:56].split(b"\x00")[0].decode("latin1", "ignore") if len(f) >= 60 else ""

def main():
    print("PUSH THE XIM4 BUTTON — connecting (retry 40s)...")
    s = None
    for _ in range(40):
        try:
            s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
            s.settimeout(4); s.connect((ADDR, CH)); break
        except OSError:
            s.close(); s = None; time.sleep(1)
    if s is None:
        print("could not connect"); return
    print(">>> CONNECTED <<<")
    s.send(HANDSHAKE); s.settimeout(1.8)
    try:
        while True:
            if not s.recv(2048): break
    except socket.timeout:
        pass

    cnt_raw = xact(s, 0x33)
    cnt = struct.unpack_from("<I", cnt_raw, 8)[0] if len(cnt_raw) >= 12 else 0
    cnt = cnt if 0 < cnt <= 64 else 23
    print("config count:", cnt)

    lst = {i: xact(s, 0x32, struct.pack("<I", i)).hex() for i in range(cnt)}

    # note currently-active config (read page 0 -> name + platform@65) to restore later
    active0 = xact(s, 0x0a, struct.pack("<I", 0))
    a_name = name_of(active0); a_plat = active0[65] if len(active0) > 65 else -1
    orig = None
    for i, h in lst.items():
        f = bytes.fromhex(h)
        if f[12:56].split(b"\x00")[0].decode("latin1", "ignore") == a_name and f[59] == a_plat:
            orig = i; break
    print("original active: '%s' plat=%d  -> index %s" % (a_name, a_plat, orig))

    backup = {"ts": TS, "count": cnt, "orig_active": orig, "list": lst, "configs": {}}
    for i in range(cnt):
        xact(s, 0x29, struct.pack("<I", i))          # activate config i (non-destructive)
        time.sleep(PACE)                              # pacing
        pages = [xact(s, 0x0a, struct.pack("<I", p)).hex() for p in range(8)]
        for _ in pages: time.sleep(0.3)
        backup["configs"][i] = pages
        print("  [%2d/%d] '%s'  (page0 %d bytes)" % (i + 1, cnt, name_of(pages[0]), len(pages[0]) // 2))

    if orig is not None:
        xact(s, 0x29, struct.pack("<I", orig))
        print("restored active config to index %d ('%s')" % (orig, a_name))

    out = os.path.expanduser("~/xim_full_backup_%s.json" % TS)
    json.dump(backup, open(out, "w"))
    print("SAVED:", out)
    s.close()

main()
