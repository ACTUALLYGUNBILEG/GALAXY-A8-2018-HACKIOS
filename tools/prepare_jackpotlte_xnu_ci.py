#!/usr/bin/env python3
"""Select and adapt the pinned S8/A5XELTE patch stack for the A8 CI build."""
import argparse
import re
import shutil
from pathlib import Path


PATCH_RANGES = ((1, 30), (65, 65), (82, 87), (89, 97), (99, 99))
STAGE_SCRIPTS = (
    "0019-stage-libpthread.sh",
    "0020-stage-bearssl.sh",
    "0026-stage-hfs.sh",
)


def selected_patch(number: int) -> bool:
    return any(first <= number <= last for first, last in PATCH_RANGES)


def trim_0086(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    sections = re.split(r"(?=^--- a/)", text, flags=re.MULTILINE)
    kept = []
    removed = 0
    for section in sections:
        first_line = section.splitlines()[0] if section.splitlines() else ""
        if first_line == "--- a/iokit/KernelConfigTables.cpp":
            removed += 1
            continue
        kept.append(section)
    if removed != 1:
        raise SystemExit(
            f"{path.name}: expected one conflicting KernelConfigTables section, found {removed}"
        )
    return "".join(kept)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="pinned S8 xnu/patches directory")
    parser.add_argument("destination", type=Path, help="new, empty output patch directory")
    args = parser.parse_args()
    source = args.source.resolve()
    destination = args.destination.resolve()
    if not source.is_dir():
        raise SystemExit(f"missing donor patch directory: {source}")
    if destination.exists() and any(destination.iterdir()):
        raise SystemExit(f"refusing to overwrite non-empty patch directory: {destination}")
    destination.mkdir(parents=True, exist_ok=True)

    chosen = []
    for path in sorted(source.glob("*.patch")):
        match = re.match(r"^(\d{4})-", path.name)
        if match and selected_patch(int(match.group(1))):
            chosen.append(path)

    expected = sum(last - first + 1 for first, last in PATCH_RANGES)
    if len(chosen) != expected:
        raise SystemExit(f"expected {expected} donor patches, found {len(chosen)}")
    if not any(path.name == "0086-a5xelte-gicv2-platform.patch" for path in chosen):
        raise SystemExit("the donor GICv2 patch is missing")

    for path in chosen:
        output = destination / path.name
        if path.name == "0086-a5xelte-gicv2-platform.patch":
            output.write_text(trim_0086(path), encoding="utf-8", newline="\n")
        else:
            shutil.copy2(path, output)

    for name in STAGE_SCRIPTS:
        path = source / name
        if not path.is_file():
            raise SystemExit(f"required source-staging script is missing: {name}")
        output = destination / name
        if name == "0026-stage-hfs.sh":
            # 0026-sweet-builtin-hfs.patch creates this directory for its
            # integration shims before the script stages Apple's HFS sources.
            text = path.read_text(encoding="utf-8")
            old = """if target.exists():
    raise SystemExit(f'refusing to overwrite existing HFS sources: {target}')
"""
            new = """if any((target / name).exists() for name in ("core", "hfs_encodings")):
    raise SystemExit(f'refusing to overwrite existing HFS sources: {target}')
target.mkdir(parents=True, exist_ok=True)
"""
            if text.count(old) != 1:
                raise SystemExit(f"unexpected HFS staging guard in {path}")
            output.write_text(text.replace(old, new), encoding="utf-8")
        else:
            shutil.copy2(path, output)

    print(f"prepared {len(chosen)} donor patches and {len(STAGE_SCRIPTS)} staging scripts")


if __name__ == "__main__":
    main()
