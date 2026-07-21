# XIMR game-database format (`.ximmr`) — reverse-engineered spec

The `.ximmr` is the XIM4 Manager app's own bundled game database (~25 MB, little-endian
throughout): game names, box art, per-game action labels, supported-platform lists, and
the encrypted aim translators. Fetch your own copy with `tools/fetch_gamedb.py`. Every
structural claim here is confirmed two ways — by parsing the file, and by disassembling the
app's native library (`libManager_arm64-v8a.so`); the cited addresses are that library's
function offsets.

The whole file is ~56% encrypted translators + ~41% box-art JPEG + ~3% directory and
strings — those three account for essentially all 25 MB.

## 1. Header (16 bytes)

| off | type | value | meaning |
|----|------|-------|---------|
| 0  | char[4] | `XIMR` | magic |
| 4  | u32 | 20260612 | build date (YYYYMMDD) |
| 8  | u32 | 95623 | build time (HHMMSS, i.e. 09:56:23) |
| 12 | u32 | 36142 | directory entry count |

## 2. Resource directory

At offset 16: `count × [id:u32][offset:u32]` (8-byte records, 36142 of them).
**All payload offsets are relative to `BASE = 16 + count*8 = 0x46980` (289,152)** — the
byte just past the directory. Confirmed in the lib: readers compute
`data = (struct+0x10 + count*8) + entry.offset` (`GameArtwork` @0x5113c,
`PlatformInputName` @0x50edc). Entries are sorted by the full `id` u32 and looked up
with `bsearch` (comparator `XIM::Repository::IsLookupBlobCompare` @0x50960; generic
reader `Database::LookupBlob(key,platform,game)` @0x5097c).

### 2.1 The `id` encoding — `[owner:u16][res:u16]`, `res = [bank:u8][item:u8]`

```
id  = (owner << 16) | res
res = (platform << 10) | item          // platform<<10 == (platform*4)<<8 == bank<<8
```
Confirmed: `GameInputAction` @0x512f8 does `lsl w10,w1,#16` then ORs the res;
`bfi w,w1,#10,#6` inserts `platform<<10`. So the **high byte of res is `bank = platform*4`**
and the low byte is the `item`.

- **owner** `0x1000 + k` (k = 0..436) → per-game resources; `k` is the game's DB index.
  `owner == the config's gameUID field`, so **gameUID is the join key** between a device
  config and this DB (verified against all 23 device-backup configs — gameUID matches
  even when the config was renamed/cloned; name matching alone is ambiguous, e.g. two
  "Rainbow Six Siege" variants `[Classic]` k=169 / `[Updated]` k=271).
- **owner** `0xffff` → the default "Console Controller Crossover" profile.
- **owner** `0xf000` (Generic, all 7 platforms), `0xf010` (Aim Lab [Exponential],
  platforms 4/5/6) → special built-in profiles.
- **platform** ordinal → bank byte: `0→0x00 Xbox One`, `1→0x04 PS4`, `2→0x08 Xbox 360`,
  `3→0x0c PS3`, `4→0x10 Xbox Series`, `5→0x14 PS5`, `6→0x18 PC`. The 0/1/2/3 names are
  proven by the app's own button-name resources; **4/5/6 (Series/PS5/PC) are inferred**
  from each game's platform-list blob (§3.4) — the app hard-codes no platform product
  names (they're data-driven via `image://artwork/L:<platform>`), so the *names* for 4/5/6
  are not independently confirmable from the binary, only the `bank=platform*4` arithmetic is.

### 2.2 Payloads are self-sizing and deduplicated

The directory stores no lengths. Sorting the distinct offsets tiles `BASE..EOF`
contiguously with no holes, so each payload's size = distance to the next distinct
offset; payloads are self-describing anyway (`[len:u32]` images, `[count:u32]` lists,
fixed 5504 B translators, fixed 4 B scalars). **Identical payloads are stored once and
shared** by many ids across owners *and* banks (e.g. the Xbox Series / PS5 / PC banks
usually alias the Xbox One / PS4 blob).

## 3. Per-owner resource items (`item` byte)

| item | contents | status |
|------|----------|--------|
| `0x73` | game name (UTF-8, null-terminated) | ✔ `Database::GameName` @0x50fb8 (`mov w9,#0x73`) |
| `0x74` | supported-platform list (§3.4) | ✔ `Database::GamePlatforms` @0x51044 (`#0x74`) |
| `0x75` | box art (§3.3) | ✔ `Database::GameArtwork` @0x510dc (`#0x75`) |
| `0x76` | per-game hint text | app-supported (`Database::GameHint` @0x51370, `#0x76`) but **0 present in this build** |
| `0x8a` | Hip aim translator (primary) | ✔ `Database::GameHipTranslator` @0x51174 (`#0x8a`) |
| `0x8b` | ADS aim translator (primary) | ✔ `Database::GameADSTranslator` @0x51224 (`#0x8b`) |
| `0x8c` / `0x8d` | Hip / ADS translator (alternate) | ✔ same shape, distinct blobs |
| `0x96` / `0x97` | per-(game,platform) f32 (Hip/ADS reference sensitivity — hypothesis) | value ≈ 68–1680; present for 254 games only |
| `0x9f`..`0xaf` | the **17 action labels** in `BTN_ORDER` | ✔ `ContentGameInputActions` @0x63e8c = 18 u32s `0x9f..0xb0` |
| `0xb0` | 18th action label ("Share", PS banks) | ✔ (18th entry of that array) |

`item` is `(platform<<10)|item` in the full res for the per-platform ones (translators,
labels, gains, art/name/platform-list live under platform 0 / bank 0x00).

### 3.1 Action labels

`BTN_ORDER = RT,LT,RS,LS,RB,LB,A,B,X,Y,Up,Down,Right,Left,Start,Back,Guide` (+ Share).
Item `0x9f + i` is the game-specific action for slot `i` on that platform's bank. The app
keeps three parallel 18-entry tables indexed by the same slot order — icons
`0x29+i` (`ContentPlatformInputIcons` @0x63dfc), platform button *names* `0x4e+i`
(`ContentPlatformInputNames` @0x63e44), and these action labels `0x9f+i`.

Labels are platform-invariant for most games; where a bank differs it's usually a
PS3-era remap (Fire/ADS on R1/L1 instead of the triggers). For example, Rainbow Six maps
`Drone` to d-pad Right and `Vote` to Down; Far Cry Primal maps `Owl/Rock/Beast/Food` to
the d-pad; most shooters put Fire/ADS on the triggers.

`tools/extract_action_labels.py` emits
`{ "<gameUID>": { "name":…, "RT":…, …, "byPlatform": { "<platformIndex>": {…overrides} } } }`.

### 3.2 Known label-data defects in *this* build (carry through faithfully; don't "fix")

- k=428/429 (The Finals Linear/Sinusoidal) and k=372 (The Finals Exponential): Guide slot
  reads "Game Menu" (duplicated with Start) instead of "Guide".
- k=110 Payday 2 (PS4 bank) and k=259 Anthem (PS4 bank): Start/Back labels swapped vs the
  other banks.
- k=123 Far Cry Classic (PS3 bank): RB reads "Fire Mode", so that bank has no plain "Fire".
- k=116 Dust 514 (PS3 bank RS): literal string is `Melee",` (a vendor authoring artifact).
- Missing k: 146, 289, 350 (gaps in the DB — those indices carry no name/labels).
- Cosmetic typos in vendor strings: `Scroreboard`, `Tailsman`, `Peak Right/Left`,
  `Disipline` — present in the source data, not extraction errors.

### 3.3 Box art (`0x75`)

`[byteLen:u32][image]`, one per game. 437 games = 256×256 JPEG; `0xffff` = 256×256 PNG.
Size the blob by `4 + byteLen` (a few are not zero-padded to alignment). ≈10.1 MB total.
Extractor: `tools/build_assets.py` → `extract_covers()`, keyed by gameUID.

### 3.4 Supported-platform list (`0x74`)

`[count:u32][count × u8 platformCode][pad to 4]`, one per owner (bank 0x00 only).
`platformCode = bank>>2` (0..6). The list equals exactly the set of banks that carry
action labels for the game, and its order is the app's display order (not numeric). This
is what pins the 4/5/6 = Series/PS5/PC reading (e.g. Returnal → `[5]` PS5-only; Aim Lab
`0xf010` → `[4,5,6]`; Generic `0xf000` → all 7). Global `0x14/0x15` = the full `[0..6]`.

## 4. Aim translators (`0x8a`/`0x8b`/`0x8c`/`0x8d`) — the encrypted payload

Each blob is **exactly 5504 bytes**:

```
[ 0..14 )  ASCII label, e.g. "R6:S-Hip-X1.12"     // <gameCode>-<Hip|ADS>-<platCode><ver>
[ 14..48 ) zero padding
[ 48..5504 ) 5456 bytes of encrypted body         // ~7.95 bit/byte, 5456 = 16×341
```

Label grammar (`tools/extract_translators.py` decodes all of them):
`<gameCode>` may contain colons (`R6:S`, `FarCry:P`, `DS:23`, `Crysis2`); `<mode>` ∈
{Hip, ADS}; `<platCode>` ∈ {X1, X3, XS, P4, P3, P5, PC} with a version (e.g. `X1.12`,
`P4.14`). Series/PS5/PC banks typically alias the One/PS4/Xbox translator (same label +
same offset), so **5756 references resolve to 2528 distinct blobs** (≈13.9 MB — the bulk
of the file). 432/437 games ship translators.

**The 5456-byte body is a 128-bit block cipher in ECB mode under a single fixed global
key** (very likely AES-128-ECB). This is established by ciphertext forensics:
- R6's Hip body = 341 blocks, only 280 distinct → **61 duplicate 16-byte blocks inside one
  body** (CBC/CTR/GCM would give ~0).
- The `0x8a` and `0x8c` same-label blobs share a **byte-identical first block** — identical
  plaintext ⇒ identical ciphertext, the ECB fingerprint. (So the "alt" translator shares a
  plaintext prefix with the primary and diverges later.)
- **One ciphertext block recurs across 1333 of 2528 distinct blobs (52.7%)** — only possible
  with a single global key over a common plaintext block. Entropy 7.957 bit/byte otherwise.

**The key is NOT in the app — it is in the XIM4 firmware.** `libManager` does not link
OpenSSL, imports zero AES/EVP symbols, and contains no S-box/round constants; the readers
(`GameHipTranslator`/`LookupBlob`) return the raw pointer, and `WriteActiveDatabase`
@0x4eac0 / `ProtocolWriteActiveDatabaseBlock` @0x4da08 `memcpy` the encrypted bytes into
480-byte packets and `Transfer` them to the device (opcodes 0x14/0x17/0x1d) — the app is a
courier; the hardware decrypts. (`QCryptographicHash` is used only for the DB download
integrity check @0x47c14, not the translators.) Full analysis in
[TRANSLATOR_CRYPTO.md](TRANSLATOR_CRYPTO.md); `tools/extract_translators.py` dumps all
distinct encrypted bodies for offline study.

**To recover the actual aim curves** you need the firmware AES key (extract from the XIM4
MCU), or a codebook attack: because it's pure ECB, a single verified (plaintext, ciphertext)
blob pair decrypts ~34–53% of every blob's blocks immediately and grows from there. A
plaintext pair cannot come from wire captures (those carry the same ciphertext) — it must
come from inside a device or XIM's authoring tool.

## 5. Global / trailer structures

| id | contents |
|----|----------|
| `0x0` | `[count:u32=440][440 × u16 owner-id]` — the game display-order array (`0xffff` first, then the games, `0xf000`, `0xf010`). |
| `0x1` | `[count:u32=440][440 × u16]` = sequential `0x1000+k` resource ids (A2). |
| `0x14`,`0x15` | global platform list `[7][0,1,2,3,4,5,6]` (deduped, both ids → one payload). |
| `0x16` | a global PNG (~15 KB). |
| `0xffff` items `0x00/0x04/0x08/0x0c` banks, `0x9f..0xb0` | the platform **button names** for the Crossover profile (Right Trigger/Left Trigger/…/Guide, and R2/L2/Cross/… on PS). Note the Crossover profile's `0x9f` range holds button names, not per-game action labels; the dedicated button-name resource is items `0x4e..0x5f`. |

## 6. What this unlocks

- **Per-game action labels** for every button, per platform — join a device config to the
  DB by `gameUID` and read slot → action (`build_assets.py`).
- **Box art** for all 437 games by gameUID.
- **Translator catalog** — which games have Hip/ADS translators, their versions and
  reference platforms (`extract_translators.py` → `translator_catalog.json`).
- **Translator payloads** remain encrypted; recovering the key would expose the actual
  mouse→stick aim curves (see `TRANSLATOR_CRYPTO.md`).

Do not redistribute the `.ximmr` itself — it is copyrighted vendor data. Only derived,
non-verbatim data (label maps, catalogs) may be shared.
