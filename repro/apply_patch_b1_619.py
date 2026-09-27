#!/usr/bin/env python3
"""从原厂 B1_6.19.bin 重建"第三方满能量"候选镜像（自包含最小实现）。

规则（机器可执行，不用自然语言描述）:
  1) 15 个 IEEE-754 float 能量系数  ->  400.0
  2) line-period 表 64 x u16        ->  floor(old * 3/2)   ← 向零截断 = 向下取整
  3) 两处 RFID curve-flag 字节      ->  03 21 改为 00 21
  4) 其余字节一律不动，输出长度与源文件相同

为什么规则 2 是 floor 而不是就近取整
------------------------------------
ThreeDaPrint 原库发布了 5.22 的成品镜像 firmware/B1_5.22_thirdparty_fullquality.bin
(md5 9826e1c1869060ae11daaadb27c3a637)。用上面这套规则从原厂 B1_5.22.bin 重建，
输出与原库成品 **逐字节完全相同**；换成 round-to-nearest-even 会有 10 项各差 1，
换成 half-up 会有 27 项各差 1。原作者自己的构建脚本也写作 int(v*1.5)（Python int()
对正数即 floor）。故规则 2、3 均由 5.22 侧的逐字节复现锚定，不是推测。

用法:
  python3 apply_patch_b1_619.py --src B1_6.19.bin --out out.bin
  # 不带 --out 时只做校验、不写文件（dry-run）

成功判据:
  输出 md5 == b7d4f4e5f07bdae5fceb75b29949e6af，且大小 124436。
"""
import argparse
import hashlib
import struct
import sys
from fractions import Fraction
from pathlib import Path

BASE = 0x01010000
SRC_MD5 = "fd9efd1441b5f05ca46c310b8d162dc1"
SRC_SIZE = 124436
OUT_MD5 = "b7d4f4e5f07bdae5fceb75b29949e6af"
COEFF_TARGET = 400.0
FEED = Fraction(3, 2)          # 1.5 精确有理数，无二进制浮点误差

# (vaddr, 期望原值, 标签)
COEFFS = [
    (0x01011E60, 74.4, "base type2"),
    (0x01011E64, 60.0, "base type1"),
    (0x01011E68, 60.8, "base type5"),
    (0x01011E6C, 120.0, "base type3"),
    (0x01016600, 20.0, "renderer A #1"),
    (0x01016614, 50.0, "renderer A #2"),
    (0x01016618, 30.0, "renderer A #3"),
    (0x0101661C, 150.0, "renderer A #4"),
    (0x01016620, 100.0, "renderer A #5"),
    (0x01016624, 90.0, "renderer A #6"),
    (0x01016D4C, 10.0, "renderer B #1"),
    (0x01016D50, 30.0, "renderer B #2"),
    (0x01016D54, 50.0, "renderer B #3"),
    (0x01016D58, 120.0, "renderer B #4"),
    (0x01016D5C, 100.0, "renderer B #5"),
]

LINEPERIOD_VADDR = 0x0102D21C
LINEPERIOD_ORIG = [
    4250, 3760, 3459, 2762, 2314, 2028, 1928, 1828, 1728, 1675, 1635, 1595,
    1565, 1543, 1523, 1503, 1486, 1466, 1446, 1426, 1406, 1384, 1364, 1344,
    1322, 1302, 1282, 1262, 1242, 1222, 1202, 1191, 1181, 1171, 1161, 1151,
    1141, 1131, 1121, 1111, 1103, 1093, 1083, 1073, 1063, 1053, 1043, 1033,
    1023, 1013, 990, 980, 970, 960, 950, 940, 930, 920, 910, 900, 890, 880,
    870, 860,
]

# RFID curve-flag：原作者镜像同样改了这两处（其 RE 文档标注 "harmless, kept"）
RFID_FLAGS = [0x01022A4C, 0x01022B90]
RFID_OLD = b"\x03\x21"
RFID_NEW = b"\x00\x21"


def scale_floor(x: int, f: Fraction) -> int:
    """floor(x * f)：纯整数实现的向下取整，无浮点误差。

    判别依据（5.22 成品逐字节复现，见模块 docstring）:
        3459 * 1.5 = 5188.5 -> 5188
        1565 * 1.5 = 2347.5 -> 2347   (就近取整会给 2348)
         860 * 1.5 = 1290.0 -> 1290   (整数项不受规则影响)
    """
    if x == 0 or f == 0:
        return 0
    n = abs(x) * abs(f.numerator)
    q = n // f.denominator
    return -q if (x < 0) != (f < 0) else q


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    src = Path(args.src)
    raw = bytearray(src.read_bytes())
    md5 = hashlib.md5(raw).hexdigest()
    print(f"源文件 : {src}  {len(raw)} 字节  md5={md5}")

    fail = 0
    if len(raw) != SRC_SIZE:
        print(f"!! 大小不符：期望 {SRC_SIZE}", file=sys.stderr)
        fail = 1
    if md5 != SRC_MD5:
        print(f"!! 源 md5 不符：期望 {SRC_MD5}（可能不是原厂 B1_6.19 镜像）", file=sys.stderr)
        fail = 1
    if fail:
        return 1

    for vaddr, expect, label in COEFFS:
        off = vaddr - BASE
        got = struct.unpack("<f", raw[off:off + 4])[0]
        if abs(got - expect) > 1e-3:
            print(f"!! {vaddr:#010x} 原值={got} 期望={expect}（{label}），中止", file=sys.stderr)
            return 1
        raw[off:off + 4] = struct.pack("<f", COEFF_TARGET)

    for vaddr in RFID_FLAGS:
        off = vaddr - BASE
        if bytes(raw[off:off + 2]) != RFID_OLD:
            print(f"!! {vaddr:#010x} RFID 字节={bytes(raw[off:off + 2]).hex(' ')} "
                  f"期望={RFID_OLD.hex(' ')}，中止", file=sys.stderr)
            return 1
        raw[off:off + 2] = RFID_NEW

    off = LINEPERIOD_VADDR - BASE
    tab = [struct.unpack("<H", raw[off + 2 * i:off + 2 * i + 2])[0]
           for i in range(len(LINEPERIOD_ORIG))]
    if tab != LINEPERIOD_ORIG:
        print(f"!! line-period 表不匹配：\n  实际 {tab}\n  期望 {LINEPERIOD_ORIG}", file=sys.stderr)
        return 1
    for i in range(len(LINEPERIOD_ORIG)):
        raw[off + 2 * i:off + 2 * i + 2] = struct.pack(
            "<H", scale_floor(LINEPERIOD_ORIG[i], FEED))

    new_md5 = hashlib.md5(bytes(raw)).hexdigest()
    print(f"重建   : {len(raw)} 字节  md5={new_md5}")
    ok = (new_md5 == OUT_MD5)
    print(f"比对   : 期望 {OUT_MD5}  ->  {'一致' if ok else '不一致'}")
    if args.out:
        Path(args.out).write_bytes(raw)
        print(f"写出   : {args.out}")
    else:
        print("（dry-run，未写文件；加 --out 才会落盘）")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
