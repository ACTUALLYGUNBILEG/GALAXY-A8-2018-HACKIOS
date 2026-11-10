#!/usr/bin/env python3
"""Apply small Linux-host compatibility edits to a prepared XNU source tree."""

from pathlib import Path
import argparse


def replace_exact(root: Path, relpath: str, old: str, new: str, expected: int) -> None:
    path = root / relpath
    raw = path.read_bytes()
    text = raw.decode("utf-8").replace("\r\n", "\n")
    found = text.count(old)
    if found == 0 and text.count(new) == expected:
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
    if not (tree / "makedefs/MakeInc.cmd").is_file():
        raise SystemExit(f"{tree}: not an XNU source tree")

    replace_exact(
        tree,
        "Makefile",
        "export SYSCTL_HW_PHYSICALCPU := $(shell /usr/sbin/sysctl -n hw.physicalcpu)",
        "export SYSCTL_HW_PHYSICALCPU := $(shell nproc)",
        3,
    )
    replace_exact(
        tree,
        "Makefile",
        "export SYSCTL_HW_LOGICALCPU  := $(shell /usr/sbin/sysctl -n hw.logicalcpu)",
        "export SYSCTL_HW_LOGICALCPU  := $(shell nproc)",
        3,
    )
    replace_exact(
        tree,
        "SETUP/config/doconf",
        "#!/bin/csh -f\n",
        "#!/usr/bin/env -S csh -f\n",
        1,
    )
    replace_exact(
        tree,
        "makedefs/MakeInc.cmd",
        "\tXCRUN = /usr/bin/xcrun -verbose\n",
        "\tXCRUN = xcrun -verbose\n",
        1,
    )
    replace_exact(
        tree,
        "makedefs/MakeInc.cmd",
        "\tXCRUN = /usr/bin/xcrun\n",
        "\tXCRUN = xcrun\n",
        1,
    )
    standard_tools = """RM = /bin/rm -f
RMDIR = /bin/rmdir
CP = /bin/cp
MV = /bin/mv
LN = /bin/ln -fs
CAT = /bin/cat
MKDIR = /bin/mkdir -p
CHMOD = /bin/chmod
FIND = /usr/bin/find
XARGS = /usr/bin/xargs
PAX = /bin/pax
BASENAME = /usr/bin/basename
DIRNAME = /usr/bin/dirname
TR = /usr/bin/tr
TOUCH = /usr/bin/touch
SLEEP = /bin/sleep
AWK = /usr/bin/awk
SED = /usr/bin/sed
PLUTIL = /usr/bin/plutil
PATCH = /usr/bin/patch
GREP = /usr/bin/grep"""
    portable_tools = """RM = rm -f
RMDIR = rmdir
CP = cp
MV = mv
LN = ln -fs
CAT = cat
MKDIR = mkdir -p
CHMOD = chmod
FIND = find
XARGS = xargs
PAX = pax
BASENAME = basename
DIRNAME = dirname
TR = tr
TOUCH = touch
SLEEP = sleep
AWK = awk
SED = sed
PLUTIL = plutil
PATCH = patch
GREP = grep"""
    replace_exact(tree, "makedefs/MakeInc.cmd", standard_tools, portable_tools, 1)
    replace_exact(
        tree,
        "makedefs/MakeInc.cmd",
        "\texport HOST_CODESIGN\t:= /usr/bin/codesign\n",
        "\texport HOST_CODESIGN\t:= codesign\n",
        1,
    )
    replace_exact(
        tree,
        "makedefs/MakeInc.top",
        "MEMORY_SIZE := $(shell /usr/sbin/sysctl -n hw.memsize)",
        "MEMORY_SIZE := $(shell if [ -r /proc/meminfo ]; then awk '/MemTotal/{printf \"%d\", $$2*1024}' /proc/meminfo; else sysctl -n hw.memsize; fi)",
        1,
    )
    compatible_ptr = """#define KALLOC_TYPE_IS_COMPATIBLE_PTR(ptr, type)                   \\
\t_Pragma(\"clang diagnostic push\")                               \\
\t_Pragma(\"clang diagnostic ignored \\\"-Wvoid-ptr-dereference\\\"") \\
\t(__builtin_xnu_types_compatible(__typeof__(*(ptr)), type) ||   \\
\t    __builtin_xnu_types_compatible(__typeof__(*(ptr)), void))  \\
\t_Pragma(\"clang diagnostic pop\")"""
    compatible_ptr_portable = """#if XNU_NO_TYPE_BUILTINS
/* Apple-only type introspection is unavailable in upstream Clang. This is a
 * compile-time assertion only; runtime kalloc type summaries stay conservative. */
#define KALLOC_TYPE_IS_COMPATIBLE_PTR(ptr, type) 1
#else
""" + compatible_ptr + "\n#endif"
    replace_exact(
        tree,
        "osfmk/kern/kalloc.h",
        compatible_ptr,
        compatible_ptr_portable,
        1,
    )
    replace_exact(
        tree,
        "libkern/libkern/c++/OSData.h",
        "\t\tstatic_assert(KALLOC_TYPE_IS_DATA_ONLY(T) || (acquisition == kValueNoCopy),\n"
        "\t\t    \"only plain data types can be contained (consider using OSValueObject)\");",
        "#if !XNU_NO_TYPE_BUILTINS\n"
        "\t\tstatic_assert(KALLOC_TYPE_IS_DATA_ONLY(T) || (acquisition == kValueNoCopy),\n"
        "\t\t    \"only plain data types can be contained (consider using OSValueObject)\");\n"
        "#endif",
        1,
    )
    print(f"Applied Linux host compatibility edits to {tree}")


if __name__ == "__main__":
    main()
