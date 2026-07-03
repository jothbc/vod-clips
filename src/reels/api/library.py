"""Scan temp/outputs for exported reel sessions and pickable clips."""

from __future__ import annotations

import re
from pathlib import Path

from reels.api.clips import list_clips
from reels.highlights import load_highlights
from reels.storage import temp_outputs_dir

_JOB_ID_RE = re.compile(r"^[a-zA-Z0-9._-]+$")


def _job_has_exports(job_dir: Path) -> bool:
    yt = job_dir / "youtube"
    rl = job_dir / "reels"
    if yt.is_dir() and any(yt.glob("*.mp4")):
        return True
    if rl.is_dir() and any(rl.glob("*.mp4")):
        return True
    return False


def _job_modified(job_dir: Path) -> float:
    latest = 0.0
    for pattern in ("youtube/*.mp4", "reels/*.mp4"):
        for p in job_dir.glob(pattern):
            try:
                latest = max(latest, p.stat().st_mtime)
            except OSError:
                pass
    return latest


def _source_video_label(highlights_path: Path) -> str:
    try:
        doc = load_highlights(highlights_path)
        return Path(doc.source_video).name
    except Exception:
        return ""


def _title_from_clip_filename(name: str) -> str:
    stem = Path(name).stem
    if len(stem) > 3 and stem[2] == "_":
        stem = stem[3:]
    return stem.replace("_", " ").strip() or name


def list_library_jobs() -> list[dict]:
    """Return exported sessions sorted by newest clip mtime."""
    root = temp_outputs_dir()
    jobs: list[dict] = []
    if not root.is_dir():
        return []

    for job_dir in root.iterdir():
        if not job_dir.is_dir():
            continue
        if not _JOB_ID_RE.match(job_dir.name):
            continue
        highlights = job_dir / "highlights.json"
        if not highlights.is_file():
            continue
        if not _job_has_exports(job_dir):
            continue
        job_id = job_dir.name
        clips = list_clips(job_id, job_dir)
        jobs.append(
            {
                "job_id": job_id,
                "output_dir": str(job_dir.resolve()),
                "source_video": _source_video_label(highlights),
                "modified": _job_modified(job_dir),
                "clip_count": len([c for c in clips if c.youtube_url or c.reels_url]),
                "clips": [c.model_dump() for c in clips],
            }
        )

    jobs.sort(key=lambda j: j["modified"], reverse=True)
    return jobs


def list_pickable_clips() -> list[dict]:
    """Flat list of exported clip files usable as pipeline input."""
    items: list[dict] = []
    for job in list_library_jobs():
        job_dir = Path(job["output_dir"])
        highlights = job_dir / "highlights.json"
        source_video = _source_video_label(highlights)
        for clip in job["clips"]:
            for fmt, url_key, fn_key in (
                ("youtube", "youtube_url", "youtube_filename"),
                ("reels", "reels_url", "reels_filename"),
            ):
                rel = clip.get(url_key)
                fn = clip.get(fn_key)
                if not rel or not fn:
                    continue
                path = job_dir / fmt / fn
                if not path.is_file():
                    continue
                try:
                    stat = path.stat()
                except OSError:
                    continue
                items.append(
                    {
                        "path": str(path.resolve()),
                        "title": clip.get("title") or _title_from_clip_filename(fn),
                        "format": fmt,
                        "job_id": job["job_id"],
                        "source_video": source_video,
                        "clip_index": clip.get("index", 0),
                        "size_bytes": stat.st_size,
                        "modified": stat.st_mtime,
                    }
                )
    items.sort(key=lambda x: x["modified"], reverse=True)
    return items
