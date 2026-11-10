/* SPDX-License-Identifier: GPL-2.0-only */
ENTRY(_start)
SECTIONS
{
    . = 0;
    .text : { KEEP(*(.text.head)) *(.text*) }
    .rodata : { *(.rodata*) }
    .data : { *(.data*) *(.bss*) *(COMMON) }
    . = ALIGN(4096);
    _image_end = .;
    /DISCARD/ : { *(.note*) *(.comment*) *(.eh_frame*) *(.ARM.attributes*) }
}
