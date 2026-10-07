#!/usr/bin/env python3
"""在 B1 FW 6.19 上重建 ThreeDaPrint 的「密度控制亮度」方案（density→coefficient 移植版）。

产物 = 6.19 满能量基线 + 4 处代码注入
------------------------------------------------
基线（与 repro/apply_patch_b1_619.py 完全相同的三条规则，已由 5.22 成品逐字节锚定）:
  A) 15 个 IEEE-754 float 能量系数        -> 400.0
  B) line-period 表 64 x u16              -> floor(old * 3/2)
  C) 两处 RFID curve-flag 字节            -> 03 21 改为 00 21
  D) RFID 读取失败旁路 0x01025478         -> 02 28 改为 ff 28（6.19 专有）
     6.19 新增的 RFID 模块在打印中读不到标签会回 0xDB 0x14（WriteRfidFail），
     无标签纸无法打印；该补丁让失败读取按空闲路径静默返回。
     详见 docs/B1_6.19_rfid_bypass.md。

代码注入（把上游 5.22 的 Cortex-M0 code-cave detour 换址移植到 6.19）:
  1) 0x010161EE  renderer A 入口 push 之后的 4 字节  -> bl det124
  2) 0x0101690E  renderer B 入口 push 之后的 4 字节  -> bl det844
  3) 0x0102CB64  cave A（68 B）: scale() + m(density) 浮点表 + 字面量池
  4) 0x0102C1EE  cave B（46 B）: det124 / det844 两个 detour 体

移植依据（6.19 与 5.22 逐条同构，全部实测，不是推测）:
  | 项目                | 5.22        | 6.19        | 校验方式                        |
  |---------------------|-------------|-------------|---------------------------------|
  | renderer A 入口     | 0x01016124  | 0x010161EC  | 反汇编前 20 条指令逐字节相同    |
  | renderer B 入口     | 0x01016844  | 0x0101690C  | 同上                            |
  | soft-float 乘法     | 0x0102529A  | 0x01026156  | 函数前 48 字节逐字节相同        |
  | density 配置字节    | 0x00020704  | 0x00020740  | config validator + SetDensity    |
  | code cave           | 0x0102BBEC  | 0x0102CB64  | 6.19 零引用零区扫描             |

  - renderer 入口 push 也是 `ff b5`（9 寄存器），故 detour 内的栈偏移与 5.22 相同:
    A 的 arg5 = [sp,#0x38]；B 的 arg6 = [sp,#0x3c]、arg7 = [sp,#0x40]。
  - density 字节: 6.19 的 config 结构体基址 = 0x0002073C（5.22 = 0x00020700，整段 +0x3C，
    由 4 个相邻变量的引用数一一对应确认），density = CFG+4 = 0x00020740；
    0x01010D88 的 validator 对 [CFG+4] 做 1..5 clamp、默认 3，
    0x01022A78 的 SetDensity 对该字节执行 `strb`。
  - cave 选址: 6.19 中仅两处「零字节且无 ldr 字面量/分支引用」的零区满足长度需求:
    0x0102CB62..0x0102CBB7 (86 B) 与 0x0102C1ED..0x0102C21D (49 B)。

安全性质（沿用上游结论）: m(d) <= 1.0，D5 = 1.0 = 满能量基线，低档只减能量。

用法:
  python3 build_b1_619_density.py --src fw/B1_6.19.bin --out fw/B1_6.19_density_coeff.bin
  # 不带 --out 时只做校验、不写文件（dry-run）
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
COEFF_TARGET = 400.0
FEED = Fraction(3, 2)

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

# ---- 移植点（6.19 实测地址） ----
DENSITY_BYTE = 0x00020740          # 5.22: 0x00020704（config struct +4）
FLOAT_MUL = 0x01026157             # 5.22: 0x0102529b（FUN_0102529a | thumb）
HOOK_A = 0x010161EE                # 5.22: 0x01016126，覆盖 `16 46 ff 36`
HOOK_B = 0x0101690E                # 5.22: 0x01016846，覆盖 `14 46 06 46`
HOOK_A_ORIG = b"\x16\x46\xff\x36"
HOOK_B_ORIG = b"\x14\x46\x06\x46"
CAVE_A = 0x0102CB64                # scale + m-table + literal pool（需 4 字节对齐）
CAVE_B = 0x0102C1EE                # det124 / det844
CAVE_A_ZONE = (0x0102CB62, 0x0102CBB7)   # 6.19 无引用零区
CAVE_B_ZONE = (0x0102C1ED, 0x0102C21D)

# m(d) = coeff(d)/400，d=1..5（上游 5.22 标定值，按 400 归一）
MTABLE = [0.675, 0.756250, 0.837500, 0.918750, 1.0]

# scale() 代码（36 B）。与 5.22 成品逐字节相同——因为 cave 内部相对布局一致，
# 只有字面量池里的三个值随版本改变。
SCALE_CODE = bytes.fromhex(
    "10b50d4c24787f210c40012c00d20124052c00d90524013ca40008490959084b984710bd")


def scale_floor(x: int, f: Fraction) -> int:
    """floor(x * f)：纯整数实现，无浮点误差（5.22 成品锚定规则）。"""
    if x == 0 or f == 0:
        return 0
    n = abs(x) * abs(f.numerator)
    q = n // f.denominator
    return -q if (x < 0) != (f < 0) else q


def enc_bl(addr: int, target: int) -> bytes:
    """Thumb-1 BL 编码（ARMv6-M）：offset = target - (addr + 4)。"""
    d = target - (addr + 4)
    if d % 2:
        raise ValueError(f"bl 目标未半字对齐: {target:#x}")
    if not -(1 << 24) <= d < (1 << 24):
        raise ValueError(f"bl 超出 ±16MB 范围: {d}")
    if d < 0:
        d += 1 << 25
    s = (d >> 24) & 1
    i1 = (d >> 23) & 1
    i2 = (d >> 22) & 1
    imm10 = (d >> 12) & 0x3FF
    imm11 = (d >> 1) & 0x7FF
    j1 = (~(i1 ^ s)) & 1
    j2 = (~(i2 ^ s)) & 1
    hw1 = 0xF000 | (s << 10) | imm10
    hw2 = 0xD000 | (j1 << 13) | (j2 << 11) | imm11
    return struct.pack("<HH", hw1, hw2)


def dec_bl(addr: int, raw: bytes) -> int:
    """enc_bl 的逆运算，用于自检。"""
    hw1, hw2 = struct.unpack("<HH", raw)
    if (hw1 & 0xF800) != 0xF000 or (hw2 & 0xD000) != 0xD000:
        raise ValueError("不是 BL 指令")
    s = (hw1 >> 10) & 1
    imm10 = hw1 & 0x3FF
    j1 = (hw2 >> 13) & 1
    j2 = (hw2 >> 11) & 1
    imm11 = hw2 & 0x7FF
    i1 = (~(j1 ^ s)) & 1
    i2 = (~(j2 ^ s)) & 1
    d = (s << 24) | (i1 << 23) | (i2 << 22) | (imm10 << 12) | (imm11 << 1)
    if s:
        d -= 1 << 25
    return addr + 4 + d


def build_cave_a(cave_a: int = CAVE_A, density: int = DENSITY_BYTE,
                 float_mul: int = FLOAT_MUL) -> bytes:
    """scale() + m-table + 字面量池 = 68 字节（布局与 5.22 成品一致）。

    参数化是为了让同一份编码器也能重建 5.22 成品
    （见 repro/reproduce_522_density.py —— 那条链路能逐字节复现上游镜像）。
    """
    code = SCALE_CODE
    table = b"".join(struct.pack("<f", v) for v in MTABLE)
    mtable_addr = cave_a + len(code)                     # +36
    pool = (struct.pack("<I", density)
            + struct.pack("<I", mtable_addr)
            + struct.pack("<I", float_mul))
    blob = code + table + pool
    assert len(blob) == 36 + 20 + 12 == 68, len(blob)
    assert cave_a % 4 == 0, "cave A 必须 4 字节对齐"
    # 回读三条 ldr 的字面量偏移
    for ins_off, pool_off in ((2, 56), (26, 60), (30, 64)):
        pc = (cave_a + ins_off + 4) & ~3
        imm = ((cave_a + pool_off) - pc) // 4
        assert 0 <= imm <= 0xFF, (ins_off, imm)
    return blob


def build_cave_b(cave_b: int = CAVE_B, cave_a: int = CAVE_A) -> bytes:
    """det124（18 B）+ det844（26 B）= 44 字节。"""
    det124 = cave_b
    det844 = cave_b + 18
    b1 = (bytes.fromhex("0fb5")                 # push {r0-r3,lr}
          + bytes.fromhex("0e98")               # ldr r0,[sp,#0x38]  (arg5)
          + enc_bl(det124 + 4, cave_a)          # bl scale
          + bytes.fromhex("0e90")               # str r0,[sp,#0x38]
          + bytes.fromhex("0fbc")               # pop {r0-r3}
          + bytes.fromhex("1646ff3600bd"))      # 位移指令 + pop {pc}
    b2 = (bytes.fromhex("0fb5")                 # push {r0-r3,lr}
          + bytes.fromhex("0f98")               # ldr r0,[sp,#0x3c]  (arg6)
          + enc_bl(det844 + 4, cave_a)
          + bytes.fromhex("0f90")               # str r0,[sp,#0x3c]
          + bytes.fromhex("1098")               # ldr r0,[sp,#0x40]  (arg7)
          + enc_bl(det844 + 12, cave_a)
          + bytes.fromhex("1090")               # str r0,[sp,#0x40]
          + bytes.fromhex("0fbc")               # pop {r0-r3}
          + bytes.fromhex("1446064600bd"))      # 位移指令 + pop {pc}
    assert len(b1) == 18 and len(b2) == 26, (len(b1), len(b2))
    return b1 + b2


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    src = Path(args.src)
    raw = bytearray(src.read_bytes())
    md5 = hashlib.md5(bytes(raw)).hexdigest()
    print(f"源文件 : {src}  {len(raw)} 字节  md5={md5}")
    if len(raw) != SRC_SIZE or md5 != SRC_MD5:
        print(f"!! 源不符：期望 {SRC_SIZE} 字节 / md5 {SRC_MD5}", file=sys.stderr)
        return 1

    # ---- 基线 A：15 个系数 ----
    for vaddr, expect, label in COEFFS:
        off = vaddr - BASE
        got = struct.unpack("<f", raw[off:off + 4])[0]
        if abs(got - expect) > 1e-3:
            print(f"!! {vaddr:#010x} 原值={got} 期望={expect}（{label}），中止", file=sys.stderr)
            return 1
        raw[off:off + 4] = struct.pack("<f", COEFF_TARGET)

    # ---- 基线 C：RFID ----
    for vaddr in RFID_FLAGS:
        off = vaddr - BASE
        if bytes(raw[off:off + 2]) != RFID_OLD:
            print(f"!! {vaddr:#010x} RFID={bytes(raw[off:off+2]).hex(' ')}，中止", file=sys.stderr)
            return 1
        raw[off:off + 2] = RFID_NEW

    # ---- 基线 D：RFID 读取失败旁路 ----
    off = RFID_BYPASS_SITE - BASE
    if bytes(raw[off:off + 2]) != RFID_BYPASS_OLD:
        print(f"!! {RFID_BYPASS_SITE:#010x} 字节={bytes(raw[off:off+2]).hex(' ')} "
              f"期望={RFID_BYPASS_OLD.hex(' ')}，中止", file=sys.stderr)
        return 1
    raw[off:off + 2] = RFID_BYPASS_NEW

    # ---- 基线 B：line-period ----
    off = LINEPERIOD_VADDR - BASE
    tab = [struct.unpack("<H", raw[off + 2 * i:off + 2 * i + 2])[0]
           for i in range(len(LINEPERIOD_ORIG))]
    if tab != LINEPERIOD_ORIG:
        print("!! line-period 表不匹配，中止", file=sys.stderr)
        return 1
    for i, v in enumerate(LINEPERIOD_ORIG):
        raw[off + 2 * i:off + 2 * i + 2] = struct.pack("<H", scale_floor(v, FEED))

    # ---- 代码注入 ----
    for hook, orig, target, name in ((HOOK_A, HOOK_A_ORIG, CAVE_B, "hook124"),
                                     (HOOK_B, HOOK_B_ORIG, CAVE_B + 18, "hook844")):
        o = hook - BASE
        if bytes(raw[o:o + 4]) != orig:
            print(f"!! {hook:#010x} 原字节={bytes(raw[o:o+4]).hex(' ')} 期望={orig.hex(' ')}，中止",
                  file=sys.stderr)
            return 1
        bl = enc_bl(hook, target)
        assert dec_bl(hook, bl) == target
        raw[o:o + 4] = bl
        print(f"  {name:<8} {hook:#010x} -> {target:#010x}  {bl.hex(' ')}")

    for zone, blob, name in ((CAVE_A_ZONE, build_cave_a(), "caveA"),
                             (CAVE_B_ZONE, build_cave_b(), "caveB")):
        vaddr = CAVE_A if name == "caveA" else CAVE_B
        o = vaddr - BASE
        zs, ze = zone
        zo = zs - BASE
        if any(raw[zo:ze - BASE + 1]):
            print(f"!! {name} 目标零区 {zs:#010x}..{ze:#010x} 非全零，中止", file=sys.stderr)
            return 1
        if vaddr + len(blob) - 1 > ze:
            print(f"!! {name} 长度 {len(blob)} 超出零区 {ze:#010x}，中止", file=sys.stderr)
            return 1
        raw[o:o + len(blob)] = blob
        print(f"  {name:<8} {vaddr:#010x}  {len(blob)} 字节  "
              f"[{vaddr:#x}..{vaddr+len(blob)-1:#x}] 区间 {zs:#x}..{ze:#x}")

    # ---- 兜底自检：cave 内所有 bl 解码回原目标 ----
    for addr in (CAVE_B + 4, CAVE_B + 18 + 4, CAVE_B + 18 + 12):
        raw4 = bytes(raw[addr - BASE:addr - BASE + 4])
        if dec_bl(addr, raw4) != CAVE_A:
            print(f"!! cave 内 {addr:#010x} 的 bl 目标错误", file=sys.stderr)
            return 1
    for hook, target in ((HOOK_A, CAVE_B), (HOOK_B, CAVE_B + 18)):
        if dec_bl(hook, bytes(raw[hook - BASE:hook - BASE + 4])) != target:
            print(f"!! hook {hook:#010x} 自检失败", file=sys.stderr)
            return 1

    out = bytes(raw)
    print(f"输出   : {len(out)} 字节  md5={hashlib.md5(out).hexdigest()}")
    print(f"        sha256={hashlib.sha256(out).hexdigest()}")
    if args.out:
        Path(args.out).write_bytes(out)
        print(f"写出   : {args.out}")
    else:
        print("（dry-run，未写文件；加 --out 才会落盘）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
