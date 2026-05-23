"""Build clip gallery metadata from job output."""

from __future__ import annotations

from pathlib import Path

from reels.api.schemas import ClipItem
from reels.export import _safe_filename
from reels.highlights import load_highlights


def list_clips(job_id: str, output_dir: Path) -> list[ClipItem]:
    highlights_path = output_dir / "highlights.json"
    if not highlights_path.exists():
        return []

    doc = load_highlights(highlights_path)
    youtube_dir = output_dir / "youtube"
    reels_dir = output_dir / "reels"
    items: list[ClipItem] = []

    for i, hl in enumerate(doc.highlights):
        safe = _safe_filename(hl.title, i)
        yt_name = f"{safe}.mp4"
        reels_name = f"{safe}.mp4"
        yt_path = youtube_dir / yt_name
        reels_path = reels_dir / reels_name

        items.append(
            ClipItem(
                index=i,
                title=hl.title,
                score=hl.score,
                start=hl.start,
                end=hl.end,
                source=hl.source,
                youtube_url=f"/media/{job_id}/youtube/{yt_name}" if yt_path.exists() else None,
                reels_url=f"/media/{job_id}/reels/{reels_name}" if reels_path.exists() else None,
                youtube_filename=yt_name if yt_path.exists() else None,
                reels_filename=reels_name if reels_path.exists() else None,
            )
        )
    return items
