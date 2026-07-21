#!/usr/bin/env python3
"""xim4ctl web backend — REST + WebSocket over the RFCOMM device driver.

The device is touched lazily and serialized; the config library is the browsable
source of truth (seeded from a full backup), so the UI works even when the XIM4 is
asleep. Switch / read / write hit the device on demand.
"""
import asyncio
import os
import threading
import time
from collections import deque

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

import xim_codec as C
from library import ConfigLibrary, parse_meta
from xim_device import Xim4Device, Xim4Error

HERE = os.path.dirname(os.path.abspath(__file__))
FRONTEND = os.environ.get("XIM4_FRONTEND", os.path.join(HERE, "..", "frontend"))
LIB_PATH = os.environ.get("XIM4_LIBRARY", os.path.join(HERE, "data", "library.json"))
SEED_BACKUP = os.environ.get("XIM4_SEED_BACKUP", "")


# ---- log hub: bridge blocking-thread logs to async WebSocket subscribers -----
class LogHub:
    def __init__(self, maxlen=500):
        self.buffer = deque(maxlen=maxlen)
        self.subs = set()
        self.loop = None

    def bind(self, loop):
        self.loop = loop

    def _push(self, obj):
        self.buffer.append(obj)
        if self.loop is not None:
            self.loop.call_soon_threadsafe(self._fanout, obj)

    def log(self, msg):
        self._push({"type": "log", "t": round(time.time(), 3), "msg": str(msg)})

    def activity(self, input_name):
        self._push({"type": "activity", "input": input_name})

    def _fanout(self, obj):
        for q in list(self.subs):
            try:
                q.put_nowait(obj)
            except asyncio.QueueFull:
                pass

    async def subscribe(self):
        q = asyncio.Queue(maxsize=200)
        self.subs.add(q)
        return q

    def unsubscribe(self, q):
        self.subs.discard(q)


hub = LogHub()
lib = ConfigLibrary(LIB_PATH)
dev = Xim4Device(logger=hub.log)
state = {"active": None}
feed = {"want": False, "last": 0, "polls": 0, "presses": 0}

app = FastAPI(title="xim4ctl")


def _feed_thread():
    """Dedicated native polling thread — the live-input feed. Runs at the radio's
    ceiling (~90 Hz) with no async/threadpool overhead, so the brief idle gaps the
    device reports between rapid taps are reliably sampled (edge = a distinct press).
    Self-heals a wedged BT link after repeated failures. Pushes each new press to the
    WebSocket via the (thread-safe) hub."""
    last = 0
    fails = 0
    connected = False
    while True:
        if not feed["want"]:
            connected = False
            last = 0
            time.sleep(0.2)
            continue
        if not dev.connected:
            connected = False
            try:
                dev.connect(attempts=2)          # self-heals EBUSY inside _open
                fails = 0
            except Xim4Error:
                last = 0
                fails += 1
                if fails % 4 == 0:
                    try:
                        dev.recover_link(reason="feed stuck")
                    except Xim4Error:
                        pass
                time.sleep(3.0)
                continue
        prime = False
        if not connected:                        # just (re)connected -> learn active config
            connected = True
            _sync_active_from_device()
            prime = True                          # first poll drains 0x0a/handshake residue
        try:
            code = dev.poll_input(False, _prime=prime)
            fails = 0
        except Xim4Error:
            fails += 1
            time.sleep(0.5)
            continue
        feed["polls"] += 1
        if code == -1:                           # lost connection -> reconnect next loop
            connected = False
            time.sleep(0.1)
            continue
        # code == -2 is an unparseable/contaminated frame -> skip (don't update last)
        if code >= 0 and code != last:
            if code > 0:
                name = C.decode_input(code)
                if name and not name.startswith("raw:"):   # drop pure-garbage reads
                    hub.activity(name)
                    feed["presses"] += 1
            last = code
        time.sleep(0.002)                        # yield the device lock briefly (~85 Hz)


def _sync_active_from_device():
    """Identify which library config is active on the device (by gameUID) so the
    main-screen live feed can resolve input→output without an explicit switch."""
    try:
        uid, name = dev.active_identity()
    except Xim4Error:
        return
    if not uid:
        return
    for slot in lib.list_slots():
        if slot.get("gameUID") == uid:
            if state["active"] != slot["index"]:
                state["active"] = slot["index"]
                hub.log(f"device active config detected: {slot['title']} (slot {slot['index']})")
                hub._push({"type": "status", "device": dev.status(), "active": state["active"]})
            return


@app.on_event("startup")
async def _startup():
    hub.bind(asyncio.get_running_loop())
    if not lib.slots and SEED_BACKUP and os.path.exists(SEED_BACKUP):
        n = lib.seed_from_backup(SEED_BACKUP)
        hub.log(f"seeded library with {n} configs from backup")
    threading.Thread(target=_feed_thread, name="xim-feed", daemon=True).start()
    hub.log(f"backend up — library has {len(lib.slots)} configs, device={dev.addr}")


@app.post("/api/feed")
async def set_feed(body: dict = None):
    """Turn the live-input feed on/off (the activity panel drives this)."""
    feed["want"] = bool((body or {}).get("on", True))
    if not feed["want"]:
        feed["last"] = 0
    return {"ok": True, "want": feed["want"]}


@app.post("/api/recover")
async def recover():
    """Manually bust a wedged Bluetooth link and reconnect (UI 'reconnect' button)."""
    feed["last"] = 0
    result = await run_in_threadpool(dev.recover)
    hub.log("manual recover -> " + ("connected" if result.get("connected") else "failed"))
    return result


# ---- library / metadata -----------------------------------------------------
@app.get("/api/status")
async def status():
    return {"device": dev.status(), "active": state["active"],
            "library": len(lib.slots),
            "feed": {"want": feed["want"], "polls": feed["polls"], "presses": feed["presses"]}}

@app.get("/api/enums")
async def enums():
    return {
        "beacon": C.BEACON,
        "platform": C.PLATFORM,
        "buttons": C.BTN_ORDER,
        "keyboard": sorted(C.HID.keys()),
        "mouse": list(C.MOUSE.keys()),
        "wheel": list(C.WHEEL.keys()),
        "controller": list(C.CTRL.values()),
        "stickKeys": [name for _, name in C._STICK_KEYS],
    }

@app.get("/api/configs")
async def configs():
    return lib.list_slots()

@app.get("/api/config/{index}")
async def config(index: int):
    parsed = lib.get_parsed(index)
    if parsed is None:
        raise HTTPException(404, f"no config in slot {index}")
    return parsed


# ---- device operations ------------------------------------------------------
@app.post("/api/capture")
async def capture(body: dict = None):
    """Press-to-assign: poll the device's 0x3c input line until the user presses
    an input, return its decoded name (same encoding as config button maps)."""
    timeout = float((body or {}).get("timeout", 6))
    try:
        code = await run_in_threadpool(dev.capture_input, timeout)
    except Xim4Error as e:
        raise HTTPException(503, str(e))
    name = C.decode_input(code) if code else None
    hub.log(f"capture -> {name}" if name else "capture: nothing pressed")
    return {"ok": True, "code": code, "name": name}

@app.post("/api/poll")
async def poll():
    """One 0x3c input-line poll → the currently-pressed input (for the live feed).
    Does not force a connection; returns connected=False when the XIM is asleep."""
    try:
        code = await run_in_threadpool(dev.poll_input, False)
    except Xim4Error:
        code = -1
    if code < 0:
        return {"connected": False, "code": 0, "name": None}
    return {"connected": True, "code": code, "name": C.decode_input(code) if code else None}

@app.post("/api/switch/{index}")
async def switch(index: int):
    try:
        resp = await run_in_threadpool(dev.switch, index)
    except Xim4Error as e:
        raise HTTPException(503, str(e))
    state["active"] = index
    hub.log(f"switched active config -> {index}")
    return {"ok": True, "active": index, "resp": resp.hex()}

@app.post("/api/sync/{index}")
async def sync_one(index: int):
    """Read one config from the device into the library (activates it)."""
    try:
        pages = await run_in_threadpool(dev.read_config, index)
    except Xim4Error as e:
        raise HTTPException(503, str(e))
    state["active"] = index
    lib.set_slot(index, pages)
    hub.log(f"synced config {index} from device")
    return lib.get_parsed(index)

@app.post("/api/sync")
async def sync_all():
    """Full paced sync of every device config into the library."""
    async def run():
        try:
            meta = await run_in_threadpool(dev.list_meta)
            cnt = len(meta)
            hub.log(f"full sync: {cnt} configs")
            for i in range(cnt):
                pages = await run_in_threadpool(dev.read_config, i)
                lib.set_slot(i, pages, parse_meta(meta[i]))
                hub.log(f"  synced {i+1}/{cnt}")
            state["active"] = None
        except Xim4Error as e:
            hub.log(f"sync failed: {e}")
    asyncio.create_task(run())
    return {"ok": True, "started": True}

@app.put("/api/config/{index}")
async def write_config(index: int, edits: dict):
    """Author `edits` onto the slot template and write to the device (0x15)."""
    try:
        write_pages, new_hex = lib.author(index, edits)
    except KeyError:
        raise HTTPException(404, f"no config in slot {index}")
    except (ValueError, Exception) as e:  # codec/encoding errors
        raise HTTPException(400, f"author failed: {e}")
    try:
        resps = await run_in_threadpool(dev.write_config, index, write_pages)
    except Xim4Error as e:
        raise HTTPException(503, str(e))
    state["active"] = index
    lib.commit(index, new_hex, title=edits.get("title"))
    hub.log(f"wrote config {index} to device ({len(write_pages)} pages)")
    return {"ok": True, "config": lib.get_parsed(index), "resps": resps}

@app.put("/api/config/{index}/library")
async def save_library_only(index: int, edits: dict):
    """Author edits into the library only (no device write) — offline editing."""
    try:
        _, new_hex = lib.author(index, edits)
    except KeyError:
        raise HTTPException(404, f"no config in slot {index}")
    lib.commit(index, new_hex, title=edits.get("title"))
    return {"ok": True, "config": lib.get_parsed(index)}


# ---- auto-switch title map --------------------------------------------------
@app.get("/api/titlemap")
async def get_titlemap():
    return lib.title_map

@app.post("/api/titlemap")
async def set_titlemap(mapping: dict):
    lib.set_title_map(mapping)
    return {"ok": True}

@app.post("/api/autoswitch")
async def autoswitch(body: dict):
    """Given a running game title, switch to its mapped config."""
    title = body.get("title", "")
    idx = lib.slot_for_title(title)
    if idx is None:
        return JSONResponse({"ok": False, "reason": "no mapping"}, status_code=404)
    try:
        await run_in_threadpool(dev.switch, idx)
    except Xim4Error as e:
        raise HTTPException(503, str(e))
    state["active"] = idx
    hub.log(f"auto-switch '{title}' -> config {idx}")
    return {"ok": True, "active": idx}


# ---- websocket log/status ---------------------------------------------------
@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    q = await hub.subscribe()
    try:
        for line in list(hub.buffer)[-50:]:
            if line.get("type") == "log":
                await websocket.send_json(line)
        await websocket.send_json({"type": "status", "device": dev.status(),
                                   "active": state["active"]})
        while True:
            await websocket.send_json(await q.get())
    except WebSocketDisconnect:
        pass
    finally:
        hub.unsubscribe(q)


# ---- static frontend (mounted last so /api wins) ----------------------------
if os.path.isdir(FRONTEND):
    app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
