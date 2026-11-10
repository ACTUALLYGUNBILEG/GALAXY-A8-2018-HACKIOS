/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * Samsung legacy Image wrapper for the SM-A530N XNU handoff.
 * It requires EL1 with the MMU off and leaves errors on the framebuffer.
 */
.section .text.head, "ax"
.global _start
_start:
    b entry
    .long 0
    .quad 0x80000
    .quad 0
    .quad 0
    .quad 0, 0, 0
    .byte 0x41, 0x52, 0x4d, 0x64 /* ARMd */
    .long 0

entry:
    msr daifset, #15
    msr spsel, #1
    adr x14, xnu_loader_stack_top
    mov sp, x14
    adr x14, xnu_loader_vectors
    msr vbar_el1, x14
    isb
    mrs x20, CurrentEL
    cmp x20, #4
    b.ne .Lhalt
    mrs x21, SCTLR_EL1
    tbnz x21, #0, .Lhalt

    bl jackpot_xnu_prepare
    cbz x0, .Lhalt

    /* The C function returns {entry PA, boot_args PA} in x0/x1. */
    mov x16, x0
    mov x0, x1
    mrs x14, SCTLR_EL1
    bic x14, x14, #1
    bic x14, x14, #4
    bic x14, x14, #0x1000
    msr SCTLR_EL1, x14
    dsb sy
    isb
    ic iallu
    dsb sy
    isb
    br x16

.Lhalt:
    wfe
    b .Lhalt

.macro XNU_VECTOR slot
    mov x16, #\slot
    b .Lxnu_exception
    .space 0x78
.endm

.balign 0x800
xnu_loader_vectors:
    XNU_VECTOR 0
    XNU_VECTOR 1
    XNU_VECTOR 2
    XNU_VECTOR 3
    XNU_VECTOR 4
    XNU_VECTOR 5
    XNU_VECTOR 6
    XNU_VECTOR 7
    XNU_VECTOR 8
    XNU_VECTOR 9
    XNU_VECTOR 10
    XNU_VECTOR 11
    XNU_VECTOR 12
    XNU_VECTOR 13
    XNU_VECTOR 14
    XNU_VECTOR 15

.Lxnu_exception:
    msr daifset, #15
    msr spsel, #1
    adr x14, xnu_exception_stack_top
    mov sp, x14
    mov x0, x16
    mrs x1, esr_el1
    mrs x2, elr_el1
    mrs x3, far_el1
    bl jackpot_xnu_exception
1:
    wfe
    b 1b

.section .data, "aw"
.balign 16
xnu_loader_stack:
    .space 8192
xnu_loader_stack_top:
.balign 16
xnu_exception_stack:
    .space 4096
xnu_exception_stack_top:
