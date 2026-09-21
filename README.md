# Niimbot B1 — density → darkness firmware patch

> ## ⚠️ READ THIS FIRST
>
> - **This firmware is for the Niimbot B1 on firmware version `5.22` ONLY.**
> - **Flashing across major versions (e.g. 5.x ↔ 6.x, or → 4.x) WILL BRICK your
>   device.** Do not flash these files to any other firmware version or model.
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

## Compatibility

- **Model:** Niimbot B1 only.
- **Firmware:** `5.22` only. Check it in the Niimbot app or via `src/niimbot_b1.py info`.
- **Expected md5:** `firmware/B1_5.22_density_coeff.bin` → `023ff56326fe8c65f01b68f32ebdba99`.

## How to flash

1. Connect the B1 by USB. On Linux it enumerates as a serial port, `/dev/ttyACM0`.
2. Flash with the niimblue-node CLI (needs Node.js; `npx` fetches it automatically):

   ```sh
   npx @mmote/niimblue-node flash -t serial -a /dev/ttyACM0 -n 5.22 \
     -f firmware/B1_5.22_density_coeff.bin
   ```

3. The printer **powers itself off after flashing — press the power button** to turn
   it back on. It re-enumerates as `/dev/ttyACM0`; this is normal, not a brick.
4. Set density in the Niimbot app (or your print tool) and print. You should see a
   clear D1→D5 darkness progression.

### Revert / fallback

- `firmware/B1_5.22_thirdparty_fullquality.bin` — full darkness on any label, **no
  density control** (fixed solid). Same-major (5.x) safe.
- To go fully stock, reflash official `5.22` firmware from the Niimbot app / niimblue.

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

## Testing

`src/niimbot_b1.py` prints 384-px-wide images over USB. Print each `test-labels/dtest_D*.png`
at its matching density to confirm the progression:

```sh
python3 src/niimbot_b1.py info                 # check firmware version first
python3 src/niimbot_b1.py image test-labels/dtest_D3.png --density 3
```
