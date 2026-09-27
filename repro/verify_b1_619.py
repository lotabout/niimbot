#!/usr/bin/env python3
"""只读校验：给定原厂与候选镜像，逐项核对 B1 6.19 满能量补丁（不修改任何文件）。

用法:
  python3 verify_b1_619.py --src B1_6.19.bin --patched B1_6.19_thirdparty_fullquality.bin

检查项:
  ① 源为原厂（大小 124436、md5 fd9efd14...）
  ② 候选大小与源相同
  ③ 15 个 float 系数 == 400.0（字节 00 00 C8 43）
  ④ 64 项 line-period == floor(old * 3/2)，且无 u16 溢出
  ⑤ 两处 RFID curve-flag == 00 21（原厂为 03 21）
  ⑥ 全文件差异只落在目标区（覆盖 192 字节），预期外变化 0
  ⑦ 候选 md5 == 期望值
退出码 0 = 全部通过。
"""
import argparse
import hashlib
import struct
import sys
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_patch_b1_619 import (BASE, COEFFS, COEFF_TARGET, FEED,  # noqa: E402
                                LINEPERIOD_ORIG, LINEPERIOD_VADDR,
                                OUT_MD5, RFID_FLAGS, RFID_NEW, RFID_OLD,
                                SRC_MD5, SRC_SIZE, scale_floor)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--patched", required=True)
    ap.add_argument("--expect-md5", default=OUT_MD5)
    args = ap.parse_args()

    o = Path(args.src).read_bytes()
    n = Path(args.patched).read_bytes()
    bad = []

    c1 = len(o) == SRC_SIZE and hashlib.md5(o).hexdigest() == SRC_MD5
    print(f"① 原厂识别      : {'PASS' if c1 else 'FAIL'}"
          f"  ({len(o)} 字节, md5={hashlib.md5(o).hexdigest()})")
    if not c1:
        bad.append("①")

    c2 = len(n) == len(o)
    print(f"② 候选大小相同  : {'PASS' if c2 else 'FAIL'}  ({len(n)} 字节)")
    if not c2:
        bad.append("②")

    c3 = True
    for vaddr, _expect, label in COEFFS:
        off = vaddr - BASE
        b = n[off:off + 4]
        if b != b"\x00\x00\xc8\x43" or struct.unpack("<f", b)[0] != COEFF_TARGET:
            c3 = False
            print(f"   !! {vaddr:#010x} {label} = {b.hex()}")
    print(f"③ 15 个系数=400 : {'PASS' if c3 else 'FAIL'}")
    if not c3:
        bad.append("③")

    off = LINEPERIOD_VADDR - BASE
    new = [struct.unpack("<H", n[off + 2 * i:off + 2 * i + 2])[0] for i in range(64)]
    want = [min(scale_floor(v, FEED), 0xFFFF) for v in LINEPERIOD_ORIG]
    c4 = new == want and max(new) <= 0xFFFF
    diffidx = [i for i in range(64) if new[i] != want[i]]
    print(f"④ 64 项 floor   : {'PASS' if c4 else 'FAIL'}"
          f"  (max={max(new)}, 不符项={diffidx})")
    if not c4:
        bad.append("④")

    c5 = True
    for vaddr in RFID_FLAGS:
        p = vaddr - BASE
        if o[p:p + 2] != RFID_OLD or n[p:p + 2] != RFID_NEW:
            c5 = False
            print(f"   !! {vaddr:#010x} 原厂={o[p:p + 2].hex(' ')} 候选={n[p:p + 2].hex(' ')}")
    print(f"⑤ 2 处 RFID 标志: {'PASS' if c5 else 'FAIL'}  (03 21 -> 00 21)")
    if not c5:
        bad.append("⑤")

    target = set()
    for vaddr, _e, _l in COEFFS:
        target.update(range(vaddr - BASE, vaddr - BASE + 4))
    for vaddr in RFID_FLAGS:
        target.update(range(vaddr - BASE, vaddr - BASE + 2))
    target.update(range(off, off + 128))
    diffs = [i for i in range(len(o)) if o[i] != n[i]]
    extra = [i for i in diffs if i not in target]
    covered = len(target)
    c6 = not extra
    print(f"⑥ 差异范围      : {'PASS' if c6 else 'FAIL'}"
          f"  (覆盖 {covered} 字节, 实际变化 {len(diffs)} 字节, 预期外 {len(extra)})")
    if not c6:
        bad.append("⑥")
        print(f"   预期外偏移: {[hex(x) for x in extra[:20]]}")

    md5 = hashlib.md5(n).hexdigest()
    c7 = md5 == args.expect_md5
    print(f"⑦ 候选 md5      : {'PASS' if c7 else 'FAIL'}  ({md5})")
    if not c7:
        bad.append("⑦")

    print("\n结论: " + ("全部通过，可用" if not bad else f"存在失败项 {'/'.join(bad)}"))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
