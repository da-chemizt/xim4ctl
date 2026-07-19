#!/usr/bin/env python3
"""XIM4 READ-ONLY backup — enumerate all configs (0x32) + read each (0x0a), save raw bytes.
NO writes. Output: ~/xim_backup_<ts>.json (pass timestamp as argv[1])."""
import socket, struct, sys, time, json, os

ADDR = os.environ.get("XIM4_ADDR", "AA:BB:CC:DD:EE:FF")  # set XIM4_ADDR to your XIM4 bdaddr
CH = 1
TS = sys.argv[1] if len(sys.argv) > 1 else "backup"

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

def main():
    print("waiting for XIM4 to be connectable — PUSH THE PAIR BUTTON now (retrying 40s)...")
    s = None
    for attempt in range(40):
        try:
            s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
            s.settimeout(4); s.connect((ADDR, CH)); break
        except OSError:
            s.close(); s = None; time.sleep(1)
    if s is None:
        print("could not connect — push the button and retry"); return
    print(">>> CONNECTED <<<")
    s.send(HANDSHAKE); s.settimeout(1.8)     # drain handshake fully
    try:
        while True:
            if not s.recv(2048): break
    except socket.timeout:
        pass

    cnt_raw = xact(s, 0x33)
    cnt = struct.unpack_from("<I", cnt_raw, 8)[0] if len(cnt_raw) >= 12 else 0
    print("config count (0x33): %d  (raw=%s)" % (cnt, cnt_raw.hex()))
    N = cnt if 0 < cnt <= 64 else 30       # fallback: scan a fixed range if count parse failed

    backup = {"ts": TS, "count": cnt, "list": {}, "read0a": {}}
    for i in range(N):
        backup["list"][i] = xact(s, 0x32, struct.pack("<I", i)).hex()
    print("enumerated %d configs via 0x32" % len(backup["list"]))

    for i in range(N):
        r = xact(s, 0x0a, struct.pack("<I", i), window=1.5)
        backup["read0a"][i] = r.hex()
        nm = r[12:56].split(b"\x00")[0].decode("latin1", "ignore") if len(r) >= 60 else ""
        print("  cfg %2d: 0x0a -> %4d bytes  %s" % (i, len(r), nm))

    import os
    out = os.path.expanduser("~/xim_backup_%s.json" % TS)
    json.dump(backup, open(out, "w"))
    print("SAVED:", out)
    s.close()

main()
