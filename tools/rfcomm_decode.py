#!/usr/bin/env python3
"""Extract RFCOMM application payloads (the XIM4 wire protocol) from a btsnoop capture.
Parses btsnoop -> HCI H4 -> ACL (with fragmentation reassembly) -> L2CAP -> RFCOMM UIH.
Usage: rfcomm_decode.py <file.btsnoop>
"""
import sys, struct

def records(data):
    # btsnoop header: 'btsnoop\0' + u32 version + u32 datalink
    assert data[:8] == b'btsnoop\x00', "not a btsnoop file"
    off = 16
    while off + 24 <= len(data):
        olen, ilen, flags, drops, ts = struct.unpack('>IIIIq', data[off:off+24])
        off += 24
        pkt = data[off:off+ilen]; off += ilen
        yield flags, ts, pkt

def main(path):
    data = open(path, 'rb').read()
    # ACL reassembly buffers per connection handle
    acc = {}   # handle -> (bytes_remaining_total, buffer)
    frames = []
    for flags, ts, pkt in records(data):
        if not pkt: continue
        htype = pkt[0]
        if htype != 0x02: continue          # ACL only
        recv = flags & 0x01                  # 1 = controller->host (from XIM4)
        handle_pb = struct.unpack('<H', pkt[1:3])[0]
        handle = handle_pb & 0x0FFF
        pb = (handle_pb >> 12) & 0x3         # 0b10 first, 0b01 continuation
        acl_len = struct.unpack('<H', pkt[3:5])[0]
        payload = pkt[5:5+acl_len]
        if pb == 0x1:                        # continuation
            if handle in acc:
                acc[handle][1].extend(payload)
        else:                                # first fragment (0b10 or 0b00)
            acc[handle] = [None, bytearray(payload)]
        buf = acc.get(handle, [None, bytearray()])[1]
        # need at least 4 bytes for L2CAP header
        while len(buf) >= 4:
            l2len, cid = struct.unpack('<HH', buf[0:4])
            if len(buf) < 4 + l2len:
                break                        # wait for more fragments
            l2pay = bytes(buf[4:4+l2len])
            del buf[0:4+l2len]
            handle_frame(frames, recv, ts, cid, l2pay)
    # optional filters: --cmd XXXX (hex LE opcode), --full (untruncated hex)
    want_cmd = None
    if '--cmd' in sys.argv:
        want_cmd = sys.argv[sys.argv.index('--cmd')+1].lower()
    full = '--full' in sys.argv
    print(f"{'DIR':4} {'cmd':>4} {'seq':>4} {'len':>4}  hex / ascii")
    for d in frames:
        recv, ts, dlci, info = d
        arrow = 'XIM>' if recv else '>XIM'
        cmd = info[4:6][::-1].hex() if len(info) >= 6 else '----'
        seq = info[6:8][::-1].hex() if len(info) >= 8 else '----'
        if want_cmd and cmd != want_cmd:
            continue
        hx = info.hex()
        asc = ''.join(chr(b) if 32 <= b < 127 else '.' for b in info)
        hxout = hx if full else hx[:80]
        print(f"{arrow} {cmd:>4} {seq:>4} {len(info):>4}  {hxout} |{asc[:40] if not full else asc}")

FTYPES = {0x2f: 'SABM', 0x63: 'UA', 0x43: 'DM', 0x0f: 'DISC', 0xef: 'UIH'}
VERBOSE = '-v' in sys.argv

def handle_frame(frames, recv, ts, cid, l2pay):
    # RFCOMM runs on dynamic CIDs; control CIDs (<0x40) are signaling/etc -> skip
    if cid < 0x40:
        return
    if len(l2pay) < 3:
        return
    addr = l2pay[0]; ctrl = l2pay[1]
    dlci = addr >> 2
    ftype = ctrl & 0xEF                      # mask P/F bit
    if VERBOSE:
        arrow = 'XIM>' if recv else '>XIM'
        print(f"{arrow} DLCI={dlci:<3} {FTYPES.get(ftype, hex(ftype)):5} raw={l2pay.hex()[:60]}")
    # UIH frame = 0xEF ; only care about UIH with data on non-zero DLCI
    if ftype != 0xEF:
        return
    # length field: EA bit
    ln = l2pay[2]
    if ln & 1:
        length = ln >> 1; idx = 3
    else:
        length = (l2pay[3] << 7) | (ln >> 1); idx = 4
    pf = (ctrl >> 4) & 1
    if pf:                                   # credit-based flow: 1 credit byte
        idx += 1
    info = l2pay[idx:idx+length]
    if dlci == 0 or not info:                # DLCI 0 = RFCOMM control channel
        return
    frames.append((recv, ts, dlci, info))

if __name__ == '__main__':
    main(sys.argv[1])
