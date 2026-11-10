/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * SM-A530N / jackpotlte stage-0 handoff probe.
 *
 * This follows the arm64 Linux Image entry contract: x0 carries the FDT,
 * interrupts are masked, and this image does not change the MMU or caches.
 */
.section .text.head, "ax"
.global _start
_start:
    b entry
    .long 0
    .quad 0x80000            /* text_offset, rewritten by build.sh */
    .quad 0                  /* image_size, rewritten by build.sh */
    .quad 0                  /* flags */
    .quad 0, 0, 0
    .byte 0x41, 0x52, 0x4d, 0x64 /* ARMd */
    .long 0

entry:
    msr daifset, #15
    mov x19, x0               /* S-Boot FDT pointer */
    mrs x20, CurrentEL

    /* SCTLR_ELx is selected from CurrentEL to avoid a lower-level access. */
    cmp x20, #0xc
    b.eq .Lread_el3
    cmp x20, #0x8
    b.eq .Lread_el2
    mrs x21, sctlr_el1
    b .Lsctlr_ready
.Lread_el2:
    mrs x21, sctlr_el2
    b .Lsctlr_ready
.Lread_el3:
    mrs x21, sctlr_el3
.Lsctlr_ready:
    mrs x22, midr_el1
    mrs x23, mpidr_el1
    mrs x24, id_aa64mmfr0_el1
    mrs x25, id_aa64pfr0_el1
    mrs x26, id_aa64isar0_el1
    mrs x27, cntfrq_el0
    mrs x28, cntpct_el0

    adr x14, jackpot_stack_top
    mov sp, x14
    sub sp, sp, #80
    stp x20, x21, [sp, #0]
    stp x22, x23, [sp, #16]
    stp x24, x25, [sp, #32]
    stp x26, x27, [sp, #48]
    str x28, [sp, #64]

    mov x0, x19
    mov x1, sp
    adr x2, _start
    bl jackpot_probe_main

.Lhalt:
    wfe
    b .Lhalt

.section .data, "aw"
.balign 16
jackpot_stack:
    .space 8192
jackpot_stack_top:
