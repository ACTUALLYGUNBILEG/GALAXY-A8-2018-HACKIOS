/*
 * Small AArch64 helpers injected into the linked diagnostic kernel by
 * patch_jackpotlte_xnu_decon.py. Keep map_decon within the first 0x100 bytes;
 * the patcher places flush_decon at offset 0x100 in a verified __text zero gap.
 */
	.text
	.p2align 2
	.global map_decon
map_decon:
	/* Allocate and zero one L2 table for the 0x14800000 DECON_F block. */
	mov	x0, #0x14800000
	add	x2, x2, #0x1000
	mov	x3, x2
	mov	x4, #512
1:
	str	xzr, [x3], #8
	subs	x4, x4, #1
	b.ne	1b

	/* Add the L1 table descriptor to the V=P root in x1. */
	and	x3, x0, #0x7fc0000000
	lsr	x3, x3, #30
	lsl	x3, x3, #3
	add	x3, x1, x3
	mov	x4, #3
	and	x5, x2, #0xfffffffff000
	orr	x5, x4, x5
	str	x5, [x3]

	/* One 2 MiB identity block; AttrIndx=3 is the bootstrap Device type. */
	and	x3, x0, #0x3fe00000
	lsr	x3, x3, #21
	add	x3, x2, x3, lsl #3
	mov	x4, #0x40d
	and	x5, x0, #0xffffffe00000
	orr	x5, x5, x4
	str	x5, [x3]
	dsb	ish
	.word	0xffffffff /* patched to B 0xfffffff007412458 */

	.org	0x100, 0
	.global flush_decon
flush_decon:
	dsb	sy
	mov	x9, #0x14860000
	add	x9, x9, #0x70
	ldr	w10, [x9]
	bic	w10, w10, #0x11
	orr	w10, w10, #0x1
	str	w10, [x9]
	dsb	sy
	sub	x9, x9, #0x10
	ldr	w10, [x9]
	mov	w11, #0x80000000
	orr	w11, w11, #0xf
	orr	w10, w10, w11
	str	w10, [x9]
	dsb	sy
	ret
