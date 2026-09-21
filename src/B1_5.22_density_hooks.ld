/* Linker script for B1_5.22_density_hooks.s (Niimbot B1 firmware 5.22).
 *
 * Places each section at its fixed flash address so the assembler resolves
 * the bl/ldr literals correctly. Note .caveA contains `.align 2` (float table),
 * so ld rounds its start from 0x0102bbea up to 0x0102bbec; .caveB and the two
 * 4-byte hook stubs land exactly where stated. Section VMAs after linking:
 *   .caveA   0x0102bbec (68 B)   .caveB   0x0102bc4a (44 B)
 *   .hook124 0x01016126 (4 B)    .hook844 0x01016846 (4 B)
 */
SECTIONS {
  . = 0x0102bbea; .caveA : { *(.caveA) }
  . = 0x0102bc4a; .caveB : { *(.caveB) }
  . = 0x01016126; .hook124 : { *(.hook124) }
  . = 0x01016846; .hook844 : { *(.hook844) }
  /DISCARD/ : { *(.ARM.attributes) *(.comment) }
}
