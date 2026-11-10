#!/usr/bin/env python3
"""Normalize text line endings in an isolated Linux-side XNU build copy."""

from pathlib import Path
import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("xnu_tree", type=Path)
    tree = parser.parse_args().xnu_tree.resolve()
    if not (tree / "makedefs/MakeInc.cmd").is_file():
        raise SystemExit(f"{tree}: not an XNU source tree")

    converted = 0
    for path in tree.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(tree)
        if ".git" in relative.parts or "BUILD" in relative.parts or "__pycache__" in relative.parts:
            continue
        data = path.read_bytes()
        if b"\0" in data or b"\r\n" not in data:
            continue
        path.write_bytes(data.replace(b"\r\n", b"\n"))
        converted += 1

    print(f"Normalized CRLF in {converted} text files under {tree}")


if __name__ == "__main__":
    main()
