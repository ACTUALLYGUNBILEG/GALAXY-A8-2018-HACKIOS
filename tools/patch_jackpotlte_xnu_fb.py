#!/usr/bin/env python3
"""Patch the linked first-A8 Mach-O to use its configured early framebuffer.

The source fix lives in osfmk/arm64/sweet_early.c. This small Mach-O patch is
for the already-linked local kernel, whose first C console call still contains
the A5XELTE donor's 0x67000000 literal and 1920-pixel row limit. It updates
those constants to the A530N framebuffer address and configured row count.
"""

from __future__ import annotations

import argparse
import hashlib
import struct
from pathlib import Path


MH_MAGIC_64 = 0xFEEDFACF
CPU_TYPE_ARM64 = 0x0100000C
MH_EXECUTE = 2
LC_SEGMENT_64 = 0x19
LC_SYMTAB = 0x2
VM_PROT_EXECUTE = 4

# MOVZ W9/W12, #0x6700, LSL #16; replacement is MOVZ W9/W12,
# #0xEC00, LSL #16. MOVZ W15/W13, #60 is the donor's 1920/32 row count;
# replace it with 69 (floor(2220/32)). Destination registers stay unchanged.
PATCHES = {
    "_sweet_early_putc": ((0x52ACE009, 0x52BD8009), (0x5280078F, 0x528008AF)),
    "_sweet_early_mark": ((0x52ACE00C, 0x52BD800C), (0x5280078D, 0x528008AD)),
}
FUNCTION_SCAN_BYTES = {
    # Exact linked function spans, ending before the next symbol. Keeping the
    # scans tight avoids matching another routine's copy of the framebuffer
    # constants in the same text segment.
    "_sweet_early_putc": 0x480,
    "_sweet_early_mark": 0x380,
}


def macho_symbols_and_exec_segments(data: bytes) -> tuple[dict[str, int], list[dict[str, int]]]:
    if len(data) < 32:
        raise SystemExit("kernel Mach-O is truncated")
    magic, cpu_type, _, file_type, ncmds, sizeofcmds, _, _ = struct.unpack_from(
        "<8I", data, 0
    )
    if magic != MH_MAGIC_64 or cpu_type != CPU_TYPE_ARM64 or file_type != MH_EXECUTE:
        raise SystemExit("expected a 64-bit ARM Mach-O executable")
    commands_end = 32 + sizeofcmds
    if commands_end > len(data):
        raise SystemExit("Mach-O load-command table exceeds the file")

    segments: list[dict[str, int]] = []
    symtab: tuple[int, int, int, int] | None = None
    offset = 32
    for _ in range(ncmds):
        if offset + 8 > commands_end:
            raise SystemExit("truncated Mach-O load command")
        command, command_size = struct.unpack_from("<II", data, offset)
        if command_size < 8 or offset + command_size > commands_end:
            raise SystemExit("invalid Mach-O load-command size")
        if command == LC_SEGMENT_64:
            if command_size < 72:
                raise SystemExit("truncated LC_SEGMENT_64")
            vmaddr, vmsize, fileoff, filesize = struct.unpack_from("<4Q", data, offset + 24)
            initprot = struct.unpack_from("<I", data, offset + 60)[0]
            if initprot & VM_PROT_EXECUTE:
                if fileoff > len(data) or filesize > len(data) - fileoff:
                    raise SystemExit("executable segment exceeds the Mach-O file")
                segments.append({
                    "vmaddr": vmaddr,
                    "vmsize": vmsize,
                    "fileoff": fileoff,
                    "filesize": filesize,
                })
        elif command == LC_SYMTAB:
            if command_size < 24:
                raise SystemExit("truncated LC_SYMTAB")
            symoff, nsyms, stroff, strsize = struct.unpack_from("<4I", data, offset + 8)
            if (symoff > len(data) or nsyms * 16 > len(data) - symoff or
                    stroff > len(data) or strsize > len(data) - stroff):
                raise SystemExit("Mach-O symbol table exceeds the file")
            symtab = (symoff, nsyms, stroff, strsize)
        offset += command_size
    if offset != commands_end:
        raise SystemExit("Mach-O load-command sizes do not match sizeofcmds")
    if symtab is None or not segments:
        raise SystemExit("Mach-O lacks a symbol table or executable segment")

    symbols: dict[str, int] = {}
    symoff, nsyms, stroff, strsize = symtab
    for index in range(nsyms):
        string_index, symbol_type, _, _, value = struct.unpack_from(
            "<IBBHQ", data, symoff + index * 16
        )
        if symbol_type & 0xE0 or not string_index or string_index >= strsize:
            continue
        name_start = stroff + string_index
        name_end = data.find(b"\0", name_start, stroff + strsize)
        if name_end < 0:
            continue
        name = data[name_start:name_end].decode("ascii", "replace")
        if name in PATCHES:
            if name in symbols and symbols[name] != value:
                raise SystemExit(f"Mach-O has duplicate symbol {name}")
            symbols[name] = value

    missing = set(PATCHES) - symbols.keys()
    if missing:
        raise SystemExit("Mach-O lacks required symbols: " + ", ".join(sorted(missing)))
    return symbols, segments


def patch_kernel(source: Path, destination: Path) -> None:
    if destination.exists():
        raise SystemExit("output already exists; choose a new kernel path")
    data = bytearray(source.read_bytes())
    symbols, segments = macho_symbols_and_exec_segments(data)
    patched: list[tuple[str, int]] = []

    for name, replacements in PATCHES.items():
        address = symbols[name]
        scan_bytes = FUNCTION_SCAN_BYTES[name]
        segment = next((item for item in segments
                        if item["vmaddr"] <= address and
                        address + scan_bytes <= item["vmaddr"] + item["filesize"]), None)
        if segment is None:
            raise SystemExit(f"{name}: function is outside a file-backed executable segment")
        function_offset = segment["fileoff"] + address - segment["vmaddr"]
        window = data[function_offset:function_offset + scan_bytes]
        for old_word, new_word in replacements:
            old_bytes = struct.pack("<I", old_word)
            offsets = [index for index in range(0, len(window) - 3, 4)
                       if window[index:index + 4] == old_bytes]
            if len(offsets) != 1:
                raise SystemExit(
                    f"{name}: expected one donor board-constant instruction in its scan window, "
                    f"found {len(offsets)}"
                )
            patch_offset = function_offset + offsets[0]
            struct.pack_into("<I", data, patch_offset, new_word)
            patched.append((name, patch_offset))

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    for name, file_offset in patched:
        print(f"patched={name} file_offset={file_offset:#x}")
    print(f"kernel_bytes={len(data)} sha256={digest}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="already-linked arm64 Mach-O")
    parser.add_argument("output", type=Path, help="new patched Mach-O output")
    args = parser.parse_args()
    patch_kernel(args.source, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
