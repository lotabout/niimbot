# Niimbot B1 — density → darkness firmware patch

> ## ⚠️ READ THIS FIRST
>
> - **Images on `main` are for firmware version `5.22` ONLY.** A port to firmware
>   `6.19` (hardware 6.01) lives on the **`niimbot-hw6.01` branch** — see *Branches* below.
> - **Flashing across major versions (e.g. 5.x ↔ 6.x, or → 4.x) WILL BRICK your
>   device.** Never flash a 5.22 image to a 6.x device, or a 6.x image to a 5.x device.
> - This project is **for experimentation and right-to-repair on hardware you own.**
> - **No warranty. Provided as-is. The author takes no responsibility whatsoever if
>   you brick your device or damage it in any way. You flash entirely at your own risk.**

---

## What this achieves

- **Full print darkness on any label** — including third-party / untagged / refill
  paper. Stock firmware throttles darkness on non-branded media; this removes that.
- **The density setting actually controls darkness.** Stock B1 firmware never wires
  the user's density value into the print head at all. This patch does:
  - `D1 → coeff 270 … D5 → coeff 400` (linear: `coeff = 270 + (d−1)·32.5`).
  - **D5 = solid black** (identical energy to the proven full-quality build).
  - **D3 is the practical minimum** on typical paper; D1 suits high-sensitivity stock.
- **Safe by design:** density only ever *reduces* energy below the proven-solid D5,
  so there is no over-burn or print-line timing risk.

## Branches

| Branch | Target | Images |
|--------|--------|--------|
| `main` | firmware `5.22` | `firmware/B1_5.22_density_coeff.bin`, `firmware/B1_5.22_thirdparty_fullquality.bin` |
| `niimbot-hw6.01` | firmware `6.19` / hardware `6.01` | `firmware/B1_6.19_density_coeff.bin` (density-controlled), `firmware/B1_6.19_thirdparty_fullquality.bin` (fixed full darkness) |

The 6.19 port is address-substituted, not re-engineered: the renderer entry points,
the soft-float multiply routine and the config struct are instruction-for-instruction
identical between 5.22 and 6.19, and the whole cave encoder is anchored by rebuilding
the upstream 5.22 image byte-for-byte (`repro/reproduce_522_density.py`). Full ledger
(address mapping, evidence, unverified items): `docs/B1_6.19_density_port_notes.md`.

```sh
# 6.19 density-controlled build — 10 read-only checks, then the root evidence
python3 repro/verify_b1_619_density.py
python3 repro/reproduce_522_density.py      # needs a stock B1_5.22.bin (see below)
```

## Compatibility

- **Model:** Niimbot B1 only.
- **Firmware:** `5.22` for `main`; `6.19` for the `niimbot-hw6.01` branch images. Check it in the Niimbot app or via `src/niimbot_b1.py info`.
- **Expected md5:** `firmware/B1_5.22_density_coeff.bin` → `023ff56326fe8c65f01b68f32ebdba99`.

## How to flash

1. Connect the B1 by USB. On Linux it enumerates as a serial port, `/dev/ttyACM0`.
2. Flash with the niimblue-node CLI (needs Node.js; `npx` fetches it automatically):

   ```sh
   # firmware 5.22 (main branch)
   npx @mmote/niimblue-node flash -t serial -a /dev/ttyACM0 -n 5.22 \
     -f firmware/B1_5.22_density_coeff.bin

   # firmware 6.19 / hardware 6.01 (niimbot-hw6.01 branch)
   npx @mmote/niimblue-node flash -t serial -a /dev/ttyACM0 -n 6.19 \
     -f firmware/B1_6.19_density_coeff.bin
   ```

3. The printer **powers itself off after flashing — press the power button** to turn
   it back on. It re-enumerates as `/dev/ttyACM0`; this is normal, not a brick.
4. Set density in the Niimbot app (or your print tool) and print. You should see a
   clear D1→D5 darkness progression.

### Revert / fallback

- `firmware/B1_5.22_thirdparty_fullquality.bin` — full darkness on any label, **no
  density control** (fixed solid). Same-major (5.x) safe.
- To go fully stock, reflash official `5.22` firmware from the Niimbot app / niimblue.
- **6.19 (branch `niimbot-hw6.01`):** revert target is official `6.19` firmware. Stock
  dumps are **not** distributed here (Niimbot copyright) — `repro/verify_b1_619_density.py`
  accepts `--src <stock B1_6.19.bin>` and `repro/reproduce_522_density.py` accepts
  `--src <stock B1_5.22.bin>`; both download from https://fw.niim.blue/stable/B1/.

## If your device is a different firmware version or model

**Do not flash the files here.** Instead, hand the docs to a capable coding LLM and
ask it to port the patch to *your* firmware dump:

- Feed it **`docs/B1_density_coefficient_checkpoint.md`** (the density work) and
  **`docs/B1_firmware_RE_checkpoint.md`** (the underlying darkness/coefficient model).
- Those document everything needed to redo it on another dump: the energy model
  (`darkness = renderer_input × coefficient`), how the real density byte was located,
  the renderer entry points to hook, the Cortex-M0 detour technique, the full cave
  assembly (`src/B1_5.22_density_hooks.s` + `.ld`), and the exact patch/byte map.
- Ask it to locate the equivalent renderer entries and density config byte in your
  dump and reproduce the input-scaling detours. **Verify on paper before flashing.**

*(That is exactly how the 6.19 / HW 6.01 port on branch `niimbot-hw6.01` was produced —
it is a worked example of the recipe, including the reference-free cave scan.)*

## Repository contents

| Path | What it is |
|------|------------|
| `firmware/B1_5.22_density_coeff.bin` | Main patch: density-controlled darkness (fw 5.22). |
| `firmware/B1_5.22_thirdparty_fullquality.bin` | Fallback: full darkness, no density control. |
| `docs/B1_density_coefficient_checkpoint.md` | Density feature RE + patch map (feed to an LLM to port). |
| `docs/B1_firmware_RE_checkpoint.md` | General B1 RE + darkness/coefficient model. |
| `src/B1_5.22_density_hooks.s` | Cortex-M0 code-cave detour source for the patch. |
| `src/B1_5.22_density_hooks.ld` | Linker script placing the caves/hook stubs at their fixed flash addresses. |
| `src/niimbot_b1.py` | Minimal B1 USB (CDC-ACM) driver for printing / testing. |
| `test-labels/dtest_D1.png … dtest_D5.png` | 384-px self-labeled density test images (D1–D5). |
| `firmware/B1_6.19_density_coeff.bin` | **fw 6.19 port**: density-controlled darkness. |
| `firmware/B1_6.19_thirdparty_fullquality.bin` | fw 6.19 fallback: full darkness, no density control. |
| `src/B1_6.19_density_hooks.s` / `.ld` | fw 6.19 cave assembly + linker script (address-substituted port). |
| `docs/B1_6.19_density_port_notes.md` | fw 6.19 port ledger: address mapping, evidence, open items (Chinese). |
| `build/`, `repro/` | Reproducible builders and read-only verifiers for both 6.19 images. |

## Testing

`src/niimbot_b1.py` prints 384-px-wide images over USB. Print each `test-labels/dtest_D*.png`
at its matching density to confirm the progression:

```sh
python3 src/niimbot_b1.py info                 # check firmware version first
python3 src/niimbot_b1.py image test-labels/dtest_D3.png --density 3
```
