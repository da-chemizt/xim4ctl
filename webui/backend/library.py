#!/usr/bin/env python3
"""Config library — external, unlimited storage of XIM4 configs.

Each library entry keeps the device's real 8 pages (the editable *template*) plus
cached metadata. Parsed/editable views are computed on demand with the codec, and
edits are written back through the codec's surgical author. Persisted as one JSON
file so it survives restarts and can seed from an existing full backup.
"""
import json
import os
import threading

import xim_codec as C


def parse_meta(hexblob):
    """Parse a 0x0032 metadata record (name@8, gameUID@-4, beacon@-2, platform@-1)."""
    f = bytes.fromhex(hexblob) if isinstance(hexblob, str) else hexblob
    name = f[8:].split(b"\x00")[0].decode("latin1", "ignore")
    gameUID = int.from_bytes(f[-4:-2], "little")
    beacon = f[-2]
    platform = f[-1]
    return {"name": name, "gameUID": gameUID,
            "beacon": C.BEACON.get(beacon, f"idx{beacon}"), "beaconIndex": beacon,
            "platform": C.PLATFORM.get(platform, f"idx{platform}"), "platformIndex": platform}


class ConfigLibrary:
    def __init__(self, path):
        self.path = path
        self._lock = threading.RLock()
        # slot(str) -> {"pages": [hex,...], "meta": {...}, "title": str}
        self.slots = {}
        # game/title name -> slot index, for auto-switch
        self.title_map = {}
        self.load()

    # -- persistence ----------------------------------------------------------
    def load(self):
        with self._lock:
            if os.path.exists(self.path):
                data = json.load(open(self.path))
                self.slots = data.get("slots", {})
                self.title_map = data.get("title_map", {})

    def save(self):
        with self._lock:
            tmp = self.path + ".tmp"
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(tmp, "w") as f:
                json.dump({"slots": self.slots, "title_map": self.title_map}, f)
            os.replace(tmp, self.path)

    # -- seeding / syncing ----------------------------------------------------
    def seed_from_backup(self, backup_path):
        """Populate slots from a tools/xim_full_backup.py JSON if the library is empty."""
        with self._lock:
            if self.slots:
                return 0
            b = json.load(open(backup_path))
            lst = b.get("list", {})
            for idx, pages in b.get("configs", {}).items():
                meta = parse_meta(lst[idx]) if idx in lst else self._meta_from_pages(pages)
                self.slots[str(idx)] = {"pages": pages, "meta": meta, "title": meta["name"]}
            self.save()
            return len(self.slots)

    def set_slot(self, index, pages, meta=None):
        """Store/refresh a slot from freshly-read device pages (bytes or hex)."""
        with self._lock:
            hexpages = [p.hex() if isinstance(p, (bytes, bytearray)) else p for p in pages]
            meta = meta or self._meta_from_pages(hexpages)
            self.slots[str(index)] = {"pages": hexpages, "meta": meta, "title": meta["name"]}
            self.save()

    def _meta_from_pages(self, hexpages):
        cfg = C.parse_config([bytes.fromhex(h) for h in hexpages])
        return {"name": cfg["name"], "gameUID": cfg["gameUID"],
                "beacon": cfg["beacon"], "beaconIndex": cfg["beaconIndex"],
                "platform": cfg["platform"], "platformIndex": cfg["platformIndex"]}

    # -- reads ----------------------------------------------------------------
    def list_slots(self):
        with self._lock:
            out = []
            for idx in sorted(self.slots, key=lambda x: int(x)):
                s = self.slots[idx]
                out.append({"index": int(idx), "title": s.get("title", s["meta"]["name"]),
                            **s["meta"]})
            return out

    def get_pages(self, index):
        with self._lock:
            s = self.slots.get(str(index))
            return [bytes.fromhex(h) for h in s["pages"]] if s else None

    def get_parsed(self, index):
        pages = self.get_pages(index)
        return C.parse_config(pages) if pages else None

    # -- writes ---------------------------------------------------------------
    def author(self, index, edits):
        """Apply edits to a slot's template -> new 0x15 write pages. Returns
        (write_pages: list[bytes], new_hexpages: list[str]) without persisting yet."""
        with self._lock:
            template = self.get_pages(index)
            if template is None:
                raise KeyError(index)
            write_pages = C.author_config(template, edits)
            # the on-disk template becomes the reassembled edited buffer, re-framed
            new_hex = [p.hex() for p in write_pages]
            return write_pages, new_hex

    def commit(self, index, new_hexpages, title=None):
        """Persist edited pages as the new template for a slot (after a successful write)."""
        with self._lock:
            s = self.slots.setdefault(str(index), {})
            s["pages"] = new_hexpages
            s["meta"] = self._meta_from_pages(new_hexpages)
            s["title"] = title or s["meta"]["name"]
            self.save()

    # -- title map (auto-switch) ---------------------------------------------
    def set_title_map(self, mapping):
        with self._lock:
            self.title_map = dict(mapping)
            self.save()

    def slot_for_title(self, title):
        with self._lock:
            if title in self.title_map:
                return self.title_map[title]
            # fall back to a case-insensitive match on slot titles/names
            t = title.lower()
            for idx, s in self.slots.items():
                if s.get("title", "").lower() == t or s["meta"]["name"].lower() == t:
                    return int(idx)
            return None
