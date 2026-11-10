#!/usr/bin/env python3
"""Package a validated A530N XNU v12 diagnostic BOOT image as a TWRP ZIP."""

from pathlib import Path
import argparse
import hashlib
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BOOT = ROOT / "outputs" / "jackpotlte-xnu-8796.141.3-entry-candidate-v12-fbfix.img"
DEFAULT_OUTPUT = ROOT / "outputs" / "jackpotlte-xnu-v12-fbfix-twrp.zip"
INSTALLER = ROOT / "tools" / "twrp_installer_v12" / "update-binary"
sys.path.insert(0, str(ROOT))
from tools.a530n_boot import arm64_header, parse_boot, parse_dtbh


def validate_image(data: bytes, path: Path) -> None:
    image = parse_boot(data)
    if image["page_size"] != 2048 or image["name"] != "SRPQH21B008KU":
        raise SystemExit(f"{path}: unexpected Samsung BOOT header")
    if len(data) > 32 * 1024 * 1024:
        raise SystemExit(f"{path}: image exceeds the 32 MiB BOOT partition")
    if arm64_header(image["kernel"]) is None:
        raise SystemExit(f"{path}: embedded Samsung kernel has no arm64 Image header")
    _, entries = parse_dtbh(image["dt"])
    if not any(entry[0] == 7885 for entry in entries):
        raise SystemExit(f"{path}: no Exynos 7885 DTBH entry")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--boot", type=Path, default=DEFAULT_BOOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--name", default="v12 framebuffer diagnostic")
    args = parser.parse_args()

    if not args.boot.is_file():
        raise SystemExit(f"BOOT image not found: {args.boot}")
    if not INSTALLER.is_file():
        raise SystemExit(f"TWRP installer not found: {INSTALLER}")

    boot_data = args.boot.read_bytes()
    validate_image(boot_data, args.boot)
    installer = INSTALLER.read_text(encoding="utf-8")
    installer = installer.replace("__IMAGE_SHA256__", hashlib.sha256(boot_data).hexdigest())
    installer = installer.replace("__IMAGE_SIZE__", str(len(boot_data)))
    installer = installer.replace("__CANDIDATE_NAME__", args.name)
    if "__IMAGE_" in installer or "__CANDIDATE_NAME__" in installer:
        raise SystemExit("installer template has an unresolved value")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr("boot.img", boot_data)
        info = zipfile.ZipInfo("META-INF/com/google/android/update-binary")
        info.external_attr = (0o100755 << 16)
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, installer.encode("utf-8"))
        archive.writestr(
            "META-INF/com/google/android/updater-script",
            "# updater logic is in update-binary\n",
        )
        archive.writestr(
            "README.txt",
            f"Experimental {args.name} kernel-only BOOT image for Galaxy A8 2018 SM-A530N (jackpotlte).\n"
            "The installer validates the image and 32 MiB BOOT partition, writes BOOT only,\n"
            "then verifies the written image hash. Keep the TWRP BOOT backup available.\n"
            "This is not an iOS install image and does not contain an iOS userland.\n",
        )

    print(args.output)


if __name__ == "__main__":
    main()
