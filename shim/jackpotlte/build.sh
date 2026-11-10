#!/bin/sh
# Build a raw arm64 Image. This is not a BOOT image and does not flash a device.
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT=$(CDPATH= cd -- "$HERE/../.." && pwd)
exec python3 "$ROOT/tools/build_jackpot_probe.py" --toolchain gcc \
    --cross "${CROSS:-aarch64-none-elf-}"
