#!/usr/bin/env python3
"""Apply the first SM-A530N hardware overrides to an A5XELTE XNU tree.

Run after the shared XNU patches and the A5XELTE/GICv2 patches:
    python tools/apply_jackpotlte_xnu.py work/xnu-8796.141.3

This prepares a single-core entry kernel. It does not build XNU or create a
Samsung BOOT image. The RAM window and timer route remain bring-up candidates.
"""
import argparse
from pathlib import Path


def apply_file(tree, rel, edits):
    path = tree / rel
    text = path.read_text()
    for old, new, expected in edits:
        found = text.count(old)
        if found == expected:
            text = text.replace(old, new)
        elif found == 0 and text.count(new) == expected:
            # The pinned donor patch stack already carries this exact override.
            # Accept it as-is so later device-specific edits remain repeatable.
            continue
        else:
            raise SystemExit(f"{rel}: expected {expected} occurrence(s), found {found}: {old!r}")
    return path, text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("xnu_tree", type=Path)
    args = parser.parse_args()
    tree = args.xnu_tree.resolve()
    if not (tree / "osfmk/arm64/start.s").is_file():
        raise SystemExit(f"{tree}: not an XNU source tree")

    plans = {
        "pexpert/pexpert/arm64/A5XELTE.h": [(
            "#define A5XELTE_VTIMER_INTID         27\n",
            """#define A5XELTE_VTIMER_INTID         30

/* Galaxy A8 2018 SM-A530N / Exynos 7885 first-kernel values. */
#define A5_FB_PHYS                    0xEC000000
#define A5_FB_WIDTH                   1080
#define A5_FB_HEIGHT                  2220
#define A5_FB_STRIDE                  4320
#define A5_FB_2M_BLOCKS               10
#define A5_ENTRY_MARKER_PHYS          0xEC923FF8
#define A5_BOOT_MPIDR                 0x100
#define A5_USE_PHYS_TIMER             1
""", 1)],
        "iokit/KernelConfigTables.cpp": [
            ("#if defined(ARM64_BOARD_CONFIG_SWEET)\n",
             "#if defined(ARM64_BOARD_CONFIG_SWEET) || defined(ARM64_BOARD_CONFIG_A5XELTE)\n", 1),
            ("    \"     'IONameMatch'     = 'xiaomi,sweet';\"\n",
             "#if defined(ARM64_BOARD_CONFIG_A5XELTE)\n"
             "    \"     'IONameMatch'     = 'samsung,a5xelte';\"\n"
             "#else\n"
             "    \"     'IONameMatch'     = 'xiaomi,sweet';\"\n"
             "#endif\n", 1),
            ("    \"     'IONameMatch'     = 'qcom,kryo470';\"\n",
             "#if defined(ARM64_BOARD_CONFIG_A5XELTE)\n"
             "    \"     'IONameMatch'     = 'arm,cortex-a53';\"\n"
             "#else\n"
             "    \"     'IONameMatch'     = 'qcom,kryo470';\"\n"
             "#endif\n", 1),
        ],
        "iokit/Kernel/IOPlatformExpert.cpp": [
            ("#include <libkern/crypto/sha1.h>\n",
             "#include <libkern/crypto/sha1.h>\n#include <libkern/crypto/crypto_internal.h>\n", 1),
            ("if (data2 && data2->getLength() == 4) {",
             "if (data2 && data2->getLength() == 4 && g_crypto_funcs &&\n"
             "\t\t\t    g_crypto_funcs->ccsha1_di && g_crypto_funcs->ccdigest_init_fn &&\n"
             "\t\t\t    g_crypto_funcs->ccdigest_update_fn) {", 1),
        ],
        # The diagnostic kernel has no corecrypto kext. Route the legacy AES
        # CBC/ECB API and the available SHA-256/MD5 paths through the portable
        # BearSSL implementations already staged by the build workflow.
        "libkern/crypto/corecrypto_aes.c": [
            ("#if defined(ARM64_BOARD_CONFIG_SWEET)\n",
             "#if defined(ARM64_BOARD_CONFIG_SWEET) || defined(ARM64_BOARD_CONFIG_A5XELTE)\n", 1),
            ("/* SWEET has a built-in portable AES provider for the legacy CBC/ECB API. */\n",
             "/* SWEET/A5XELTE diagnostics use portable AES for the legacy CBC/ECB API. */\n", 1),
        ],
        "libkern/crypto/sweet_aes.c": [
            ("#if defined(ARM64_BOARD_CONFIG_SWEET)\n",
             "#if defined(ARM64_BOARD_CONFIG_SWEET) || defined(ARM64_BOARD_CONFIG_A5XELTE)\n", 1),
        ],
        "libkern/crypto/sweet_aes_ct.c": [
            ("#if defined(ARM64_BOARD_CONFIG_SWEET)\n",
             "#if defined(ARM64_BOARD_CONFIG_SWEET) || defined(ARM64_BOARD_CONFIG_A5XELTE)\n", 1),
        ],
        "libkern/crypto/sweet_aes_ct_enc.c": [
            ("#if defined(ARM64_BOARD_CONFIG_SWEET)\n",
             "#if defined(ARM64_BOARD_CONFIG_SWEET) || defined(ARM64_BOARD_CONFIG_A5XELTE)\n", 1),
        ],
        "libkern/crypto/sweet_aes_ct_dec.c": [
            ("#if defined(ARM64_BOARD_CONFIG_SWEET)\n",
             "#if defined(ARM64_BOARD_CONFIG_SWEET) || defined(ARM64_BOARD_CONFIG_A5XELTE)\n", 1),
        ],
        "libkern/crypto/sweet_aes_ct_cbcenc.c": [
            ("#if defined(ARM64_BOARD_CONFIG_SWEET)\n",
             "#if defined(ARM64_BOARD_CONFIG_SWEET) || defined(ARM64_BOARD_CONFIG_A5XELTE)\n", 1),
        ],
        "libkern/crypto/sweet_aes_ct_cbcdec.c": [
            ("#if defined(ARM64_BOARD_CONFIG_SWEET)\n",
             "#if defined(ARM64_BOARD_CONFIG_SWEET) || defined(ARM64_BOARD_CONFIG_A5XELTE)\n", 1),
        ],
        "libkern/crypto/corecrypto_sha2.c": [
            ("#if defined(ARM64_BOARD_CONFIG_SWEET)\n",
             "#if defined(ARM64_BOARD_CONFIG_SWEET) || defined(ARM64_BOARD_CONFIG_A5XELTE)\n", 1),
            (" * SWEET has no corecrypto kext, so g_crypto_funcs stays NULL. SHA-256 uses\n",
             " * SWEET/A5XELTE diagnostics have no corecrypto kext. SHA-256 uses\n", 1),
        ],
        "libkern/crypto/corecrypto_md5.c": [
            ("#if defined(ARM64_BOARD_CONFIG_SWEET)\n",
             "#if defined(ARM64_BOARD_CONFIG_SWEET) || defined(ARM64_BOARD_CONFIG_A5XELTE)\n", 1),
            ("#else /* !ARM64_BOARD_CONFIG_SWEET */\n",
             "#else /* neither SWEET nor A5XELTE */\n", 1),
        ],
        "libkern/crypto/sweet_md5.c": [
            ("#if defined(ARM64_BOARD_CONFIG_SWEET)\n",
             "#if defined(ARM64_BOARD_CONFIG_SWEET) || defined(ARM64_BOARD_CONFIG_A5XELTE)\n", 1),
        ],
        "libkern/crypto/sweet_enc32le.c": [
            ("#if defined(ARM64_BOARD_CONFIG_SWEET)\n",
             "#if defined(ARM64_BOARD_CONFIG_SWEET) || defined(ARM64_BOARD_CONFIG_A5XELTE)\n", 1),
        ],
        "libkern/crypto/sweet_dec32le.c": [
            ("#if defined(ARM64_BOARD_CONFIG_SWEET)\n",
             "#if defined(ARM64_BOARD_CONFIG_SWEET) || defined(ARM64_BOARD_CONFIG_A5XELTE)\n", 1),
        ],
        "bsd/pthread/sweet_pthread_init.c": [
            ("#if defined(ARM64_BOARD_CONFIG_SWEET)\n",
             "#if defined(ARM64_BOARD_CONFIG_SWEET) || defined(ARM64_BOARD_CONFIG_A5XELTE)\n", 1),
            ('    kprintf("SWEET pthread: libpthread-514.100.2 registered\\n");\n',
             '#if defined(ARM64_BOARD_CONFIG_A5XELTE)\n'
             '    kprintf("A5XELTE pthread: libpthread-514.100.2 registered\\n");\n'
             '#else\n'
             '    kprintf("SWEET pthread: libpthread-514.100.2 registered\\n");\n'
             '#endif\n', 1),
            ("#endif /* ARM64_BOARD_CONFIG_SWEET */\n",
             "#endif /* SWEET || A5XELTE */\n", 1),
        ],
        "bsd/pthread/sweet_pthread_support.c": [
            ("#if defined(ARM64_BOARD_CONFIG_SWEET)\n",
             "#if defined(ARM64_BOARD_CONFIG_SWEET) || defined(ARM64_BOARD_CONFIG_A5XELTE)\n", 1),
            ("#endif /* ARM64_BOARD_CONFIG_SWEET */\n",
             "#endif /* SWEET || A5XELTE */\n", 1),
        ],
        "bsd/pthread/sweet_pthread_synch.c": [
            ("#if defined(ARM64_BOARD_CONFIG_SWEET)\n",
             "#if defined(ARM64_BOARD_CONFIG_SWEET) || defined(ARM64_BOARD_CONFIG_A5XELTE)\n", 1),
            ("#endif /* ARM64_BOARD_CONFIG_SWEET */\n",
             "#endif /* SWEET || A5XELTE */\n", 1),
        ],
        "bsd/sys/pthread_internal.h": [
            ("\t#if defined(ARM64_BOARD_CONFIG_SWEET)\n",
             "\t#if defined(ARM64_BOARD_CONFIG_SWEET) || defined(ARM64_BOARD_CONFIG_A5XELTE)\n", 1),
        ],
        "bsd/conf/Makefile.template": [
            ("# This provider is built into SWEET; other boards use their normal kext.\n",
             "# This provider is built into SWEET and A5XELTE diagnostic kernels.\n", 1),
            ("ifeq ($(CURRENT_MACHINE_CONFIG),SWEET)\n",
             "ifneq ($(filter $(CURRENT_MACHINE_CONFIG),SWEET A5XELTE),)\n", 1),
        ],
        "osfmk/arm64/start.s": [
            ("MOV64\tx10, 0x469ff100", "MOV64\tx10, A5_ENTRY_MARKER_PHYS", 1),
            ("MOV64\tx10, 0x6705d0c0", "MOV64\tx10, (A5_FB_PHYS + 88 * A5_FB_STRIDE + 240 * 4)", 1),
            ("MOV64\tx10, 0x6707ecc0", "MOV64\tx10, (A5_FB_PHYS + 120 * A5_FB_STRIDE + 240 * 4)", 1),
            ("MOV64\tx10, 0x670a08c0", "MOV64\tx10, (A5_FB_PHYS + 152 * A5_FB_STRIDE + 240 * 4)", 1),
            ("MOV64\tx10, 0x670c24c0", "MOV64\tx10, (A5_FB_PHYS + 184 * A5_FB_STRIDE + 240 * 4)", 1),
            ("MOV64\tx10, 0x670e40c0", "MOV64\tx10, (A5_FB_PHYS + 216 * A5_FB_STRIDE + 240 * 4)", 1),
            ("mov\t\tx15, #4320", "mov\t\tx15, #A5_FB_STRIDE", 2),
            ("mov\tx15, #4320", "mov\tx15, #A5_FB_STRIDE", 3),
            ("MOV64\tx0, 0x67000000\n\tmov\t\tx4, x0\n\tmov\t\tx5, #5\n",
             "MOV64\tx0, A5_FB_PHYS\n\tmov\t\tx4, x0\n\tmov\t\tx5, #A5_FB_2M_BLOCKS\n", 1),
            ("MOV64\tx10, 0x67000000", "MOV64\tx10, A5_FB_PHYS", 1),
            ("mov\t\tx13, #5\nLa5_fb_attr:", "mov\t\tx13, #A5_FB_2M_BLOCKS\nLa5_fb_attr:", 1),
            ("/* Five 2 MiB blocks map the 1080x1920 scanout buffer VA=PA.",
             "/* A5_FB_2M_BLOCKS 2 MiB blocks map the scanout buffer VA=PA.", 1),
            ("MOV64\tx4, 0x67000000\n\tmov\tx5, #4320",
             "MOV64\tx4, A5_FB_PHYS\n\tmov\tx5, #A5_FB_STRIDE", 1),
        ],
        "iokit/Kernel/arm/SweetCPU.cpp": [
            ("\tuint32_t initialized = 0; /* release/acquire publication after initCPU sends SGI */",
             "\tuint32_t initialized = 0; /* release/acquire publication after local initCPU signal handling */", 1),
            ("extern \"C\" boolean_t sweet_cpu_signal_is_enabled(unsigned int cpu);\n",
             "extern \"C\" boolean_t sweet_cpu_signal_is_enabled(unsigned int cpu);\n"
             "extern \"C\" void cpu_signal_handler(void);\n", 1),
            ("\t/* The supplied ADT has cpu0 as the boot CPU and ascending A55 nodes. */\n"
             "\tif (topology->boot_cpu->cpu_id != 0 || topology->boot_cpu->phys_id != 0) {\n"
             "\t\tpanic(\"SWEET CPU: expected boot MPIDR 0 and logical CPU 0\");\n",
             "\t/* The ADT's single active CPU is the A53 boot core at MPIDR 0x100. */\n"
             "\tif (topology->boot_cpu->cpu_id != 0 || topology->boot_cpu->phys_id != A5_BOOT_MPIDR) {\n"
             "\t\tpanic(\"jackpotlte: expected boot MPIDR %#x and logical CPU 0\", A5_BOOT_MPIDR);\n", 1),
            ("\t/* Secondary startup runs at splsched: queue the self-IPI and return.\n"
             "\t * startAll waits for its delivery after the startup thread unmasks IRQs.\n"
             "\t * Waiting here with DAIF.I set would deadlock every secondary. */\n"
             "\tsignalCPU(this);",
             "\t/* This diagnostic ADT exposes only the already-running boot CPU. Clear\n"
             "\t * XNU's initial SIGPdisabled state locally; the donor GICv2 SGI path\n"
             "\t * can deadlock startup before ml_init_interrupt() completes. */\n"
             "\tcpu_signal_handler();", 1),
        ],
        "pexpert/arm/pe_fiq.c": [
            ("\t/* INTID 27 is the virtual timer PPI; SGI 1 is the local self signal. */\n"
             "\ta5_gic_write32(a5_gicd_base, 0x080,\n"
             "\t    a5_gic_read32(a5_gicd_base, 0x080) | (1U << 27) | (1U << 1));",
             "\t/* INTID 30 is the physical timer PPI; SGI 1 is the local self signal. */\n"
             "\ta5_gic_write32(a5_gicd_base, 0x080,\n"
             "\t    a5_gic_read32(a5_gicd_base, 0x080) | (1U << A5XELTE_VTIMER_INTID) | (1U << 1));", 1),
            ("\ta5_gic_write32(a5_gicd_base, 0x100, (1U << 27) | (1U << 1));",
             "\ta5_gic_write32(a5_gicd_base, 0x100, (1U << A5XELTE_VTIMER_INTID) | (1U << 1));", 1),
        ],
        "osfmk/arm64/machine_routines.c": [
            ('\t\t__builtin_arm_wsr64("CNTV_TVAL_EL0", (uint64_t)dec_value);\n',
             '#if defined(A5_USE_PHYS_TIMER)\n\t\t__builtin_arm_wsr64("CNTP_TVAL_EL0", (uint64_t)dec_value);\n#else\n\t\t__builtin_arm_wsr64("CNTV_TVAL_EL0", (uint64_t)dec_value);\n#endif\n', 1),
            ('\t\twide_val = __builtin_arm_rsr64("CNTV_TVAL_EL0");\n',
             '#if defined(A5_USE_PHYS_TIMER)\n\t\twide_val = __builtin_arm_rsr64("CNTP_TVAL_EL0");\n#else\n\t\twide_val = __builtin_arm_rsr64("CNTV_TVAL_EL0");\n#endif\n', 1),
            ('\tuint64_t cntv_ctl = __builtin_arm_rsr64("CNTV_CTL_EL0");\n',
             '#if defined(A5_USE_PHYS_TIMER)\n\tuint64_t cntv_ctl = __builtin_arm_rsr64("CNTP_CTL_EL0");\n#else\n\tuint64_t cntv_ctl = __builtin_arm_rsr64("CNTV_CTL_EL0");\n#endif\n', 1),
            ('\t__builtin_arm_wsr64("CNTV_CTL_EL0", cntvctl);\n'
             '\t/* disable the physical timer as a precaution, as its registers reset to architecturally unknown values */\n'
             '\t__builtin_arm_wsr64("CNTP_CTL_EL0", CNTP_CTL_EL0_IMASKED);\n',
             '#if defined(A5_USE_PHYS_TIMER)\n'
             '\t__builtin_arm_wsr64("CNTP_CTL_EL0", cntvctl);\n'
             '\t__builtin_arm_wsr64("CNTV_CTL_EL0", CNTV_CTL_EL0_IMASKED);\n'
             '#else\n'
             '\t__builtin_arm_wsr64("CNTV_CTL_EL0", cntvctl);\n'
             '\t/* disable the physical timer as a precaution, as its registers reset to architecturally unknown values */\n'
             '\t__builtin_arm_wsr64("CNTP_CTL_EL0", CNTP_CTL_EL0_IMASKED);\n'
             '#endif\n', 1),
        ],
    }

    pending = []
    for rel, edits in plans.items():
        pending.append(apply_file(tree, rel, edits))
    for path, text in pending:
        path.write_text(text)
        print(f"updated {path.relative_to(tree)}")
    print("jackpotlte XNU source overrides applied; kernel not built")


if __name__ == "__main__":
    main()
