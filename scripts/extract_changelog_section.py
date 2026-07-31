#!/usr/bin/env python3
"""Extract a single CHANGELOG.md version section for GitHub Releases."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def extract_section(changelog: str, version: str) -> str | None:
    """Return the markdown section for version (with header), or None."""
    clean = version.lstrip("vV").strip()
    if not clean:
        return None

    header_re = re.compile(rf"(?m)^## \[(?:v)?{re.escape(clean)}\][^\n]*")
    match = header_re.search(changelog)
    if not match:
        return None

    start = match.start()
    rest = changelog[match.end() :]
    next_header = re.search(r"(?m)^## \[", rest)
    end = match.end() + (next_header.start() if next_header else len(rest))
    return changelog[start:end].strip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--changelog", type=Path, default=Path("CHANGELOG.md"))
    parser.add_argument("--version", required=True, help="e.g. v7.0.0 or 7.0.0")
    parser.add_argument("--output", type=Path, default=Path("release_body.md"))
    args = parser.parse_args(argv)

    if not args.changelog.is_file():
        args.output.write_text(f"Release {args.version}\n", encoding="utf-8")
        print(f"CHANGELOG not found; wrote stub to {args.output}", file=sys.stderr)
        return 0

    text = args.changelog.read_text(encoding="utf-8")
    section = extract_section(text, args.version)
    if section is None:
        args.output.write_text(f"Release {args.version}\n", encoding="utf-8")
        print(f"No CHANGELOG section for {args.version}; wrote stub", file=sys.stderr)
        return 0

    args.output.write_text(section, encoding="utf-8")
    print(f"Wrote CHANGELOG section for {args.version} → {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
