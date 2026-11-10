#!/usr/bin/env python3
"""Generate the first single-core Apple Device Tree for SM-A530N.

This is an XNU bring-up ADT, not a complete iOS device tree. It reuses the
minimal ADT schema helpers from the locally cloned ios-galaxy-s8 reference;
that checkout is deliberately kept under ignored work/references/.

The only RAM exposed to the first kernel is a provisional 512 MiB window at
0x880000000. Do not expand it until XNU's physical-address handling and an
early memory test have been confirmed on this device.
"""
import argparse
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
XNU_RAM_BASE = 0x880000000
XNU_RAM_SIZE = 0x20000000
FB_BASE = 0xEC000000
FB_SIZE = 0x01400000
FB_WIDTH = 1080
FB_HEIGHT = 2220
TIMEBASE_HZ = 26_000_000


def reference_tools_path(explicit):
    if explicit:
        path = explicit.resolve()
        if (path / "mkadt.py").is_file() and (path / "adt.py").is_file():
            return path
        raise SystemExit(f"{path}: expected mkadt.py and adt.py")

    candidates = sorted((ROOT / "work" / "references" / "s8").glob(
        "ios-galaxy-s8-*/tools"))
    candidates = [p for p in candidates
                  if (p / "mkadt.py").is_file() and (p / "adt.py").is_file()]
    if not candidates:
        raise SystemExit(
            "missing local S8 reference helpers; clone ios-galaxy-s8 under "
            "work/references/s8/ or pass --reference-tools PATH")
    return candidates[-1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--reference-tools", type=Path,
                        help="path to the referenced S8 project's tools directory")
    parser.add_argument("--dump", action="store_true",
                        help="print the generated ADT tree after writing it")
    args = parser.parse_args()

    sys.path.insert(0, str(reference_tools_path(args.reference_tools)))
    import adt
    import mkadt

    def set_prop(node, name, value):
        for index, (key, flags, _) in enumerate(node.props):
            if key == name:
                node.props[index] = (key, flags, value)
                return
        node.props.append((name, 0, value))

    def child(node, name):
        expected = mkadt.cstr(name)
        for candidate in node.children:
            if candidate.prop("name") == expected:
                return candidate
        raise ValueError(f"missing expected ADT node {name}")

    root = mkadt.build(seed=os.urandom(64), qemu=True)
    set_prop(root, "compatible", b"".join(mkadt.cstr(value) for value in (
        "D22AP", "iPhone10,3", "samsung,jackpotlte", "samsung,a5xelte",
        "samsung,exynos7885", "AppleARM")))

    chosen = child(root, "chosen")
    set_prop(chosen, "dram-base", mkadt.u64(XNU_RAM_BASE))
    set_prop(chosen, "dram-size", mkadt.u64(XNU_RAM_SIZE))
    set_prop(chosen, "firmware-version", mkadt.cstr("jackpotlte-entry"))
    set_prop(chosen, "system-firmware-version", mkadt.cstr("jackpotlte-entry"))

    cpus = child(root, "cpus")
    cpu0 = child(cpus, "cpu0")
    cpu0.props = [(key, flags, value) for key, flags, value in cpu0.props
                  if key in ("name", "AAPL,phandle")]
    for key, value in (
        ("device_type", mkadt.cstr("cpu")),
        ("compatible", mkadt.cstr("arm,cortex-a53") + mkadt.cstr("ARM,v8")),
        ("reg", mkadt.u32(0x100)),
        ("cpu-id", mkadt.u32(0)),
        ("cluster-id", mkadt.u32(0)),
        ("cluster-type", mkadt.u32(0)),
        ("die-cluster-id", mkadt.u32(0)),
        ("cluster-core-id", mkadt.u32(0)),
        ("l2-cache-id", mkadt.u32(0)),
        ("l3-cache-id", mkadt.u32(0)),
        ("state", mkadt.cstr("running")),
        ("timebase-frequency", mkadt.u32(TIMEBASE_HZ)),
    ):
        set_prop(cpu0, key, value)
    cpus.children = [cpu0]

    arm_io = child(root, "arm-io")
    set_prop(arm_io, "device_type", mkadt.cstr("jackpotlte-io"))
    set_prop(arm_io, "compatible", mkadt.cstr("samsung,exynos7885-io") +
             mkadt.cstr("arm-io"))
    set_prop(arm_io, "ranges", mkadt.u64(0, 0x10000000, 0xF0000000))
    # Keep the schema's 0x10000000 physical base. GIC child addresses are
    # bus-relative, so these offsets resolve to physical 0x12301000/0x12302000.
    arm_io.children = [node for node in arm_io.children
                       if node.prop("name") == mkadt.cstr("wdt")]
    arm_io.children.append(mkadt.node("gic", [
        ("compatible", mkadt.cstr("arm,cortex-a15-gic")),
        ("interrupt-controller", mkadt.cstr("master")),
        # Initial candidate: non-secure physical timer PPI 14 = INTID 30.
        ("virtual-timer-intid", mkadt.u32(30)),
        ("reg", mkadt.u64(0x02301000, 0x1000, 0x02302000, 0x1000)),
    ]))
    arm_io.children.append(mkadt.node("disp0", [
        ("device_type", mkadt.cstr("display-subsystem")),
        ("compatible", mkadt.cstr("samsung,jackpotlte-display") +
         mkadt.cstr("samsung,a5xelte-display")),
        ("canvas-width", mkadt.u32(FB_WIDTH)),
        ("canvas-height", mkadt.u32(FB_HEIGHT)),
    ]))

    root.children = [node for node in root.children
                     if node.prop("name") not in
                     (mkadt.cstr("sweet-fbcon"), mkadt.cstr("sweet-ufs"))]
    root.children.append(mkadt.node("a5xelte-fbcon", [
        ("reg", mkadt.u64(FB_BASE, FB_SIZE)),
        ("width", mkadt.u32(FB_WIDTH)),
        ("height", mkadt.u32(FB_HEIGHT)),
        ("stride", mkadt.u32(FB_WIDTH * 4)),
    ]))

    blob = adt.serialize(root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(blob)
    if args.dump:
        adt.dump(adt.parse(blob)[0])
    print(f"{args.output}: {len(blob)} bytes")


if __name__ == "__main__":
    main()
