#!/usr/bin/env python3
"""XIM4 switch active config — the auto-switcher core. Usage: xim_switch.py <config_index>."""
import socket, struct, sys, time, os

ADDR = os.environ.get("XIM4_ADDR", "AA:BB:CC:DD:EE:FF")  # set XIM4_ADDR to your XIM4 bdaddr
CH = 1
IDX = int(sys.argv[1])

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

def main():
    s = None
    for _ in range(30):
        try:
            s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
            s.settimeout(4); s.connect((ADDR, CH)); break
        except OSError:
            s.close(); s = None; time.sleep(1)
    if s is None:
        print("could not connect"); return
    print(">>> connected <<<")
    s.send(HANDSHAKE); s.settimeout(1.5)
    try:
        while s.recv(2048): pass
    except socket.timeout:
        pass
    s.send(build(0x29, 0x0200, struct.pack("<I", IDX)))
    s.settimeout(2); r = b""
    try:
        while True:
            c = s.recv(1024)
            if not c: break
            r += c
    except socket.timeout:
        pass
    print("switch to config %d -> resp: %s" % (IDX, r.hex()))
    s.close()

main()
