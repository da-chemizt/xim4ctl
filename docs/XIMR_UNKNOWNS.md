# XIM4 .ximmr — structure reference (platform lists, gains, blobs, trailer)

A companion to [XIMR_FORMAT.md](XIMR_FORMAT.md) covering the remaining `.ximmr` structures
in detail: the per-owner resource items, the global/owner-0 catalogue resources, the value
pools, and the file trailer. Byte offsets are for one representative build; they will differ
in another, but the structure and encoding rules hold.

The game database (`.ximmr`) is ~24,979,069 bytes, little-endian.
`BASE = 16 + 36142*8 = 0x46980 = 289,152` (end of directory). All payload offsets below are given as
`abs` (absolute file offset) and `rel` (BASE-relative, i.e. the value stored in the directory).

**Length rule (verified):** the directory stores no lengths. Sorting the *unique* offsets tiles the
payload region `BASE..EOF` contiguously with **zero unreferenced holes** (first offset is rel 0), so an
entry's size = distance to the next distinct referenced offset. Payloads are self-sizing anyway
(`[len:u32]` for images, `[count:u32]` for lists, fixed 5504 B for translator blobs, fixed 4 B for scalars).

**Dedup rule (verified):** identical payloads are stored once and shared — any number of directory ids,
across arbitrary owners *and* banks, may point at the same offset. This applies to strings, 4-byte
scalars, platform lists, images and whole 5504-byte translator blobs (the PC bank usually aliases an
Xbox bank's blobs). 5,872 translator-blob references resolve to only 2,572 distinct blobs.

---

## 1. Res 0x74 — supported-platform list

Exists once per owner (bank byte 0x00 only; 440 instances = 437 games + 0xf000 + 0xf010 + 0xffff).

```
[count:u32][count × u8 platformCode][zero-pad to 4-byte multiple]
platformCode = bank >> 2 :
  0 = Xbox One   1 = PS4   2 = Xbox 360   3 = PS3
  4 = Xbox Series (confirmed)   5 = PS5 (confirmed)   6 = PC (confirmed)
```

* Observed sizes: 8 B (count ≤ 4) or 12 B (count 5–7); one 5 B entry truncated at EOF (see below).
* **Validated 438/438** scanned owners: the platform set always equals the exact set of banks that carry
  the 0x9f action labels. This *proves* the bank→platform hypotheses 0x10 = Xbox Series, 0x14 = PS5,
  0x18 = PC (e.g. Returnal 0x115d → `[5]`; Aim Lab [Exponential] 0xf010 → `[4,5,6]`; Generic 0xf000 → all 7).
* List order is the app's **display order**, not numeric (e.g. `04 05 00 01 06` = Series X, PS5, Xb1, PS4, PC).
* Global 0xffff = `[0,1,2,3]` (Crossover profile exists only for the four legacy platforms).
* Payloads are dedup-pooled in two places: abs 24,977,004–24,977,032 (rel 24,687,852–24,687,880,
  3 payloads) and the file trailer abs 24,978,812–24,979,069 (rel 24,689,660+), 32 distinct lists.
* Quirks: Bioshock 2 SP (0x1001) has `count=6, [0,1,2,3,6,6]` — platform 6 listed twice, matching its
  doubled PC-bank directory entries (§7). The final payload in the file (Returnal, abs 24,979,064 /
  rel 24,689,912) is `01 00 00 00 05` — 5 bytes, its 3 pad bytes dropped at EOF.

## 2. Res 0x75 — box art image

Exists once per owner (bank 0x00 slot; 440 instances). Structure:

```
[byteLen:u32][image bytes][zero-pad to 4-byte multiple — usually, not guaranteed]
```

* 437 game entries are **JPEG, 256×256** (box art shown by XIM4 Manager); global 0xffff is **PNG 256×256**
  (48,516 B, abs 14,618,268 / rel 14,329,116); 0xf000/0xf010 also JPEG.
* This is image data, not a float array — reinterpreting the JPEG/PNG bytes as f32 yields nonsense.
* Total ≈ 10.14 MB of distinct image data — 41 % of the file (the single biggest reason the DB is 25 MB).
* Padding caveat: at least one image (owner 0x11b9, abs 24,936,868) ends unpadded, directly followed by
  the next string. Always use `4 + byteLen`, not alignment, to size it.

## 3. Res 0x96 / 0x97 — Hip / ADS gain scalar

One per (owner, bank) — 1,468 pairs each. **Each is a single f32 (4 bytes).**

* Value range 35.03 … 3774.0, median ≈ 420. Global CCC profile = 1680.359 on all four of its banks.
* **0x96 = Hip, 0x97 = ADS** (evidence): for every (owner, bank) whose translator blobs have *no*
  Hip/ADS split, 0x96 == 0x97 — 525/525 cases. Where the blobs are named `-Hip-`/`-ADS-`, the two floats
  differ in 628/943 cases (the remaining 315 games simply use equal gains).
* Plausible meaning: per-translator normalisation constant (max turn rate / sensitivity scale) applied to
  the Smart Translator output — one for hip aim, one for ADS.
* Storage: a dedup'd **4-byte value pool** at abs 24,973,088–24,977,004 (rel 24,683,936–24,687,852):
  979 contiguous 4-byte slots — 978 distinct floats + one u32 slot shared by res 0xc4/0xc5 (§7).
  830 of the 1,458 game (0x96,0x97) pairs point both ids at the same slot.

## 4. Res 0x8a..0x8d — Smart Translator ballistic blobs

Each of these four items is **a fixed 5,504-byte blob per (owner, bank)** — not an
`[id, offset]` sub-table (pairing the ASCII label bytes with the ciphertext that follows can
create that illusion). Totals: 1,468 banks × 4 = 5,872 refs, 2,572 distinct blobs = 14.16 MB,
57 % of the file.

```
offset 0   : ASCII name, NUL-terminated (observed max 22 chars)
       ..43: zero padding
offset 44  : 4 flag/status bytes — usually 00 00 00 00; observed 00 ff 00 01 (Warframe-Hip-P4.3),
             01 ff ff 00 (Minecraft-P4.2), 01 01 01 ff (Neverwinter-P4.2). Semantics UNKNOWN.
offset 48  : 5,456 bytes payload = 341 × 16 — high entropy (~7.96 bits/byte) → encrypted
             (16-byte block aligned, AES-like) or compressed. NOT yet decodable.
```

* Name grammar: `<GameAbbrev>[-Hip|-ADS]-<X|P><gen>.<rev>` — `X` = Xbox lineage, `P` = PlayStation,
  gen digit matches the bank (X1 = Xbox One, X3 = 360, P3, P4 …). Examples: `Bf:BC2-Hip-X3.2` (bank 0x08),
  `Bf:BC2-Hip-P3.1` (bank 0x0c), `Bioshock2-X1.1`, `Warframe-Hip-P4.3`. Global 0xffff = `CCC.1`
  (Console Controller Crossover). 0xf000 = Generic curves.
* Pairing: **0x8a/0x8b = Hip/ADS of set A; 0x8c/0x8d = Hip/ADS of set B.** A and B carry *identical
  names* but the encrypted payload differs in **1458/1458** sampled banks → best hypothesis: X-axis vs
  Y-axis translator data. 0x8a == 0x8b blob-identical in 521 banks = games without an ADS translator
  (their names then lack `-Hip`/`-ADS`).
* Example blob: owner 0x1000 bank 0x08 → abs 355,200 / rel 66,048 (`Bf:BC2-Hip-X3.2`).

## 5. Directory ids 0 & 1, owner-0 resources, and the file trailer

Owner 0x0000 is an **app-global catalogue owner** (its res ids are not bank/item pairs like game owners).

### res 0 (abs 24,977,032 / rel 24,687,880, 884 B) and res 1 (abs 24,977,916 / rel 24,688,764, 884 B)

Both are `[count:u32 = 440][440 × u16 ownerId]` — a leading u32 count of 440, then 440 ids
(the two are referred to elsewhere as A1 = res 0, A2 = res 1):

* **res 0 = UI display order**: 0xffff (Crossover) first, then the 437 games in curated
  ~alphabetical order (not strict casefold — e.g. Battlefield V is placed before the Battlefield 6
  variants), ending with 0xf010 "Aim Lab [Exponential]", 0x11ab "Aim Lab [Linear]", 0xf000 "Generic".
* **res 1 = the same 440 ids strictly ascending**: 0x1000..0x11b9 with exactly **5 skipped slots**
  (0x1075, 0x1092, 0x10d5, 0x1121, 0x115e — retired/removed games; 442 − 5 = 437), then 0xf000,
  0xf010, 0xffff.
* Two special owners exist outside the 0x1000+k space: **0xf000 = "Generic"** (all 7 platforms) and
  **0xf010 = "Aim Lab [Exponential]"** (Series/PS5/PC) — full profiles with labels, blobs and art.

### owner-0 res 0x14 / 0x15 (both abs 24,978,800 / rel 24,689,648, 12 B — dedup'd to one slot)

`[7][00 01 02 03 04 05 06][pad]` = the complete platform-code list (same encoding as res 0x74).
Two ids, one payload; likely "known platforms" + "displayable platforms".

### owner-0 res (bank<<8)|0x16 — platform logos

`[len:u32][PNG 128×128]` per bank, all 7 banks (bank 0 = abs 14,666,788 / rel 14,377,636, 15,149 B).

### owner-0 res (bank<<8)|(0x29+i) — button glyph icons

`[len:u32][PNG 60×60]`, one per BTN_ORDER slot: 17 per Xbox-style bank, 18 on PS4/PS5 banks
(0x3a = Share glyph). Total 160 KB.

### owner-0 res (bank<<8)|(0x4e+i) — platform button names

Plain NUL-terminated strings per BTN_ORDER slot: bank 0 `RTrigger, LTrigger, RStick, LStick, RBumper,
LBumper, A, B, X, Y, Up, Down, Right, Left, Menu, View, Guide`; PS banks `R2, L2, R3, L3, R1, L1, Cross,
Circle, Square, Triange [sic — typo in DB], … Options, Touch, Guide, Share`. This is a second copy of
platform button names, independent of the per-profile 0xffff (bank<<8)|0x9f set.

### Trailer (abs 24,978,800–24,979,069 / rel 24,689,648–24,689,917, 269 B)

Not opaque: it is dedup pool #2 — the 0x14/0x15 platform list followed by 32 distinct shared 0x74
platform-list payloads (each referenced by 1–94 owners). The file's last 5 bytes are the truncated
`[1][5]` (PS5-only, Returnal) list, its padding cut off at EOF.

## 6. The "3948-byte gap" (abs ~24,973,090–24,977,038) — fully referenced

With BASE-relative addressing, **every byte of the gap is directory-referenced**:

| abs | rel | contents |
|---|---|---|
| 24,973,088–24,977,004 | 24,683,936–24,687,852 | 4-byte value pool: 979 slots (0x96/0x97 floats; slot abs 24,973,148 = u32 224 for 0xc4/0xc5) |
| 24,977,004–24,977,032 | 24,687,852–24,687,880 | dedup pool #1 of 0x74 platform lists (3 payloads, incl. global `[0,1,2,3]` at abs 24,977,024) |
| 24,977,032 | 24,687,880 | owner-0 res 0 (display-order owner list) count header |

Whole-file byte budget (data region 24,689,917 B + 289,152 B header/directory):
translator blobs 14,156,288 · box art 10,142,594 · button glyphs 160,132 · res 0x82 tables 156,672 ·
platform logos 47,744 · strings (names + labels + button names) 20,506 · value pool 3,916 ·
owner lists 1,768 · platform lists 297.

---

## 7. Open questions

* **Res 0x82:** fixed 9,216 B = 2,304 u32, present on only **32 modern
  competitive-shooter profiles** (R6 Siege, Apex [ALC/Classic/Linear], Fortnite, Overwatch, PUBG, Halo
  Infinite, Valorant, The Finals, Rust, CoD BO6/BO7, Battlefield 6, Marvel Rivals, ARC Raiders,
  Marathon); every bank of an owner aliases one payload; 17 distinct payloads. Content is plaintext
  records mixing flags (0/1), percent-like ints (5/9/10/25/50/75/100/150/200) and f32 bit patterns
  (1.0, 2.0, 50.0, 0.667…), e.g. leading `(1,100,1,0,100)(1,100,1,0,100)(1,200,1,0,50)…`.
  **Hypothesis:** model of the game's in-game look-settings menu (supported sensitivity / response-curve
  / ALC options) backing the app's "expected in-game settings" guidance. Record layout not yet decoded.
* **Res 0xc4 / 0xc5:** each a u32 = **224 (0xE0)**, all refs dedup'd to the single pool slot
  abs 24,973,148 / rel 24,683,996. 0xc4 appears on 86 (owner,bank) ids across **21 Call of Duty titles**
  (CoD2 → WWII); 0xc5 only on CoD: Modern Warfare (2019)'s 3 banks. A CoD-specific constant —
  meaning unknown (only one distinct value in this DB, so it cannot be correlated yet).
* **Blob flag bytes** at translator-blob offset 44–47: semantics unknown (§4).
* **Translator payload encryption** (5,456 B, 16-byte aligned, ~7.96 bits/byte): key/algorithm unknown.
* **23 duplicated directory ids:** owner 0x1001 (Bioshock 2 SP) bank 0x18 res 0x8a–0xb0 are listed twice
  with identical offsets — a generator artifact, consistent with the doubled platform-6 entry in its
  0x74 list. Parsers should de-duplicate on id.
* **id0 collation rules** (series-aware ordering like Battlefield V before 6) are curated, not algorithmic.
