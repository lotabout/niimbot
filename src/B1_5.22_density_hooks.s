    .syntax unified
    .cpu cortex-m0
    .thumb

    /* ============ Cave A @ 0x0102bbea : shared scale + mtable ============ */
    .section .caveA, "ax", %progbits
    .thumb_func
    .global scale
scale:                       @ in: r0=input float ; out: r0 = input * m(density)
    push {r4, lr}
    ldr  r4, =0x00020704     @ &density
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
    ldr  r3, =0x0102529b     @ FUN_0102529a | thumb
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

    /* ============ Cave B @ 0x0102bc4a : renderer detours ============ */
    .section .caveB, "ax", %progbits
    .thumb_func
    .global det124
det124:                      @ FUN_01016124 detour body (entered after entry push)
    push {r0-r3, lr}
    ldr  r0, [sp, #0x38]     @ arg5 (renderer input float)
    bl   scale
    str  r0, [sp, #0x38]
    pop  {r0-r3}
    .short 0x4616            @ displaced: mov  r6, r2
    .short 0x36ff            @ displaced: adds r6, #0xff
    pop  {pc}                @ -> 0x0101612a

    .thumb_func
    .global det844
det844:                      @ FUN_01016844 detour body (entered after entry push)
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
    pop  {pc}                @ -> 0x0101684a

    /* ============ detour stubs (4 bytes each) ============ */
    .section .hook124, "ax", %progbits
    .thumb_func
h124:
    bl   det124              @ replaces 4 bytes at 0x01016126

    .section .hook844, "ax", %progbits
    .thumb_func
h844:
    bl   det844              @ replaces 4 bytes at 0x01016846
