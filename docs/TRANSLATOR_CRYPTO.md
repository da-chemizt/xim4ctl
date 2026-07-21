# XIM4 translator-blob crypto — reverse-engineering findings

Subject: the 5,504-byte aim-translator blobs (`.ximmr` directory items `0x8a`/`0x8b`/`0x8c`/`0x8d`)
in the game database. Cited code addresses are offsets in the XIM4 Manager app's native library
`libManager_arm64-v8a.so` (AArch64 ELF; its LOAD segment has `off==vaddr`, so file offset ==
virtual address).

## TL;DR

- **Cipher / mode:** a **128-bit block cipher in ECB mode, encrypted under a single fixed global key**
  shared by every blob in the database. Almost certainly **AES-128-ECB** (the natural default; the app
  even ships OpenSSL 1.1) — but "AES specifically" is *inferred*, not proven, from ciphertext alone.
- **Key:** **NOT present anywhere in the APK.** The XIM4 Manager app is a **courier** — it reads the
  blob and streams it *verbatim* to the XIM4 **hardware device**, which decrypts it internally. The AES
  key lives in **device firmware**, not in this app, its native libs, its dex, or its QML bundle.
- **Verified decryption of R6's Hip translator:** **NOT achieved** — no key is recoverable from these
  materials. (An AES key cannot be derived from ECB ciphertext; that would break AES.)
- **Confidence:** ECB mode = **very high**; single global key = **very high**; app-is-a-courier /
  key-not-in-app = **high**; cipher == AES (vs. some other 128-bit block cipher) = **moderate**.

---

## 1. The crypto path — traced, and it contains no decryption

The three reader functions all just `bsearch` the directory and **return a raw pointer into the mmap'd
file** at `blob + 0x30` (i.e. body start, skipping the 48-byte header). None of them transforms bytes.

| Function | VA / file offset | What it does |
|---|---|---|
| `XIM::Repository::Database::GameHipTranslator(uchar,ushort,char**)` | `0x51174` | builds key `mov w10,#0x8a` @`0x51198`; `bsearch`@`0x511cc`; returns `add x0,x8,#0x30` @`0x51208` |
| `XIM::Repository::Database::GameADSTranslator(uchar,ushort,char**)` | `0x51224` | identical, `mov w10,#0x8b` @`0x51248` |
| `XIM::Repository::Database::LookupBlob(uint,uchar,ushort)` | `0x5097c` | generic `bsearch` @`0x509c8`; returns raw `add x0,x8,x9` @`0x509dc` |

**No decryption at the consumer either.** Following the returned pointer:

- **`XIM::Tweaker::ModifyDatabase(uint,uchar*,uchar*)` @`0x5012c`** — this is the *only* function in the
  binary that references the body size `0x1550` (5456): `mov w2,#0x1550` @`0x50148` →
  `memcmp(new, old, 5456)` @`0x50158`. If the two bodies are **equal** it returns a status; if they
  **differ** it tail-calls `WriteActiveDatabase` (`b 0x4eac0` @`0x50180`). It only *compares* the
  ciphertext — never decrypts it.
- **`XIM::Tweaker::WriteActiveDatabase(uint,bool,uchar*,uchar*)` @`0x4eac0`** — a block **delta-uploader**
  to the device. It walks 12 blocks (11 × `0x160`=352 B, final `0x1d0`=464 B), `memcmp`s each block
  old-vs-new (@`0x4ebac`), and for each *changed* block `memcpy`s the raw bytes (@`0x4ebf8`) into a
  `0x1e0`=480-byte protocol packet and calls `Tweaker::Transfer` @`0x4cfc8`. Transport opcodes:
  `0x14` begin (@`0x4eb10`), `0x17` write-block (@`0x4ebb4`), `0x1d` end (@`0x4ec50`), `0x0d` verify
  (@`0x4eca8`). **The blob bytes reach the device unmodified — no XOR, no cipher, no key.**
- **`XIM::Tweaker::ProtocolWriteActiveDatabaseBlock(uint,uint,uint,uchar*)` @`0x4da08`** — same story:
  `memcpy` block into the `0x1e0` packet (@`0x4da74`), `Transfer` with opcode `0x17`. Pure passthrough.

**UI does not decrypt it.** `BallisticsGraph::paint(QPainter*)` @`0x3acd8` only reads the QQuickItem's
`width`/`height` and draws grid lines / the user's own editable mouse-ballistics curve via `QPainter`.
It never calls the translator readers. The dex strings `mTranslateX/mTranslateY/translateX/translateY`
and the QML `Translate { … }` blocks are UI transforms, unrelated to the smart translator.

## 2. No standard crypto primitive is present in the app

- `libManager_arm64-v8a.so` **does not even link OpenSSL**: `NEEDED` lists only Qt libs, `libz`, `libm`,
  `libdl`, `libc`, `libc++_shared` — **no `libcrypto_1_1` / `libssl_1_1`**. (Those two libs ship with the
  app but are pulled in by Qt Network for TLS, i.e. the HTTPS download of the `.ximmr`, not for blobs.)
- `nm -Du libManager…` imports **zero** `EVP_*`, `AES_*`, `SHA*`, `MD5`, `RC4`, `CRYPTO_*`,
  `EVP_BytesToKey` symbols. The **only** crypto import is `QCryptographicHash::hash` (PLT `0x313a0`),
  and its **sole** call site is `Repository::onNetworkDownloadFinished()` @`0x47c14` (call @`0x48190`)
  — an integrity check on the *downloaded database file*, not per-blob decryption.
- Byte-scans of the whole lib for the **AES forward/inverse S-box**, **AES Te0 table**
  (`c66363a5`/`a56363c6`), and **ChaCha/Salsa** `"expand 32-byte k"` all returned **nothing**. There is
  no inlined/statically-linked AES in `libManager`.
- `classes.dex` is Qt-Android loader boilerplate + `com.xim4.manager.{BuildConfig,R,Utility}` using
  `DexClassLoader` — **no crypto classes, no key, no `SecretKeySpec`/`Cipher`.**
- `assets/android_rcc_bundle.rcc` (Qt qres/QML) is QuickControls styling only — **no key material.**

## 3. Ciphertext forensics: ECB mode + one global key

Sample: R6 Siege classic, Xbox One (game `0x10a9`, platform `0`), item `0x8a` "R6:S-Hip-X1.12".

- Blob offsets (this file): `0x8a` abs `0x4ca380` / rel `0x483a00`; `0x8b` abs `0x4cb900`;
  `0x8c` abs `0x4cce80`; `0x8d` abs `0x4ce400`. Header `[0:14]`=`R6:S-Hip-X1.12`, `[14:44]`=all-zero,
  flag bytes `[44:48]`=`00000000`. **No per-blob IV/nonce anywhere in the header.**
- Body = 5,456 B = 341 × 16. `body[0:16]` (0x8a) = `c4620135116c3e7885c84d70644878d2`.
- Shannon entropy of the body = **7.957 bits/byte**; the finite-sample expectation for *perfectly
  uniform* 5,456 bytes is **7.966** — i.e. the body is **statistically indistinguishable from random**
  (all 256 byte values present). ⇒ not a byte substitution and not compression with residual redundancy.
- **Repeating-XOR test (periods 1–64): flat** (all "alignment" scores ≈ 1/32, the uniform baseline;
  period 16 does **not** stand out). ⇒ it is **not** a block-wise / repeating-key XOR — it is a genuine
  diffusing block cipher.

**The 16-byte-block collision structure is the proof of ECB with a fixed key:**

| Observation | Measured | Under CBC/CTR/GCM |
|---|---|---|
| Duplicate 16-B blocks **within one 341-block body** | median **11**, mean **26.5**, max **145** | ≈ 0 (birthday bound over 2¹²⁸) |
| Same-label pair 0x8a vs 0x8c: identical 16-B blocks | **first block identical** + 3/341 identical (75 shared block-values overall) | ≈ 0 |
| Across all **2,572 distinct blobs** (877,052 blocks): duplicates | **294,808** dup occurrences (~34%); 582,244 unique | ≈ 0 |
| Single most-common ciphertext block `e5c323d1350ad3629511754690bd541a` | appears in **1,371 / 2,572 blobs (53.3%)** | impossible |
| Next four common blocks | each in **46–50%** of all blobs | impossible |

Identical ciphertext blocks recurring **within** a body, **between same-label blobs**, and **across
unrelated games** can only happen if identical *plaintext* 16-byte blocks map to identical *ciphertext*
blocks — i.e. **ECB mode, no chaining, no IV, one key for the entire dataset**. The ~5 blocks present in
~half of all blobs are common plaintext rows (flat curve segments / shared table entries / padding)
shared across games. CBC, CTR, GCM, or any per-blob IV would randomise every block and drive all these
counts to zero.

## 4. Why the key is not recoverable from these materials

- The key is **not in the app** (Sections 1–2): the app never decrypts; it forwards the ciphertext to
  the device. The XIM4 hardware performs the mouse→stick "smart translation" and therefore holds the key
  in firmware.
- Even with the full ECB **codebook** of this DB in hand, an AES (or any modern block-cipher) key
  **cannot** be recovered from ciphertext — the security of AES guarantees this. ECB leaks plaintext-block
  *equality* (the property §3 uses to identify the mode) but not the key.

## 5. Candidate constants / leads found

- No 16- or 32-byte key-looking constant sits near any code that touches the body (there is no such code
  beyond `memcmp`/`memcpy`). The `adrp 0x274000` references throughout `Tweaker` are GOT slots (transport
  state, session counters), not key bytes.
- The transport packet header (opcode + rolling `ushort` sequence counter at GOT `0x274000+0xd08`) is the
  only structured framing; the DB block payload inside it is opaque ciphertext.

## 6. Paths to the plaintext

1. **Codebook attack (best path without touching the device again).** Obtain **one** verified
   (ciphertext-blob, plaintext-blob) pair — e.g. capture the device's decrypted translator output, or
   confirm the plaintext of an *identity/linear* profile (`Generic` owner `0xf000`, or `CCC.1` global
   `0xffff`). Then build a ciphertext-16B → plaintext-16B map. Because it is pure ECB with one key, that
   map **immediately decrypts ~34% of every block in the whole DB** (all shared blocks) and grows
   incrementally as more blobs are learned. No AES key required.
2. **Pull the key from XIM4 device firmware** (firmware-update image, flash/JTAG dump). That is the only
   place the AES key exists. Then AES-128-ECB-decrypt each 5,456-byte body directly.
3. **Known-plaintext guessing of the common blocks.** The 5 ciphertext blocks present in ~half of all
   blobs are the prime targets: they correspond to the most common plaintext rows of the ballistic
   tables (likely a repeated anchor value or a zero/flat segment). Guessing those plaintexts + confirming
   against a device dump would seed the codebook cheaply.

## 7. Reproducing this

- Static analysis needs only `objdump`/`nm`/`strings` on `libManager_arm64-v8a.so` (extract it from the
  app's APK) plus Python's standard library (`struct`, `hashlib`, `collections`) — no disassembler or
  crypto library required. All function addresses above are both file offsets and virtual addresses
  (the LOAD segment has `off==vaddr`).
- To reproduce the ECB evidence: extract the four Rainbow Six blobs at the offsets in §3, split each
  5,456-byte body into 341 × 16-byte blocks, and count the intra- and inter-blob block collisions —
  they match the table in §3.
