#!/usr/bin/env python3
"""Extract the XIM4 aim-translator catalog from the .ximmr game DB.

Each game/platform carries up to four translator blobs (directory items):
    0x8a = Hip (primary)   0x8b = ADS (primary)
    0x8c = Hip (alt)       0x8d = ADS (alt)
keyed  (owner<<16) | (platform<<10) | item,  owner = 0x1000+k (== the config's
gameUID), platform 0..6 (Xbox One, PS4, Xbox 360, PS3, Xbox Series, PS5, PC).

Every blob is exactly 5504 bytes: a 48-byte header (a 14-ish-char ASCII label,
e.g. "R6:S-Hip-X1.12" = <gameCode>-<Hip|ADS>-<platCode><ver>, zero-padded) then
5456 bytes of encrypted body (~7.95 bit/byte, 16-aligned; a block cipher — the
key lives in libManager, see docs/XIMR_FORMAT.md). Series/PS5/PC banks usually
alias the One/PS4/Xbox blob (identical offset), which is why 5756 references
resolve to only ~2528 distinct blobs.

This tool decodes the plaintext labels (works today) and can dump the raw
encrypted bodies for offline cryptanalysis. It never modifies the .ximmr.

Usage:
    python3 extract_translators.py <XIMR.ximmr> [--json out.json] [--dump dir/]
"""
import argparse
import collections
import json
import struct

BLOB_LEN = 5504
HDR_LEN = 48
DIR_OFF = 16
NAME_RES = 0x73
TR_ITEMS = {0x8a: "hip", 0x8b: "ads", 0x8c: "hip_alt", 0x8d: "ads_alt"}
PLATFORMS = {0: "Xbox One", 1: "PS4", 2: "Xbox 360", 3: "PS3",
             4: "Xbox Series", 5: "PS5", 6: "PC"}


def load_dir(data):
    count = struct.unpack_from("<I", data, 12)[0]
    base = DIR_OFF + count * 8
    dmap, offs = {}, set()
    for i in range(count):
        rid, off = struct.unpack_from("<II", data, DIR_OFF + 8 * i)
        dmap[rid] = off
        offs.add(off)
    return dmap, base


def cstr(data, base, off, maxlen=64):
    if off is None:
        return None
    o = base + off
    end = data.find(b"\x00", o, o + maxlen)
    return data[o:end].decode("latin1", "replace") if end >= 0 else None


def key(owner, plat, item):
    return (owner << 16) | (plat << 10) | item


def catalog(data):
    dmap, base = load_dir(data)
    games = {}
    distinct = set()
    for k in range(437):
        owner = 0x1000 + k
        name = cstr(data, base, dmap.get(key(owner, 0, NAME_RES)))
        if not name:
            continue
        plats = {}
        for p, pname in PLATFORMS.items():
            slots = {}
            for item, role in TR_ITEMS.items():
                off = dmap.get(key(owner, p, item))
                if off is None:
                    continue
                o = base + off
                label = data[o:data.find(b"\x00", o, o + HDR_LEN)].decode("latin1", "replace")
                slots[role] = {"label": label, "offset": off, "shared": off in distinct}
                distinct.add(off)
            if slots:
                plats[pname] = slots
        if plats:
            games[str(owner)] = {"gameUID": owner, "k": k, "name": name, "platforms": plats}
    return games, len(distinct)


def parse_label(label):
    """"R6:S-Hip-X1.12" -> ("R6:S", "Hip", "X1", "12")  (best-effort)."""
    try:
        head, plat_ver = label.rsplit("-", 1)
        code, mode = head.rsplit("-", 1)
        plat = plat_ver.split(".", 1)[0]
        ver = plat_ver.split(".", 1)[1] if "." in plat_ver else ""
        return code, mode, plat, ver
    except ValueError:
        return None, None, None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ximmr")
    ap.add_argument("--json", help="write the catalog as JSON")
    ap.add_argument("--dump", help="dump raw encrypted blobs into this dir (one file per distinct blob)")
    args = ap.parse_args()

    data = open(args.ximmr, "rb").read()
    games, ndistinct = catalog(data)
    nrefs = sum(len(s) for g in games.values() for s in g["platforms"].values())
    print(f"games with translators: {len(games)}  refs: {nrefs}  distinct blobs: {ndistinct}")

    codes = collections.Counter()
    for g in games.values():
        for slots in g["platforms"].values():
            for s in slots.values():
                _, _, plat, _ = parse_label(s["label"])
                if plat:
                    codes[plat] += 1
    print("platform codes in labels:", dict(codes))

    if args.json:
        json.dump(games, open(args.json, "w"), indent=1)
        print("wrote", args.json)

    if args.dump:
        import os
        os.makedirs(args.dump, exist_ok=True)
        dmap, base = load_dir(data)
        seen = set()
        for g in games.values():
            for slots in g["platforms"].values():
                for s in slots.values():
                    off = s["offset"]
                    if off in seen:
                        continue
                    seen.add(off)
                    o = base + off
                    open(os.path.join(args.dump, f"{off:08x}_{s['label'].replace(':','_').replace('/','_')}.bin"),
                         "wb").write(data[o:o + BLOB_LEN])
        print(f"dumped {len(seen)} distinct blobs -> {args.dump}")


if __name__ == "__main__":
    main()
