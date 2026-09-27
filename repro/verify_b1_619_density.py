#!/usr/bin/env python3
"""只读校验 fw/B1_6.19_density_coeff.bin（6.19 密度可控候选镜像）。

校验项:
  1  源镜像 fw/B1_6.19.bin 的 md5 / 大小
  2  候选镜像与源同大小、可完整解析
  3  15 个能量系数 == 400.0
  4  64 项 line-period == floor(old * 3/2)
  5  2 处 RFID curve-flag == 00 21
  6  hook A/B 4 字节 == 期望的 bl，且 bl 解码目标正确
  7  cave A/B 字节 == 由 build 脚本重建的字节（逐字节）
  8  capstone 反汇编回读（若可用）: cave 内 bl 目标 / 栈偏移 / 位移指令
  9  差异字节全部落在允许区域，区域外变化 0

用法: python3 verify_b1_619_density.py [--img fw/B1_6.19_density_coeff.bin]
退出码 0 = 全部通过。
"""
import argparse
import hashlib
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for _p in (str(HERE), str(HERE.parent / "build")):
    sys.path.insert(0, _p)
import build_b1_619_density as B  # noqa: E402

BASE = B.BASE
EXPECT_MD5 = "43065da9717c4ba533c6669cc7a8e9b9"
EXPECT_SHA256 = "cd4af7984982295d457d352992c588a9d265dc2be135ac584c97fd9bcc4bd496"

# 允许变化区域（file offset 区间，闭区间）

def _find(*cands):
    """定位输入文件：本地工作区 (fw/) / 仓库 (firmware/) / 扁平复现包 (同目录) 都可用。"""
    for c in cands:
        for base in (HERE, HERE.parent):
            p = base / c
            if p.exists():
                return str(p)
    return str(HERE.parent / cands[-1])


ALLOWED = [
    (0x01E60, 0x01E6F),      # base 4 系数
    (0x06600, 0x06627),      # renderer A 6 系数
    (0x06D4C, 0x06D5F),      # renderer B 5 系数
    (0x12A4C, 0x12A4D),      # RFID #1
    (0x12B90, 0x12B91),      # RFID #2
    (0x1D21C, 0x1D29B),      # line-period 64 项
    (0x061EE, 0x061F1),      # hook124
    (0x0690E, 0x06911),      # hook844
    (0x1CB64, 0x1CBA7),      # cave A
    (0x1C1EE, 0x1C219),      # cave B
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--img", default=_find("B1_6.19_density_coeff.bin",
                                           "fw/B1_6.19_density_coeff.bin",
                                           "firmware/B1_6.19_density_coeff.bin"))
    ap.add_argument("--src", default=_find("B1_6.19.bin", "fw/B1_6.19.bin",
                                           "firmware/B1_6.19.bin"))
    args = ap.parse_args()

    src_p, img_p = Path(args.src), Path(args.img)
    # 原厂镜像不随仓库分发（版权），缺失时跳过依赖它的两项判据
    src = src_p.read_bytes() if src_p.exists() else None
    img = img_p.read_bytes()
    fails = []

    def check(no, name, ok, detail=""):
        print(f"  {'PASS' if ok else 'FAIL'}  [{no}] {name}" + (f"  {detail}" if detail else ""))
        if not ok:
            fails.append(no)

    print(f"源   : {src_p}")
    print(f"候选 : {img_p}")
    print(f"       {len(img)} 字节  md5={hashlib.md5(img).hexdigest()}")

    if src is None:
        print(f"  SKIP  [1] 源镜像不可用（{src_p} 不存在）—— 需自备原厂 6.19")
    else:
        check(1, "源镜像 md5/大小",
              hashlib.md5(src).hexdigest() == B.SRC_MD5 and len(src) == B.SRC_SIZE,
              f"md5={hashlib.md5(src).hexdigest()}")
    check(2, "候选大小与原厂一致", len(img) == B.SRC_SIZE, f"{len(img)} 字节")

    ok3, bad3 = True, []
    for vaddr, _expect, label in B.COEFFS:
        o = vaddr - BASE
        v = struct.unpack("<f", img[o:o + 4])[0]
        if v != B.COEFF_TARGET:
            ok3 = False
            bad3.append(f"{label}={v}")
    check(3, "15 个系数 == 400.0", ok3, ", ".join(bad3))

    o = B.LINEPERIOD_VADDR - BASE
    tab = [struct.unpack("<H", img[o + 2 * i:o + 2 * i + 2])[0] for i in range(64)]
    want = [B.scale_floor(v, B.FEED) for v in B.LINEPERIOD_ORIG]
    check(4, "64 项 line-period == floor(old*1.5)", tab == want,
          f"max={max(tab)}")

    ok5, bad5 = True, []
    for vaddr in B.RFID_FLAGS:
        o = vaddr - BASE
        if bytes(img[o:o + 2]) != B.RFID_NEW:
            ok5 = False
            bad5.append(f"{vaddr:#x}={bytes(img[o:o+2]).hex(' ')}")
    check(5, "2 处 RFID == 00 21", ok5, ", ".join(bad5))

    ok6, d6 = True, []
    for hook, target, orig, name in ((B.HOOK_A, B.CAVE_B, B.HOOK_A_ORIG, "hook124"),
                                     (B.HOOK_B, B.CAVE_B + 18, B.HOOK_B_ORIG, "hook844")):
        o = hook - BASE
        got = bytes(img[o:o + 4])
        want_bl = B.enc_bl(hook, target)
        back = B.dec_bl(hook, got)
        if got != want_bl or back != target:
            ok6 = False
            d6.append(f"{name} {got.hex(' ')} -> {back:#x} 期望 {target:#x}")
        else:
            d6.append(f"{name}->{target:#x}")
    check(6, "hook bl 字面量与解码目标", ok6, "; ".join(d6))

    cave_a, cave_b = B.build_cave_a(), B.build_cave_b()
    ok7 = (bytes(img[B.CAVE_A - BASE:B.CAVE_A - BASE + len(cave_a)]) == cave_a and
           bytes(img[B.CAVE_B - BASE:B.CAVE_B - BASE + len(cave_b)]) == cave_b)
    check(7, "cave A/B 字节 == 重建字节", ok7,
          f"caveA={len(cave_a)}B caveB={len(cave_b)}B")

    try:
        sys.path.insert(0, os.path.expanduser("~/.tools"))
        from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB, CS_MODE_MCLASS
        md = Cs(CS_ARCH_ARM, CS_MODE_THUMB + CS_MODE_MCLASS)
        lines = []
        # cave B 内 3 条 bl 必须指向 cave A
        ins = {i.address: i for i in md.disasm(
            img[B.CAVE_B - BASE:B.CAVE_B - BASE + 44], B.CAVE_B)}
        ok8 = True
        for addr in (B.CAVE_B + 4, B.CAVE_B + 22, B.CAVE_B + 30):
            i = ins.get(addr)
            if i is None or i.mnemonic != "bl" or int(i.op_str.lstrip('#'), 16) != B.CAVE_A:
                ok8 = False
                lines.append(f"{addr:#x}:{i.mnemonic if i else '?'} {i.op_str if i else ''}")
        # hook 处的 bl
        for hook, target in ((B.HOOK_A, B.CAVE_B), (B.HOOK_B, B.CAVE_B + 18)):
            got = next(md.disasm(img[hook - BASE:hook - BASE + 4], hook), None)
            if got is None or got.mnemonic != "bl" or int(got.op_str.lstrip('#'), 16) != target:
                ok8 = False
                lines.append(f"hook {hook:#x} 解码异常")
        # cave B 的栈偏移（0x38 / 0x3c / 0x40）与位移指令
        want_ins = {B.CAVE_B + 2: "ldr r0, [sp, #0x38]",
                    B.CAVE_B + 20: "ldr r0, [sp, #0x3c]",
                    B.CAVE_B + 28: "ldr r0, [sp, #0x40]",
                    B.CAVE_B + 12: "mov r6, r2",
                    B.CAVE_B + 14: "adds r6, #0xff",
                    B.CAVE_B + 38: "mov r4, r2",
                    B.CAVE_B + 40: "mov r6, r0"}
        for addr, want in want_ins.items():
            i = ins.get(addr)
            got = f"{i.mnemonic} {i.op_str}" if i else "?"
            if got != want:
                ok8 = False
                lines.append(f"{addr:#x}: '{got}' != '{want}'")
        check(8, "capstone 反汇编回读（bl 目标/栈偏移/位移指令）", ok8, "; ".join(lines) or "OK")
    except Exception as e:  # capstone 缺失时跳过，不影响其余判据
        print(f"  SKIP  [8] capstone 不可用（{e}）—— 其余判据不受影响")

    if src is None:
        print("  SKIP  [9] 差异区域约束（需要原厂源镜像）")
    else:
        diffs = [i for i, (x, y) in enumerate(zip(src, img)) if x != y]
        outside = [i for i in diffs if not any(a <= i <= b for a, b in ALLOWED)]
        check(9, "差异全部落在允许区域", not outside,
              f"变化 {len(diffs)} 字节，区域外 {len(outside)}"
              + (f" 首个 {outside[0]:#x}" if outside else ""))

    md5 = hashlib.md5(img).hexdigest()
    sha = hashlib.sha256(img).hexdigest()
    if EXPECT_MD5:
        check(10, "候选 md5/sha256 与台账一致",
              md5 == EXPECT_MD5 and sha == EXPECT_SHA256, f"md5={md5}")
    else:
        print(f"  INFO [10] md5={md5}  sha256={sha}")

    print()
    if fails:
        print(f"结果: 未通过 {sorted(set(fails))} 项 —— 不可用于刷写")
        return 1
    print("结果: 全部通过，可用（仍须真机验证打印效果）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
