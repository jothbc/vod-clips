#!/usr/bin/env python3
"""Syntax and import structure check when pip/pytest are unavailable."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "reels"


def main() -> int:
    errors: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as e:
            errors.append(f"{path}: {e}")

    required = [
        ROOT / "config" / "default.yaml",
        ROOT / "config" / "twitch_gaming.yaml",
        ROOT / "pyproject.toml",
        ROOT / "prompts" / "twitch_highlight_window.txt",
    ]
    for p in required:
        if not p.exists():
            errors.append(f"missing: {p}")

    if errors:
        for e in errors:
            print(e, file=sys.stderr)
        return 1
    print(f"OK: {len(list(SRC.rglob('*.py')))} Python files parse cleanly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
