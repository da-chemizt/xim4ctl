#!/usr/bin/env python3
"""XIM4 RFCOMM device driver — a single, serialized, self-reconnecting connection.

All device access goes through one lock: the XIM4 wedges if two hosts / two sockets
compete, so only ever one operation is in flight. Blocking sockets; call from an
async context via run_in_threadpool. Mirrors the proven flow in tools/xim_*.py:
connect (retry within the connectable window) -> handshake -> transact.
"""
import errno
import os
import shutil
import socket
import struct
import subprocess
import threading
import time

from xim_codec import build_frame, N_PAGES

ADDR = os.environ.get("XIM4_ADDR", "AA:BB:CC:DD:EE:FF")  # set XIM4_ADDR to your XIM4 bdaddr
CH = int(os.environ.get("XIM4_CHANNEL", "1"))
HANDSHAKE = bytes.fromhex(
    "4b72fc2b00000100342e30302e32303136303430350000000000000000000000aca6121074420a00"
)


class Xim4Error(RuntimeError):
    pass


class Xim4Device:
    def __init__(self, addr=ADDR, channel=CH, logger=None):
        self.addr = addr
        self.channel = channel
        self._sock = None
        self._lock = threading.RLock()
        self._seq = 0x0100
        self._log = logger or (lambda *_: None)
        self.firmware = None
        self._trusted = False
        self._recoveries = 0        # count of wedge auto-recoveries (for telemetry)

    # -- connection -----------------------------------------------------------
    @property
    def connected(self):
        return self._sock is not None

    def _btctl(self, *args, timeout=8):
        """Run a bluetoothctl subcommand (best-effort). Returns stdout or ''."""
        exe = shutil.which("bluetoothctl")
        if not exe:
            return ""
        try:
            r = subprocess.run([exe, *args], timeout=timeout, capture_output=True, text=True)
            return (r.stdout or "") + (r.stderr or "")
        except (OSError, subprocess.TimeoutExpired):
            return ""

    def _ensure_trusted(self):
        """Trust the device once so BlueZ reconnects it cleanly (no wedge on an
        unbonded, sleep-prone adapter). Idempotent, best-effort."""
        if self._trusted:
            return
        out = self._btctl("trust", self.addr)
        self._trusted = True
        if "succeeded" in out or "Trusted: yes" in out:
            self._log(f"trusted {self.addr}")

    def recover_link(self, reason=""):
        """Self-heal a wedged / half-open ACL: tear the link down at the BlueZ
        level so the next RFCOMM channel-open succeeds. This is what clears the
        [Errno 16] EBUSY state where BlueZ holds an ACL but the SPP channel won't
        open. Best-effort; safe to call even when nothing is wedged."""
        self._recoveries += 1
        self._log(f"recovering BT link{f' ({reason})' if reason else ''} "
                  f"[#{self._recoveries}]")
        self._reset()                       # drop our own socket first
        self._btctl("disconnect", self.addr)
        self._ensure_trusted()              # trust so it doesn't wedge again
        time.sleep(1.5)                     # let BlueZ settle the teardown

    def _open(self, attempts=8, per_timeout=4.0):
        if not hasattr(socket, "AF_BLUETOOTH"):
            raise Xim4Error("this host has no Bluetooth RFCOMM support "
                            "(AF_BLUETOOTH missing) — run on a Linux BR/EDR host")
        self._ensure_trusted()
        last = None
        recovered = False
        i = 0
        while i < attempts:
            s = None
            try:
                s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
                s.settimeout(per_timeout)
                s.connect((self.addr, self.channel))
                self._sock = s
                self._log(f"RFCOMM connected to {self.addr} ch{self.channel}")
                self._handshake()
                return
            except OSError as e:
                last = e
                if s is not None:
                    try:
                        s.close()
                    except OSError:
                        pass
                # EBUSY / EHOSTDOWN with a lingering ACL == a wedged link. Clear it
                # once and retry the SAME budget (recovery attempt is "free").
                if e.errno in (errno.EBUSY, errno.EHOSTUNREACH) and not recovered:
                    recovered = True
                    self.recover_link(reason=f"errno {e.errno} on connect")
                    continue
                time.sleep(1.0)
                i += 1
        raise Xim4Error(f"could not connect to {self.addr} after {attempts} tries: {last}")

    def _handshake(self):
        self._sock.send(HANDSHAKE)
        r = self._drain(1.8)
        if len(r) >= 9:
            self.firmware = r[9:].split(b"\x00")[0].decode("latin1", "ignore") or None
            self._log(f"handshake ok, firmware={self.firmware}")

    def ensure(self):
        if self._sock is None:
            self._open()

    def connect(self, attempts=1, per_timeout=2.5):
        """Quick, bounded connect for the background feed (fails fast when asleep)."""
        with self._lock:
            if self._sock is None:
                self._open(attempts=attempts, per_timeout=per_timeout)

    def close(self):
        with self._lock:
            if self._sock is not None:
                try:
                    self._sock.close()
                finally:
                    self._sock = None
                    self._log("connection closed")

    def _reset(self):
        try:
            if self._sock:
                self._sock.close()
        except OSError:
            pass
        self._sock = None
        self.firmware = None

    # -- low-level transaction ------------------------------------------------
    def _drain(self, window, oneshot=False):
        """Read the response. Normally waits out `window` collecting everything.
        `oneshot=True` returns as soon as the first chunk arrives (a single fixed
        frame, e.g. the 0x3c poll) — keeps the poll rate high for the live feed."""
        s = self._sock
        s.settimeout(window)
        data = b""
        try:
            while True:
                c = s.recv(2048)
                if not c:
                    break
                data += c
                if oneshot:
                    break
        except socket.timeout:
            pass
        return data

    def _xact(self, cmd, payload=b"", window=1.4, oneshot=False):
        self._seq = (self._seq + 1) & 0xFFFF
        try:
            self._sock.send(build_frame(cmd, self._seq, payload))
            return self._drain(window, oneshot=oneshot)
        except OSError as e:
            self._reset()
            raise Xim4Error(f"transaction 0x{cmd:04x} failed: {e}")

    # -- public API (all serialized) -----------------------------------------
    def status(self):
        with self._lock:
            return {"connected": self.connected, "addr": self.addr,
                    "channel": self.channel, "firmware": self.firmware,
                    "trusted": self._trusted, "recoveries": self._recoveries}

    def recover(self):
        """Manual wedge-buster: clear the BlueZ link and re-establish. Returns the
        post-recovery connection state."""
        with self._lock:
            self.recover_link(reason="manual")
            try:
                self._open()
            except Xim4Error as e:
                return {"connected": False, "error": str(e), "recoveries": self._recoveries}
            return {"connected": self.connected, "firmware": self.firmware,
                    "recoveries": self._recoveries}

    def ping(self):
        with self._lock:
            self.ensure()
            return self._xact(0x0001)

    def count(self):
        with self._lock:
            self.ensure()
            raw = self._xact(0x0033)
            c = struct.unpack_from("<I", raw, 8)[0] if len(raw) >= 12 else 0
            return c if 0 < c <= 64 else 0

    def list_meta(self, count=None):
        """0x0032 per-config metadata (name/gameUID/beacon/platform) — read without
        changing the active config. Returns list of raw hex blobs."""
        with self._lock:
            self.ensure()
            n = count if count is not None else self.count()
            return [self._xact(0x0032, struct.pack("<I", i)).hex() for i in range(n)]

    def read_active_pages(self, pace=0.25):
        """Read the 8 pages (0x0a) of the currently-active config."""
        with self._lock:
            self.ensure()
            pages = []
            for p in range(N_PAGES):
                pages.append(self._xact(0x000A, struct.pack("<I", p)))
                time.sleep(pace)
            return pages

    def active_identity(self):
        """Read page 0 of the active config and return (gameUID, name) so the UI
        can resolve live inputs against whatever's active on the device."""
        with self._lock:
            self.ensure()
            p0 = self._xact(0x000A, struct.pack("<I", 0))
            if len(p0) < 12 + 0x34:
                return None, None
            uid = struct.unpack_from("<H", p0, 12 + 0x32)[0]
            name = p0[12:12 + 48].split(b"\x00")[0].decode("latin1", "ignore")
            return uid, name

    def switch(self, index):
        """0x0029 — make config `index` the active one."""
        with self._lock:
            self.ensure()
            return self._xact(0x0029, struct.pack("<I", index))

    def read_config(self, index, settle=1.5, pace=0.25):
        """Activate `index`, let it settle, read its 8 pages. (0x0a reads active only.)"""
        with self._lock:
            self.ensure()
            self._xact(0x0029, struct.pack("<I", index))
            time.sleep(settle)
            pages = []
            for p in range(N_PAGES):
                pages.append(self._xact(0x000A, struct.pack("<I", p)))
                time.sleep(pace)
            return pages

    @staticmethod
    def _poll_3c_code(resp):
        """Input code from the freshest 0x013c frame in the buffer.
        Frame layout: [crc4][cmd=3c01 @4][seq2 @6][code2 @8]…."""
        if len(resp) >= 28 and resp[-28:][4:6] == b"\x3c\x01":
            return struct.unpack_from("<H", resp[-28:], 8)[0]
        i = resp.rfind(b"\x3c\x01")
        if i >= 0 and i + 6 <= len(resp):
            return struct.unpack_from("<H", resp, i + 4)[0]
        return 0

    def _flush_rx(self):
        """Non-blocking drain of any buffered/stale frames so the next poll reads a
        fresh response (prevents request/response desync)."""
        s = self._sock
        s.setblocking(False)
        try:
            while s.recv(4096):
                pass
        except (BlockingIOError, socket.error):
            pass
        finally:
            s.setblocking(True)

    def poll_input(self, connect=False, _prime=False):
        """One 0x3c poll -> current input code (0 = idle). Lean send + single recv +
        freshest-frame parse — the sequence proven to run at the radio's ~85 Hz ceiling
        and sample the device's release gaps. `_prime=True` pre-drains residue left by
        a prior non-poll read (0x0a/handshake) so the first frame isn't contaminated."""
        with self._lock:
            if not connect and self._sock is None:
                return -1
            self.ensure()
            s = self._sock
            if _prime:
                self._flush_rx()
            self._seq = (self._seq + 1) & 0xFFFF
            try:
                s.send(build_frame(0x003C, self._seq, b"\x00\x00\x00\x00"))
                s.settimeout(0.2)
                buf = s.recv(2048)
            except socket.timeout:
                return 0
            except OSError as e:
                self._reset()
                raise Xim4Error(f"poll failed: {e}")
            return self._poll_3c_code(buf)

    def capture_input(self, timeout=6.0):
        """Press-to-assign: poll 0x3c (seq-matched) until a fresh non-idle input
        appears, or the window expires. Requires one idle reading first so a held
        input at start isn't mis-captured. Returns the u16 code (0 if nothing)."""
        with self._lock:
            self.ensure()
            end = time.monotonic() + timeout
            baseline_cleared = False
            first = True
            while time.monotonic() < end:
                code = self.poll_input(connect=True, _prime=first)
                first = False
                if code < 0:
                    continue
                if not baseline_cleared:
                    if code == 0:
                        baseline_cleared = True
                elif code:
                    return code
            return 0

    def write_config(self, index, pages, settle=1.5, pace=0.3):
        """Activate `index`, then write the 8 authored pages (0x15). Writes target
        the active config, so we activate first."""
        if len(pages) != N_PAGES:
            raise Xim4Error(f"expected {N_PAGES} pages, got {len(pages)}")
        with self._lock:
            self.ensure()
            self._xact(0x0029, struct.pack("<I", index))
            time.sleep(settle)
            resps = []
            for pg in pages:
                # pg is a full 0x15 frame already built by the codec; send verbatim
                self._seq = (self._seq + 1) & 0xFFFF
                try:
                    self._sock.send(pg)
                    resps.append(self._drain(1.4).hex())
                except OSError as e:
                    self._reset()
                    raise Xim4Error(f"page write failed: {e}")
                time.sleep(pace)
            return resps
