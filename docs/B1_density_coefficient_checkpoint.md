# NIIMBOT B1 — density→coefficient feature checkpoint

Making the **density knob (1–5) actually control print darkness** on firmware **5.22**, by
runtime-scaling the render energy from the real density value. Written 2026-09-19.

This builds on `B1_firmware_RE_checkpoint.md` (general firmware facts, load recipes, the
coefficient/darkness model, flashing). Read that first; this doc covers only the density work.

---

## 0. TL;DR outcome

- **Result:** density now gives a clear darkness progression. `D1 → coeff 270 … D5 → coeff 400`
  (linear: `coeff(d) = 270 + (d−1)·32.5`). D5 = solid black (identical to the locked coeff-400
  build). On typical third-party paper **D3 is the practical minimum**; D1 suits high-sensitivity
  thermal paper.
- **Why density never worked before:** the B1 firmware **never wires the user density into the
  print engine.** The heat/energy code reads a byte at `0x2007f`, which is a **motor/phase byte**
  (set to 2 or 8 during printing by `FUN_010170f0`), *not* density. The real density is stored in
  a config struct and only echoed back via GetInfo — it never reaches the head.
- **Real density byte: `0x20704`** (config struct `0x20700`, offset +4; range 1–5, default 3).
- **Fix:** keep the 11 renderer coefficients pinned at 400 (solid) and, at each renderer entry,
  **scale the renderer's input float by `m(density) = coeff(density)/400`** via two code-cave
  detours. At D5 `m=1.0` (no change → proven-solid); lower densities only *reduce* energy, so
  there is no over-burn or line-timing risk.
- **Final firmware:** `B1_5.22_density_coeff.bin` (md5 `023ff56326fe8c65f01b68f32ebdba99`).
  It is the coeff-400 solid build + 4 detour patches (112 bytes changed). Source of the cave
  assembly: `B1_5.22_density_hooks.s`. Revert target: `fw/B1_5.22.bin` (stock) or
  `B1_5.22_thirdparty_fullquality.bin` (fixed coeff-400, no density).

---

## 1. The energy model (how darkness is actually produced)

```
per-dot burn  ≈  renderer_input  ×  coefficient
```
- **Coefficients:** 11 IEEE floats in flash, in the two renderers `FUN_01016124` /
  `FUN_01016844` (addresses in the base checkpoint §5). All pinned to **400.0** = solid black.
  Flash is read-only at runtime, so they can't be changed per-print.
- **Renderer input:** a per-print float the caller passes to the renderers:
  - `FUN_01016124(…, arg5 = *(u32*)(state+0xac))`   → `state+0xac = 0x208fc`
  - `FUN_01016844(…, arg6 = *(u32*)(state+0xac), arg7 = *(u32*)(state+0xb0))` → `0x208fc`, `0x20900`
  - `state = 0x20850` (print-state struct). These inputs are written **indirectly** (no absolute
    xref), so the write site can't be cleanly hooked either.
- Since output scales linearly with **both** input and coeff, multiplying the *input* by
  `m = coeff(d)/400` is equivalent to using `coeff = 400·m = coeff(d)` — with the coeffs left at
  400. That is the lever the detours use.

**Density's real path (dead for energy):** host `SetDensity` → `0x20704`. `GetInfo(density)`
reads it back (round-trips correctly). But the renderers never read `0x20704`; nothing copies it
into the render input. Hence density had zero effect until this patch.

---

## 2. Finding the real density byte (the hard part)

`0x2007f` (read by every "density-looking" `*(x) & 0x7f` in the heat code) is a **red herring** —
its only writer is `FUN_010170f0`, which stores 2/8 (a motor/phase value). Reading it gave a
constant → the first build printed uniformly (~coeff 302 = `m(2)`), no progression.

The command dispatch is fragmented (a text/AT console, a BLE "bt" dispatcher, an RX state machine
`FUN_0101ee60`, the packet validator `FUN_0101edf4`), and `SetDensity` is **not** in any switch8
jump table or `cmp #0x21` chain. What cracked it:

1. **Config-validator signature.** `FUN_01010d1a` clamps a config struct (`DAT_01010e60 =
   0x20700`): `CFG[4]`→1..5 default 3, `CFG[5]`→1..3 default 2, `CFG[6]`→1..5 default 1.
   `CFG[6] = 0x20706` is the **paper type already used by the heat code**, which pins `CFG = 0x20700`.
   ⇒ **density = `CFG+4 = 0x20704`** (matches range 1–5, default 3).
2. **Defaults confirm it.** `FUN_0101cfc6` writes the factory defaults `[4]=3, [5]=2, [6]=1`.
3. **SetDensity handler confirms it.** `FUN_01021db0` clamps the payload to 1..5 and does
   `strb r0, [0x20700 + 4]` (i.e. writes `0x20704`); the next handler `FUN_01021dec` is
   SetLabelType writing `0x20706`.
4. **GetInfo round-trip** (over USB) proved the stored value is live: set 1→reads 1, set 5→reads 5.

Config struct `0x20700`: `+4` density(1–5), `+5` speed(1–3), `+6` paper type(1–5).

---

## 3. The hook design (Cortex-M0 detour)

Constraints: ARMv6-M has **no 32-bit unconditional branch (B.W)**, and `ldr pc,[pc]` can't target
`pc`. Detouring the *first* instruction would clobber `lr` (the renderer's return address) before
the entry `push` saves it.

Solution: **detour the instruction right after the entry `push {r0-r3,r4-r7,lr}`.** By then `lr`
and `r0-r3` are on the stack, so a `bl` into a code cave is safe. The cave scales the stacked
input float(s), replays the two displaced instructions, and returns via `pop {pc}`.

Stacked-arg offsets (post entry-push of 9 regs, then the detour's `push {r0-r3,lr}` of 5 regs):
- `FUN_01016124` detour @ `0x01016126`: input arg5 at `[sp,#0x38]`.
- `FUN_01016844` detour @ `0x01016846`: arg6 at `[sp,#0x3c]`, arg7 at `[sp,#0x40]` (arg5 is an
  integer count — left alone).

Shared `scale(r0)→r0` helper: read density `0x20704`, `& 0x7f`, clamp 1..5, index a 5-entry float
table, and multiply via the firmware's own soft-float `FUN_0102529a` (`blx` to `0x0102529b`).

`m(d) = coeff(d)/400`:

| d | coeff | m | float bytes (LE) |
|---|------:|------:|---|
| 1 | 270   | 0.675   | `cd cc 2c 3f` |
| 2 | 302.5 | 0.75625 | `9a 99 41 3f` |
| 3 | 335   | 0.8375  | `66 66 56 3f` |
| 4 | 367.5 | 0.91875 | `33 33 6b 3f` |
| 5 | 400   | 1.0     | `00 00 80 3f` |

**Safety:** `m ≤ 1` always ⇒ energy never exceeds the proven-solid coeff-400 config ⇒ no
over-burn, no strobe-vs-line-period timing break (the failure mode of forcing the strobe register,
base checkpoint §4.5). D5 is byte-for-byte energy-equivalent to the locked solid build.

### Cave assembly (`B1_5.22_density_hooks.s`)
```asm
    .syntax unified
    .cpu cortex-m0
    .thumb
    /* Cave A @ 0x0102bbec : shared scale + m-table */
    .section .caveA,"ax",%progbits
    .thumb_func
scale:                       @ r0=input float -> r0 = input * m(density)
    push {r4, lr}
    ldr  r4, =0x00020704     @ &density  (config struct +4)
    ldrb r4, [r4]
    movs r1, #0x7f
    ands r4, r1
    cmp  r4, #1
    bhs  1f
    movs r4, #1
1:  cmp  r4, #5
    bls  2f
    movs r4, #5
2:  subs r4, r4, #1
    lsls r4, r4, #2
    ldr  r1, =mtable
    ldr  r1, [r1, r4]        @ r1 = m(d)
    ldr  r3, =0x0102529b     @ FUN_0102529a | thumb
    blx  r3                  @ r0 = r0 * r1
    pop  {r4, pc}
    .align 2
mtable: .float 0.675, 0.756250, 0.837500, 0.918750, 1.0
    .ltorg
    /* Cave B @ 0x0102bc4a : renderer detours */
    .section .caveB,"ax",%progbits
    .thumb_func
det124:                      @ FUN_01016124 detour (after entry push)
    push {r0-r3, lr}
    ldr  r0, [sp, #0x38]     @ arg5 (renderer input)
    bl   scale
    str  r0, [sp, #0x38]
    pop  {r0-r3}
    .short 0x4616            @ displaced: mov  r6, r2
    .short 0x36ff            @ displaced: adds r6, #0xff
    pop  {pc}                @ -> 0x0101612a
    .thumb_func
det844:                      @ FUN_01016844 detour (after entry push)
    push {r0-r3, lr}
    ldr  r0, [sp, #0x3c]     @ arg6
    bl   scale
    str  r0, [sp, #0x3c]
    ldr  r0, [sp, #0x40]     @ arg7
    bl   scale
    str  r0, [sp, #0x40]
    pop  {r0-r3}
    .short 0x4614            @ displaced: mov r4, r2
    .short 0x4606            @ displaced: mov r6, r0
    pop  {pc}                @ -> 0x0101684a
    /* 4-byte detour stubs installed over the renderer entries */
    .section .hook124,"ax",%progbits
    bl   det124              @ overwrites 0x01016126
    .section .hook844,"ax",%progbits
    bl   det844              @ overwrites 0x01016846
```
Assemble/link at fixed addresses:
```bash
arm-none-eabi-as -mcpu=cortex-m0 -mthumb hooks.s -o hooks.o
arm-none-eabi-ld -T hooks.ld hooks.o -o hooks.elf      # .caveA@0x0102bbea .caveB@0x0102bc4a
                                                       # .hook124@0x01016126 .hook844@0x01016846
arm-none-eabi-objcopy -O binary --only-section=.caveA hooks.elf caveA.bin   # etc.
```

---

## 4. Patch map (density build = coeff-400 base + these 4 patches)

Base (from `B1_firmware_RE_checkpoint.md` §5, builder `build(400,…, feed=1.5)`): 15 float coeffs →
400.0, line-period table ×1.5, RFID flag `03 21`→`00 21` at `0x1021d84` & `0x1021ec8`.

| Site (vaddr) | file off | original | patched | meaning |
|---|---|---|---|---|
| `0x01016126` | `0x6126` | `16 46 ff 36` | `15 f0 90 fd` | `bl det124` (detour after FUN_01016124 push) |
| `0x01016846` | `0x6846` | `14 46 06 46` | `15 f0 09 fa` | `bl det844` (detour after FUN_01016844 push) |
| `0x0102bbec` | `0x1bbec` | zeros (68 B) | cave A | `scale` + m-table + literal pool |
| `0x0102bc4a` | `0x1bc4a` | zeros (44 B) | cave B | `det124` + `det844` |

Cave A bytes:
`10b50d4c24787f210c40012c00d20124052c00d90524013ca40008490959084b984710bd` +
`cdcc2c3f 9a99413f 6666563f 33336b3f 0000803f` (m-table) +
`04070200 10bc0201 9b520201` (pool: `0x00020704`, `0x0102bc10`, `0x0102529b`)

Cave B bytes:
`0fb50e98fff7cdff0e900fbc1646ff3600bd0fb50f98fff7c4ff0f901098fff7c0ff10900fbc1446064600bd`

Code caves were chosen from **reference-free zero-runs** (a Ghidra pass counting refs into each
zero run). `0x0102bbea` (86 B) and `0x0102bc49` (61 B) were clean; the section aligner placed the
code at `…bbec` / `…bc4a`. Do **not** reuse the other zero-runs — several are referenced data.

To re-tune the mapping: edit the 5 floats in `mtable` (any per-density values ≤ 1.0 stay safe;
> 1.0 would risk over-burn/timing), reassemble, rebuild, reflash.

---

## 5. Techniques that were decisive here (beyond the base checkpoint)

1. **Force-create functions at every `push {…,lr}` prologue, then decompile all.** Much of the
   command/config code is reached only indirectly, so Ghidra never auto-creates it. A pre-script
   that force-creates at every `0xb5xx` (bit-8 set) prologue turned ~280 auto functions into ~729
   and exposed the config accessors.
2. **Config-validator clamp signature.** A function that clamps several bytes to small ranges
   (`if (N < byte-1) byte = default`) *is* the settings validator; the clamp bounds/defaults
   identify each field (density 1–5/3, speed 1–3/2, type 1–5/1). This located `0x20704` when the
   command dispatch itself was untraceable.
3. **GetInfo round-trip as ground truth.** `SetDensity(d)` then `GetInfo(density)` over USB proved
   which values are live and stored, independent of static analysis.
4. **Reference-free zero-run scan** to find safe code caves (and to reject zero-runs that are
   actually zeroed data tables).
5. **Empirical probe → correction.** The first build (reading `0x2007f`) printing *uniformly*
   was the clue that the address was a constant, not density — which redirected the search to the
   real config byte.

### Dead ends (don't repeat)
- `0x2007f` is a motor/phase byte, **not** density (reads 2/8 during print).
- `SetDensity` (`0x21`) is **not** in any switch8 command table or `cmp #0x21` chain; those all
  belong to the text console / BLE state machine. Find config fields via the validator instead.
- Renderer coeffs (flash) and the render-input write site (indirect) are both un-hookable → hook
  the renderer *entries* and scale the stacked input.
- On Cortex-M0 you cannot far-jump off the first instruction without losing `lr`; detour *after*
  the entry `push`.

---

## 6. Flash & test (unchanged tooling)

```bash
# Flash the density build (printer awake, in dialout)
npx --yes @mmote/niimblue-node flash -t serial -a /dev/ttyACM0 -n 5.22 -f B1_5.22_density_coeff.bin
# printer powers OFF after flash -> press power to boot

# Per-density sweep (self-labeled D1..D5 images; darkness set by -q)
for d in 1 2 3 4 5; do
  npx @mmote/niimblue-node print -t serial -a /dev/ttyACM0 -p B1 -q $d -l 1 dtest_D$d.png
done
```
Expected: monotonic darkening D1→D5; D5 solid black. `dtest_D1..5.png` are the 384-px test labels
(solid band + big D#, generated by the snippet in the base checkpoint §8). Density persists across
prints (host sends `SetDensity` before each job).

**Revert:** flash `B1_5.22_thirdparty_fullquality.bin` (fixed solid, no density) or `fw/B1_5.22.bin`
(stock). No internal CRC; brick risk low (separate bootloader). Same-major (5.x) only.

---

## 7. Files

- `B1_5.22_density_coeff.bin` — **final, flashed** (md5 `023ff56326fe8c65f01b68f32ebdba99`).
- `B1_5.22_density_hooks.s` — the cave assembly source.
- `B1_5.22_thirdparty_fullquality.bin` — fixed coeff-400 solid (no density); revert/fallback.
- stock `B1_5.22` firmware — not distributed here (Niimbot copyright); obtain via the official Niimbot app / niimblue if you need to revert to stock.
- `B1_firmware_RE_checkpoint.md` — the general RE + tuning checkpoint (prerequisite reading).
