# NIIMBOT B1 firmware RE + tuning checkpoint

Reverse-engineering the B1 app firmware to make **third-party (untagged) labels print
at full quality**, plus how to flash and test. Written 2026-09-19 for firmware **5.22**.

---

## 0. TL;DR outcome

- The RFID "quality throttle" was a **red herring** — it did not cause the faint prints.
- Faint prints were an **energy problem** on less-sensitive third-party paper:
  1. **Thermal history compensation** starved black dots repeated across consecutive
     rows → solid fills printed only their leading edge.
  2. **Base heat too low** for this paper.
- **Fix:** raise ~15 float coefficients in the image and reflash. Working value = **400.0**
  (feed slowed ×1.5 for headroom). Result: solid black, crisp text, no over-burn.
- **Density (1–5) does nothing** — it is computed into a write-only field. The coefficients
  are the only real darkness control.
- Final firmware: `B1_5.22_thirdparty_fullquality.bin` (coeff 400). Stock: `fw/B1_5.22.bin`.

---

## 1. Firmware facts (load parameters)

| Property | Value |
|---|---|
| File | `fw/B1_5.22.bin`, 120288 bytes (raw, headerless) |
| Arch | ARM **Thumb, Cortex-M0** (no movw/movt; constants via LDR-literal pools + ADR) |
| App load base | **0x01010000** |
| SRAM base | **0x00020000** (Yichip low-mapped, NOT 0x20000000) |
| Peripherals | ~**0x000Fxxxx** (e.g. timer at 0x000f0c40) |
| Bootloader | separate 64 KB at **0x01000000**, **NOT in the .bin** (handles DFU/flash) |
| Version word | **0x0516 = 5.22** (major=high byte 5, minor=low byte 0x16=22); hw 0x050a = 5.10 |
| Integrity | CRC handled by the flash **transfer protocol**; **no internal CRC** in the image to fix. Magic `67 e3 c9 65` at file 0x1d5da is just an end marker. |
| MCU | Yichip YC3121-L (Cortex-M0 BLE SoC) |

Version-encoding gotcha: `niimbot_b1.py info` prints version as raw/100, so 0x0516 shows as
"13.02" and 0x050a as "12.9" — both are the same 5.22 / 5.10. `niimblue-node info` prints
it correctly as `0x0516 (5.22 or 13.02)`.

---

## 2. Tooling

Installed and used:

- **radare2 5.5.0** — interactive disassembly, strings, ESIL-based xrefs.
- **Ghidra 12.1.3** (`/opt/ghidra_12.1.3_PUBLIC`) — decompiler + reference search (the workhorse).
- **arm-none-eabi-{objdump,gcc,nm}** — available; barely needed (r2+Ghidra covered everything).
- **Python 3 (`struct`)** — locate pool/float constants, byte-patch, build variants.
- **`@mmote/niimblue-node`** (via `npx`) — flash/info/print over serial. THE flashing path.
- capstone (earlier attempts) — **hit a ceiling**, see dead ends.

### radare2 load recipe (raw firmware at correct base)
```bash
r2 -q -n -a arm -b 16 -m 0x01010000 \
   -e asm.arch=arm -e asm.bits=16 -e scr.color=0 -e scr.utf8=false \
   -c 'om' fw/B1_5.22.bin
# then inside: `aa; aae` (ESIL) to resolve ADR/pool refs, `axt <addr>` for xrefs,
# `pdf @ <addr>` / `pd N @ <addr>` to disassemble, `izz~<substr>` for strings.
```
`-n` skips bin parsing; `-m 0x01010000` maps the file at the right vaddr. Do NOT use `-B`
on this raw file (it warns and mis-maps).

### Ghidra headless recipe
```bash
GH=/opt/ghidra_12.1.3_PUBLIC
$GH/support/analyzeHeadless <projdir> <projname> \
  -import fw/B1_5.22.bin \
  -processor ARM:LE:32:Cortex \
  -loader BinaryLoader -loader-baseAddr 0x01010000 \
  -scriptPath <dir-with-scripts> \
  -preScript AddRam.java \        # <-- CRITICAL: maps RAM so RAM xrefs resolve
  -postScript <YourScript>.java \
  -deleteProject
```

---

## 3. What was USEFUL (do this)

1. **Ghidra + a mapped RAM block.** Adding an uninitialized block at 0x00020000 (len 0x40000)
   BEFORE analysis lets the decompiler resolve reads/writes to RAM globals. Without it you
   can't trace state variables (RFID flag, heat vars). This unlocked everything.
2. **"FindReaders" script** — given an address (RAM or code), list every reference and
   decompile each referencing function. Single most valuable tool for tracing a flag/global
   to its producers and consumers.
3. **Force-create functions in analysis "gaps."** Much of the print/calibration code is only
   reached via indirect/command-table calls, so Ghidra never auto-creates those functions.
   Find the `push {..,lr}` prologues (via r2) and force a function at each, then decompile.
4. **radare2 ESIL (`aae`) for ADR references.** The `LABEL RFID OK/ERR` strings are reached
   via `adr` (PC-relative), which capstone's literal-pool scan can't see. `axt` after `aae`
   found them instantly.
5. **Python constant search.** Locate which literal pools hold a given RAM pointer (scan for
   the 4-byte LE value, word-aligned), and decode float constants (`struct.unpack('<f', ...)`).
   This is how the heat coefficients (IEEE floats like 60.0, 150.0) were found.
6. **The empirical patch→flash→test loop.** When static analysis was ambiguous (which of
   several "heat" values is live), a bold firmware change + one test print was decisive. The
   real darkness lever was confirmed this way, not by reading code alone.
7. **Diagnostic print patterns** (see §7) — a banded solid/white pattern instantly
   distinguishes history-comp failure vs low base heat vs a feed/label-size problem.

---

## 4. DEAD ENDS (don't repeat)

1. **capstone-only window scanning.** False positives in the soft-float library region
   (float exponent bytes 0x7f=127, 0x96=150 look like addresses); can't resolve ADR or
   indirect accesses. Superseded by r2/Ghidra.
2. **The RFID "throttle" / `0x204aa` curve flag = RED HERRING for faintness.** Fully traced:
   RFID validity `0x205fb` → predicate `FUN_01021a7c` → curve-mode selector `0x204aa`
   (0=full, 3=degraded) → renderers `FUN_01016124`/`FUN_01016844`. Patching the two
   `movs #3`→`#0` sites (0x1021d84, 0x1021ec8) forced full mode — **but `0x204aa` was already
   0 in normal prints, so it changed nothing.** The community RFID-throttle story did not
   explain the faint output. (Kept the patch anyway; harmless.)
3. **The density→heat curve is architecturally DEAD.** `FUN_01011bee` correctly computes
   `heat = (int)(density*2 * paper_coeff)` (helpers: `FUN_0102529a`=float multiply,
   `FUN_01025796`=float→int, `FUN_01025712`=int→float) and stores it at **printbase+0x80+0x1e
   (0x208ee), which is WRITE-ONLY.** The strobe reads **printbase+0x80+0x20 (0x208f0)**, a
   different field. So density has no effect and chasing it was wasted effort.
4. **`FUN_01024de8` is NOT a heat function** — it's software integer division (Cortex-M0 has
   no hardware divide). Calls like `(x, 800)` mean `x/800`.
5. **Forcing the strobe register broke timing.** `FUN_01011b38` → `FUN_01017a90` writes the
   strobe width to `0x2ad84+0x12`; forcing it to a fixed large value (2000) + slowing feed
   ×2 made the strobe exceed the line period → missed/merged lines ("only one line prints").
   **Don't force a fixed strobe; scale the float coeffs instead** (the renderer path
   self-manages against the line-period budget).
6. **Flashing via the niim.blue WEBSITE failed in this environment.** In an
   automation-controlled Chrome, WebSerial connect kept timing out (heartbeat), and the
   native serial-port picker can't be automated anyway. Use the **niimblue-node CLI** instead
   (works perfectly over /dev/ttyACM0).
7. **Indirect writes are invisible to Ghidra's absolute-address xref search.** Globals
   written via a register-held pointer + offset (e.g. 0x208f0) show reads but "no writers."
   Expect this; fall back to empirical testing rather than assuming the value is unused.

---

## 5. The real mechanism + patch map

Darkness is controlled by float coefficients (defaults in parens). Higher = darker,
**up to a line-period clamp (you cannot over-burn by raising them — confirmed clean at 700).**

**Base density→heat coefficients** (per paper type; `FUN_01011bee`):
| Addr | Paper type | Default |
|---|---|---|
| 0x01011df0 | type 1 | 60.0 |
| 0x01011df4 | type 5 | 60.8 |
| 0x01011dec | type 2 | 74.4 |
| 0x01011df8 | type 3 | 120.0 |

**Renderer sub-pulse / history coefficients** (fix the solid-fill failure):
| Addr | Default | | Addr | Default |
|---|---|---|---|---|
| 0x01016538 | 20.0 | | 0x01016c84 | 10.0 |
| 0x0101654c | 50.0 | | 0x01016c88 | 30.0 |
| 0x01016550 | 30.0 | | 0x01016c8c | 50.0 |
| 0x01016554 | 150.0 | | 0x01016c90 | 120.0 |
| 0x01016558 | 100.0 | | 0x01016c94 | 100.0 |
| 0x0101655c | 90.0 | | | |

**Line-period table** (u16 array, feed timing; monotonic ~4250→~1100, ~64 entries):
`0x0102c2a4`. Multiplying entries slows the feed (more energy headroom per line).

**RFID curve flag** (harmless, kept): `movs r1,#3` → `movs r1,#0` at `0x01021d84` and
`0x01021ec8` (bytes `03 21` → `00 21`).

**Working config (locked):** all 15 float coeffs above = **400.0**, line-period ×**1.5**,
plus the two `0x204aa` bytes. Sweep results on this paper: 200 faded · 250 not solid ·
325 close · 370 nearly · **400 solid (chosen)** · 500 solid · 700 still solid (clamped).

To re-tune for other paper: edit the 15 floats (and optionally the feed multiplier) with the
builder in §8 and reflash. Raise for darker, lower for lighter, until solid without waste.

---

## 6. Flash instructions

Prereqs: `node`/`npx` present; printer on `/dev/ttyACM0` (be in `dialout`); **printer awake**.

```bash
# Flash a firmware image over USB serial (the working path)
npx --yes @mmote/niimblue-node flash -t serial -a /dev/ttyACM0 -n 5.22 -f <image.bin>
```
- `-n 5.22` = version label; match the real version (0x0516).
- Successful flash ends with `FirmwareNoMoreChunks → In_FirmwareCheckResult → FirmwareCommit
  → "printer will shut down"`. The printer's own check passing confirms integrity is fine.
- **After every flash the printer powers OFF — press the power button to turn it back on.**
- It also re-enumerates a new `/dev/ttyACM0`; USB staying enumerated ≠ powered on.
- **Recovery / revert to stock:** `... flash ... -f fw/B1_5.22.bin`. Brick risk low (bootloader
  is separate and reflashes independently).

⚠️ Only flash **same-major** firmware (5.x). Cross-major (→4.x or →6.x) can brick per the wiki.

---

## 7. Test instructions

Confirm it's awake first (if this times out / says "is it turned on?", the printer is
asleep or off — press power):
```bash
npx @mmote/niimblue-node info -t serial -a /dev/ttyACM0     # correct version print
python3 niimbot_b1.py info                                  # shows version as raw/100
```

Print tests (images must be **384 px wide** = the head; length in dots = mm × 8):
```bash
python3 niimbot_b1.py test  --density 5                 # built-in bordered test label
python3 niimbot_b1.py image FILE.png --density 5        # any 384-wide PNG
npx @mmote/niimblue-node print -t serial -a /dev/ttyACM0 -p B1 -q 5 -l 1 FILE.png
```
Note: density 1–5 all look identical on the tuned firmware (density is dead — §4.3); leave it
anywhere.

### Diagnostic patterns (what a bad result means)
Generate with the snippet in §8, then read the output:
- **Alternating solid-black / white bands** →
  - bands come out as **thin edge-lines only** = history compensation starving repeated
    rows (raise the renderer coeffs, §5).
  - bands **fill but faint** = base heat too low (raise all coeffs).
  - only **a small strip** prints = label-size / feed / label-type mismatch, not darkness.
- **Solid block + text** → text legible & block solid = good; block dark but text bleeds =
  over-driven (lower coeffs — though the clamp usually prevents this).

---

## 8. Reproducible helper scripts

Put the three Java files in one dir and pass it as `-scriptPath`. The Python builder makes any
coefficient variant.

### AddRam.java (prescript — map RAM so xrefs resolve)
```java
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.mem.*;
public class AddRam extends GhidraScript {
    public void run() throws Exception {
        Address ram = toAddr(0x00020000L);
        Memory mem = currentProgram.getMemory();
        if (mem.getBlock(ram)==null){
            MemoryBlock b = mem.createUninitializedBlock("RAM", ram, 0x40000L, false);
            b.setRead(true); b.setWrite(true); b.setExecute(false);
        }
    }
}
```

### FindReaders.java (postscript — refs to B1_TARGET addrs + decompile referrers)
```java
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.app.decompiler.*;
import java.io.*; import java.util.*;
public class FindReaders extends GhidraScript {
    public void run() throws Exception {
        PrintWriter pw = new PrintWriter(new FileWriter(System.getenv("B1_OUT")));
        DecompInterface dec = new DecompInterface(); dec.openProgram(currentProgram);
        ReferenceManager rm = currentProgram.getReferenceManager();
        FunctionManager fm = currentProgram.getFunctionManager();
        for (String ts: System.getenv("B1_TARGET").split(",")) {
            Address t = toAddr(Long.decode(ts.trim()));
            pw.println("\n=== REFERENCES TO "+t+" ===");
            Set<Function> fns = new LinkedHashSet<>();
            for (ReferenceIterator it = rm.getReferencesTo(t); it.hasNext();) {
                Reference r = it.next(); Address from = r.getFromAddress();
                Function f = fm.getFunctionContaining(from);
                pw.println("  ref from "+from+" ("+r.getReferenceType()+") in "
                           +(f==null?"(nofunc)":f.getName()));
                if (f!=null) fns.add(f);
            }
            for (Function f: fns) {
                pw.println("\n----- "+f.getName()+" @ "+f.getEntryPoint()+" -----");
                DecompileResults dr = dec.decompileFunction(f,60,monitor);
                pw.println(dr!=null&&dr.decompileCompleted()
                           ? dr.getDecompiledFunction().getC() : "// decompile failed");
            }
        }
        pw.flush(); pw.close();
    }
}
```

### CreateDump.java (postscript — force-create + decompile B1_FUNCS addrs)
```java
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import ghidra.app.decompiler.*;
import ghidra.app.cmd.function.CreateFunctionCmd;
import java.io.*;
public class CreateDump extends GhidraScript {
    public void run() throws Exception {
        PrintWriter pw = new PrintWriter(new FileWriter(System.getenv("B1_OUT")));
        FunctionManager fm = currentProgram.getFunctionManager();
        String[] addrs = System.getenv("B1_FUNCS").split(",");
        for (String s: addrs){ Address a=toAddr(Long.decode(s.trim()));
            if (fm.getFunctionAt(a)==null){ disassemble(a);
                new CreateFunctionCmd(a).applyTo(currentProgram, monitor); } }
        DecompInterface dec = new DecompInterface(); dec.openProgram(currentProgram);
        for (String s: addrs){ Address a=toAddr(Long.decode(s.trim()));
            Function f=fm.getFunctionContaining(a);
            pw.println("\n##### @ "+a+" -> "+(f==null?"NONE":f.getName()));
            if (f!=null){ DecompileResults dr=dec.decompileFunction(f,60,monitor);
                pw.println(dr!=null&&dr.decompileCompleted()
                           ? dr.getDecompiledFunction().getC():"// failed"); } }
        pw.flush(); pw.close();
    }
}
```
Run example:
```bash
B1_OUT=out.txt B1_TARGET=0x000205fb,0x00020850 \
$GH/support/analyzeHeadless proj p -import fw/B1_5.22.bin \
  -processor ARM:LE:32:Cortex -loader BinaryLoader -loader-baseAddr 0x01010000 \
  -scriptPath . -preScript AddRam.java -postScript FindReaders.java -deleteProject
```

### Python: build a coefficient variant
```python
import struct
def build(coeff, out, feed=1.5, src='fw/B1_5.22.bin'):
    BASE=0x01010000; data=open(src,'rb').read(); d=bytearray(data)
    def patch(va,old,new):
        o=va-BASE; assert d[o:o+len(old)]==old; d[o:o+len(new)]=new
    N=struct.pack('<f',float(coeff))
    def setf(va,ov):
        o=va-BASE; assert abs(struct.unpack('<f',d[o:o+4])[0]-ov)<0.5; d[o:o+4]=N
    # harmless RFID curve flag 3->0
    patch(0x1021d84,b'\x03\x21',b'\x00\x21'); patch(0x1021ec8,b'\x03\x21',b'\x00\x21')
    for va,ov in [(0x1011dec,74.4),(0x1011df0,60.0),(0x1011df4,60.8),(0x1011df8,120.0),
                  (0x1016538,20),(0x101654c,50),(0x1016550,30),(0x1016554,150),
                  (0x1016558,100),(0x101655c,90),(0x1016c84,10),(0x1016c88,30),
                  (0x1016c8c,50),(0x1016c90,120),(0x1016c94,100)]:
        setf(va,ov)
    tbl=0x0102c2a4-BASE                       # line-period table x feed
    for i in range(64):
        o=tbl+2*i; v=struct.unpack('<H',d[o:o+2])[0]
        if 100<=v<=40000: d[o:o+2]=struct.pack('<H',min(int(v*feed),65535))
        else: break
    open(out,'wb').write(d)
build(400,'fw/B1_5.22_coeff400.bin')          # the locked config
```

### Python: generate a diagnostic banded pattern
```python
from PIL import Image, ImageDraw, ImageFont
W,H,band=384,240,30; img=Image.new("L",(W,H),255); d=ImageDraw.Draw(img)
f=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",22)
for i,y in enumerate(range(0,H,band)):
    if i%2==0: d.rectangle([0,y,W-1,min(y+band-1,H-1)],fill=0); d.text((6,y+4),f"B{i}",font=f,fill=255)
    else:      d.text((6,y+4),f"w{i}",font=f,fill=0)
img.save("bands.png")
```

---

## 9. Operational gotchas

- Printer **sleeps** on idle: `info` timeout / `Unable to fetch printer info (is it turned on?)`
  / heartbeat timeouts just mean asleep — press power.
- After each flash it **powers off** — press power.
- `niimbot_b1.py` needs `/dev/ttyACM0` free; ModemManager is active but releases the port
  (Node/pyserial take it exclusively).
- Files: `fw/B1_5.22.bin` = stock; `B1_5.22_thirdparty_fullquality.bin` = tuned (coeff 400);
  `niimbot_b1.py` = local driver (info/test/image subcommands).
