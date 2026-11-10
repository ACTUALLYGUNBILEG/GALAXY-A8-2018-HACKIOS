#!/usr/bin/env python3
"""Build the freestanding AArch64 S-Boot handoff probe for jackpotlte."""

from __future__ import annotations

import argparse
import os
import shutil
import struct
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "shim" / "jackpotlte"
DEFAULT_OUT = SOURCE_DIR / "out"

CFLAGS = [
    "-O2",
    "-ffreestanding",
    "-fno-builtin",
    "-fno-stack-protector",
    "-fno-pic",
    "-fno-pie",
    "-fno-asynchronous-unwind-tables",
    "-fno-unwind-tables",
    "-fno-jump-tables",
    "-mgeneral-regs-only",
    "-mstrict-align",
    "-mcpu=cortex-a53",
    "-Wall",
    "-Wextra",
    "-Werror",
    "-I",
    str(SOURCE_DIR),
]


def run(command: list[str], env: dict[str, str] | None = None) -> None:
    print("+", subprocess.list2cmdline(command))
    subprocess.run(command, check=True, env=env)


def tool_path(prefix: str, name: str) -> str:
    candidate = f"{prefix}{name}"
    resolved = shutil.which(candidate)
    if resolved is None:
        raise SystemExit(f"tool not found: {candidate} (set --cross to another prefix)")
    return resolved


def validate_static_elf(path: Path) -> None:
    data = path.read_bytes()
    if data[:4] != b"\x7fELF" or data[4] != 2 or data[5] != 1:
        raise SystemExit("linker output is not a 64-bit little-endian ELF")
    if len(data) < 64:
        raise SystemExit("truncated ELF header")

    shoff = struct.unpack_from("<Q", data, 40)[0]
    shentsize, shnum = struct.unpack_from("<HH", data, 58)
    if shentsize < 64 or shoff + shentsize * shnum > len(data):
        raise SystemExit("invalid ELF section table")

    for index in range(shnum):
        offset = shoff + index * shentsize
        section_type = struct.unpack_from("<I", data, offset + 4)[0]
        section_size = struct.unpack_from("<Q", data, offset + 32)[0]
        if section_type in (4, 9) and section_size:
            raise SystemExit("linked image still contains relocation sections")


def patch_image_header(path: Path) -> None:
    image = bytearray(path.read_bytes())
    if len(image) < 64 or image[56:60] != b"ARMd":
        raise SystemExit("objcopy output has no arm64 Image magic")
    struct.pack_into("<QQQ", image, 8, 0x80000, len(image), 0)
    path.write_bytes(image)
    print(f"{path}: {len(image)} bytes; arm64 Image header OK")


def build_with_zig(zig: str, out_dir: Path) -> Path:
    zig_env = os.environ.copy()
    zig_env["ZIG_LOCAL_CACHE_DIR"] = str(out_dir / "zig-cache" / "local")
    zig_env["ZIG_GLOBAL_CACHE_DIR"] = str(out_dir / "zig-cache" / "global")
    zig_flags = [flag.replace("cortex-a53", "cortex_a53") for flag in CFLAGS]
    objects: list[Path] = []
    for source_name in ("probe.S", "probe.c", "fdtmem.c", "fbtext.c"):
        source = SOURCE_DIR / source_name
        obj = out_dir / f"{source_name}.o"
        run(
            [
                zig,
                "cc",
                "-target",
                "aarch64-freestanding-none",
                "-c",
                *zig_flags,
                str(source),
                "-o",
                str(obj),
            ],
            env=zig_env,
        )
        objects.append(obj)

    elf = out_dir / "probe.elf"
    run(
        [
            zig,
            "cc",
            "-target",
            "aarch64-freestanding-none",
            "-nostdlib",
            "-no-pie",
            "-Wl,-T," + str(SOURCE_DIR / "image.ld"),
            "-Wl,--build-id=none",
            *[str(obj) for obj in objects],
            "-o",
            str(elf),
        ],
        env=zig_env,
    )
    validate_static_elf(elf)

    image = out_dir / "probe.Image"
    run([zig, "objcopy", "-O", "binary", str(elf), str(image)], env=zig_env)
    patch_image_header(image)
    return image


def build_with_gcc(cross: str, out_dir: Path) -> Path:
    gcc = tool_path(cross, "gcc")
    ld = tool_path(cross, "ld")
    objcopy = tool_path(cross, "objcopy")
    objects: list[Path] = []

    for source_name in ("probe.S", "probe.c", "fdtmem.c", "fbtext.c"):
        source = SOURCE_DIR / source_name
        obj = out_dir / f"{source_name}.o"
        run([gcc, "-c", *CFLAGS, str(source), "-o", str(obj)])
        objects.append(obj)

    elf = out_dir / "probe.elf"
    run(
        [
            ld,
            "-static",
            "-T",
            str(SOURCE_DIR / "image.ld"),
            "--build-id=none",
            *[str(obj) for obj in objects],
            "-o",
            str(elf),
        ]
    )
    validate_static_elf(elf)

    image = out_dir / "probe.Image"
    run([objcopy, "-O", "binary", str(elf), str(image)])
    patch_image_header(image)
    return image


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--toolchain", choices=("auto", "zig", "gcc"), default="auto")
    parser.add_argument("--zig", help="path to zig executable")
    parser.add_argument("--cross", default=os.environ.get("CROSS", "aarch64-none-elf-"))
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    zig = args.zig or os.environ.get("ZIG") or shutil.which("zig")
    if zig and Path(zig).is_file():
        zig = str(Path(zig).resolve())
    toolchain = args.toolchain
    if toolchain == "auto":
        toolchain = "zig" if zig else "gcc"
    if toolchain == "zig" and not zig:
        raise SystemExit("zig was selected but not found; pass --zig or set ZIG")

    args.out.mkdir(parents=True, exist_ok=True)
    if toolchain == "zig":
        build_with_zig(str(zig), args.out.resolve())
    else:
        build_with_gcc(args.cross, args.out.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
