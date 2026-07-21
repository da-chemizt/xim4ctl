#!/usr/bin/env python3
"""Extract per-game cover art from the XIM4 game DB (.ximmr). See docs/XIMR_FORMAT.md.

The .ximmr embeds ~468 images as a packed stream of [size:u32][image] records
(JPEG or PNG), starting at the first size-prefixed image (~offset 14.6M). The first
63 entries are UI/default icons (reticle, XIM logo, controller buttons, platform
logos); entry 63 onward are game covers in ASCENDING-gameUID order (≈ database
insertion / chronological order).

gameUID is per-ENGINE, not per-game (e.g. Zombie Army 4 and Sniper Elite V4 share
0x1123 but have different covers), so the reliable key is the game NAME; covers are
simply laid out in uid order. STREAM_MAP maps names to stream indices; use `--all`
to dump every image by index and match names to any additional titles.

Usage:
  python3 extract_covers.py <XIMR.ximmr> <out_dir> [--all]
    default: extract the mapped game covers named by slug
    --all:    dump every image as <index>.<ext>
"""
import os, re, struct, sys, json

FIRST_IMAGE = 14602112          # offset of the first [size][image] record
LEADING_ICONS = 63              # entries 0..62 are UI/default icons

# game name -> stream index (verified by matching rendered images to titles).
STREAM_MAP = {
    "Crysis 2": 71,
    "Bioshock Infinite": 162,
    "Alien: Isolation": 197,
    "Dying Light": 207,
    "Rainbow Six Siege": 224,
    "Far Cry Primal": 226,
    "No Man's Sky": 239,
    "Resident Evil 7": 255,
    "Sniper Elite V4": 259,
    "Prey": 265,
    "Strange Brigade": 298,
    "Days Gone": 315,
    "World War Z": 317,
    "Zombie Army 4: Dead War": 338,
    "Hitman 3": 350,
    "Mass Effect: Legendary Edition (ME1)": 356,
    "Chivalry 2": 361,
    "Far Cry 6": 366,
    "Battlefield 2042": 371,
    "Dead Space (2023)": 395,
}


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def img_type(data, o):
    if data[o:o + 3] == b"\xff\xd8\xff":
        return "jpg"
    if data[o:o + 8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    return None


def read_stream(data):
    """Walk the packed [size:u32][image] stream; return list of (offset,size,type)."""
    out, o, N = [], FIRST_IMAGE, len(data)
    while o < 24_960_000 - 8:
        sz = struct.unpack_from("<I", data, o)[0]
        t = img_type(data, o + 4)
        if t and 100 <= sz <= 300000 and o + 4 + sz <= N:
            out.append((o + 4, sz, t))
            o = o + 4 + sz
            while o < N - 8 and img_type(data, o + 4) is None:  # skip alignment padding
                o += 1
        else:
            o += 1
    return out


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(1)
    data = open(sys.argv[1], "rb").read()
    out_dir = sys.argv[2]
    os.makedirs(out_dir, exist_ok=True)
    stream = read_stream(data)
    if len(stream) < 400:
        print(f"warning: only {len(stream)} images found (expected ~468)")

    if "--all" in sys.argv:
        for i, (off, sz, t) in enumerate(stream):
            open(os.path.join(out_dir, f"{i:03d}.{t}"), "wb").write(data[off:off + sz])
        print(f"dumped {len(stream)} images to {out_dir}")
        return

    manifest = {}
    for name, idx in STREAM_MAP.items():
        off, sz, t = stream[idx]
        fn = f"{slug(name)}.{t}"
        open(os.path.join(out_dir, fn), "wb").write(data[off:off + sz])
        manifest[name] = fn
    json.dump(manifest, open(os.path.join(out_dir, "manifest.json"), "w"), indent=1)
    print(f"extracted {len(manifest)} covers to {out_dir}")


if __name__ == "__main__":
    main()
