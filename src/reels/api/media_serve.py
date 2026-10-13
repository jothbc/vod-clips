"""Serve exported clip files from disk without an active job."""

from __future__ import annotations

from pathlib import Path

MIN_CLIP_BYTES = 1000


def is_readable_clip(path: Path) -> bool:
    """True if path looks like a readable exported clip file."""
    try:
        if not path.is_file():
            return False
        return path.stat().st_size >= MIN_CLIP_BYTES
    except OSError:
        return False


def resolve_media_clip(job_id: str, fmt: str, filename: str) -> Path:
    """Resolve a clip path under temp/outputs and validate job_id/filename."""
    from reels.storage import temp_outputs_dir

    if fmt not in ("youtube", "reels"):
        raise ValueError("format must be youtube or reels")
    if ".." in job_id or ".." in filename.replace("\\", "/"):
        raise ValueError("Invalid path")
    if "/" in filename or "\\" in filename:
        raise ValueError("Invalid filename")

    base = temp_outputs_dir().resolve()
    clip = (base / job_id / fmt / filename).resolve()
    if not clip.is_relative_to(base):
        raise ValueError("Forbidden")
    return clip
