#!/usr/bin/env python3
"""Inspect or package a candidate SM-A530N Samsung BOOT image.

This program is host-side only. It reads a user-supplied stock BOOT backup and
creates a separate candidate file; it never opens a block device or flashes.
"""

from __future__ import annotations

import argparse
import hashlib
import struct
import sys
from pathlib import Path


ANDROID_MAGIC = b"ANDROID!"
ARM64_MAGIC = b"ARMd"
DTBH_MAGIC = b"DTBH"
TARGET_BOARD = "SRPQH21B008KU"
TARGET_CHIP_ID = 7885
TARGET_PAGE_SIZE = 2048
TARGET_BOOT_SIZE = 32 * 1024 * 1024
SEANDROID_MARKER = b"SEANDROIDENFORCE"
SAMSUNG_FOOTER_HEADER = SEANDROID_MARKER + b"\x09" + bytes(15)
SAMSUNG_FOOTER_SIGNATURE_BYTES = 256


def align(value: int, page_size: int) -> int:
    return (value + page_size - 1) // page_size * page_size


def parse_boot(data: bytes) -> dict[str, object]:
    if len(data) < 2048 or data[:8] != ANDROID_MAGIC:
        raise SystemExit("not a legacy Android BOOT image")

    (kernel_size, kernel_addr, ramdisk_size, ramdisk_addr, second_size,
     second_addr, tags_addr, page_size, dt_size, unused) = struct.unpack_from(
        "<10I", data, 8
    )
    if page_size not in (2048, 4096):
        raise SystemExit(f"unsupported Android BOOT page size: {page_size}")

    kernel_off = page_size
    ramdisk_off = kernel_off + align(kernel_size, page_size)
    second_off = ramdisk_off + align(ramdisk_size, page_size)
    dt_off = second_off + align(second_size, page_size)
    dt_end = dt_off + dt_size
    if dt_end > len(data):
        raise SystemExit("BOOT image is truncated")

    return {
        "page_size": page_size,
        "kernel_addr": kernel_addr,
        "ramdisk_addr": ramdisk_addr,
        "second_addr": second_addr,
        "tags_addr": tags_addr,
        "unused": unused,
        "name": data[48:64].split(b"\0", 1)[0].decode(errors="replace"),
        "cmdline": data[64:576].split(b"\0", 1)[0].decode(errors="replace"),
        "kernel": data[kernel_off:kernel_off + kernel_size],
        "ramdisk": data[ramdisk_off:ramdisk_off + ramdisk_size],
        "second": data[second_off:second_off + second_size],
        "dt": data[dt_off:dt_end],
        "tail": data[dt_off + align(dt_size, page_size):],
    }


def arm64_header(kernel: bytes) -> tuple[int, int, int] | None:
    if len(kernel) < 64 or kernel[56:60] != ARM64_MAGIC:
        return None
    return struct.unpack_from("<3Q", kernel, 8)


def parse_dtbh(data: bytes) -> tuple[int, list[tuple[int, ...]]]:
    if len(data) < 12 or data[:4] != DTBH_MAGIC:
        raise SystemExit("stock DT segment has no DTBH header")
    version, count = struct.unpack_from("<2I", data, 4)
    end = 12 + count * 32
    if not 1 <= count <= 64 or end > len(data):
        raise SystemExit("stock DTBH table is malformed")
    entries = [struct.unpack_from("<8I", data, 12 + index * 32) for index in range(count)]
    return version, entries


def maybe_dtbh(data: bytes) -> tuple[int | None, list[tuple[int, ...]]]:
    """Return DTBH metadata for inspection without requiring Samsung DTBH."""
    if data[:4] != DTBH_MAGIC:
        return None, []
    return parse_dtbh(data)


def validate_boot_tail(tail: bytes, drop_oem_signature: bool) -> bool:
    """Validate a footer and report whether the stock OEM signature is dropped."""
    if not tail or not any(tail):
        return False
    if tail.startswith(SEANDROID_MARKER) and not any(tail[len(SEANDROID_MARKER):]):
        return False
    expected_signed_tail = len(SAMSUNG_FOOTER_HEADER) + SAMSUNG_FOOTER_SIGNATURE_BYTES
    if (
        len(tail) == expected_signed_tail
        and tail.startswith(SAMSUNG_FOOTER_HEADER)
    ):
        if not drop_oem_signature:
            raise SystemExit(
                "stock BOOT has a Samsung OEM signature; pass --drop-oem-signature "
                "to create an unsigned custom candidate"
            )
        return True
    raise SystemExit(
        "stock BOOT has unrecognized data after the DT section; refusing to discard it"
    )


def describe(stock_path: Path, boot: dict[str, object]) -> None:
    data = stock_path.read_bytes()
    print(f"stock_bytes={len(data)} sha256={hashlib.sha256(data).hexdigest()}")
    print(f"page_size={boot['page_size']} board_name={boot['name']!r}")
    print(f"kernel_bytes={len(boot['kernel'])} load_addr={boot['kernel_addr']:#x}")
    print(f"ramdisk_bytes={len(boot['ramdisk'])} load_addr={boot['ramdisk_addr']:#x}")
    print(f"second_bytes={len(boot['second'])} dt_bytes={len(boot['dt'])}")
    print(f"cmdline={boot['cmdline']!r}")
    header = arm64_header(boot["kernel"])
    if header:
        print("arm64_Image: text_offset={:#x} image_size={:#x} flags={:#x}".format(*header))
    else:
        print("stock kernel has no raw arm64 Image header")
    version, entries = maybe_dtbh(boot["dt"])
    if version is None:
        print(f"DT segment is not DTBH (starts {boot['dt'][:8]!r})")
    else:
        print(f"DTBH_version={version} entries={len(entries)}")
        for entry in entries:
            print(
                "  chip={} platform={:#x} subtype={:#x} hw_rev={}..{} off={:#x} size={:#x}".format(
                    *entry[:7]
                )
            )
    tail = boot["tail"]
    if not tail or not any(tail):
        footer = "none"
    elif len(tail) == len(SAMSUNG_FOOTER_HEADER) + SAMSUNG_FOOTER_SIGNATURE_BYTES and tail.startswith(SAMSUNG_FOOTER_HEADER):
        footer = f"Samsung OEM footer with {SAMSUNG_FOOTER_SIGNATURE_BYTES}-byte signature"
    elif tail.startswith(SEANDROID_MARKER) and not any(tail[len(SEANDROID_MARKER):]):
        footer = "SEANDROIDENFORCE marker plus zero padding"
    else:
        footer = "unrecognized"
    print(f"tail_bytes={len(tail)} footer={footer}")


def make_candidate(args: argparse.Namespace) -> None:
    if args.output.exists():
        raise SystemExit("output already exists; choose a new candidate path")

    stock_data = args.stock.read_bytes()
    stock = parse_boot(stock_data)
    dropped_signature = validate_boot_tail(stock["tail"], args.drop_oem_signature)
    if stock["page_size"] != TARGET_PAGE_SIZE:
        raise SystemExit(
            f"unexpected BOOT page size {stock['page_size']}; expected {TARGET_PAGE_SIZE}"
        )
    if stock["name"] != args.board_name:
        raise SystemExit(
            f"unexpected board name {stock['name']!r}; expected {args.board_name!r}"
        )

    _, entries = parse_dtbh(stock["dt"])
    if not any(entry[0] == args.chip_id for entry in entries):
        raise SystemExit(f"stock DTBH has no target chip entry {args.chip_id}")

    image = bytearray(args.image.read_bytes())
    image_header = arm64_header(image)
    if image_header is None:
        raise SystemExit("probe image has no arm64 Image header")
    stock_kernel_header = arm64_header(stock["kernel"])
    if stock_kernel_header is None:
        raise SystemExit("stock kernel has no raw arm64 Image header")

    text_offset, _, flags = stock_kernel_header
    if text_offset == 0 or text_offset >= 0x2000000:
        raise SystemExit(f"stock arm64 text_offset is implausible: {text_offset:#x}")
    image_size = align(len(image) + 0x10000, 4096)
    struct.pack_into("<3Q", image, 8, text_offset, image_size, flags)

    ramdisk = args.ramdisk.read_bytes() if args.ramdisk else stock["ramdisk"]
    parts = (bytes(image), ramdisk, stock["second"], stock["dt"])
    header = bytearray(stock_data[:TARGET_PAGE_SIZE])
    struct.pack_into("<I", header, 8, len(image))
    struct.pack_into("<I", header, 16, len(ramdisk))

    digest = hashlib.sha1()
    for part in parts:
        digest.update(part)
        digest.update(struct.pack("<I", len(part)))
    header[576:596] = digest.digest()
    header[596:608] = bytes(12)

    candidate = bytearray(header)
    for part in parts:
        if part:
            candidate.extend(part)
            candidate.extend(bytes(align(len(part), TARGET_PAGE_SIZE) - len(part)))
    candidate.extend(SEANDROID_MARKER)

    if len(candidate) > args.partition_size:
        raise SystemExit(
            f"candidate is {len(candidate)} bytes, larger than BOOT partition {args.partition_size}"
        )

    args.output.write_bytes(candidate)
    print("candidate only; no device write")
    if dropped_signature:
        print("dropped the stock Samsung OEM signature; candidate is unsigned")
        print("booting it requires an unlocked boot chain that accepts custom images")
    print(f"stock_sha256={hashlib.sha256(stock_data).hexdigest()}")
    print(f"candidate_sha256={hashlib.sha256(candidate).hexdigest()}")
    print(f"candidate_bytes={len(candidate)} partition_limit={args.partition_size}")
    if args.ramdisk:
        print(f"replacement_ramdisk_bytes={len(ramdisk)} source={args.ramdisk}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    info = subparsers.add_parser("info", help="inspect a stock BOOT image")
    info.add_argument("stock", type=Path)

    pack = subparsers.add_parser("pack", help="create a separate candidate BOOT image")
    pack.add_argument("stock", type=Path)
    pack.add_argument("image", type=Path)
    pack.add_argument("output", type=Path)
    pack.add_argument(
        "--ramdisk",
        type=Path,
        help="replace the stock ramdisk with these raw bytes (for a custom handoff payload)",
    )
    pack.add_argument("--board-name", default=TARGET_BOARD)
    pack.add_argument("--chip-id", type=int, default=TARGET_CHIP_ID)
    pack.add_argument("--partition-size", type=int, default=TARGET_BOOT_SIZE)
    pack.add_argument(
        "--drop-oem-signature",
        action="store_true",
        help="drop the recognized 256-byte Samsung footer signature from the candidate",
    )

    args = parser.parse_args()
    if args.command == "info":
        boot = parse_boot(args.stock.read_bytes())
        describe(args.stock, boot)
    else:
        make_candidate(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
