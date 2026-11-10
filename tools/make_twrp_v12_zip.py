#!/usr/bin/env python3
"""Package the inspected A530N XNU v12 candidate as a TWRP ZIP."""

from pathlib import Path
import argparse
import zipfile


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BOOT = ROOT / "outputs" / "jackpotlte-xnu-8796.141.3-entry-candidate-v12-pthread-provider.img"
DEFAULT_OUTPUT = ROOT / "outputs" / "jackpotlte-xnu-v12-pthread-provider-twrp-r2.zip"
INSTALLER = ROOT / "tools" / "twrp_installer_v12" / "update-binary"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--boot", type=Path, default=DEFAULT_BOOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    if not args.boot.is_file():
        raise SystemExit(f"BOOT image not found: {args.boot}")
    if not INSTALLER.is_file():
        raise SystemExit(f"TWRP installer not found: {INSTALLER}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.write(args.boot, "boot.img")
        info = zipfile.ZipInfo("META-INF/com/google/android/update-binary")
        info.external_attr = (0o100755 << 16)
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, INSTALLER.read_bytes())
        archive.writestr(
            "META-INF/com/google/android/updater-script",
            "# updater logic is in update-binary\n",
        )
        archive.writestr(
            "README.txt",
            "Experimental kernel-only BOOT image for Galaxy A8 2018 SM-A530N (jackpotlte).\n"
            "The installer validates the image and 32 MiB BOOT partition, writes BOOT only,\n"
            "then verifies the written image hash. Keep the TWRP BOOT backup available.\n"
            "This is not an iOS install image and does not contain an iOS userland.\n",
        )

    print(args.output)


if __name__ == "__main__":
    main()
