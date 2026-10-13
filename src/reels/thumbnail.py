"""Thumbnail frame sizing and title overlay."""

from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path
from typing import Any

from reels.caption_fonts import resolve_font_path
from reels.config import AppConfig


def target_dimensions(info: Any, platform: str) -> tuple[int, int]:
    """Return (width, height) for thumbnail export."""
    if platform == "youtube":
        if info.height > info.width:
            return (1080, 1920)
        return (1920, 1080)
    # short_form / reels
    return (1080, 1920)


def wrap_title_lines(title: str, max_chars: int = 28, max_lines: int = 3) -> str:
    wrapped = textwrap.wrap(title, width=max_chars)
    if not wrapped:
        return title
    return "\n".join(wrapped[:max_lines])


def overlay_title_on_image(
    frame_path: Path,
    title: str,
    output_path: Path,
    *,
    config: AppConfig,
    platform: str,
    work_dir: Path,
    frame_height: int = 720,
) -> None:
    """Draw wrapped title text onto a JPEG frame using ffmpeg."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wrapped = wrap_title_lines(title, max_chars=24, max_lines=3)
    escaped = (
        wrapped.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace("%", "\\%")
    )
    font_size = max(28, frame_height // 18)
    y_pos = int(frame_height * 0.78)
    font_path = resolve_font_path(config.publish.default_font)
    font_part = ""
    if font_path and font_path.is_file():
        font_esc = str(font_path.resolve()).replace("\\", "/").replace(":", "\\:")
        font_part = f"fontfile='{font_esc}':"
    vf = (
        f"drawtext={font_part}text='{escaped}':fontsize={font_size}:fontcolor=white:"
        f"borderw=3:bordercolor=black@0.7:x=(w-text_w)/2:y={y_pos}:line_spacing=8"
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(frame_path),
        "-vf",
        vf,
        "-q:v",
        str(max(2, min(31, 31 - config.publish.thumbnail_jpeg_quality // 4))),
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        # Windows often lacks fontconfig; fall back to frame-only thumbnail.
        shutil.copy2(frame_path, output_path)
