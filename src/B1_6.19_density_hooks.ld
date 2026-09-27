/* Linker script for B1_6.19_density_hooks.s (Niimbot B1 firmware 6.19).
 *
 * Places each section at its fixed flash address so the assembler resolves the
 * bl/ldr literals correctly. Section VMAs (4-byte aligned where required):
 *   .caveA   0x0102cb64 (68 B)   .caveB   0x0102c1ee (44 B)
 *   .hook124 0x010161ee (4 B)    .hook844 0x0101690e (4 B)
 *
 * .caveA must stay 4-byte aligned (it holds the float m-table and the literal pool).
 * .caveA/.caveB sit inside reference-free zero runs of the 6.19 dump:
 *   0x0102cb62..0x0102cbb7 (86 B)  and  0x0102c1ed..0x0102c21d (49 B).
 * Do not move them without re-running the reference scan.
 */
SECTIONS {
  . = 0x0102cb64; .caveA : { *(.caveA) }
  . = 0x0102c1ee; .caveB : { *(.caveB) }
  . = 0x010161ee; .hook124 : { *(.hook124) }
  . = 0x0101690e; .hook844 : { *(.hook844) }
  /DISCARD/ : { *(.ARM.attributes) *(.comment) }
}
