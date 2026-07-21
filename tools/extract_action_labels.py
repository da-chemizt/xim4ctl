#!/usr/bin/env python3
"""Extract the per-game action-label map (and box art) from the XIM4 .ximmr.

Standalone RE tool — writes JSON + optional cover images, never touches the web UI.
See docs/XIMR_FORMAT.md for the full format. Output map is keyed by gameUID (== the
device config's gameUID field == the DB owner id 0x1000+k), which uniquely identifies a
title and survives config renames/clones.

Usage:
    python3 extract_action_labels.py <XIMR.ximmr> [--json out.json] [--covers dir/]

Output JSON shape:
    { "<gameUID>": { "name": str,
                     "RT": "Fire", "LT": "Aim Down Sight", ..., "Guide": "Guide",
                     "byPlatform": { "<platformIndex>": { "<slot>": "<override>" } } } }
`byPlatform` is present only when a platform's bank diverges from the common layout.
"""
import argparse
import json
import os
import re
import struct

DIR_OFF = 16
NAME_RES = 0x0073
ART_RES = 0x0075
SLOT0_RES = 0x9f
BTN_ORDER = ["RT", "LT", "RS", "LS", "RB", "LB", "A", "B", "X", "Y",
             "Up", "Down", "Right", "Left", "Start", "Back", "Guide"]
# config platformIndex -> bank byte (bank = platform*4); XIM4 outputs these five
PLATFORM_BANK = {0: 0x00, 1: 0x04, 2: 0x08, 3: 0x0c, 4: 0x18}
ALL_BANKS = (0x00, 0x04, 0x08, 0x0c, 0x10, 0x14, 0x18)


def read_directory(data):
    count = struct.unpack_from("<I", data, 12)[0]
    base = DIR_OFF + count * 8
    dirmap = {}
    for i in range(count):
        rid, off = struct.unpack_from("<II", data, DIR_OFF + 8 * i)
        dirmap.setdefault(rid >> 16, {})[rid & 0xffff] = off
    return dirmap, base


def _cstr(data, base, off, maxlen=128):
    if off is None:
        return None
    o = base + off
    end = data.find(b"\x00", o, o + maxlen)
    if end < 0:
        return None
    try:
        return data[o:end].decode("utf-8")
    except UnicodeDecodeError:
        return None


def _img_type(b):
    if b[:3] == b"\xff\xd8\xff":
        return "jpg"
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    return "bin"


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def action_labels(data):
    dirmap, base = read_directory(data)
    out = {}
    for owner, res in sorted(dirmap.items()):
        if not (0x1000 <= owner < 0x2000):
            continue
        name = _cstr(data, base, res.get(NAME_RES))
        if not name:
            continue
        per_bank = {}
        for bank in ALL_BANKS:
            slots = [_cstr(data, base, res.get((bank << 8) | (SLOT0_RES + i)))
                     for i in range(17)]
            if all(s is not None for s in slots):
                per_bank[bank] = slots
        if not per_bank:
            continue
        common = max(per_bank.values(),
                     key=lambda v: sum(1 for w in per_bank.values() if w == v))
        entry = {"name": name}
        entry.update({BTN_ORDER[i]: common[i] for i in range(17)})
        by_platform = {}
        for pidx, bank in PLATFORM_BANK.items():
            slots = per_bank.get(bank)
            if slots and slots != common:
                by_platform[str(pidx)] = {BTN_ORDER[i]: slots[i]
                                          for i in range(17) if slots[i] != common[i]}
        if by_platform:
            entry["byPlatform"] = by_platform
        out[str(owner)] = entry
    return out


def extract_covers(data, covers_dir):
    dirmap, base = read_directory(data)
    os.makedirs(covers_dir, exist_ok=True)
    out = {}
    for owner, res in sorted(dirmap.items()):
        if not (0x1000 <= owner < 0x2000):
            continue
        name = _cstr(data, base, res.get(NAME_RES))
        aoff = res.get(ART_RES)
        if aoff is None or not name:
            continue
        o = base + aoff
        ln = struct.unpack_from("<I", data, o)[0]
        img = data[o + 4:o + 4 + ln]
        fn = f"{owner}-{_slug(name)}.{_img_type(img)}"
        open(os.path.join(covers_dir, fn), "wb").write(img)
        out[str(owner)] = fn
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ximmr")
    ap.add_argument("--json")
    ap.add_argument("--covers")
    args = ap.parse_args()
    data = open(args.ximmr, "rb").read()
    labels = action_labels(data)
    print(f"games with action labels: {len(labels)}")
    if args.json:
        json.dump(labels, open(args.json, "w"), indent=1)
        print("wrote", args.json)
    if args.covers:
        covers = extract_covers(data, args.covers)
        print(f"covers: {len(covers)} -> {args.covers}")


if __name__ == "__main__":
    main()
