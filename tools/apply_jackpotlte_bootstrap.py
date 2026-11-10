#!/usr/bin/env python3
"""Apply A530N framebuffer, DECON, persistent-alias, and boot-stage patches."""

import argparse
from pathlib import Path


def patch(tree: Path, rel: str, edits: list[tuple[str, str]]) -> None:
    path = tree / rel
    if not path.is_file():
        raise SystemExit(f"missing XNU source: {path}")
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    original = text
    for old, new in edits:
        count = text.count(old)
        if count == 1:
            text = text.replace(old, new, 1)
        elif count == 0 and text.count(new) == 1:
            continue
        else:
            raise SystemExit(
                f"{path}: expected one patch anchor, found {count}: {old[:100]!r}"
            )
    if text != original:
        path.write_text(text, encoding="utf-8", newline="\n")
        print(f"updated {rel}")
    else:
        print(f"already patched {rel}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("xnu_tree", type=Path)
    tree = parser.parse_args().xnu_tree.resolve()
    if not (tree / "osfmk/arm64/start.s").is_file():
        raise SystemExit(f"{tree}: not an XNU source tree")

    patch(tree, "osfmk/arm64/sweet_early.c", [
        ("""/* The bootstrap TTBR0 maps DECON scanout VA=PA until arm_vm_init. */
#define A5_FB ((volatile uint32_t *)(uintptr_t)0x67000000)
#define A5_STRIDE 1080u
#define A5_SCALE 2u
#define A5_ROW_HEIGHT (16u * A5_SCALE)
#define A5_COL_WIDTH (8u * A5_SCALE)
#define A5_COLS (1080u / A5_COL_WIDTH)
extern unsigned char iso_font[256 * 16];
static unsigned int a5_row = 4, a5_col, a5_active = 1, a5_panicking;

static void
a5_clear_row""", """/* A530N bootstrap scanout and DECON_F, mapped by start.s until arm_vm_init. */
static volatile uint32_t *a5_fb = (volatile uint32_t *)(uintptr_t)A5_FB_PHYS;
static volatile uint32_t *a5_decon = (volatile uint32_t *)(uintptr_t)0x14860000u;
#define A5_FB a5_fb
#define A5_STRIDE (A5_FB_STRIDE / sizeof(uint32_t))
#define A5_SCALE 2u
#define A5_ROW_HEIGHT (16u * A5_SCALE)
#define A5_COL_WIDTH (8u * A5_SCALE)
#define A5_COLS (A5_FB_WIDTH / A5_COL_WIDTH)
#define A5_ROWS (A5_FB_HEIGHT / A5_ROW_HEIGHT)
#define A5_DECON_HW_SW_TRIG_CONTROL 0x70u
#define A5_DECON_SHADOW_REG_UPDATE_REQ 0x60u
extern unsigned char iso_font[256 * 16];
static unsigned int a5_row = 4, a5_col, a5_active = 1, a5_panicking;

static void
a5_decon_flush(void)
{
	volatile uint32_t *trigger = a5_decon + A5_DECON_HW_SW_TRIG_CONTROL / sizeof(uint32_t);
	uint32_t value = *trigger;
	value &= ~((1u << 0) | (1u << 4));
	value |= 1u << 0;
	*trigger = value;
	__asm__ volatile("dsb sy" ::: "memory");

	volatile uint32_t *update = a5_decon + A5_DECON_SHADOW_REG_UPDATE_REQ / sizeof(uint32_t);
	*update |= (1u << 31) | 0x0fu;
	__asm__ volatile("dsb sy" ::: "memory");
}

static void
a5_clear_row"""),
        ("for (unsigned int x = 0; x < A5_STRIDE; x++) {",
         "for (unsigned int x = 0; x < A5_FB_WIDTH; x++) {"),
        ("a5_row = (a5_row + 1) % (1920u / A5_ROW_HEIGHT);",
         "a5_row = (a5_row + 1) % A5_ROWS;"),
        ("""if (!a5_active || stage > 7) {
		return;
	}
	a5_string("A5 XNU STAGE ");
	sweet_early_putc((char)('0' + stage));
	a5_string(": ");
	a5_string(label);
	sweet_early_putc('\\n');
	__asm__ volatile("dsb sy" ::: "memory");
	/* arm_vm_init replaces TTBR0; low physical aliases then cease to exist. */
	if (stage == 7) {
		a5_active = 0;
	}""", """if (!a5_active || stage > 90) {
		return;
	}
	a5_string("A5 XNU STAGE ");
	if (stage >= 10) {
		sweet_early_putc((char)('0' + stage / 10));
	}
	sweet_early_putc((char)('0' + stage % 10));
	a5_string(": ");
	a5_string(label);
	sweet_early_putc('\\n');
	a5_decon_flush();"""),
        ("""sweet_early_putc('\\n');
	__asm__ volatile("dsb sy" ::: "memory");
}

void sweet_early_relocate(uint64_t base) { (void)base; }""", """sweet_early_putc('\\n');
	a5_decon_flush();
}

void
sweet_early_relocate(uint64_t framebuffer_base, uint64_t decon_base)
{
	a5_fb = (volatile uint32_t *)(uintptr_t)framebuffer_base;
	a5_decon = (volatile uint32_t *)(uintptr_t)decon_base;
	a5_active = 1;
	sweet_early_mark(9, "kernel framebuffer aliases live");
}""")
    ])

    patch(tree, "osfmk/arm64/sweet_early.h", [
        ("void sweet_early_relocate(uint64_t base);",
         "void sweet_early_relocate(uint64_t framebuffer_base, uint64_t decon_base);")
    ])

    patch(tree, "osfmk/arm64/start.s", [
        ("""
	subs	x13, x13, #1
	b.ne	La5_fb_attr
#endif""", """
	subs	x13, x13, #1
	b.ne	La5_fb_attr

	/* A530N DECON_F is in this 2 MiB device-memory block. */
	MOV64	x0, 0x14800000
	mov		x4, x0
	mov		x5, #1
	create_bootstrap_mapping x0, x4, x5, x1, x2, x6, x10, x11, x12, x13
	MOV64	x10, 0x14800000
	and		x11, x10, #(ARM_TT_L2_INDEX_MASK)
	lsr		x11, x11, #(ARM_TT_L2_SHIFT)
	add		x12, x2, x11, lsl #TTE_SHIFT
	ldr		x11, [x12]
	bic		x11, x11, #(ARM_TTE_BLOCK_ATTRINDXMASK)
	orr		x11, x11, #(ARM_TTE_BLOCK_ATTRINDX(CACHE_ATTRINDX_DISABLE))
	bic		x11, x11, #(ARM_TTE_BLOCK_SHMASK)
	str		x11, [x12]
	dsb		sy
#endif""")
    ])

    patch(tree, "osfmk/arm64/arm_vm_init.c", [
        ("""#if defined(SWEET) && !defined(A5XELTE)
/*
 * The reserved low-globals/kernel region is excluded from VM allocation.
 * Use the otherwise empty 32MB block above low globals and below gVirtBase
 * for a Normal-NC framebuffer alias that survives bootstrap TTBR0 teardown.
 */
#define SWEET_EARLY_FB_VA (VM_MIN_KERNEL_ADDRESS + ARM_TT_L2_SIZE)

static void
sweet_early_map_final(void)
{
	const vm_map_address_t va = SWEET_EARLY_FB_VA;
	assert(va + ARM_TT_L2_SIZE <= gVirtBase);
	tt_entry_t l1 = cpu_tte[(va & ARM_TT_L1_INDEX_MASK) >> ARM_TT_L1_SHIFT];
	assert((l1 & (ARM_TTE_VALID | ARM_TTE_TYPE_MASK)) == (ARM_TTE_VALID | ARM_TTE_TYPE_TABLE));
	tt_entry_t *l2 = (tt_entry_t *)phystokv(l1 & ARM_TTE_TABLE_MASK);
	tt_entry_t *slot = &l2[(va & ARM_TT_L2_INDEX_MASK) >> ARM_TT_L2_SHIFT];
	assert(*slot == ARM_TTE_EMPTY);
	*slot = 0x9c000000ULL | ARM_TTE_VALID | ARM_TTE_TYPE_BLOCK |
	    ARM_TTE_BLOCK_SH(SH_OUTER_MEMORY) |
	    ARM_TTE_BLOCK_ATTRINDX(CACHE_ATTRINDX_WRITECOMB) |
	    ARM_TTE_BLOCK_AF | ARM_TTE_BLOCK_PNX | ARM_TTE_BLOCK_NX;
	__asm__ volatile("dsb ishst" ::: "memory");
}
#endif""", """#if defined(SWEET)
/* Kernel VA aliases keep scanout and DECON reachable after TTBR0 teardown. */
#define SWEET_EARLY_FB_VA (VM_MIN_KERNEL_ADDRESS + ARM_TT_L2_SIZE)
#if defined(A5XELTE)
#define SWEET_EARLY_FB_PA A5_FB_PHYS
#define SWEET_EARLY_FB_BLOCKS A5_FB_2M_BLOCKS
#define SWEET_EARLY_DECON_VA (SWEET_EARLY_FB_VA + (A5_FB_2M_BLOCKS * ARM_TT_L2_SIZE))
#define SWEET_EARLY_DECON_PA 0x14800000ULL
#else
#define SWEET_EARLY_FB_PA 0x9c000000ULL
#define SWEET_EARLY_FB_BLOCKS 1
#endif

static void
sweet_early_map_final(void)
{
	const vm_map_address_t va = SWEET_EARLY_FB_VA;
	assert((va & (ARM_TT_L2_SIZE - 1)) == 0);
	assert(va + (SWEET_EARLY_FB_BLOCKS * ARM_TT_L2_SIZE) <= gVirtBase);
#if defined(A5XELTE)
	assert((SWEET_EARLY_DECON_VA & (ARM_TT_L2_SIZE - 1)) == 0);
	assert(SWEET_EARLY_DECON_VA + ARM_TT_L2_SIZE <= gVirtBase);
#endif
	vm_map_address_t l1_start = va & ~ARM_TT_L1_OFFMASK;
	init_ptpages(cpu_tte, l1_start, l1_start + ARM_TT_L1_SIZE, TRUE,
	    ARM_DYNAMIC_TABLE_XN | ARM_TTE_TABLE_AP(ARM_TTE_TABLE_AP_USER_NA));
	tt_entry_t l1 = cpu_tte[(va & ARM_TT_L1_INDEX_MASK) >> ARM_TT_L1_SHIFT];
	assert((l1 & (ARM_TTE_VALID | ARM_TTE_TYPE_MASK)) == (ARM_TTE_VALID | ARM_TTE_TYPE_TABLE));
	tt_entry_t *l2 = (tt_entry_t *)phystokv(l1 & ARM_TTE_TABLE_MASK);
	for (unsigned int i = 0; i < SWEET_EARLY_FB_BLOCKS; i++) {
		vm_map_address_t block_va = va + ((vm_map_address_t)i * ARM_TT_L2_SIZE);
		pmap_paddr_t block_pa = SWEET_EARLY_FB_PA + ((pmap_paddr_t)i * ARM_TT_L2_SIZE);
		tt_entry_t *slot = &l2[(block_va & ARM_TT_L2_INDEX_MASK) >> ARM_TT_L2_SHIFT];
		assert(*slot == ARM_TTE_EMPTY);
		*slot = (block_pa & ARM_TTE_BLOCK_L2_MASK) |
		    ARM_TTE_VALID | ARM_TTE_TYPE_BLOCK |
		    ARM_TTE_BLOCK_SH(SH_OUTER_MEMORY) |
		    ARM_TTE_BLOCK_ATTRINDX(CACHE_ATTRINDX_WRITECOMB) |
		    ARM_TTE_BLOCK_AF | ARM_TTE_BLOCK_PNX | ARM_TTE_BLOCK_NX;
	}
#if defined(A5XELTE)
	tt_entry_t *decon_slot = &l2[(SWEET_EARLY_DECON_VA & ARM_TT_L2_INDEX_MASK) >> ARM_TT_L2_SHIFT];
	assert(*decon_slot == ARM_TTE_EMPTY);
	*decon_slot = (SWEET_EARLY_DECON_PA & ARM_TTE_BLOCK_L2_MASK) |
	    ARM_TTE_VALID | ARM_TTE_TYPE_BLOCK | ARM_TTE_BLOCK_SH(SH_NONE) |
	    ARM_TTE_BLOCK_ATTRINDX(CACHE_ATTRINDX_DISABLE) |
	    ARM_TTE_BLOCK_AF | ARM_TTE_BLOCK_PNX | ARM_TTE_BLOCK_NX;
#endif
	__asm__ volatile("dsb ishst" ::: "memory");
}
#endif"""),
        ("""#if defined(SWEET) && !defined(A5XELTE)
	/* phystokv() must still refer to the bootstrap aperture here. */
	sweet_early_map_final();
#endif""", """#if defined(SWEET)
	/* phystokv() must still refer to the bootstrap aperture here. */
	sweet_early_map_final();
	sweet_early_mark(8, "final framebuffer mappings installed");
#endif"""),
        ("""#if defined(SWEET) && !defined(A5XELTE)
	/* The final TTBR1 is live; leave the outgoing VA=PA framebuffer alias. */
	sweet_early_relocate(SWEET_EARLY_FB_VA);
#endif""", """#if defined(SWEET)
	/* Rebind early output to the aliases that survive the TTBR1 switch. */
#if defined(A5XELTE)
	sweet_early_relocate(SWEET_EARLY_FB_VA, SWEET_EARLY_DECON_VA + 0x60000);
#else
	sweet_early_relocate(SWEET_EARLY_FB_VA, 0);
#endif
#endif""")
    ])

    patch(tree, "osfmk/arm/arm_init.c", [
        ("""	kprintf("kprintf initialized\\n");
	sweet_early_mark(20, "kprintf startup complete");
	if (serial_exists) {
		sweet_early_disable();
	}
""", """	kprintf("kprintf initialized\\n");
	sweet_early_mark(20, "kprintf startup complete");
	/* Keep the bootstrap console for progress and panic diagnostics. */
"""),
        ("	__stack_chk_guard &= ~(0xFFULL << 8);\n\tmachine_startup(args);",
         "	__stack_chk_guard &= ~(0xFFULL << 8);\n\tsweet_early_mark(30, \"entering machine_startup\");\n\tmachine_startup(args);")
    ])

    patch(tree, "osfmk/arm64/machine_routines.c", [
        ("#include <arm/machine_routines.h>\n", "#include <arm/machine_routines.h>\n#include <arm64/sweet_early.h>\n"),
        ("\tmachine_conf();\n", "\tmachine_conf();\n\tsweet_early_mark(31, \"machine_conf returned\");\n"),
        ("\tkernel_bootstrap();\n", "\tsweet_early_mark(32, \"calling kernel_bootstrap\");\n\tkernel_bootstrap();\n")
    ])

    patch(tree, "osfmk/kern/startup.c", [
        ("#include <kern/startup.h>\n", "#include <kern/startup.h>\n#include <arm64/sweet_early.h>\n"),
        ("\tprintf(\"%s\\n\", version); /* log kernel version */\n",
         "\tsweet_early_mark(33, \"kernel_bootstrap entered\");\n\tprintf(\"%s\\n\", version); /* log kernel version */\n\tsweet_early_mark(34, \"kernel version printed\");\n"),
        ("\tscale_setup();\n", "\tscale_setup();\n\tsweet_early_mark(35, \"scale_setup returned\");\n"),
        ("\tkernel_bootstrap_log(\"vm_mem_bootstrap\");\n\tvm_mem_bootstrap();\n",
         "\tkernel_bootstrap_log(\"vm_mem_bootstrap\");\n\tsweet_early_mark(36, \"calling vm_mem_bootstrap\");\n\tvm_mem_bootstrap();\n\tsweet_early_mark(65, \"vm_mem_bootstrap returned\");\n"),
        ("\tconsole_init();\n", "\tconsole_init();\n\tsweet_early_mark(66, \"console_init returned\");\n"),
        ("\tsched_init();\n", "\tsched_init();\n\tsweet_early_mark(67, \"sched_init returned\");\n"),
        ("\tPMAP_ACTIVATE_KERNEL(master_cpu);\n", "\tPMAP_ACTIVATE_KERNEL(master_cpu);\n\tsweet_early_mark(68, \"kernel pmap activated\");\n"),
        ("\tmachine_init();\n", "\tmachine_init();\n\tsweet_early_mark(69, \"machine_init returned\");\n"),
        ("\tthread_init();\n", "\tthread_init();\n\tsweet_early_mark(70, \"thread_init returned\");\n"),
        ("\tresult = kernel_thread_create((thread_continue_t)kernel_bootstrap_thread, NULL, MAXPRI_KERNEL, &thread);\n",
         "\tresult = kernel_thread_create((thread_continue_t)kernel_bootstrap_thread, NULL, MAXPRI_KERNEL, &thread);\n\tsweet_early_mark(71, \"kernel bootstrap thread created\");\n"),
        ("\tprocessor_t processor = current_processor();\n", "\tprocessor_t processor = current_processor();\n\tsweet_early_mark(72, \"kernel_bootstrap_thread entered\");\n"),
        ("\tsched_startup();\n", "\tsched_startup();\n\tsweet_early_mark(73, \"sched_startup returned\");\n"),
        ("\tthread_daemon_init();\n", "\tthread_daemon_init();\n\tsweet_early_mark(74, \"thread_daemon_init returned\");\n"),
        ("\tthread_bind(processor);\n", "\tthread_bind(processor);\n\tsweet_early_mark(75, \"thread_bind returned\");\n"),
        ("\tmapping_adjust();\n", "\tmapping_adjust();\n\tsweet_early_mark(76, \"mapping_adjust returned\");\n"),
        ("\tclock_service_create();\n", "\tclock_service_create();\n\tsweet_early_mark(77, \"clock_service_create returned\");\n"),
        ("\tdevice_service_create();\n", "\tdevice_service_create();\n\tsweet_early_mark(78, \"device_service_create returned\");\n"),
        ("\tphys_carveout_init();\n", "\tphys_carveout_init();\n\tsweet_early_mark(79, \"phys_carveout_init returned\");\n"),
        ("\tPE_init_iokit();\n", "\tPE_init_iokit();\n\tsweet_early_mark(80, \"PE_init_iokit returned\");\n"),
        ("\t(void) spllo();         /* Allow interruptions */\n",
         "\t(void) spllo();         /* Allow interruptions */\n\tsweet_early_mark(81, \"interrupts enabled\");\n"),
        ("\tinitialize_screen(NULL, kPEAcquireScreen);\n",
         "\tinitialize_screen(NULL, kPEAcquireScreen);\n\tsweet_early_mark(82, \"initialize_screen returned\");\n")
    ])

    patch(tree, "osfmk/vm/vm_init.c", [
        ("#include <vm/vm_init.h>\n", "#include <vm/vm_init.h>\n#include <arm64/sweet_early.h>\n"),
        ("\tvm_page_bootstrap(&start, &end);\n",
         "\tsweet_early_mark(37, \"entering vm_page_bootstrap\");\n\tvm_page_bootstrap(&start, &end);\n\tsweet_early_mark(56, \"vm_page_bootstrap returned\");\n"),
        ("\tzone_bootstrap();\n", "\tzone_bootstrap();\n\tsweet_early_mark(57, \"zone_bootstrap returned\");\n"),
        ("\tvm_object_bootstrap();\n", "\tvm_object_bootstrap();\n\tsweet_early_mark(58, \"vm_object_bootstrap returned\");\n"),
        ("\tvm_retire_boot_pages();\n", "\tvm_retire_boot_pages();\n\tsweet_early_mark(59, \"vm_retire_boot_pages returned\");\n"),
        ("\tvm_map_init();\n", "\tvm_map_init();\n\tsweet_early_mark(60, \"vm_map_init returned\");\n"),
        ("\tkmem_init(start, end);\n", "\tkmem_init(start, end);\n\tsweet_early_mark(61, \"kmem_init returned\");\n"),
        ("\tkernel_startup_initialize_upto(STARTUP_SUB_KMEM);\n",
         "\tkernel_startup_initialize_upto(STARTUP_SUB_KMEM);\n\tsweet_early_mark(62, \"STARTUP_SUB_KMEM completed\");\n"),
        ("\tvm_fault_init();\n", "\tvm_fault_init();\n\tsweet_early_mark(63, \"vm_fault_init returned\");\n"),
        ("\tkernel_startup_initialize_upto(STARTUP_SUB_ZALLOC);\n",
         "\tkernel_startup_initialize_upto(STARTUP_SUB_ZALLOC);\n\tsweet_early_mark(64, \"STARTUP_SUB_ZALLOC completed\");\n")
    ])

    patch(tree, "osfmk/vm/vm_resident.c", [
        ("#include <san/kasan.h>\n", "#include <san/kasan.h>\n#include <arm64/sweet_early.h>\n"),
        ("\tkernel_startup_initialize_upto(STARTUP_SUB_PMAP_STEAL);\n",
         "\tkernel_startup_initialize_upto(STARTUP_SUB_PMAP_STEAL);\n\tsweet_early_mark(38, \"STARTUP_SUB_PMAP_STEAL completed\");\n"),
        ("\t    sizeof(vm_page_bucket_t), 0);\n",
         "\t    sizeof(vm_page_bucket_t), 0);\n\tsweet_early_mark(39, \"vm page buckets allocated\");\n"),
        ("\t    sizeof(lck_spin_t), 0);\n",
         "\t    sizeof(lck_spin_t), 0);\n\tsweet_early_mark(40, \"vm page bucket locks allocated\");\n"),
        ("\t}\n\n\tfor (i = 0; i < vm_page_bucket_lock_count; i++) {\n",
         "\t}\n\tsweet_early_mark(41, \"vm page buckets initialized\");\n\n\tfor (i = 0; i < vm_page_bucket_lock_count; i++) {\n"),
        ("\t}\n\n\tvm_tag_init();\n",
         "\t}\n\tsweet_early_mark(42, \"vm page bucket locks initialized\");\n\n\tvm_tag_init();\n"),
        ("\tpmap_startup(&virtual_space_start, &virtual_space_end);\n",
         "\tpmap_startup(&virtual_space_start, &virtual_space_end);\n\tsweet_early_mark(55, \"pmap_startup returned\");\n"),
        ("\tuint_t          low_page_count = 0;\n",
         "\tuint_t          low_page_count = 0;\n\tsweet_early_mark(43, \"pmap_startup entered\");\n"),
        ("\tnpages = (uint_t)(mem_sz / (PAGE_SIZE + sizeof(*vm_pages)));\n",
         "\tnpages = (uint_t)(mem_sz / (PAGE_SIZE + sizeof(*vm_pages)));\n\tsweet_early_mark(44, \"pmap page count computed\");\n"),
        ("\tvm_pages = (vm_page_t) pmap_steal_freeable_memory(npages * sizeof *vm_pages);\n",
         "\tvm_pages = (vm_page_t) pmap_steal_freeable_memory(npages * sizeof *vm_pages);\n\tsweet_early_mark(45, \"vm_pages array allocated\");\n"),
        ("\tvm_page_pages_count = 0;\n",
         "\tvm_page_pages_count = 0;\n")
    ])


if __name__ == "__main__":
    main()
