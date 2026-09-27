#!/usr/bin/env python3
"""全链路锚定：用「6.19 移植所用的同一套工具」重建 ThreeDaPrint 的 5.22 density 成品。

这是 6.19 移植的**根证据升级版**。原来的 verify_recipe_on_522.py 只锚定了数据侧规则
（15 float / line-period / RFID）；本脚本连**代码注入侧**也一起锚定：
  - 同一份 cave 编码器（build_b1_619_density.build_cave_a / build_cave_b / enc_bl）
  - 同一份 m-table、同一份 detour 布局
只把地址换成 5.22 的地址，看能否逐字节复现上游发布的
firmware/B1_5.22_density_coeff.bin (md5 023ff56326fe8c65f01b68f32ebdba99)。

若逐字节相同 → bl 编码、栈偏移、字面量池、位移指令重放、m-table 全部被成品锚定，
6.19 侧只是换址（换址依据见 analysis/density-port-6.19.md）。

用法:
  python3 reproduce_522_density.py \
      --src ../fw/B1_5.22.bin \
      --ref ../fw/threeDaPrint/B1_5.22_density_coeff.bin [--out /tmp/repro.bin]
"""
import argparse
import hashlib
import struct
import sys
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
for _p in (str(HERE), str(HERE.parent / "build")):
    sys.path.insert(0, _p)
import build_b1_619_density as B  # noqa: E402

BASE = 0x01010000
SRC_MD5 = "eae22cd5cb04d4d4bc4d67f49191af88"
SRC_SIZE = 120288
REF_MD5 = "023ff56326fe8c65f01b68f32ebdba99"

# ---- 5.22 侧地址（与 6.19 侧一一对应，见 analysis/density-port-6.19.md 对照表） ----
COEFFS = [
    (0x01011DEC, 74.4), (0x01011DF0, 60.0), (0x01011DF4, 60.8), (0x01011DF8, 120.0),
    (0x01016538, 20.0), (0x0101654C, 50.0), (0x01016550, 30.0), (0x01016554, 150.0),
    (0x01016558, 100.0), (0x0101655C, 90.0),
    (0x01016C84, 10.0), (0x01016C88, 30.0), (0x01016C8C, 50.0), (0x01016C90, 120.0),
    (0x01016C94, 100.0),
]
RFID_FLAGS = [0x01021D84, 0x01021EC8]
LINEPERIOD_VADDR = 0x0102C2A4
DENSITY_BYTE = 0x00020704
FLOAT_MUL = 0x0102529B
CAVE_A = 0x0102BBEC
CAVE_B = 0x0102BC4A
HOOK_A = 0x01016126
HOOK_B = 0x01016846
HOOK_A_ORIG = b"\x16\x46\xff\x36"
HOOK_B_ORIG = b"\x14\x46\x06\x46"
RFID_OLD, RFID_NEW = b"\x03\x21", b"\x00\x21"
FEED = Fraction(3, 2)
COEFF_TARGET = 400.0



def _find(*cands):
    """定位输入文件：本地工作区 (fw/) / 仓库 (firmware/) / 扁平复现包 (同目录) 都可用。"""
    for c in cands:
        for base in (HERE, HERE.parent):
            p = base / c
            if p.exists():
                return str(p)
    return str(HERE.parent / cands[-1])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=_find("B1_5.22.bin", "fw/B1_5.22.bin",
                                           "firmware/B1_5.22.bin"))
    ap.add_argument("--ref", default=_find("B1_5.22_density_coeff.bin",
                                           "fw/B1_5.22_density_coeff.bin",
                                           "fw/threeDaPrint/B1_5.22_density_coeff.bin",
                                           "firmware/B1_5.22_density_coeff.bin"))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    raw = bytearray(Path(args.src).read_bytes())
    ref = Path(args.ref).read_bytes()
    bad = []

    ok = len(raw) == SRC_SIZE and hashlib.md5(bytes(raw)).hexdigest() == SRC_MD5
    print(f"① 原厂 5.22 识别    : {'PASS' if ok else 'FAIL'}"
          f"  ({len(raw)} 字节, md5={hashlib.md5(bytes(raw)).hexdigest()})")
    if not ok:
        return 1

    for va, ov in COEFFS:
        o = va - BASE
        got = struct.unpack("<f", raw[o:o + 4])[0]
        if abs(got - ov) > 1e-3:
            print(f"   !! {va:#010x} 原值={got} 期望={ov}")
            bad.append("float")
        raw[o:o + 4] = struct.pack("<f", COEFF_TARGET)
    print(f"② 15 个系数 -> 400  : {'PASS' if 'float' not in bad else 'FAIL'}")

    for va in RFID_FLAGS:
        o = va - BASE
        if bytes(raw[o:o + 2]) != RFID_OLD:
            bad.append("rfid")
        raw[o:o + 2] = RFID_NEW
    print(f"③ 2 处 RFID         : {'PASS' if 'rfid' not in bad else 'FAIL'}  (03 21 -> 00 21)")

    o = LINEPERIOD_VADDR - BASE
    for i in range(64):
        v = struct.unpack("<H", raw[o + 2 * i:o + 2 * i + 2])[0]
        raw[o + 2 * i:o + 2 * i + 2] = struct.pack("<H", B.scale_floor(v, FEED))
    print(f"④ 64 项 line-period : PASS  (max={max(struct.unpack('<64H', raw[o:o + 128]))})")

    for hook, orig, target, name in ((HOOK_A, HOOK_A_ORIG, CAVE_B, "hook124"),
                                     (HOOK_B, HOOK_B_ORIG, CAVE_B + 18, "hook844")):
        ho = hook - BASE
        if bytes(raw[ho:ho + 4]) != orig:
            print(f"   !! {hook:#010x} 原字节={bytes(raw[ho:ho+4]).hex(' ')} 期望={orig.hex(' ')}")
            bad.append("hook")
            continue
        raw[ho:ho + 4] = B.enc_bl(hook, target)
    print(f"⑤ 2 处 hook bl 注入 : {'PASS' if 'hook' not in bad else 'FAIL'}")

    cave_a = B.build_cave_a(CAVE_A, DENSITY_BYTE, FLOAT_MUL)
    cave_b = B.build_cave_b(CAVE_B, CAVE_A)
    raw[CAVE_A - BASE:CAVE_A - BASE + len(cave_a)] = cave_a
    raw[CAVE_B - BASE:CAVE_B - BASE + len(cave_b)] = cave_b
    print(f"⑥ 两处 code cave    : PASS  (caveA={len(cave_a)}B @{CAVE_A:#x}, "
          f"caveB={len(cave_b)}B @{CAVE_B:#x})")

    diff = [i for i in range(min(len(raw), len(ref))) if raw[i] != ref[i]]
    md5 = hashlib.md5(bytes(raw)).hexdigest()
    ok7 = not diff and md5 == REF_MD5
    print(f"⑦ 与上游成品逐字节  : {'PASS' if ok7 else 'FAIL'}"
          f"  (重建 md5={md5}, 差异 {len(diff)} 字节"
          + (f", 前几处 {[hex(x) for x in diff[:12]]}" if diff else "") + ")")
    print(f"⑧ md5 == 上游声明   : {'PASS' if md5 == REF_MD5 else 'FAIL'}  (期望 {REF_MD5})")
    if not ok7:
        bad.append("mismatch")

    if args.out:
        Path(args.out).write_bytes(bytes(raw))
        print(f"写出: {args.out}")

    print("\n结论: " + ("变换规则 + cave 编码器 + hook 布局全部被 5.22 成品逐字节锚定"
                       if not bad else f"不一致 {'/'.join(sorted(set(bad)))}"))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
