#!/usr/bin/env python3
"""Extract XIM4 artwork (button icons + game covers) from the .ximmr into the web UI.

The .ximmr embeds ~468 images as a packed [size:u32][image] stream (~offset 14.6M):
  index 0..62   = UI / default icons (reticle, XIM logo, controller buttons, platform
                  glyphs) grouped by platform.
  index 63..    = game covers in ASCENDING-gameUID (≈ database) order.
Covers are keyed by game NAME (gameUID is per-engine, not per-game); the name→index map
below was verified by matching the rendered images to their titles.

Usage: python3 build_assets.py <XIMR.ximmr> <frontend_assets_dir>
"""
import json, os, re, struct, sys

FIRST_IMAGE = 14602112

# game name -> stream index
COVERS = {
    "Crysis 2": 71, "Bioshock Infinite": 162, "Alien: Isolation": 197, "Dying Light": 207,
    "Rainbow Six Siege": 224, "Far Cry Primal": 226, "No Man's Sky": 239, "Resident Evil 7": 255,
    "Sniper Elite V4": 259, "Prey": 265, "Strange Brigade": 298, "Days Gone": 315,
    "World War Z": 317, "Zombie Army 4: Dead War": 338, "Hitman 3": 350,
    "Mass Effect: Legendary Edition (ME1)": 356, "Chivalry 2": 361, "Far Cry 6": 366,
    "Battlefield 2042": 371, "Dead Space (2023)": 395,
}

# stream index of each icon in the 0..62 UI block
ICON = {
    "reticle": 0, "logo": 1, "controller": 2,
    # platform logos
    "pl_xboxone": 3, "pl_ps4": 21, "pl_xbox360": 40, "pl_ps3": 50,
    "pl_xboxseries": 59, "pl_ps5": 61, "pl_pc": 62,
    # Xbox One
    "xb_RT": 4, "xb_LT": 5, "xb_RS": 6, "xb_LS": 7, "xb_RB": 8, "xb_LB": 9,
    "xb_A": 10, "xb_B": 11, "xb_X": 12, "xb_Y": 13,
    "xb_Up": 14, "xb_Down": 15, "xb_Left": 16, "xb_Right": 17,
    "xb_Menu": 18, "xb_View": 19, "xb_Guide": 20,
    # PS4
    "ps_R2": 22, "ps_L2": 23, "ps_R3": 24, "ps_L3": 25, "ps_R1": 26, "ps_L1": 27,
    "ps_Cross": 28, "ps_Circle": 29, "ps_Square": 30, "ps_Triangle": 31,
    "ps_Up": 32, "ps_Down": 33, "ps_Left": 34, "ps_Right": 35,
    "ps_Options": 36, "ps_Touchpad": 37, "ps_PS": 38, "ps_Share": 39,
}

# config's 17-button slot order -> icon name, per platform (0 Xbox One, 1 PS4).
# XIM4 only outputs Xbox-One-class and PS4-class controllers; newer consoles map onto these.
BTN_ORDER = ["RT", "LT", "RS", "LS", "RB", "LB", "A", "B", "X", "Y",
             "Up", "Down", "Right", "Left", "Start", "Back", "Guide"]
BUTTON_ICONS = {
    0: {"RT": "xb_RT", "LT": "xb_LT", "RS": "xb_RS", "LS": "xb_LS", "RB": "xb_RB", "LB": "xb_LB",
        "A": "xb_A", "B": "xb_B", "X": "xb_X", "Y": "xb_Y",
        "Up": "xb_Up", "Down": "xb_Down", "Right": "xb_Right", "Left": "xb_Left",
        "Start": "xb_Menu", "Back": "xb_View", "Guide": "xb_Guide"},
    1: {"RT": "ps_R2", "LT": "ps_L2", "RS": "ps_R3", "LS": "ps_L3", "RB": "ps_R1", "LB": "ps_L1",
        "A": "ps_Cross", "B": "ps_Circle", "X": "ps_Square", "Y": "ps_Triangle",
        "Up": "ps_Up", "Down": "ps_Down", "Right": "ps_Right", "Left": "ps_Left",
        "Start": "ps_Options", "Back": "ps_Share", "Guide": "ps_PS"},
}

# platform-appropriate display label per button slot
BUTTON_LABELS = {
    0: {b: b for b in BTN_ORDER},  # Xbox uses the canonical slot names
    1: {"RT": "R2", "LT": "L2", "RS": "R3", "LS": "L3", "RB": "R1", "LB": "L1",
        "A": "✕", "B": "○", "X": "□", "Y": "△",
        "Up": "Up", "Down": "Down", "Right": "Right", "Left": "Left",
        "Start": "Options", "Back": "Share", "Guide": "PS"},
}

# platform badge: colour + logo icon (XIM only outputs Xbox-One- and PS4-class;
# newer consoles map onto these, so PS5->PS blue, Series->Xbox green).
PLATFORMS = {
    0: {"name": "Xbox One", "color": "#16a34a", "icon": "pl_xboxone"},
    1: {"name": "PS4",      "color": "#2f6fed", "icon": "pl_ps4"},
    2: {"name": "Xbox 360", "color": "#16a34a", "icon": "pl_xbox360"},
    3: {"name": "PS3",      "color": "#2f6fed", "icon": "pl_ps3"},
    4: {"name": "PC",       "color": "#6b7280", "icon": "pl_pc"},
}


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def img_type(data, o):
    if data[o:o + 3] == b"\xff\xd8\xff":
        return "jpg"
    if data[o:o + 8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    return None


def read_stream(data):
    out, o, N = [], FIRST_IMAGE, len(data)
    while o < 24_960_000 - 8:
        sz = struct.unpack_from("<I", data, o)[0]
        t = img_type(data, o + 4)
        if t and 100 <= sz <= 300000 and o + 4 + sz <= N:
            out.append((o + 4, sz, t)); o = o + 4 + sz
            while o < N - 8 and img_type(data, o + 4) is None:
                o += 1
        else:
            o += 1
    return out


def main():
    if len(sys.argv) < 3:
        print(__doc__); raise SystemExit(1)
    data = open(sys.argv[1], "rb").read()
    base = sys.argv[2]
    icons_dir = os.path.join(base, "icons"); covers_dir = os.path.join(base, "covers")
    os.makedirs(icons_dir, exist_ok=True); os.makedirs(covers_dir, exist_ok=True)
    stream = read_stream(data)
    assert len(stream) >= 460, f"only {len(stream)} images found"

    icon_files = {}
    for name, idx in ICON.items():
        off, sz, t = stream[idx]
        fn = f"{name}.{t}"
        open(os.path.join(icons_dir, fn), "wb").write(data[off:off + sz])
        icon_files[name] = f"icons/{fn}"

    cover_files = {}
    for name, idx in COVERS.items():
        off, sz, t = stream[idx]
        fn = f"{slug(name)}.{t}"
        open(os.path.join(covers_dir, fn), "wb").write(data[off:off + sz])
        cover_files[name] = f"covers/{fn}"

    # per-game action labels (produced by the standalone tools/extract_action_labels.py,
    # keyed by gameUID = directory owner id = config gameUID). Folded in if present.
    action_labels = {}
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in ("work/re-actions/action_labels.json",
                 os.path.join(here, "..", "work", "re-actions", "action_labels.json")):
        if os.path.exists(cand):
            action_labels = json.load(open(cand))
            break

    manifest = {
        "icons": icon_files,
        "covers": cover_files,
        "buttonIcons": {str(p): {b: icon_files[BUTTON_ICONS[p][b]] for b in BTN_ORDER}
                        for p in BUTTON_ICONS},
        "buttonLabels": {str(p): BUTTON_LABELS[p] for p in BUTTON_LABELS},
        "platforms": {str(p): {"name": v["name"], "color": v["color"],
                               "icon": icon_files.get(v["icon"])}
                      for p, v in PLATFORMS.items()},
        "actionLabels": action_labels,
    }
    json.dump(manifest, open(os.path.join(base, "manifest.json"), "w"), indent=1)
    print(f"icons: {len(icon_files)}  covers: {len(cover_files)}  "
          f"actionLabels: {len(action_labels)}  -> {base}")


if __name__ == "__main__":
    main()
