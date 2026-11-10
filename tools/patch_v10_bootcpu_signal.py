#!/usr/bin/env python3
"""Create a one-core v11 diagnostic by enabling XNU CPU signals locally."""

from __future__ import annotations

import argparse
import hashlib
import struct
from pathlib import Path


V10_SHA256 = "41d1bf586906ded46b6c280ee9ea90ccf858d9ca43ff908a59f9496da314c55a"
CPU_SIGNAL_HANDLER = "_cpu_signal_handler"
INIT_CPU_SYMBOL = "__ZN8SweetCPU7initCPUEb"
EXPECTED_INIT_CPU = 0xFFFFFFF0079C4A60
CALL_SITE = 0xFFFFFFF0079C4AD0
EXPECTED_CALL_WORD = 0xD63F0100  # blr x8 (SweetCPU::signalCPU virtual call)
LC_SEGMENT_64 = 0x19
LC_SYMTAB = 0x2
MH_MAGIC_64 = 0xFEEDFACF
CPU_TYPE_ARM64 = 0x0100000C
MH_EXECUTE = 2


def parse_macho(data: bytes) -> tuple[dict[str, tuple[int, int, int]], dict[str, int]]:
    if len(data) < 32:
        raise SystemExit("input Mach-O is truncated")
    magic, cpu_type, _, file_type, ncmds, sizeofcmds, _, _ = struct.unpack_from(
        "<8I", data, 0
    )
    if magic != MH_MAGIC_64 or cpu_type != CPU_TYPE_ARM64 or file_type != MH_EXECUTE:
        raise SystemExit("expected the v10 arm64 Mach-O executable")
    if 32 + sizeofcmds > len(data):
        raise SystemExit("Mach-O load commands exceed the file")

    segments: dict[str, tuple[int, int, int]] = {}
    symbols: dict[str, int] = {}
    symtab: tuple[int, int, int, int] | None = None
    offset = 32
    for _ in range(ncmds):
        if offset + 8 > 32 + sizeofcmds:
            raise SystemExit("truncated Mach-O load command")
        cmd, cmdsize = struct.unpack_from("<II", data, offset)
        if cmdsize < 8 or offset + cmdsize > 32 + sizeofcmds:
            raise SystemExit("invalid Mach-O load-command size")
        if cmd == LC_SEGMENT_64:
            if cmdsize < 72:
                raise SystemExit("truncated LC_SEGMENT_64")
            name = data[offset + 8:offset + 24].split(b"\0", 1)[0].decode("ascii")
            vmaddr, _, fileoff, filesize = struct.unpack_from("<4Q", data, offset + 24)
            segments[name] = (vmaddr, fileoff, filesize)
        elif cmd == LC_SYMTAB:
            if cmdsize < 24:
                raise SystemExit("truncated LC_SYMTAB")
            symoff, nsyms, stroff, strsize = struct.unpack_from("<4I", data, offset + 8)
            symtab = (symoff, nsyms, stroff, strsize)
        offset += cmdsize
    if offset != 32 + sizeofcmds:
        raise SystemExit("Mach-O load-command sizes do not match sizeofcmds")
    if symtab is None:
        raise SystemExit("Mach-O has no symbol table")

    symoff, nsyms, stroff, strsize = symtab
    if symoff + nsyms * 16 > len(data) or stroff + strsize > len(data):
        raise SystemExit("Mach-O symbol or string table exceeds the file")
    for index in range(nsyms):
        strx, n_type, _, _, value = struct.unpack_from("<IBBHQ", data, symoff + 16 * index)
        if strx >= strsize or n_type & 0xE == 0:
            continue
        end = data.find(b"\0", stroff + strx, stroff + strsize)
        if end < 0:
            continue
        name = data[stroff + strx:end].decode("utf-8", "replace")
        symbols[name] = value
    return segments, symbols


def vm_to_file(segments: dict[str, tuple[int, int, int]], address: int, size: int) -> int:
    for vmaddr, fileoff, filesize in segments.values():
        if vmaddr <= address and address + size <= vmaddr + filesize:
            return fileoff + address - vmaddr
    raise SystemExit(f"address {address:#x} is not backed by a file segment")


def create(source: Path, destination: Path) -> None:
    if destination.exists():
        raise SystemExit("output already exists; choose a new destination")
    original = source.read_bytes()
    digest = hashlib.sha256(original).hexdigest()
    if digest != V10_SHA256:
        raise SystemExit(f"unexpected v10 Mach-O SHA-256: {digest}")

    segments, symbols = parse_macho(original)
    if symbols.get(INIT_CPU_SYMBOL) != EXPECTED_INIT_CPU:
        raise SystemExit("v10 SweetCPU::initCPU symbol does not match the known image")
    target = symbols.get(CPU_SIGNAL_HANDLER)
    if target is None:
        raise SystemExit("v10 Mach-O has no _cpu_signal_handler symbol")

    call_offset = vm_to_file(segments, CALL_SITE, 4)
    expected = struct.unpack_from("<I", original, call_offset)[0]
    if expected != EXPECTED_CALL_WORD:
        raise SystemExit(f"unexpected initCPU call-site instruction: {expected:#010x}")
    delta = target - CALL_SITE
    if delta & 3 or not -(1 << 27) <= delta < (1 << 27):
        raise SystemExit("cpu_signal_handler is outside the ARM64 BL range")

    branch = 0x94000000 | ((delta >> 2) & 0x03FFFFFF)
    patched = bytearray(original)
    struct.pack_into("<I", patched, call_offset, branch)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as stream:
        stream.write(patched)
    check = struct.unpack_from("<I", destination.read_bytes(), call_offset)[0]
    if check != branch:
        destination.unlink(missing_ok=True)
        raise SystemExit("patched call instruction did not verify")
    print(f"source_sha256={digest}")
    print(f"initCPU_call_site={CALL_SITE:#x} target={target:#x} instruction={branch:#010x}")
    print(f"output={destination}")
    print(f"output_sha256={hashlib.sha256(patched).hexdigest()}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("v10_kernel", type=Path)
    parser.add_argument("v11_kernel", type=Path)
    args = parser.parse_args()
    create(args.v10_kernel, args.v11_kernel)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
