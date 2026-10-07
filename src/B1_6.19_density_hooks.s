/* Cortex-M0 code-cave detour source — Niimbot B1 firmware 6.19 (HW 6.01).
 *
 * Ported from ThreeDaPrint/niimbot src/B1_5.22_density_hooks.s (fw 5.22) by address
 * substitution; the instruction stream is unchanged. Address mapping (all measured,
 * see analysis/density-port-6.19.md):
 *
 *   density byte   0x00020704 -> 0x00020740      (config struct 0x20700 -> 0x2073c)
 *   soft-float mul 0x0102529b -> 0x01026157      (FUN_0102529a -> FUN_01026156)
 *   hook A         0x01016126 -> 0x010161ee      (FUN_01016124 -> FUN_010161ec)
 *   hook B         0x01016846 -> 0x0101690e      (FUN_01016844 -> FUN_0101690c)
 *   cave A         0x0102bbec -> 0x0102cb64      (ref-free zero run)
 *   cave B         0x0102bc4a -> 0x0102c1ee      (ref-free zero run)
 *
 * Not part of this cave code, but applied by the same builder: the 6.19-only RFID
 * read-failure bypass at 0x010254c2 (movs r1,#1 -> movs r1,#0, bytes 01 21 -> 00 21,
 * see docs/B1_6.19_rfid_bypass.md.
 *
 * Authoritative byte source for the shipped image is build/build_b1_619_density.py.
 * That encoder is anchored by byte-exact reproduction of the upstream 5.22 image
 * (repro/reproduce_522_density.py -> 0 bytes difference vs md5 023ff563...).
 * This .s is provided for review and for re-tooling with arm-none-eabi-*; it was NOT
 * assembled on the machine that produced the .bin (no ARM toolchain there).
 *
 * Safety: m(d) <= 1.0, so D5 (m=1.0) is energy-identical to the full-quality baseline
 * and lower densities only reduce energy.
 */
    .syntax unified
    .cpu cortex-m0
    .thumb

    /* ===== Cave A @ 0x0102cb64 : shared scale + m-table (68 B) ===== */
    .section .caveA, "ax", %progbits
    .thumb_func
    .global scale
scale:                       @ in: r0 = input float ; out: r0 = input * m(density)
    push {r4, lr}
    ldr  r4, =0x00020740     @ &density  (config struct 0x2073c, +4)
    ldrb r4, [r4]
    movs r1, #0x7f
    ands r4, r1              @ d = density & 0x7f
    cmp  r4, #1
    bhs  1f
    movs r4, #1              @ clamp low
1:  cmp  r4, #5
    bls  2f
    movs r4, #5              @ clamp high
2:  subs r4, r4, #1          @ index 0..4
    lsls r4, r4, #2          @ *4
    ldr  r1, =mtable
    ldr  r1, [r1, r4]        @ r1 = m(d)
    ldr  r3, =0x01026157     @ FUN_01026156 | thumb (soft-float multiply)
    blx  r3                  @ r0 = r0 * r1
    pop  {r4, pc}
    .align 2
    .global mtable
mtable:
    .float 0.675
    .float 0.756250
    .float 0.837500
    .float 0.918750
    .float 1.0
    .ltorg

    /* ===== Cave B @ 0x0102c1ee : renderer detours (44 B) ===== */
    .section .caveB, "ax", %progbits
    .thumb_func
    .global det124
det124:                      @ FUN_010161ec detour body (entered after entry push)
    push {r0-r3, lr}
    ldr  r0, [sp, #0x38]     @ arg5 (renderer input float)
    bl   scale
    str  r0, [sp, #0x38]
    pop  {r0-r3}
    .short 0x4616            @ displaced: mov  r6, r2
    .short 0x36ff            @ displaced: adds r6, #0xff
    pop  {pc}                @ -> 0x010161f2

    .thumb_func
    .global det844
det844:                      @ FUN_0101690c detour body (entered after entry push)
    push {r0-r3, lr}
    ldr  r0, [sp, #0x3c]     @ arg6 (input float A)
    bl   scale
    str  r0, [sp, #0x3c]
    ldr  r0, [sp, #0x40]     @ arg7 (input float B)
    bl   scale
    str  r0, [sp, #0x40]
    pop  {r0-r3}
    .short 0x4614            @ displaced: mov r4, r2
    .short 0x4606            @ displaced: mov r6, r0
    pop  {pc}                @ -> 0x01016912

    /* ===== detour stubs (4 bytes each), installed over the renderer entries ===== */
    .section .hook124, "ax", %progbits
    .thumb_func
h124:
    bl   det124              @ replaces 4 bytes at 0x010161ee

    .section .hook844, "ax", %progbits
    .thumb_func
h844:
    bl   det844              @ replaces 4 bytes at 0x0101690e
