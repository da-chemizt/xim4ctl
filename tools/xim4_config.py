#!/usr/bin/env python3
"""XIM4 config codec — parse/author the 452-byte config-with-setting wire blob.
Layout (frame offsets; frame = [crc4][cmd2][seq2][idx4][payload440]):
  12   config name (48B, null-padded)
  66   SETTING base:  +0x00 setting name(24) +0x34 sensitivity(u16 ×100) +0x36 yxRatio(u16)
       +0x38 boost(u16) +0xCC joystickDeadZone(u16) +0xF8..+0x118 17 primary button codes(u16)
       +0x13C..+0x15C 17 secondary button codes(u16). Ballistic curve = 20 raw bytes near +0x3d.
Input codes: keyboard=0x6000|(hid>>3<<8)|(1<<(hid&7)); mouse=0x4000|mask(L1 R2 M4); wheel=0xa000|(up4 dn8)."""
import struct
from xim4_frame import build  # for emitting a 0x15 write frame

# --- USB HID usage IDs (Keyboard/Keypad page 0x07) ---
HID = {**{c: 0x04+i for i,c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ")},
       **{str((i+1)%10): 0x1E+i for i in range(10)},
       "Enter":0x28,"Esc":0x29,"Backspace":0x2A,"Tab":0x2B,"Space":0x2C,"Minus":0x2D,
       "Equal":0x2E,"LBracket":0x2F,"RBracket":0x30,"Backslash":0x31,"Semicolon":0x33,
       "Quote":0x34,"Grave":0x35,"Comma":0x36,"Period":0x37,"Slash":0x38,"CapsLock":0x39,
       **{f"F{i+1}":0x3A+i for i in range(12)},
       "Pause":0x48,"Insert":0x49,"Home":0x4A,"PageUp":0x4B,"Delete":0x4C,"End":0x4D,"PageDown":0x4E,
       "Right":0x4F,"Left":0x50,"Down":0x51,"Up":0x52,
       "LCtrl":0xE0,"LShift":0xE1,"LAlt":0xE2,"LGui":0xE3,"RCtrl":0xE4,"RShift":0xE5,"RAlt":0xE6}

def kb(key):    u=HID[key]; return 0x6000 | ((u>>3)<<8) | (1<<(u&7))
MOUSE={"LMB":0x4001,"RMB":0x4002,"MMB":0x4004,"Mouse4":0x4008,"Mouse5":0x4010}
WHEEL={"WheelUp":0xa004,"WheelDown":0xa008}

def code(name):
    if name in MOUSE: return MOUSE[name]
    if name in WHEEL: return WHEEL[name]
    return kb(name)

_HID_REV={v:k for k,v in HID.items()}
def decode(c):
    if c==0: return None
    for k,v in {**MOUSE,**WHEEL}.items():
        if v==c: return k
    if 0x6000 <= c < 0x8000:              # keyboard bitmap (byte index 0..31 -> 0x60xx..0x7fxx)
        byte=(c>>8)-0x60; bit=c&0xff
        usage=byte*8 + (bit.bit_length()-1)
        return _HID_REV.get(usage, f"HID:{usage:#x}")
    return f"?{c:#06x}"

# controller-button order in the setting struct (primary code array @base+0xf8)
BTN_ORDER=["RT","LT","RS","LS","RB","LB","A","B","X","Y","Up","Down","Right","Left","Start","Back","Guide"]
SB=66  # setting base (frame offset)

# beacon (shell LED) = palette index @ frame64. 0..15. Lower confirmed, upper approx from user's cycle.
BEACON={0:"red",1:"green",2:"blue",3:"yellow",4:"magenta",5:"cyan",6:"white",
        7:"darkgreen",8:"purple",9:"orange",10:"red2?",11:"bluishpurple",12:"kiwi",13:"eggyolk",14:"lightblue"}

def parse(frame: bytes) -> dict:
    p={"name": frame[12:12+48].split(b'\0')[0].decode('latin1'),
       "beacon": BEACON.get(frame[64], f"idx{frame[64]}"),
       "setting": frame[SB:SB+24].split(b'\0')[0].decode('latin1'),
       "sensitivity": struct.unpack_from('<H',frame,SB+0x34)[0]/100.0,
       "yxRatio": struct.unpack_from('<H',frame,SB+0x36)[0]/100.0,
       "boost": struct.unpack_from('<H',frame,SB+0x38)[0],
       "deadzone": struct.unpack_from('<H',frame,SB+0xCC)[0],
       "pushToTalkKey": decode(struct.unpack_from('<H',frame,376)[0]),
       "curve": [b/2.0 for b in frame[127:147]],   # ballistic curve: byte = multiplier ×2 (0.5 steps)
       "buttons": {}}
    for i,b in enumerate(BTN_ORDER):
        c=struct.unpack_from('<H',frame,SB+0xF8+i*2)[0]
        if c: p["buttons"][b]=decode(c)
    return p

if __name__=='__main__':
    import sys
    if len(sys.argv) < 2:
        print("usage: python3 xim4_config.py <config-frame-hex | path-to-hex-file>")
        print("  parses a 452-byte 0x0a/0x15 config page and prints its fields")
        raise SystemExit(1)
    arg = sys.argv[1]
    try:
        hx = open(arg).read().strip()
    except OSError:
        hx = arg.strip()
    frame = bytes.fromhex(hx)
    for k, v in parse(frame).items():
        print(f"{k}: {v}")
