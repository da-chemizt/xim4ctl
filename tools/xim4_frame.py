#!/usr/bin/env python3
"""XIM4 RFCOMM frame builder.
Frame = [crc:4 LE][cmd:2 LE][seq:2 LE][payload]. crc = CRC-32 (poly 0xEDB88320) over the body
(cmd+seq+payload), with init=0x000000FF (not the usual 0xFFFFFFFF) and xorout=0xFFFFFFFF."""
import struct, os
_TBL = list(struct.unpack('<256I', open(os.path.join(os.path.dirname(__file__),'crc32table.bin'),'rb').read()))

def gen_crc(body: bytes) -> int:
    crc = 0xFF
    for b in body:
        crc = (_TBL[(crc ^ b) & 0xff] ^ (crc >> 8)) & 0xffffffff
    return (~crc) & 0xffffffff

def build(cmd: int, seq: int, payload: bytes = b'') -> bytes:
    body = struct.pack('<HH', cmd & 0xffff, seq & 0xffff) + payload
    return struct.pack('<I', gen_crc(body)) + body

def activate_config(index: int, seq: int) -> bytes:
    """cmd 0x0029 — switch active config to `index`."""
    return build(0x0029, seq, struct.pack('<I', index))

if __name__ == '__main__':
    # self-test against a captured frame
    assert build(0x0029, 0x0044, struct.pack('<I',0)).hex() == '1ec844ab2900440000000000', 'CRC self-test FAILED'
    print('self-test OK. activate_config(2, 0x00aa) =', activate_config(2,0x00aa).hex())
