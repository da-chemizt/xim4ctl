#!/usr/bin/env python3
"""XIM4 Pi client — connect over RFCOMM, handshake, and drive the device.
Usage: python3 xim_pi.py [channel]  (default channel 1 = DLCI 2)."""
import socket, struct, sys, time, os

ADDR = os.environ.get("XIM4_ADDR", "AA:BB:CC:DD:EE:FF")  # set XIM4_ADDR to your XIM4 bdaddr
CH   = int(sys.argv[1]) if len(sys.argv) > 1 else 1

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

# self-test the CRC against a known captured 0x29 frame
assert build(0x29, 0x44, struct.pack("<I", 0)) == bytes.fromhex("1ec844ab2900440000000000"), "CRC self-test FAILED"
print("CRC self-test OK")

def recvall(s, t=3.0):
    s.settimeout(t); data = b""
    try:
        while True:
            c = s.recv(1024)
            if not c: break
            data += c
            if len(c) < 1024: break
    except socket.timeout:
        pass
    return data

def main():
    s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
    s.settimeout(20)
    print("connecting to %s channel %d ..." % (ADDR, CH))
    s.connect((ADDR, CH))
    print(">>> RFCOMM CONNECTED <<<")
    s.send(HANDSHAKE); print("sent handshake (%d bytes)" % len(HANDSHAKE))
    r = recvall(s)
    print("handshake resp (%d bytes): %s" % (len(r), r.hex()))
    if len(r) >= 9:
        fw = r[9:].split(b"\x00")[0].decode("latin1", "ignore")
        print("   >>> DEVICE FIRMWARE: %s <<<" % fw)
    time.sleep(0.3)
    s.send(build(0x0033, 0x0002)); print("sent game-count query (0x33)")
    print("count resp: %s" % recvall(s).hex())
    s.close(); print("done.")

main()
