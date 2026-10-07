# Niimbot B1 — firmware patch for hardware 6.01 / firmware 6.19

Firmware patch for the **Niimbot B1 on hardware 6.01 / firmware 6.19**: it removes the
vendor throttle that keeps third-party label stock faint, and it makes the density
setting **actually control the print head** (stock firmware never wires the density
value into the print engine at all).

- **Main branch: `niimbot-hw6.01`** — this page, targeting FW 6.19 / HW 6.01.
- `main` keeps the upstream [ThreeDaPrint/niimbot](https://github.com/ThreeDaPrint/niimbot)
  firmware **5.22** material untouched, as reference for how this port was derived.

> ## ⚠️ READ THIS FIRST
>
> - **The images on this branch are for firmware `6.19` (hardware 6.01) ONLY.** The 5.22
>   images live on `main`.
> - **Flashing across major versions WILL BRICK your device** (5.x ↔ 6.x, or → 4.x).
>   Never flash a 5.22 image to a 6.x device, or a 6.x image to a 5.x device.
> - This project is **for experimentation and right-to-repair on hardware you own.**
> - **No warranty. Provided as-is.** You flash entirely at your own risk.
> - Stock firmware is **not** distributed here (Niimbot copyright): fetch it from
>   <https://fw.niim.blue/stable/B1/> and keep a copy before you flash.

---

## What this patch does

1. **Full darkness on third-party / untagged / refill paper** — stock firmware throttles
   heat on non-branded media; this removes that throttle.
2. **The density setting actually does something.** Stock firmware only *stores* the
   user's density byte (and echoes it back via GetInfo); the value never reaches the
   print head. This patch reads it and scales the render energy.
3. **D5 = solid black**, energy-identical to the proven full-quality build; lower
   densities only *reduce* energy below that, so there is no over-burn and no
   print-line timing risk.
4. **Untagged paper prints at all.** Firmware 6.19 (unlike 5.22) refuses to print when it
   cannot read a label RFID tag: every job on third-party paper fails with
   `0xDB 0x14` / niimblue `Print error 20: WriteRfidFail` — on **stock** 6.19 too. Both
   images carry a 1-byte bypass that makes a failed tag read return silently; genuine
   rolls (tag read OK) are handled exactly as before. Details:
   `docs/B1_6.19_rfid_bypass.md`.

## Images

| File | md5 | What it is |
|---|---|---|
| `firmware/B1_6.19_density_coeff.bin` | `89b78b234df74ab6d62e8fc5025eaab1` | **Recommended**: density-controlled darkness (D1–D5) |
| `firmware/B1_6.19_thirdparty_fullquality.bin` | `76b55d0472110e6da95f5c0fb68d09e1` | Fixed full darkness, **no** density control |

Both are **124436 bytes**, the same size as stock 6.19 (no partition changes).
SHA-256 sums for every file: `repro/SHA256SUMS.txt`.

## How it works

```
per-dot burn ≈ renderer input × energy coefficient
```

Stock firmware keeps 15 IEEE-754 energy coefficients in flash and picks a low set per
paper type — that is why third-party paper prints faint. The patch does two things:

**Build A (fixed full quality)** — data-only rewrite:
- 15 coefficients (4 base + 6 renderer A + 5 renderer B) → `400.0`
- the 64-entry line-period table → `floor(old × 1.5)` (slower feed = more heat budget per line)
- two RFID curve-flag bytes `03 21` → `00 21` (following the upstream build; harmless)
- the 6.19-only RFID read-failure bypass: `0x01025478` `02 28` → `ff 28`
  (`cmp r0,#2` → `cmp r0,#0xff`), so a tag read that fails during printing no longer
  escalates to error `0x14` (see `docs/B1_6.19_rfid_bypass.md`)

**Build B (density-controlled)** = build A **+ 4 code injections**: one `bl` right after
each renderer's entry `push`, jumping into a code cave in free flash, which scales the
renderer's stacked input float by

```
m(d) = coeff(d) / 400
```

| Density | m | Equivalent coeff | Notes |
|---|---|---|---|
| D1 | 0.675 | 270 | high-sensitivity thermal paper |
| D2 | 0.75625 | 302.5 | |
| D3 | 0.8375 | 335 | practical minimum on typical paper |
| D4 | 0.91875 | 367.5 | |
| **D5** | **1.0** | **400** | **solid black, energy-identical to build A** |

Injection points (measured on 6.19; full ledger in `docs/B1_6.19_density_port_notes.md`):

| Item | Upstream 5.22 | This device (6.19) |
|---|---|---|
| density byte | `0x00020704` | `0x00020740` |
| firmware soft-float multiply | `0x0102529a` | `0x01026156` |
| renderer A / B entry | `0x01016124` / `0x01016844` | `0x010161ec` / `0x0101690c` |
| code cave A / B | `0x0102bbec` / `0x0102bc4a` | `0x0102cb64` / `0x0102c1ee` |

## Branches

| Branch | Target | Contents |
|---|---|---|
| **`niimbot-hw6.01`** (main branch) | **FW 6.19 / HW 6.01** | the 6.19 port, builders, verifiers, port ledger |
| `main` | FW 5.22 | upstream ThreeDaPrint material as-is (5.22 builds, RE docs, cave assembly) |

## Repository contents

| Path | What it is |
|---|---|
| `firmware/B1_6.19_density_coeff.bin` | **Build B**: density-controlled darkness (HW 6.01 / FW 6.19) |
| `firmware/B1_6.19_thirdparty_fullquality.bin` | **Build A**: fixed full darkness, no density control |
| `build/build_b1_619_density.py` | Build B builder (Thumb `bl` encoder, cave assembly, self-checks) |
| `build/build_b1_619.py` | Build A builder |
| `repro/verify_b1_619_density.py` | Build B read-only verifier (10 checks, incl. capstone disassembly read-back) |
| `repro/verify_b1_619.py` | Build A read-only verifier (7 checks) |
| `repro/reproduce_522_density.py` | **Root evidence**: rebuilds the upstream 5.22 density image byte-for-byte with the same cave encoder |
| `repro/verify_recipe_on_522.py` | **Root evidence**: rebuilds the upstream 5.22 full-quality image byte-for-byte |
| `repro/SHA256SUMS.txt` | SHA-256 of every file in this branch |
| `src/B1_6.19_density_hooks.s` / `.ld` | 6.19 cave assembly + linker script (equivalent source; see ledger §6) |
| `docs/B1_6.19_density_port_notes.md` | 6.19 port ledger: address mapping, evidence chain, open items |
| `docs/B1_6.19_rfid_bypass.md` | Why 6.19 refuses untagged paper (`WriteRfidFail`) and the 1-byte bypass, with the RE chain |
| `docs/B1_density_coefficient_checkpoint.md` | Upstream 5.22 density RE + patch map (read this to port to another dump) |
| `docs/B1_firmware_RE_checkpoint.md` | Upstream 5.22 energy model and general B1 RE |
| `src/niimbot_b1.py` | Minimal B1 USB (CDC-ACM) driver for printing / testing |
| `test-labels/dtest_D1..D5.png` | 384-px self-labeled test images (print each at its density) |

## Flashing

1. Connect the B1 by USB. On Linux it enumerates as `/dev/ttyACM0`.
2. Flash with the niimblue-node CLI (needs Node.js; `npx` fetches it automatically):

   ```sh
   # Build B (recommended) — density D1..D5 active
   npx --yes @mmote/niimblue-node flash -t serial -a /dev/ttyACM0 -n 6.19 \
     -f firmware/B1_6.19_density_coeff.bin

   # or build A — fixed full darkness, density setting ignored
   npx --yes @mmote/niimblue-node flash -t serial -a /dev/ttyACM0 -n 6.19 \
     -f firmware/B1_6.19_thirdparty_fullquality.bin
   ```

3. The printer **powers itself off after flashing — press the power button** to turn it
   back on. It re-enumerates as `/dev/ttyACM0`; that is normal, not a brick.
4. Success looks like `FirmwareNoMoreChunks → In_FirmwareCheckResult → FirmwareCommit`.

### Revert

- Reflash **stock 6.19** (same major version, safe): md5
  `fd9efd1441b5f05ca46c310b8d162dc1`, from <https://fw.niim.blue/stable/B1/B1_6.19.bin>.
- Build A can also serve as a fallback if density control turns out unusable on your paper.
- ⚠️ **Never** flash a 5.22 image (upstream or from `main`) onto this device.

## Reproduce and verify

```sh
# 1) read-only verification (10 checks; check 8 is skipped if capstone is absent)
python3 repro/verify_b1_619_density.py --src <stock B1_6.19.bin>

# 2) rebuild build B from stock (omit --out for a dry run)
python3 build/build_b1_619_density.py --src <stock B1_6.19.bin> --out rebuilt.bin

# 3) root evidence: rebuild the upstream 5.22 density image with the same cave encoder
python3 repro/reproduce_522_density.py --src <stock B1_5.22.bin>
```

Stock images are not distributed here; download them from
<https://fw.niim.blue/stable/B1/>. Step 3 additionally needs the upstream 5.22 images kept
on `main`. Check 8 needs `pip install capstone`.

## Proven / not proven

**Proven (byte level)**

- Build B rebuilds byte-for-byte from stock 6.19 (md5 `89b78b23…`); all 271 changed bytes
  fall inside the expected regions — **0 bytes outside**.
- All 15 coefficients, the 64 line-period entries, both RFID flags, the RFID bypass byte,
  both hook `bl` literals and both code caves were checked item by item; capstone disassembly read-back
  confirms the `bl` targets, the stack offsets `0x38/0x3c/0x40` and the replayed displaced
  instructions.
- The cave encoder itself is anchored by upstream: with the same encoder and only the
  addresses swapped, the published 5.22 density image (`023ff563…`) is reproduced
  byte-for-byte — **0 bytes difference**.
- The 6.19 renderer entries, soft-float multiply routine and config struct are
  instruction-for-instruction identical to 5.22 (first 20–48 bytes each).

**Not proven (do not treat as established)**

- **Never flashed or printed on any device** — everything above is static analysis plus
  byte-exact reproduction of released images.
- `400.0` and the m-table are values upstream calibrated on **5.22** (200 faint / 250 not
  solid / 325 close / 370 nearly / 400 solid / 500 solid / 700 still solid). Your 6.19
  print head batch, supply and paper may differ.
- The `×1.5` line-period timing is unverified on 6.19 (upstream verified ×1.5 as safe and
  ×2 as dropping lines on 5.22 hardware).
- **Dual-colour is not a B1 feature**: the vendor confirms the B1 (non-PRO) cannot print
  red/black dual-layer paper — that needs a **B1 PRO**. Builds A and B also raise renderer
  A's six coefficients to 400, which on a dual-colour head would collapse the red energy
  window; this device has no such window to lose, so no variant is needed.

## Testing notes

1. **Use third-party / untagged thermal paper.** Genuine Niimbot stock carries an RFID tag
   and always prints dark regardless of firmware, so it cannot show any difference.
2. Take a baseline print on third-party paper **before** flashing, for comparison.
3. Set the correct paper type (gap / black-mark / continuous) before judging darkness.
   Without an RFID tag the printer cannot learn the type from the roll, so the host has
   to send it; a positioning calibration can be triggered without a tag with
   `python3 src/niimbot_b1.py calibrate --type gap` (see `docs/B1_6.19_rfid_bypass.md` §4).
4. Print `test-labels/dtest_D1..D5.png` (or your own image): darkness should increase
   monotonically D1 → D5, with D5 solid black.
5. **Over-burn** (ink bleeding, fuzzy edges, scorched coating) means your energy window is
   lower than 5.22's: rebuild with a lower coefficient, e.g.
   ```sh
   python3 build/build_b1_619.py --coeff 300 --feed 1.5 --out firmware/B1_6.19_c300.bin
   ```
6. Print/test helper:
   ```sh
   python3 src/niimbot_b1.py info          # check the firmware version first
   python3 src/niimbot_b1.py image test-labels/dtest_D3.png --density 3
   ```

## How this port was made

This branch — the disassembly work, the cave encoder, the reproducible builders and every
verifier under `build/` and `repro/` — was produced with **DeepSeek Harness (DSH)**, a
local agentic coding environment, working against a firmware dump of the author's own
printer. Nothing was hand-patched: each step is a re-runnable script in this repository.

1. **Disassemble and compare.** Capstone decodes both dumps side by side; the renderer
   entries, the soft-float multiply routine and the config struct turned out to be
   instruction-for-instruction identical between 5.22 and 6.19, which reduced the job to
   swapping addresses.
2. **Locate the density byte.** Found through the config validator's clamp signature
   (`[CFG+4]` → 1..5, default 3) and the SetDensity handler's `strb`, then cross-checked
   through the reference chain — the whole `0x207xx` block shifts by +0x3C between the two
   versions.
3. **Find safe code caves.** The dump was scanned for zero runs that are *also*
   unreferenced (no literal-pool pointer, no branch target). Only two runs qualified; the
   others are referenced data.
4. **Emit the cave with a purpose-built encoder.** A small Python Thumb-1 encoder writes
   the `bl` instructions and the cave bytes, then decodes them back for self-checking — no
   ARM toolchain is needed to rebuild the image.
5. **Anchor the tooling on a released image first.** Before touching 6.19, the same encoder
   rebuilds the published 5.22 density image byte-for-byte (0 bytes difference). That is
   what makes the 6.19 result auditable rather than merely plausible.
6. **Verify read-only, then publish.** A 10-check verifier re-derives the image,
   disassembles it back and asserts that every changed byte lies inside an expected region.

The whole chain can be re-run without trusting the author:

```sh
python3 repro/reproduce_522_density.py --src <stock B1_5.22.bin>   # anchor on upstream
python3 build/build_b1_619_density.py  --src <stock B1_6.19.bin>   # rebuild this image
python3 repro/verify_b1_619_density.py --src <stock B1_6.19.bin>   # verify it read-only
```

## Other models or firmware versions

**Do not flash these images.** Instead, hand `docs/` to a capable coding LLM and have it
redo the patch on your own dump:

- `docs/B1_density_coefficient_checkpoint.md` — density feature RE + patch map + cave assembly
- `docs/B1_firmware_RE_checkpoint.md` — energy model, coefficient locations, Cortex-M0 detour technique

This branch is a worked example of that recipe: first prove your tooling by reproducing a
**released** upstream image byte-for-byte, then substitute the addresses on the new dump,
then confirm each new address from the disassembly and the code's own reference chain.
Before reusing a code cave, re-run the reference-free zero-run scan — in the 6.19 dump only
two zero runs were both large enough and completely unreferenced; the others are
referenced data.

## Credits and licence

- Upstream project: [ThreeDaPrint/niimbot](https://github.com/ThreeDaPrint/niimbot) — the
  5.22 patch, the RE checkpoints and the cave assembly all originate there.
- This repository is a fork; `main` keeps the upstream material as-is and
  `niimbot-hw6.01` is the 6.19 / HW 6.01 port.
- The upstream project states **no explicit open-source licence**, only an as-is,
  no-warranty disclaimer. Evaluate the legal risk of using, modifying or redistributing it
  yourself; the firmware itself remains Niimbot's copyright.
