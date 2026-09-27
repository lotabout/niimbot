#!/usr/bin/env python3
"""用同一套规则重建 ThreeDaPrint 的 5.22 成品镜像 —— 用于锚定"规则是否正确"。

这是本复现包的**根证据**：它不依赖任何 6.19 侧的推断，只做一件事——
把同一套规则作用在 5.22 原厂镜像上，看能否逐字节复原原作者发布的成品。

  规则: 15 float -> 400.0 ; 64 项 line-period -> floor(old*3/2) ; 2 处 RFID 03 21 -> 00 21

用法:
  python3 verify_recipe_on_522.py --src B1_5.22.bin \
      --patched B1_5.22_thirdparty_fullquality.bin

成功判据:
  重建结果与 --patched **逐字节相同**，且 md5 == 9826e1c1869060ae11daaadb27c3a637。
  若换成 round-to-nearest-even，会有 10 项 line-period 各差 1（12 字节不同）；
  换成 half-up，会有 27 项各差 1 —— 本脚本同样能测出这种"规则错但近似对"的情况。
"""
import argparse
import hashlib
import struct
import sys
from fractions import Fraction
from pathlib import Path

BASE = 0x01010000
SRC_MD5 = "eae22cd5cb04d4d4bc4d67f49191af88"
SRC_SIZE = 120288
OUT_MD5 = "9826e1c1869060ae11daaadb27c3a637"   # ThreeDaPrint 原库成品
COEFF_TARGET = 400.0
FEED = Fraction(3, 2)

COEFFS = [
    (0x01011DEC, 74.4, "base type2"),
    (0x01011DF0, 60.0, "base type1"),
    (0x01011DF4, 60.8, "base type5"),
    (0x01011DF8, 120.0, "base type3"),
    (0x01016538, 20.0, "renderer A #1"),
    (0x0101654C, 50.0, "renderer A #2"),
    (0x01016550, 30.0, "renderer A #3"),
    (0x01016554, 150.0, "renderer A #4"),
    (0x01016558, 100.0, "renderer A #5"),
    (0x0101655C, 90.0, "renderer A #6"),
    (0x01016C84, 10.0, "renderer B #1"),
    (0x01016C88, 30.0, "renderer B #2"),
    (0x01016C8C, 50.0, "renderer B #3"),
    (0x01016C90, 120.0, "renderer B #4"),
    (0x01016C94, 100.0, "renderer B #5"),
]

RFID_FLAGS = [0x01021D84, 0x01021EC8]
RFID_OLD = b"\x03\x21"
RFID_NEW = b"\x00\x21"
LINEPERIOD_VADDR = 0x0102C2A4


def scale_floor(x: int, f: Fraction) -> int:
    """floor(x * f)，纯整数实现。"""
    n = abs(x) * abs(f.numerator)
    q = n // f.denominator
    return -q if (x < 0) != (f < 0) else q


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="原厂 B1_5.22.bin")
    ap.add_argument("--patched", required=True, help="ThreeDaPrint 成品镜像")
    args = ap.parse_args()

    raw = bytearray(Path(args.src).read_bytes())
    ref = Path(args.patched).read_bytes()
    bad = []

    c0 = len(raw) == SRC_SIZE and hashlib.md5(raw).hexdigest() == SRC_MD5
    print(f"① 原厂 5.22 识别 : {'PASS' if c0 else 'FAIL'}"
          f"  ({len(raw)} 字节, md5={hashlib.md5(raw).hexdigest()})")
    if not c0:
        return 1

    for va, ov, label in COEFFS:
        o = va - BASE
        got = struct.unpack("<f", raw[o:o + 4])[0]
        if abs(got - ov) > 1e-3:
            print(f"   !! {va:#010x} 原值={got} 期望={ov}（{label}）")
            bad.append("float")
        raw[o:o + 4] = struct.pack("<f", COEFF_TARGET)
    print(f"② 15 个系数->400  : {'PASS' if 'float' not in bad else 'FAIL'}")

    for va in RFID_FLAGS:
        o = va - BASE
        if bytes(raw[o:o + 2]) != RFID_OLD:
            print(f"   !! {va:#010x} RFID 原值={bytes(raw[o:o+2]).hex(' ')} 期望={RFID_OLD.hex(' ')}")
            bad.append("rfid")
        raw[o:o + 2] = RFID_NEW
    print(f"③ 2 处 RFID 标志  : {'PASS' if 'rfid' not in bad else 'FAIL'}  (03 21 -> 00 21)")

    off = LINEPERIOD_VADDR - BASE
    for i in range(64):
        v = struct.unpack("<H", raw[off + 2 * i:off + 2 * i + 2])[0]
        raw[off + 2 * i:off + 2 * i + 2] = struct.pack("<H", min(scale_floor(v, FEED), 0xFFFF))
    newmax = max(struct.unpack("<64H", raw[off:off + 128]))
    print(f"④ 64 项 floor     : PASS  (max={newmax})")

    same = bytes(raw) == ref
    md5 = hashlib.md5(bytes(raw)).hexdigest()
    diff = [i for i in range(min(len(raw), len(ref))) if raw[i] != ref[i]]
    print(f"⑤ 与成品逐字节相同: {'PASS' if same else 'FAIL'}"
          f"  (重建 md5={md5}, 差异 {len(diff)} 字节"
          + (f", 前几处 {[hex(x) for x in diff[:12]]}" if diff else "") + ")")
    c6 = md5 == OUT_MD5
    print(f"⑥ md5 == 原库声明 : {'PASS' if c6 else 'FAIL'}  (期望 {OUT_MD5})")
    if not same or not c6:
        bad.append("mismatch")

    print("\n结论: " + ("规则与原作者成品逐字节一致 —— 配方已锚定"
                       if not bad else f"不一致，规则有误 {'/'.join(sorted(set(bad)))}"))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
