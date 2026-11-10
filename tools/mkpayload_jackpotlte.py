#!/usr/bin/env python3
"""Create a 4 KiB SWEETXNU handoff payload for the Galaxy A8 2018.

The output is a raw payload intended to be supplied as the Samsung boot
ramdisk/initrd to the local jackpotlte EL1 loader. It is not a kernel Image,
Samsung BOOT image, or flashable image by itself.
"""

from __future__ import annotations

import argparse
import os
import struct
import sys
from pathlib import Path

from mkadt_jackpotlte import reference_tools_path


ROOT = Path(__file__).resolve().parents[1]
PAGE_SIZE = 0x1000
KERNEL_VA_ALIGN = 0x2000000
XNU_RAM_BASE = 0x880000000
XNU_RAM_SIZE = 0x20000000
BOOT_LINE_LENGTH = 608
CMDLINE_OFFSET = 0x48
SEGMENT_TABLE_OFFSET = CMDLINE_OFFSET + BOOT_LINE_LENGTH
LC_SEGMENT_64 = 0x19
LC_UNIXTHREAD = 0x5
LC_DYLD_CHAINED_FIXUPS = 0x80000034
MH_MAGIC_64 = 0xFEEDFACF
CPU_TYPE_ARM64 = 0x0100000C
VM_PROT_EXECUTE = 4


def align(value: int, boundary: int) -> int:
    return (value + boundary - 1) & ~(boundary - 1)


def adt_ram(adt_path: Path, reference_tools: Path) -> tuple[int, int]:
    sys.path.insert(0, str(reference_tools))
    import adt  # type: ignore[import-not-found]

    root, _ = adt.parse(adt_path.read_bytes())
    chosen = next((node for node in root.children
                   if node.prop("name") == b"chosen\0"), None)
    if chosen is None:
        raise SystemExit("ADT has no /chosen node")
    base_blob = chosen.prop("dram-base")
    size_blob = chosen.prop("dram-size")
    if base_blob is None or size_blob is None or len(base_blob) != 8 or len(size_blob) != 8:
        raise SystemExit("ADT /chosen lacks 64-bit dram-base/dram-size")
    return struct.unpack("<Q", base_blob)[0], struct.unpack("<Q", size_blob)[0]


def parse_macho(data: bytes) -> dict[str, object]:
    if len(data) < 32:
        raise SystemExit("kernel Mach-O is truncated")
    magic, cpu_type, cpu_subtype, file_type, ncmds, sizeofcmds, flags, _ = \
        struct.unpack_from("<8I", data, 0)
    if magic != MH_MAGIC_64 or cpu_type != CPU_TYPE_ARM64 or file_type != 2:
        raise SystemExit("expected a 64-bit ARM Mach-O executable")
    if 32 + sizeofcmds > len(data):
        raise SystemExit("Mach-O load-command table exceeds the file")

    segments: list[dict[str, int | str]] = []
    entry = None
    offset = 32
    for _ in range(ncmds):
        if offset + 8 > 32 + sizeofcmds:
            raise SystemExit("truncated Mach-O load command")
        command, command_size = struct.unpack_from("<II", data, offset)
        if command_size < 8 or offset + command_size > 32 + sizeofcmds:
            raise SystemExit("invalid Mach-O load-command size")
        if command == LC_SEGMENT_64:
            if command_size < 72:
                raise SystemExit("truncated LC_SEGMENT_64")
            name = data[offset + 8:offset + 24].split(b"\0", 1)[0].decode("ascii", "replace")
            vmaddr, vmsize, fileoff, filesize = struct.unpack_from("<4Q", data, offset + 24)
            initprot = struct.unpack_from("<I", data, offset + 60)[0]
            if fileoff > len(data) or filesize > len(data) - fileoff:
                raise SystemExit(f"{name}: segment file range exceeds the kernel")
            if vmaddr + vmsize < vmaddr:
                raise SystemExit(f"{name}: segment virtual range overflows")
            segments.append({"name": name, "vmaddr": vmaddr, "vmsize": vmsize,
                             "fileoff": fileoff, "filesize": filesize,
                             "initprot": initprot})
        elif command == LC_UNIXTHREAD:
            if command_size < 16 + 33 * 8:
                raise SystemExit("truncated ARM64 LC_UNIXTHREAD")
            flavor, count = struct.unpack_from("<II", data, offset + 8)
            if flavor != 6 or count < 68:
                raise SystemExit("LC_UNIXTHREAD is not ARM_THREAD_STATE64")
            entry = struct.unpack_from("<Q", data, offset + 16 + 32 * 8)[0]
        elif command == LC_DYLD_CHAINED_FIXUPS:
            raise SystemExit(
                "this first A8 payload packer does not apply chained fixups; "
                "rebuild a kernel without LC_DYLD_CHAINED_FIXUPS"
            )
        offset += command_size
    if offset != 32 + sizeofcmds:
        raise SystemExit("Mach-O load-command sizes do not match sizeofcmds")
    if entry is None or not segments:
        raise SystemExit("Mach-O lacks loadable segments or an entry point")

    text = next((segment for segment in segments if segment["name"] == "__TEXT"), None)
    if text is None or text["fileoff"] != 0 or text["vmsize"] == 0:
        raise SystemExit("Mach-O __TEXT segment is missing or malformed")
    if not any(segment["initprot"] & VM_PROT_EXECUTE and
               segment["vmaddr"] <= entry < segment["vmaddr"] + segment["vmsize"]
               for segment in segments):
        raise SystemExit("Mach-O entry point is not in an executable segment")
    return {"cpu_subtype": cpu_subtype & 0xFF, "flags": flags,
            "segments": segments, "entry": entry, "text": text}


def build(kernel_path: Path, adt_path: Path, reference_tools: Path,
          cmdline: str) -> tuple[bytes, dict[str, object]]:
    data = bytearray(kernel_path.read_bytes())
    macho = parse_macho(data)
    segments = [segment for segment in macho["segments"] if segment["vmsize"]]
    text = macho["text"]
    assert isinstance(text, dict)
    if text["name"] != "__TEXT":
        raise SystemExit("first segment must be __TEXT for this loader")
    virt_base = text["vmaddr"] & ~(KERNEL_VA_ALIGN - 1)
    kernel_end = align(max(segment["vmaddr"] + segment["vmsize"]
                           for segment in segments), PAGE_SIZE)
    if kernel_end <= virt_base:
        raise SystemExit("kernel virtual range is invalid")

    for index, segment in enumerate(segments):
        relative = segment["vmaddr"] - virt_base
        if relative < 0 or relative + segment["vmsize"] > XNU_RAM_SIZE:
            raise SystemExit(f"{segment['name']}: segment exceeds the A8 512 MiB window")
        if segment["vmaddr"] % PAGE_SIZE:
            raise SystemExit(f"{segment['name']}: segment start is not 4 KiB aligned")
        for prior in segments[:index]:
            prior_start = prior["vmaddr"]
            prior_end = prior_start + prior["vmsize"]
            if segment["vmaddr"] < prior_end and prior_start < segment["vmaddr"] + segment["vmsize"]:
                raise SystemExit(f"{segment['name']}: virtual segment overlaps {prior['name']}")

    adt_blob = adt_path.read_bytes()
    phys_base, mem_size = adt_ram(adt_path, reference_tools)
    if phys_base != XNU_RAM_BASE or mem_size != XNU_RAM_SIZE:
        raise SystemExit(
            f"expected provisional A8 RAM window {XNU_RAM_BASE:#x}+{XNU_RAM_SIZE:#x}, "
            f"ADT contains {phys_base:#x}+{mem_size:#x}"
        )
    if (macho["entry"] < virt_base or macho["entry"] >= kernel_end or
            kernel_end - virt_base > mem_size):
        raise SystemExit("kernel entry or extent lies outside the selected RAM window")
    required = (kernel_end - virt_base) + len(adt_blob) + PAGE_SIZE * 2
    if required > mem_size:
        raise SystemExit("kernel, ADT, and boot arguments do not fit in the RAM window")

    output = bytearray(SEGMENT_TABLE_OFFSET + 32 * len(segments))
    table: list[tuple[int, int, int, int]] = []
    for segment in segments:
        file_offset = len(output)
        start = segment["fileoff"]
        end = start + segment["filesize"]
        output.extend(data[start:end])
        output.extend(b"\0" * (-len(output) & 0xF))
        table.append((segment["vmaddr"], segment["vmsize"], file_offset, segment["filesize"]))

    adt_offset = len(output)
    output.extend(adt_blob)
    output.extend(b"\0" * (-len(output) & 0xF))
    struct.pack_into("<8sII", output, 0, b"SWEETXNU", 1, len(table))
    struct.pack_into("<7Q", output, 0x10, virt_base, macho["entry"], adt_offset,
                     len(adt_blob), kernel_end, phys_base, mem_size)
    encoded_cmdline = cmdline.encode("ascii", "strict")[:BOOT_LINE_LENGTH - 1]
    output[CMDLINE_OFFSET:CMDLINE_OFFSET + len(encoded_cmdline)] = encoded_cmdline
    for index, segment in enumerate(table):
        struct.pack_into("<4Q", output, SEGMENT_TABLE_OFFSET + 32 * index, *segment)

    return bytes(output), {
        "virtual_base": virt_base,
        "entry": macho["entry"],
        "kernel_end": kernel_end,
        "physical_base": phys_base,
        "memory_size": mem_size,
        "adt_size": len(adt_blob),
        "payload_size": len(output),
        "segments": [(segment["name"], segment["vmaddr"], segment["vmsize"])
                     for segment in segments],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kernel", type=Path)
    parser.add_argument("adt", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--reference-tools", type=Path,
                        help="directory containing the donor adt.py helper")
    parser.add_argument("--cmdline", default="debug=0x14 cpus=1 keepsyms=1")
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("output already exists; choose a new payload path")
    reference_tools = reference_tools_path(args.reference_tools)
    payload, info = build(args.kernel, args.adt, reference_tools, args.cmdline)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("xb") as stream:
        stream.write(payload)
    for key, value in info.items():
        if key != "segments":
            print(f"{key}={value:#x}" if isinstance(value, int) else f"{key}={value}")
    for name, vmaddr, vmsize in info["segments"]:
        print(f"segment={name} vmaddr={vmaddr:#x} vmsize={vmsize:#x}")
    print("format=raw SWEETXNU v1; initrd content is not a gzip/cpio archive")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
