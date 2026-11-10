#!/usr/bin/env python3
"""Build the freestanding Samsung Image that hands off to the A8 XNU payload."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path

from build_jackpot_probe import (
    CFLAGS,
    patch_image_header,
    tool_path,
    validate_static_elf,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "shim" / "jackpotlte"
DEFAULT_OUT = SOURCE_DIR / "outxnu"


def run(command: list[str], env: dict[str, str] | None = None) -> None:
    print("+", subprocess.list2cmdline(command))
    subprocess.run(command, check=True, env=env)


def build_with_zig(zig: str, out: Path) -> Path:
    zig_env = os.environ.copy()
    zig_env["ZIG_LOCAL_CACHE_DIR"] = str(out / "zig-cache" / "local")
    zig_env["ZIG_GLOBAL_CACHE_DIR"] = str(out / "zig-cache" / "global")
    zig_flags = [flag.replace("cortex-a53", "cortex_a53") for flag in CFLAGS]
    objects: list[Path] = []
    for source_name in ("xnu_loader.S", "xnu_loader.c", "fdtmem.c", "fbtext.c"):
        source = SOURCE_DIR / source_name
        obj = out / f"{source_name}.o"
        run([zig, "cc", "-target", "aarch64-freestanding-none", "-c",
             *zig_flags, str(source), "-o", str(obj)], env=zig_env)
        objects.append(obj)

    elf = out / "xnu_loader.elf"
    run([zig, "cc", "-target", "aarch64-freestanding-none", "-nostdlib",
         "-no-pie", "-Wl,-T," + str(SOURCE_DIR / "image.ld"),
         "-Wl,--build-id=none", *[str(obj) for obj in objects], "-o", str(elf)],
        env=zig_env)
    validate_static_elf(elf)
    image = out / "xnu_loader.Image"
    run([zig, "objcopy", "-O", "binary", str(elf), str(image)], env=zig_env)
    patch_image_header(image)
    return image


def build_with_gcc(cross: str, out: Path) -> Path:
    gcc = tool_path(cross, "gcc")
    ld = tool_path(cross, "ld")
    objcopy = tool_path(cross, "objcopy")
    objects: list[Path] = []
    for source_name in ("xnu_loader.S", "xnu_loader.c", "fdtmem.c", "fbtext.c"):
        source = SOURCE_DIR / source_name
        obj = out / f"{source_name}.o"
        run([gcc, "-c", *CFLAGS, str(source), "-o", str(obj)])
        objects.append(obj)

    elf = out / "xnu_loader.elf"
    run([ld, "-static", "-T", str(SOURCE_DIR / "image.ld"),
         "--build-id=none", *[str(obj) for obj in objects], "-o", str(elf)])
    validate_static_elf(elf)
    image = out / "xnu_loader.Image"
    run([objcopy, "-O", "binary", str(elf), str(image)])
    patch_image_header(image)
    return image


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--toolchain", choices=("auto", "zig", "gcc"), default="auto")
    parser.add_argument("--zig", help="path to the Zig executable")
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

    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    image = build_with_zig(str(zig), out) if toolchain == "zig" else build_with_gcc(args.cross, out)
    print(f"loader Image ready: {image}")
    print("This Image is a bootloader; pair it with a SWEETXNU payload as raw initrd.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
