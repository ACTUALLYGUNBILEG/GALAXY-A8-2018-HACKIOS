#!/usr/bin/env python3
"""Apply small target and toolchain fixes for the A8 XNU bring-up build."""

from pathlib import Path
import argparse


def replace_exact(
    root: Path,
    relpath: str,
    old: str,
    new: str,
    expected: int = 1,
    existing_new: int = 0,
) -> None:
    path = root / relpath
    if not path.is_file():
        return
    raw = path.read_bytes()
    text = raw.decode("utf-8").replace("\r\n", "\n")
    found = text.count(old)
    if found == 0 and text.count(new) == expected + existing_new:
        return
    if found != expected:
        raise SystemExit(f"{relpath}: expected {expected} match(es), found {found} for {old!r}")
    text = text.replace(old, new)
    newline = "\r\n" if b"\r\n" in raw else "\n"
    path.write_bytes(text.replace("\n", newline).encode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("xnu_tree", type=Path)
    tree = parser.parse_args().xnu_tree.resolve()
    if not (tree / "config/MASTER.arm64.a5xelte").is_file():
        raise SystemExit(f"{tree}: missing A5XELTE XNU config")

    replace_exact(
        tree,
        "config/MASTER.arm64.a5xelte",
        "#  VM_BASE =        [ vm_pressure_events memorystatus config_code_decryption encrypted_swap config_deferred_reclaim ]",
        "#  VM_BASE =        [ vm_pressure_events jetsam memorystatus config_code_decryption encrypted_swap config_deferred_reclaim ]",
    )
    replace_exact(
        tree,
        "bsd/kern/syscalls.master",
        "#if CONFIG_EMBEDDED\n435\tAUE_NULL\tALL\t{ int pid_hibernate(int pid); }",
        "#if CONFIG_EMBEDDED || defined(ARM64_BOARD_CONFIG_A5XELTE)\n435\tAUE_NULL\tALL\t{ int pid_hibernate(int pid); }",
    )

    asm = "osfmk/arm64/corecrypto/arm64_isa_compatibility.h"
    for old, new, existing_new in (
        ("sha256su0    q$0, q$1", "sha256su0    v$0.4s, v$1.4s", 1),
        ("sha256su1    q$0, q$1, q$2", "sha256su1    v$0.4s, v$1.4s, v$2.4s", 1),
        ("sha256h    v$0.4s, v$1.4s, v$2.4s", "sha256h    q$0, q$1, v$2.4s", 1),
        ("sha256h2    v$0.4s, v$1.4s, v$2.4s", "sha256h2    q$0, q$1, v$2.4s", 1),
    ):
        replace_exact(tree, asm, old, new, existing_new=existing_new)

    replace_exact(
        tree,
        "makedefs/MakeInc.def",
        "SFLAGS_ARM64\t= $(CFLAGS_ARM64)",
        "SFLAGS_ARM64\t= $(CFLAGS_ARM64) $(if $(filter A5XELTE,$(CURRENT_MACHINE_CONFIG)),-march=armv8-a+crypto)",
    )
    replace_exact(
        tree,
        "makedefs/MakeInc.def",
        "CFLAGS_GEN += $(foreach x,$(UBSAN_DISABLED),-fno-sanitize=$(x))",
        "CFLAGS_GEN += $(foreach x,$(UBSAN_DISABLED),-fno-sanitize=$(x))\n\n"
        "# The Linux bring-up toolchain has no Apple kernel sanitizer/profile runtime.\n"
        "ifeq ($(CURRENT_MACHINE_CONFIG),A5XELTE)\n"
        "CFLAGS_GEN += -fno-sanitize=signed-integer-overflow\n"
        "endif",
    )
    replace_exact(
        tree,
        "makedefs/MakeInc.def",
        "\t\t  $($(addsuffix $(CURRENT_KERNEL_CONFIG),CXXFLAGS_))",
        "\t\t  $($(addsuffix $(CURRENT_KERNEL_CONFIG),CXXFLAGS_))\n"
        "ifeq ($(CURRENT_MACHINE_CONFIG),A5XELTE)\n"
        "CXXFLAGS_GEN += -fno-sanitize=signed-integer-overflow -fno-c++-static-destructors\n"
        "endif",
    )

    pgo_compat = tree / "osfmk/arm64/a5xelte_pgo_compat.c"
    pgo_compat.parent.mkdir(parents=True, exist_ok=True)
    pgo_source = (
        "/* A8 diagnostic builds do not collect compiler profile data. */\n"
        "#if defined(ARM64_BOARD_CONFIG_A5XELTE)\n"
        "#include <stdint.h>\n"
        "uint64_t __llvm_profile_get_size_for_buffer_internal(\n"
        "    const char *DataBegin, const char *DataEnd,\n"
        "    const char *CountersBegin, const char *CountersEnd,\n"
        "    const char *NamesBegin, const char *NamesEnd)\n"
        "{\n"
        "    (void)DataBegin; (void)DataEnd;\n"
        "    (void)CountersBegin; (void)CountersEnd;\n"
        "    (void)NamesBegin; (void)NamesEnd;\n"
        "    return 0;\n"
        "}\n"
        "int __llvm_profile_write_buffer_internal(\n"
        "    char *Buffer, const char *DataBegin, const char *DataEnd,\n"
        "    const char *CountersBegin, const char *CountersEnd,\n"
        "    const char *NamesBegin, const char *NamesEnd)\n"
        "{\n"
        "    (void)Buffer; (void)DataBegin; (void)DataEnd;\n"
        "    (void)CountersBegin; (void)CountersEnd;\n"
        "    (void)NamesBegin; (void)NamesEnd;\n"
        "    return 0;\n"
        "}\n"
        "/* The Apple minimal UBSan runtime is unavailable in the Linux SDK.\n"
        " * Preserve its recoverable behavior for this diagnostic kernel. */\n"
        "void __ubsan_handle_add_overflow_minimal(void) {}\n"
        "void __ubsan_handle_sub_overflow_minimal(void) {}\n"
        "void __ubsan_handle_mul_overflow_minimal(void) {}\n"
        "void __ubsan_handle_negate_overflow_minimal(void) {}\n"
        "void __ubsan_handle_divrem_overflow_minimal(void) {}\n"
        "typedef void (*a5xelte_cxa_dtor_t)(void *);\n"
        "int __cxa_atexit(a5xelte_cxa_dtor_t dtor, void *arg, void *dso)\n"
        "{\n"
        "    (void)dtor; (void)arg; (void)dso;\n"
        "    return 0;\n"
        "}\n"
        "#endif\n"
    )
    if not pgo_compat.exists() or pgo_compat.read_text() != pgo_source:
        pgo_compat.write_text(pgo_source)
    files_arm64 = tree / "osfmk/conf/files.arm64"
    raw = files_arm64.read_bytes()
    text = raw.decode("utf-8").replace("\r\n", "\n")
    pgo_entry = "osfmk/arm64/a5xelte_pgo_compat.c\tstandard"
    lines = [line for line in text.splitlines() if line != pgo_entry]
    try:
        sha_index = lines.index("osfmk/arm64/corecrypto/sha256_compress_arm64.s\tstandard")
    except ValueError as exc:
        raise SystemExit(f"{files_arm64}: SHA-256 source entry not found") from exc
    lines.insert(sha_index + 1, pgo_entry)
    newline = "\r\n" if b"\r\n" in raw else "\n"
    normalized = (newline.join(lines) + newline).encode("utf-8")
    if normalized != raw:
        files_arm64.write_bytes(normalized)

    hfs = tree / "bsd/sweet_hfs"
    config = hfs / "core/kext-config.h"
    if config.is_file():
        replace_exact(
            tree,
            "bsd/sweet_hfs/core/kext-config.h",
            "#define CONFIG_PROTECT 1",
            "#define CONFIG_PROTECT 0",
        )

    compat = hfs / "sweet_hfs_compat.h"
    if compat.is_file():
        raw = compat.read_bytes()
        text = raw.decode("utf-8").replace("\r\n", "\n")
        marker = "#define OSKextGetCurrentLoadTag sweet_hfs_current_load_tag\n"
        addition = (
            marker
            + "\n/* iOS HFS+ uses Unicode names; the legacy converter module is absent. */\n"
            + "void hfs_converterinit(void);\n"
            + "void hfs_converterdone(void);\n"
        )
        if text.count(marker) == 1 and "void hfs_converterinit(void);" not in text:
            text = text.replace(marker, addition)
            newline = "\r\n" if b"\r\n" in raw else "\n"
            compat.write_bytes(text.replace("\n", newline).encode("utf-8"))

    encodings = hfs / "hfs_encodings/hfs_encodings.c"
    if encodings.is_file():
        raw = encodings.read_bytes()
        text = raw.decode("utf-8", errors="surrogateescape").replace("\r\n", "\n")
        marker = "uint64_t hfs_allocated __attribute__((aligned(8)));\n"
        if "#if TARGET_OS_IPHONE\n/* HFS+ filenames are Unicode" not in text:
            if text.count(marker) != 1:
                raise SystemExit(f"{encodings}: expected the HFS allocation counter once")
            text = text.replace(
                marker,
                "#if TARGET_OS_IPHONE\n"
                "/* HFS+ filenames are Unicode; iOS does not build the legacy converter. */\n"
                "uint64_t hfs_allocated __attribute__((aligned(8)));\n"
                "void hfs_converterinit(void) {}\n"
                "void hfs_converterdone(void) {}\n"
                "#else\n"
                + marker,
            )
            text = text.rstrip("\n") + "\n#endif /* TARGET_OS_IPHONE */\n"
            newline = "\r\n" if b"\r\n" in raw else "\n"
            encodings.write_bytes(text.replace("\n", newline).encode("utf-8", errors="surrogateescape"))

    print(f"Prepared A8 XNU bring-up sources in {tree}")


if __name__ == "__main__":
    main()
