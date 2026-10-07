#!/usr/bin/env python3
"""构建 Niimbot B1 (FW 6.19) 第三方标签纸满质量候选镜像。

复刻 ThreeDaPrint/niimbot 在 5.22 上的做法，地址按 6.19 重新定位：
  - 15 个能量系数（4 base + 6 renderer A + 5 renderer B）→ 目标值（默认 400.0）
  - line-period 表 64×u16 → ×feed（默认 1.5，走纸降速换热量裕度），
    取整规则固定为 floor（向下取整，纯整数实现）——与 ThreeDaPrint 5.22 成品一致
  - 2 处 RFID curve-flag 字节 03 21 → 00 21（原作者成品同样改了这两处）
  - RFID 读取失败旁路 0x01025478: 02 28 → ff 28（6.19 专有，否则无标签纸报
    WriteRfidFail/0x14 无法打印；见 docs/B1_6.19_rfid_bypass.md）

用法:
  python3 build/build_b1_619.py [--coeff 400.0] [--feed 1.5] [--out fw/xxx.bin]

安全: 每个写入点在改前都会校验原值，任一不符即中止（防止地址定位错误）。
镜像未经实机验证，刷写风险自负；同大版本可刷回原厂 B1_6.19.bin。
"""
import argparse
import hashlib
import struct
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "fw" / "B1_6.19.bin"
SRC_MD5 = "fd9efd1441b5f05ca46c310b8d162dc1"
BASE = 0x01010000

# (vaddr, 期望原值, 说明)
COEFFS = [
    (0x01011E60, 74.4, "base type2"),
    (0x01011E64, 60.0, "base type1"),
    (0x01011E68, 60.8, "base type5"),
    (0x01011E6C, 120.0, "base type3"),
    (0x01016600, 20.0, "renderer A sub-pulse"),
    (0x01016614, 50.0, "renderer A"),
    (0x01016618, 30.0, "renderer A"),
    (0x0101661C, 150.0, "renderer A"),
    (0x01016620, 100.0, "renderer A"),
    (0x01016624, 90.0, "renderer A"),
    (0x01016D4C, 10.0, "renderer B history"),
    (0x01016D50, 30.0, "renderer B"),
    (0x01016D54, 50.0, "renderer B"),
    (0x01016D58, 120.0, "renderer B"),
    (0x01016D5C, 100.0, "renderer B"),
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

# RFID curve-flag（原作者 RE 文档标注 harmless，但其成品确实改了）
RFID_FLAGS = [0x01022A4C, 0x01022B90]
RFID_OLD = b"\x03\x21"
RFID_NEW = b"\x00\x21"

# RFID read-failure bypass（6.19 新增 RFID 模块；5.22 无此路径，见 docs/B1_6.19_rfid_bypass.md）
#   0x01025478  cmp r0,#2  (02 28)  ->  cmp r0,#0xff  (ff 28)
#   无标签纸读取失败时，0x102543e 只在打印机状态==2（打印中）才升级为错误 0x14
#   (WriteRfidFail)；比较改为永不成立后，失败读取与空闲时一样静默返回。
RFID_BYPASS_SITE = 0x01025478
RFID_BYPASS_OLD = b"\x02\x28"
RFID_BYPASS_NEW = b"\xff\x28"


def scale_floor(x: int, f: Fraction) -> int:
    """floor(x * f)：纯整数实现，不经过浮点，也不依赖任何语言的 round() 语义。

    规则由 ThreeDaPrint 的 5.22 成品镜像逐字节锚定（repro/verify_recipe_on_522.py）：
    用同一套规则从原厂 5.22 重建，与其发布的成品逐字节相同（差异 0 字节）。
    判别证据：
        3459*1.5 = 5188.5 -> 5188
        1565*1.5 = 2347.5 -> 2347（ties-to-even 会给 2348）
        1181*1.5 = 1771.5 -> 1771（ties-to-even 会给 1772）
    原作者构建脚本亦写作 int(v*1.5)（Python int() 对正数即 floor）。
    """
    if x == 0 or f == 0:
        return 0
    n = abs(x) * abs(f.numerator)
    q = n // f.denominator
    return -q if (x < 0) != (f < 0) else q


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coeff", type=float, default=400.0)
    # feed 用精确有理数（"1.5" 或 "3/2"），避免二进制浮点误差带来的边界抖动
    ap.add_argument("--feed", default="1.5")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    try:
        feed = Fraction(args.feed)
    except (ValueError, ZeroDivisionError):
        print(f"!! --feed 无法解析为有理数: {args.feed!r}", file=sys.stderr)
        return 1
    if feed <= 0:
        print(f"!! --feed 必须为正: {args.feed!r}", file=sys.stderr)
        return 1

    out = Path(args.out) if args.out else ROOT / "fw" / f"B1_6.19_thirdparty_fullquality.bin"
    raw = bytearray(SRC.read_bytes())
    md5 = hashlib.md5(raw).hexdigest()
    print(f"源镜像 : {SRC.name}  {len(raw)} 字节  md5={md5}")
    if md5 != SRC_MD5:
        print(f"!! 源镜像 md5 与预期不符（期望 {SRC_MD5}），中止", file=sys.stderr)
        return 1

    changes = []
    for vaddr, expect, label in COEFFS:
        off = vaddr - BASE
        got = struct.unpack("<f", raw[off:off + 4])[0]
        if abs(got - expect) > 1e-3:
            print(f"!! {vaddr:#010x} 原值={got} 期望={expect}（{label}），中止", file=sys.stderr)
            return 1
        raw[off:off + 4] = struct.pack("<f", args.coeff)
        changes.append((off, vaddr, f"{expect} -> {args.coeff}", label))

    for vaddr in RFID_FLAGS:
        o = vaddr - BASE
        if bytes(raw[o:o + 2]) != RFID_OLD:
            print(f"!! {vaddr:#010x} RFID 原值={bytes(raw[o:o+2]).hex(' ')} "
                  f"期望={RFID_OLD.hex(' ')}，中止", file=sys.stderr)
            return 1
        raw[o:o + 2] = RFID_NEW
        changes.append((o, vaddr, "03 21 -> 00 21", "RFID curve flag"))

    o = RFID_BYPASS_SITE - BASE
    if bytes(raw[o:o + 2]) != RFID_BYPASS_OLD:
        print(f"!! {RFID_BYPASS_SITE:#010x} 原值={bytes(raw[o:o+2]).hex(' ')} "
              f"期望={RFID_BYPASS_OLD.hex(' ')}，中止", file=sys.stderr)
        return 1
    raw[o:o + 2] = RFID_BYPASS_NEW
    changes.append((o, RFID_BYPASS_SITE, "02 28 -> ff 28", "RFID read-failure bypass"))

    off = LINEPERIOD_VADDR - BASE
    tab = [struct.unpack("<H", raw[off + 2 * i:off + 2 * i + 2])[0] for i in range(len(LINEPERIOD_ORIG))]
    if tab != LINEPERIOD_ORIG:
        print(f"!! line-period 表不匹配:\n  实际 {tab}\n  期望 {LINEPERIOD_ORIG}", file=sys.stderr)
        return 1
    for i, v in enumerate(LINEPERIOD_ORIG):
        if v:
            # 规则固定为 floor（见 scale_floor）：纯整数，无浮点、无语言 round() 依赖
            nv = min(scale_floor(v, feed), 0xFFFF)
            raw[off + 2 * i:off + 2 * i + 2] = struct.pack("<H", nv)
    changes.append((off, LINEPERIOD_VADDR, f"64x u16 x{feed}", "line-period (feed)"))

    out.write_bytes(raw)
    new_md5 = hashlib.md5(bytes(raw)).hexdigest()
    diff = sum(1 for a, b in zip(SRC.read_bytes(), raw) if a != b)
    print(f"\n写入 : {out}  {len(raw)} 字节  md5={new_md5}")
    print(f"改动 : {diff} 个字节，{len(changes)} 处\n")
    for o, v, d, label in changes:
        print(f"  off 0x{o:06x}  vaddr {v:#010x}  {d:28s}  {label}")
    print("\n提示: 候选镜像未经实机验证；回退 = 刷回原厂 fw/B1_6.19.bin")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
