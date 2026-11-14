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
        if text.count(new) == 1:
            continue
        if count == 1:
            text = text.replace(old, new, 1)
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
	}""", """if (!a5_active || stage > 220) {
		return;
	}
	a5_string("A5 XNU STAGE ");
	if (stage >= 100) {
		sweet_early_putc((char)('0' + stage / 100));
	}
	if (stage >= 10) {
		sweet_early_putc((char)('0' + (stage / 10) % 10));
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
         "\tinitialize_screen(NULL, kPEAcquireScreen);\n\tsweet_early_mark(82, \"initialize_screen returned\");\n"),
        ("\tvm_commpage_init();\n",
         "\tsweet_early_mark(83, \"enter vm_commpage_init\");\n\tvm_commpage_init();\n\tsweet_early_mark(84, \"vm_commpage_init returned\");\n"),
        ("\tvm_commpage_text_init();\n",
         "\tvm_commpage_text_init();\n\tsweet_early_mark(85, \"commpage text returned\");\n"),
        ("#if CONFIG_MACF\n\tkernel_bootstrap_log(\"mac_policy_initmach\");",
         "\tsweet_early_mark(86, \"early policy setup entered\");\n#if CONFIG_MACF\n\tkernel_bootstrap_log(\"mac_policy_initmach\");"),
        ("#endif\n\n#ifndef BCM2837\n\tkernel_bootstrap_log(\"trust_cache_init\");",
         "#endif\n\tsweet_early_mark(87, \"early policy setup returned\");\n\n#ifndef BCM2837\n\tkernel_bootstrap_log(\"trust_cache_init\");"),
        ("\ttrust_cache_runtime_init();\n",
         "\tsweet_early_mark(88, \"trust runtime entered\");\n\ttrust_cache_runtime_init();\n\tsweet_early_mark(89, \"trust runtime returned\");\n"),
        ("\tload_static_trust_cache();\n",
         "\tsweet_early_mark(90, \"static trust cache entered\");\n\tload_static_trust_cache();\n\tsweet_early_mark(91, \"static trust cache returned\");\n"),
        ("\tkernel_startup_initialize_upto(STARTUP_SUB_LOCKDOWN);\n",
         "\tkernel_startup_initialize_upto(STARTUP_SUB_LOCKDOWN);\n\tsweet_early_mark(92, \"STARTUP_SUB_LOCKDOWN returned\");\n"),
        ("\tOSKextRemoveKextBootstrap();\n",
         "\tsweet_early_mark(93, \"kext removal entered\");\n\tOSKextRemoveKextBootstrap();\n\tsweet_early_mark(94, \"kext removal returned\");\n"),
        ("\tmachine_lockdown();\n",
         "\tsweet_early_mark(95, \"machine lockdown entered\");\n\tmachine_lockdown();\n\tsweet_early_mark(96, \"machine lockdown returned\");\n"),
        ("#ifdef  IOKIT\n\tkernel_bootstrap_log(\"PE_lockdown_iokit\");",
         "\tsweet_early_mark(97, \"IOKit lockdown entered\");\n#ifdef  IOKIT\n\tkernel_bootstrap_log(\"PE_lockdown_iokit\");"),
        ("\tPE_lockdown_iokit();\n#endif\n\t/*\n\t * max_cpus",
         "\tPE_lockdown_iokit();\n#endif\n\tsweet_early_mark(98, \"IOKit lockdown returned\");\n\t/*\n\t * max_cpus"),
        ("\tvm_set_restrictions(machine_info.max_cpus);\n",
         "\tvm_set_restrictions(machine_info.max_cpus);\n\tsweet_early_mark(99, \"vm restrictions returned\");\n"),
        ("#ifdef  MACH_BSD\n\tbsd_init();\n#endif",
         "\tsweet_early_mark(100, \"BSD init entered\");\n#ifdef  MACH_BSD\n\tbsd_init();\n#endif\n\tsweet_early_mark(101, \"BSD init returned\");"),
        ("\tkdebug_free_early_buf();\n",
         "\tkdebug_free_early_buf();\n\tsweet_early_mark(102, \"early kdebug buffer freed\");\n"),
        ("\tserial_keyboard_init();         /* Start serial keyboard if wanted */\n",
         "\tserial_keyboard_init();         /* Start serial keyboard if wanted */\n\tsweet_early_mark(103, \"serial keyboard init returned\");\n"),
        ("\tvm_page_init_local_q(machine_info.max_cpus);\n",
         "\tvm_page_init_local_q(machine_info.max_cpus);\n\tsweet_early_mark(104, \"local page queue returned\");\n"),
        ("\tthread_bind(PROCESSOR_NULL);\n",
         "\tthread_bind(PROCESSOR_NULL);\n\tsweet_early_mark(105, \"boot thread unbound\");\n"),
        ("\tvm_free_delayed_pages();\n",
         "\tvm_free_delayed_pages();\n\tsweet_early_mark(106, \"delayed pages freed\");\n"),
        ("\tvm_pageout();\n",
         "\tsweet_early_mark(107, \"entering vm_pageout\");\n\tvm_pageout();\n")
    ])

    patch(tree, "bsd/kern/bsd_init.c", [
        ("#include <kern/startup.h>\n", "#include <kern/startup.h>\n#include <arm64/sweet_early.h>\n"),
        ("\tthrottle_init();\n", "\tsweet_early_mark(108, \"throttle_init entered\");\n\tthrottle_init();\n\tsweet_early_mark(109, \"throttle_init returned\");\n"),
        ("\tprintf(copyright);\n", "\tsweet_early_mark(110, \"copyright print entered\");\n\tprintf(copyright);\n\tsweet_early_mark(111, \"copyright print returned\");\n"),
        ("#if CONFIG_DEV_KMEM\n\tbsd_init_kprintf(\"calling dev_kmem_init\\n\");", "\tsweet_early_mark(112, \"dev_kmem setup entered\");\n#if CONFIG_DEV_KMEM\n\tbsd_init_kprintf(\"calling dev_kmem_init\\n\");"),
        ("\tdev_kmem_init();\n#endif\n\n\t/* Initialize kauth", "\tdev_kmem_init();\n#endif\n\tsweet_early_mark(113, \"dev_kmem setup returned\");\n\n\t/* Initialize kauth"),
        ("\tkauth_init();\n", "\tsweet_early_mark(114, \"kauth_init entered\");\n\tkauth_init();\n\tsweet_early_mark(115, \"kauth_init returned\");\n"),
        ("\tset_bsdtask_info(kernel_task, (void *)kernproc);\n", "\tsweet_early_mark(116, \"kernel task process link entered\");\n\tset_bsdtask_info(kernel_task, (void *)kernproc);\n\tsweet_early_mark(117, \"kernel task process link returned\");\n"),
        ("\tprocess_name(\"kernel_task\", kernproc);\n", "\tsweet_early_mark(118, \"kernel process naming entered\");\n\tprocess_name(\"kernel_task\", kernproc);\n\tsweet_early_mark(119, \"kernel process naming returned\");\n"),
        ("\tfdt_init(kernproc);\n", "\tsweet_early_mark(120, \"fdt_init entered\");\n\tfdt_init(kernproc);\n\tsweet_early_mark(121, \"fdt_init returned\");\n"),
        ("\tut = current_uthread();\n", "\tsweet_early_mark(122, \"current_uthread entered\");\n\tut = current_uthread();\n\tsweet_early_mark(123, \"current_uthread returned\");\n"),
        ("\tstruct session *session0 = session_alloc(kernproc);\n", "\tsweet_early_mark(124, \"process zero session setup entered\");\n\tstruct session *session0 = session_alloc(kernproc);\n"),
        ("\tproc_list_unlock();\n\n\tproc_set_task(kernproc, kernel_task);", "\tproc_list_unlock();\n\tsweet_early_mark(125, \"process zero linked\");\n\n\tsweet_early_mark(126, \"proc_set_task entered\");\n\tproc_set_task(kernproc, kernel_task);\n\tsweet_early_mark(127, \"proc_set_task returned\");"),
        ("\tproc_update_creds_onproc(kernproc);\n", "\tsweet_early_mark(128, \"proc credential update entered\");\n\tproc_update_creds_onproc(kernproc);\n\tsweet_early_mark(129, \"proc credential update returned\");\n"),
        ("\t(void)chgproccnt(0, 1);\n", "\tsweet_early_mark(130, \"chgproccnt entered\");\n\t(void)chgproccnt(0, 1);\n\tsweet_early_mark(131, \"chgproccnt returned\");\n"),
        ("\tbsd_init_kprintf(\"calling kmem_suballoc\\n\");\n\tbsd_pageable_map = kmem_suballoc(kernel_map,", "\tsweet_early_mark(132, \"BSD kmem_suballoc entered\");\n\tbsd_init_kprintf(\"calling kmem_suballoc\\n\");\n\tbsd_pageable_map = kmem_suballoc(kernel_map,"),
        ("\t    VM_KERN_MEMORY_BSD).kmr_submap;\n", "\t    VM_KERN_MEMORY_BSD).kmr_submap;\n\tsweet_early_mark(133, \"BSD kmem_suballoc returned\");\n"),
        ("\tbsd_bufferinit();\n", "\tsweet_early_mark(134, \"bsd_bufferinit entered\");\n\tbsd_bufferinit();\n\tsweet_early_mark(135, \"bsd_bufferinit returned\");\n"),
        ("\tIOKitInitializeTime();\n", "\tsweet_early_mark(136, \"IOKitInitializeTime entered\");\n\tIOKitInitializeTime();\n\tsweet_early_mark(137, \"IOKitInitializeTime returned\");\n"),
        ("\tvfsinit();\n", "\tsweet_early_mark(138, \"vfsinit entered\");\n\tvfsinit();\n\tsweet_early_mark(139, \"vfsinit returned\");\n"),
        ("#if CONFIG_PROC_UUID_POLICY\n\t/* Initial proc_uuid_policy subsystem */", "\tsweet_early_mark(142, \"proc UUID policy setup entered\");\n#if CONFIG_PROC_UUID_POLICY\n\t/* Initial proc_uuid_policy subsystem */"),
        ("\tproc_uuid_policy_init();\n#endif\n\n#if SOCKETS", "\tproc_uuid_policy_init();\n#endif\n\tsweet_early_mark(143, \"proc UUID policy setup returned\");\n\n#if SOCKETS"),
        ("\tmbinit();\n", "\tsweet_early_mark(144, \"mbinit entered\");\n\tmbinit();\n\tsweet_early_mark(145, \"mbinit returned\");\n"),
        ("#if CONFIG_AUDIT\n\tbsd_init_kprintf(\"calling audit_init\\n\");", "\tsweet_early_mark(146, \"audit initialization entered\");\n#if CONFIG_AUDIT\n\tbsd_init_kprintf(\"calling audit_init\\n\");"),
        ("\taudit_init();\n#endif\n\n\t/* Initialize kqueues */", "\taudit_init();\n#endif\n\tsweet_early_mark(147, \"audit initialization returned\");\n\n\t/* Initialize kqueues */"),
        ("\tknote_init();\n", "\tsweet_early_mark(148, \"knote_init entered\");\n\tknote_init();\n\tsweet_early_mark(149, \"knote_init returned\");\n"),
        ("\teventhandler_init();\n", "\tsweet_early_mark(150, \"eventhandler_init entered\");\n\teventhandler_init();\n\tsweet_early_mark(151, \"eventhandler_init returned\");\n"),
        ("\taio_init();\n", "\tsweet_early_mark(152, \"aio_init entered\");\n\taio_init();\n\tsweet_early_mark(153, \"aio_init returned\");\n"),
        ("\tpthread_init();\n", "\tsweet_early_mark(154, \"pthread_init entered\");\n\tpthread_init();\n\tsweet_early_mark(155, \"pthread_init returned\");\n"),
        ("\tpshm_cache_init();\n", "\tsweet_early_mark(156, \"pshm_cache_init entered\");\n\tpshm_cache_init();\n\tsweet_early_mark(157, \"pshm_cache_init returned\");\n"),
        ("\tpsem_cache_init();\n", "\tsweet_early_mark(158, \"psem_cache_init entered\");\n\tpsem_cache_init();\n\tsweet_early_mark(159, \"psem_cache_init returned\");\n"),
        ("\tnwk_wq_init();\n", "\tsweet_early_mark(160, \"nwk_wq_init entered\");\n\tnwk_wq_init();\n\tsweet_early_mark(161, \"nwk_wq_init returned\");\n"),
        ("\tdlil_init();\n", "\tsweet_early_mark(162, \"dlil_init entered\");\n\tdlil_init();\n\tsweet_early_mark(163, \"dlil_init returned\");\n"),
        ("\tsocketinit();\n", "\tsweet_early_mark(164, \"socketinit entered\");\n\tsocketinit();\n\tsweet_early_mark(165, \"socketinit returned\");\n"),
        ("\tdomaininit();\n", "\tsweet_early_mark(166, \"domaininit entered\");\n\tdomaininit();\n\tsweet_early_mark(167, \"domaininit returned\");\n"),
        ("\t(void) skywalk_init();\n", "\tsweet_early_mark(168, \"skywalk_init entered\");\n\t(void) skywalk_init();\n\tsweet_early_mark(169, \"skywalk_init returned\");\n"),
        ("\tmemorystatus_freeze_init();\n", "\tsweet_early_mark(170, \"memorystatus_freeze_init entered\");\n\tmemorystatus_freeze_init();\n\tsweet_early_mark(171, \"memorystatus_freeze_init returned\");\n"),
        ("\tmemorystatus_init();\n", "\tsweet_early_mark(172, \"memorystatus_init entered\");\n\tmemorystatus_init();\n\tsweet_early_mark(173, \"memorystatus_init returned\");\n"),
        ("\tsysctl_mib_init();\n", "\tsweet_early_mark(174, \"sysctl_mib_init entered\");\n\tsysctl_mib_init();\n\tsweet_early_mark(175, \"sysctl_mib_init returned\");\n"),
        ("\tbsd_autoconf();\n", "\tsweet_early_mark(176, \"bsd_autoconf entered\");\n\tbsd_autoconf();\n\tsweet_early_mark(177, \"bsd_autoconf returned\");\n"),
        ("\tloopattach();                   /* XXX */\n", "\tsweet_early_mark(178, \"loopattach entered\");\n\tloopattach();                   /* XXX */\n\tsweet_early_mark(179, \"loopattach returned\");\n"),
        ("\tether_family_init();\n", "\tsweet_early_mark(180, \"ether_family_init entered\");\n\tether_family_init();\n\tsweet_early_mark(181, \"ether_family_init returned\");\n"),
        ("\tnet_init_run();\n", "\tsweet_early_mark(182, \"net_init_run entered\");\n\tnet_init_run();\n\tsweet_early_mark(183, \"net_init_run returned\");\n"),
        ("\tinittodr(0);\n", "\tsweet_early_mark(184, \"inittodr entered\");\n\tinittodr(0);\n\tsweet_early_mark(185, \"inittodr returned\");\n"),
        ("\t\tsetconf();\n", "\t\tsweet_early_mark(186, \"setconf entered\");\n\t\tsetconf();\n\t\tsweet_early_mark(187, \"setconf returned\");\n"),
        ("\t\tif (0 == (err = vfs_mountroot())) {\n", "\t\tsweet_early_mark(188, \"vfs_mountroot entered\");\n\t\tif (0 == (err = vfs_mountroot())) {\n\t\t\tsweet_early_mark(189, \"vfs_mountroot returned\");\n"),
        ("\tIOSecureBSDRoot(rootdevice);\n", "\tsweet_early_mark(190, \"IOSecureBSDRoot entered\");\n\tIOSecureBSDRoot(rootdevice);\n\tsweet_early_mark(191, \"IOSecureBSDRoot returned\");\n"),
        ("\tif (VFS_ROOT(mountlist.tqh_first, &init_rootvnode, vfs_context_kernel())) {\n", "\tsweet_early_mark(192, \"VFS_ROOT entered\");\n\tif (VFS_ROOT(mountlist.tqh_first, &init_rootvnode, vfs_context_kernel())) {\n"),
        ("\tinit_rootvnode = NULLVP;  /* use rootvnode after this point */\n", "\tinit_rootvnode = NULLVP;  /* use rootvnode after this point */\n\tsweet_early_mark(193, \"root vnode setup returned\");\n"),
        ("#if DEVFS\n\t{\n\t\tchar mounthere[] = \"/dev\";", "\tsweet_early_mark(194, \"devfs mount entered\");\n#if DEVFS\n\t{\n\t\tchar mounthere[] = \"/dev\";"),
        ("\t}\n#endif /* DEVFS */\n\n#if CONFIG_BASESYSTEMROOT", "\t}\n#endif /* DEVFS */\n\tsweet_early_mark(195, \"devfs mount returned\");\n\n#if CONFIG_BASESYSTEMROOT"),
        ("\tsiginit(kernproc);\n", "\tsweet_early_mark(196, \"siginit entered\");\n\tsiginit(kernproc);\n\tsweet_early_mark(197, \"siginit returned\");\n"),
        ("\tbsd_utaskbootstrap();\n", "\tsweet_early_mark(198, \"bsd_utaskbootstrap entered\");\n\tbsd_utaskbootstrap();\n\tsweet_early_mark(199, \"bsd_utaskbootstrap returned\");\n"),
        ("\tpal_kernel_announce();\n", "\tsweet_early_mark(200, \"pal_kernel_announce entered\");\n\tpal_kernel_announce();\n\tsweet_early_mark(201, \"pal_kernel_announce returned\");\n"),
        ("\tbsd_init_kprintf(\"calling mountroot_post_hook\\n\");\n", "\tsweet_early_mark(202, \"mountroot_post_hook entered\");\n\tbsd_init_kprintf(\"calling mountroot_post_hook\\n\");\n"),
        ("#endif\n\n#if 0 /* not yet */\n\tconsider_zone_gc(FALSE);", "#endif\n\tsweet_early_mark(203, \"mountroot_post_hook returned\");\n\n#if 0 /* not yet */\n\tconsider_zone_gc(FALSE);"),
        ("\tbsd_init_kprintf(\"done\\n\");\n}\n", "\tbsd_init_kprintf(\"done\\n\");\n\tsweet_early_mark(204, \"bsd_init complete\");\n}\n")
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
        ("\tvm_page_buckets = (vm_page_bucket_t *)\n\t    pmap_steal_memory(vm_page_bucket_count *\n\t    sizeof(vm_page_bucket_t), 0);\n",
         "\tvm_page_buckets = (vm_page_bucket_t *)\n\t    pmap_steal_memory(vm_page_bucket_count *\n\t    sizeof(vm_page_bucket_t), 0);\n\tsweet_early_mark(39, \"vm page buckets allocated\");\n"),
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
        ("\tnpages = (uint_t)(mem_sz / (PAGE_SIZE + sizeof(*vm_pages)));    /* scaled to include the vm_page_ts */\n",
         "\tnpages = (uint_t)(mem_sz / (PAGE_SIZE + sizeof(*vm_pages)));    /* scaled to include the vm_page_ts */\n\tsweet_early_mark(44, \"pmap page count computed\");\n"),
        ("\tvm_pages = (vm_page_t) pmap_steal_freeable_memory(npages * sizeof *vm_pages);\n",
         "\tvm_pages = (vm_page_t) pmap_steal_freeable_memory(npages * sizeof *vm_pages);\n\tsweet_early_mark(45, \"vm_pages array allocated\");\n"),
    ])


if __name__ == "__main__":
    main()
