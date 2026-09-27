# Niimbot B1 固件补丁 · 硬件 6.01 / 固件 6.19

针对 **Niimbot B1（硬件 6.01 / 固件 6.19）** 的固件补丁：解除原厂对第三方标签纸的浓度压制，
并让 App 里的浓度档 **D1–D5 真正控制打印头能量**（出厂固件根本没把密度值接进打印头）。

- **主分支：`niimbot-hw6.01`** —— 本页即该分支，面向 FW 6.19 / HW 6.01。
- `main` 分支保留上游 [ThreeDaPrint/niimbot](https://github.com/ThreeDaPrint/niimbot) 的
  **5.22** 原样内容，仅用于对照、取素材与同步上游。

---

> ## ⚠️ 先读这一段
>
> - **本分支的镜像只适用于固件 `6.19`（硬件 6.01）。** 5.22 的镜像在 `main` 分支。
> - **跨大版本刷写会变砖**（5.x ↔ 6.x、→ 4.x）：不要把 5.22 镜像刷进 6.x 机器，反之亦然。
> - 本项目面向**自有硬件上的实验与维修**，按原样提供，**不提供任何担保**；
>   刷坏设备、丢失序列号/MAC 等后果完全自负。
> - 原厂镜像不随仓库分发（精臣版权）：需要时从
>   <https://fw.niim.blue/stable/B1/> 自取（建议刷写前先备份并留好回退镜像）。

---

## 1. 这个补丁解决什么

1. **第三方 / 无芯片 / 填充纸打不满浓度** —— 原厂固件对非官方耗材压低热量，补丁解除该压制。
2. **浓度档形同虚设** —— 原厂固件把用户设置的密度只存进配置结构体、用 GetInfo 回读，
   却**从未送进打印头**；补丁把它真正接到渲染能量上。
3. **D5 = 实心黑**，且能量与"固定满能量版"完全一致；低档只会在 D5 基础上**减少**能量，
   因此不会过烧、也不会打乱走纸时序。

## 2. 两个候选镜像

| 文件 | md5 | 说明 |
|---|---|---|
| `firmware/B1_6.19_density_coeff.bin` | `43065da9717c4ba533c6669cc7a8e9b9` | **推荐**：密度可控版，D1–D5 生效 |
| `firmware/B1_6.19_thirdparty_fullquality.bin` | `b7d4f4e5f07bdae5fceb75b29949e6af` | 固定满能量版，密度档无效 |

两个镜像均为 **124436 字节**，与原厂 6.19 同尺寸、无需改分区表；SHA-256 见 `repro/SHA256SUMS.txt`。

## 3. 原理（够用版）

```
每点热量 ≈ 渲染输入 × 能量系数
```

出厂固件在 flash 里放了 15 个 IEEE-754 能量系数，并按纸张类型取用较低的一组；第三方纸
因此明显偏淡。补丁做两件事：

**候选 A（固定满能量）** —— 纯数据改写：
- 15 个系数（4 个 base + 6 个 renderer A + 5 个 renderer B）→ `400.0`
- line-period 表 64×u16 → `floor(原值 × 1.5)`（走纸降速，给每行更多加热时间）
- 2 处 RFID curve-flag `03 21` → `00 21`（跟随上游成品，效果无害）

**候选 B（密度可控）** = 候选 A + 4 处代码注入：在两个渲染函数入口 `push` 之后各放一条
`bl`，跳进 flash 空白区的代码洞穴，按密度缩放栈上的渲染输入：

```
m(d) = coeff(d) / 400
```

| 档位 | m | 等效系数 | 说明 |
|---|---|---|---|
| D1 | 0.675 | 270 | 高灵敏热敏纸 |
| D2 | 0.75625 | 302.5 | |
| D3 | 0.8375 | 335 | 普通纸的实用最低值 |
| D4 | 0.91875 | 367.5 | |
| **D5** | **1.0** | **400** | **实心黑，与候选 A 能量完全等价** |

注入点（6.19 实测换址，依据见 `docs/B1_6.19_density_port_notes.md`）：

| 项目 | 上游 5.22 | 本机 6.19 |
|---|---|---|
| 密度字节 | `0x00020704` | `0x00020740` |
| 固件自带 soft-float 乘法 | `0x0102529a` | `0x01026156` |
| renderer A / B 入口 | `0x01016124` / `0x01016844` | `0x010161ec` / `0x0101690c` |
| 代码洞穴 A / B | `0x0102bbec` / `0x0102bc4a` | `0x0102cb64` / `0x0102c1ee` |

## 4. 分支

| 分支 | 目标机型 | 内容 |
|---|---|---|
| **`niimbot-hw6.01`**（主分支） | **FW 6.19 / HW 6.01** | 本仓库主线：6.19 移植、构建/校验脚本、移植台账 |
| `main` | FW 5.22 | 上游 ThreeDaPrint 原样（5.22 成品、RE 文档、cave 汇编），用于对照与同步 |

## 5. 仓库目录

| 路径 | 说明 |
|---|---|
| `firmware/B1_6.19_density_coeff.bin` | **候选 B**：密度可控版镜像 |
| `firmware/B1_6.19_thirdparty_fullquality.bin` | **候选 A**：固定满能量版镜像 |
| `build/build_b1_619_density.py` | 候选 B 的构建脚本（Thumb `bl` 编码器 + cave 组装 + 自检） |
| `build/build_b1_619.py` | 候选 A 的构建脚本 |
| `repro/verify_b1_619_density.py` | 候选 B 只读校验（10 项，含 capstone 反汇编回读） |
| `repro/verify_b1_619.py` | 候选 A 只读校验（7 项） |
| `repro/reproduce_522_density.py` | **根证据**：用同一套 cave 编码器逐字节复现上游 5.22 密度成品 |
| `repro/verify_recipe_on_522.py` | **根证据**：用同一套数据规则复现上游 5.22 满能量成品 |
| `src/B1_6.19_density_hooks.s` / `.ld` | 6.19 的 cave 汇编源与链接脚本（等价汇编，见台账 §6） |
| `docs/B1_6.19_density_port_notes.md` | **移植台账**：地址对照、证据链、未验证项 |
| `docs/B1_density_coefficient_checkpoint.md` | 上游 5.22 的密度特性 RE（把补丁移植到别的固件时读它） |
| `docs/B1_firmware_RE_checkpoint.md` | 上游 5.22 的能量模型与通用 RE |
| `src/niimbot_b1.py` | 极简 B1 USB（CDC-ACM）打印/查询驱动 |
| `test-labels/dtest_D1..D5.png` | 384 px 自标注测试图，按对应档位打印即可看出梯度 |

## 6. 刷机与回退（风险自负，本仓库不代为执行）

```sh
# 候选 B（推荐）——需 Node.js，npx 会自动拉取 niimblue-node
npx --yes @mmote/niimblue-node flash -t serial -a /dev/ttyACM0 -n 6.19 \
  -f firmware/B1_6.19_density_coeff.bin

# 或候选 A（固定满能量，密度档无效）
npx --yes @mmote/niimblue-node flash -t serial -a /dev/ttyACM0 -n 6.19 \
  -f firmware/B1_6.19_thirdparty_fullquality.bin
```

- 打印机会在刷完后**自动关机**，按电源键开机即可；USB 会重新枚举，属正常现象，不是变砖。
- 成功标志：刷写过程以 `FirmwareNoMoreChunks → In_FirmwareCheckResult → FirmwareCommit` 结束。
- **回退**：刷回原厂 6.19（同大版本互刷安全）。原厂镜像从
  <https://fw.niim.blue/stable/B1/B1_6.19.bin> 自取，md5 `fd9efd1441b5f05ca46c310b8d162dc1`。
- 原厂 App 里的固件升级提示**一律忽略**。

## 7. 复现与自检

```sh
# ① 只读校验（10 项；缺少 capstone 时第 8 项自动跳过）
python3 repro/verify_b1_619_density.py --src <原厂 B1_6.19.bin>

# ② 从原厂镜像重建候选 B（不带 --out 为 dry-run）
python3 build/build_b1_619_density.py --src <原厂 B1_6.19.bin> --out rebuilt.bin

# ③ 根证据：用同一套 cave 编码器复现上游 5.22 密度成品（应 0 字节差异）
python3 repro/reproduce_522_density.py --src <原厂 B1_5.22.bin>
```

原厂镜像不随仓库分发，从 <https://fw.niim.blue/stable/B1/> 下载；两条根证据脚本需要
5.22 原厂镜像 + `main` 分支的 5.22 成品。反汇编回读需要 `pip install capstone`。

仓库内**不含**原厂镜像（精臣版权）。如需含原厂镜像副本的离线复现包，请另行索取。

## 8. 已证实 / 尚未证实

**已证实（字节级）**

- 候选 B 可由原厂 6.19 逐字节重建（md5 `43065da9…`），全部 270 个变化字节都在预期区域内，
  预期外 0 字节。
- 15 个系数、64 项 line-period、2 处 RFID 标志、2 条 hook 的 `bl` 字面量、两处代码洞穴字节
  均逐项核对通过；capstone 反汇编回读确认 `bl` 目标、栈偏移 `0x38/0x3c/0x40` 与被覆盖指令的重放。
- 整套 cave 编码器被上游成品锚定：用同一编码器只换地址，可从原厂 5.22 逐字节复现
  ThreeDaPrint 发布的 5.22 密度成品（md5 `023ff563…`，**0 字节差异**）。
- 6.19 与 5.22 的 renderer 入口、soft-float 乘法例程、配置结构体逐条同构（前 20~48 字节全同）。

**尚未证实（别当成已证明）**

- **未在任何设备上刷写或打印过** —— 全部结论来自静态分析与成品复现。
- `400.0` 与 m 表是上游在 **5.22** 上标定的经验值（200 淡 / 250 不实 / 325 接近 / 370 差不多 /
  400 实心 / 500 实心 / 700 仍实心）；本机 6.19 的打印头批次、供电、纸材未必相同。
- line-period ×1.5 对时序的影响在 6.19 上未验证（上游在 5.22 上验证过 ×1.5 安全、×2 丢行）。
- **双色纸的红档很可能失效**：候选 A/B 都把 renderer A 的 6 个系数一并拉到 400，
  而红黑双色正是靠这组系数的能量窗口分档。需要保双色请见 §9。

## 9. 实机测试要点

1. **必须用第三方 / 无芯片热敏纸**：原厂纸带 RFID，无论固件怎么改都会打得深，看不出档位差异。
2. 刷写**前**先用第三方纸打一张基线，便于对照。
3. 打印时先设对纸张类型（间隙纸 / 黑标纸 / 连续纸），否则走纸与定位会干扰判断。
4. 依次打印 `test-labels/dtest_D1..D5.png`（或用自己的图），D1→D5 应单调变深，D5 实心黑。
5. **过烧**（文字洇墨、边缘糊、纸面发焦）说明本机能量窗口比 5.22 低：用较低系数重建，例如
   ```sh
   python3 build/build_b1_619.py --coeff 300 --feed 1.5 --out firmware/B1_6.19_c300.bin
   ```
6. **要保双色**：重建时跳过 renderer A 的 6 个系数（改 `build/build_b1_619.py` 里的 `COEFFS`
   列表），或只改 base 组 + renderer B + line-period。本仓库暂未提供该变体。
7. 测试脚本：
   ```sh
   python3 src/niimbot_b1.py info          # 先确认固件版本
   python3 src/niimbot_b1.py image test-labels/dtest_D3.png --density 3
   ```

## 10. 换机型 / 换固件怎么办

**不要**把本分支的镜像刷到别的机型或固件版本上。正确做法是把 `docs/` 里的两份 checkpoint
交给一个有能力的编码 LLM，让它在你自己的固件 dump 上重做一遍：

- `docs/B1_density_coefficient_checkpoint.md` —— 密度特性逆向 + 补丁图（含 cave 汇编）
- `docs/B1_firmware_RE_checkpoint.md` —— 能量模型、系数定位、Cortex-M0 detour 技巧

本仓库的 6.19 移植就是这么来的，可以作为范例：**先**用同一套编码器复现上游 5.22 成品
（逐字节）证明工具正确，**再**换址应用到新 dump，最后用反汇编回读与引用链核对新地址。
换址前务必确认零引用零字节区（代码洞穴）——6.19 里只有两处满足条件，其余零区都被引用。

## 11. 来源与许可

- 上游项目：[ThreeDaPrint/niimbot](https://github.com/ThreeDaPrint/niimbot)（5.22 补丁、RE 文档、cave 汇编的原始来源）。
- 本仓库是它的 fork；`main` 保留上游原样，`niimbot-hw6.01` 是面向 6.19 的移植分支。
- 上游项目**没有明确指定开源许可证**，仅声明"按原样提供、不提供任何担保"。
  使用、修改、分发请自行评估法律风险；固件本身版权归精臣（Niimbot）所有。
