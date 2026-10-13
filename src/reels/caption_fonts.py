"""Bundled caption font catalog."""

from __future__ import annotations

import re
from pathlib import Path

from reels.config import get_config_dir


def _fonts_dir() -> Path:
    return get_config_dir().parent / "assets" / "fonts"


def _font_id(filename: str) -> str:
    stem = Path(filename).stem
    slug = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")
    return slug


def _font_label(filename: str) -> str:
    stem = Path(filename).stem.replace("-", " ").replace("_", " ")
    return re.sub(r"\s+", " ", stem).strip()


def list_caption_fonts() -> list[dict[str, str]]:
    """Return catalog entries for fonts shipped under assets/fonts/."""
    fonts_dir = _fonts_dir()
    if not fonts_dir.is_dir():
        return []
    entries: list[dict[str, str]] = []
    for path in sorted(fonts_dir.glob("*.ttf")):
        font_id = _font_id(path.name)
        entries.append(
            {
                "id": font_id,
                "label": _font_label(path.name),
                "filename": path.name,
                "preview_url": f"/api/captions/fonts/{font_id}/preview",
            }
        )
    return entries


def resolve_font_path(font_id: str) -> Path | None:
    for entry in list_caption_fonts():
        if entry["id"] == font_id:
            return _fonts_dir() / entry["filename"]
    return None
