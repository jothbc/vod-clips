"""Shared transcript per video - Whisper once, reuse everywhere."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from reels.config import AppConfig, load_config
from reels.models import VideoMetadata, VideoTranscript
from reels.probe import probe_video
from reels.proxy import generate_proxy
from reels.transcribe import transcribe_audio
from reels.video_store import (
    audio_path,
    resolve_video_id,
    segments_original_path,
    segments_path,
    source_path,
    transcript_dir,
)


def load_segments(slug: str) -> list[dict[str, Any]] | None:
    path = segments_path(slug)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def slice_segments_for_window(
    segments: list[dict[str, Any]],
    start: float,
    end: float,
) -> list[dict[str, Any]]:
    """Return segments overlapping [start, end] with times clipped to the window."""
    if start >= end:
        return []
    out: list[dict[str, Any]] = []
    for seg in segments:
        seg_start = float(seg.get("start", 0))
        seg_end = float(seg.get("end", 0))
        if seg_end < start or seg_start > end:
            continue
        clipped = dict(seg)
        clipped["start"] = max(seg_start, start)
        clipped["end"] = min(seg_end, end)
        out.append(clipped)
    return out


def segments_for_clip_job(
    parent_slug: str,
    clip_start: float,
    clip_end: float,
    config: AppConfig | None,
    warnings: list[str] | None,
    *,
    shift_to_zero: bool = True,
    work_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Load parent transcript, slice to clip window, optionally shift times to clip-relative."""
    _, segments = load_or_transcribe(
        parent_slug, config, warnings=warnings, persist=False, work_dir=work_dir
    )
    sliced = slice_segments_for_window(segments, clip_start, clip_end)
    if not shift_to_zero:
        return sliced
    return [
        {
            **s,
            "start": float(s["start"]) - clip_start,
            "end": float(s["end"]) - clip_start,
        }
        for s in sliced
    ]


def save_segments(slug: str, segments: list[dict[str, Any]], *, original: bool = True) -> None:
    transcript_dir(slug).mkdir(parents=True, exist_ok=True)
    segments_path(slug).write_text(json.dumps(segments, ensure_ascii=False, indent=2), encoding="utf-8")
    if original:
        shutil.copy2(segments_path(slug), segments_original_path(slug))
    _sync_transcript_to_db(slug, segments)


def _sync_transcript_to_db(slug: str, segments: list[dict[str, Any]]) -> None:
    """Write-through: keep the transcripts table in sync with the on-disk JSON."""
    try:
        from reels import video_repo

        original: list[dict[str, Any]] = []
        orig_path = segments_original_path(slug)
        if orig_path.is_file():
            original = json.loads(orig_path.read_text(encoding="utf-8"))
        video_repo.save_transcript(slug, segments, original)
    except Exception:
        pass


def load_or_transcribe(
    video_id: str,
    config: AppConfig | None = None,
    *,
    warnings: list[str] | None = None,
    force: bool = False,
    persist: bool = False,
    work_dir: Path | None = None,
) -> tuple[VideoMetadata, list[dict[str, Any]]]:
    """Return metadata + Whisper segments.

    By default does **not** write library transcript files/DB (``persist=False``).
    Pass ``work_dir`` to cache audio/segments under a job folder for ephemeral reuse.
    """
    meta = resolve_video_id(video_id)
    if meta.kind == "clip" and meta.parent_slug:
        video_id = meta.parent_slug
        meta = resolve_video_id(video_id)

    if not force:
        if work_dir is not None:
            job_seg = work_dir / "segments.json"
            if job_seg.is_file():
                return meta, json.loads(job_seg.read_text(encoding="utf-8"))
        # Read existing library transcript if present (do not require persist).
        existing = load_segments(video_id)
        if existing is not None:
            return meta, existing

    cfg = config or load_config("twitch_gaming")
    video_path = source_path(video_id)
    if not video_path.is_file():
        raise FileNotFoundError(f"Source video missing: {video_path}")

    out = work_dir if work_dir is not None else transcript_dir(video_id)
    out.mkdir(parents=True, exist_ok=True)
    info = probe_video(video_path)
    _proxy, audio, _preview = generate_proxy(video_path, out, cfg, info, skip_if_exists=True)

    segments = transcribe_audio(audio, cfg, warnings=warnings)
    if work_dir is not None:
        (work_dir / "segments.json").write_text(
            json.dumps(segments, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    if persist:
        if audio.resolve() != audio_path(video_id).resolve() and audio.is_file():
            audio_path(video_id).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(audio, audio_path(video_id))
        save_segments(video_id, segments, original=True)
    return meta, segments


def ensure_transcript(
    video_id: str,
    config: AppConfig | None = None,
    *,
    warnings: list[str] | None = None,
    force: bool = False,
) -> VideoTranscript:
    meta, segments = load_or_transcribe(video_id, config, warnings=warnings, force=force)
    slug = meta.slug if meta.kind == "original" else (meta.parent_slug or video_id)
    original: list[dict[str, Any]] = []
    orig_path = segments_original_path(slug)
    if orig_path.is_file():
        original = json.loads(orig_path.read_text(encoding="utf-8"))
    return VideoTranscript(video_id=slug, segments=segments, segments_original=original)


def _match_segment_index(
    segments: list[dict[str, Any]],
    edit_start: float,
    edit_end: float,
) -> int | None:
    """Find the parent segment with the largest overlap for a clip-window edit."""
    best_idx: int | None = None
    best_overlap = 0.0
    for i, seg in enumerate(segments):
        seg_start = float(seg.get("start", 0))
        seg_end = float(seg.get("end", 0))
        overlap = max(0.0, min(seg_end, edit_end) - max(seg_start, edit_start))
        if overlap > best_overlap:
            best_overlap = overlap
            best_idx = i
    return best_idx if best_overlap > 0 else None


def _update_clip_transcript(
    meta: VideoMetadata,
    video_id: str,
    edited_segments: list[dict[str, Any]],
) -> VideoTranscript:
    """Apply clip-window edits back onto the parent VOD transcript."""
    parent_slug = meta.parent_slug
    if not parent_slug:
        raise ValueError("Clip has no parent VOD")
    clip_start = float(meta.start or 0)
    clip_end = float(meta.end or clip_start)
    parent_segments = load_segments(parent_slug)
    if parent_segments is None:
        raise FileNotFoundError("Transcript not found - run metadata first")

    merged = [dict(s) for s in parent_segments]
    for edit in edited_segments:
        edit_start = float(edit.get("start", 0))
        edit_end = float(edit.get("end", 0))
        idx = _match_segment_index(merged, edit_start, edit_end)
        if idx is not None:
            merged[idx]["text"] = str(edit.get("text", ""))

    save_segments(parent_slug, merged, original=False)
    original: list[dict[str, Any]] = []
    orig_path = segments_original_path(parent_slug)
    if orig_path.is_file():
        original = json.loads(orig_path.read_text(encoding="utf-8"))

    sliced = slice_segments_for_window(merged, clip_start, clip_end)
    orig_sliced = slice_segments_for_window(original, clip_start, clip_end) if original else []
    return VideoTranscript(
        video_id=video_id,
        segments=sliced,
        segments_original=orig_sliced,
    )


def update_transcript(video_id: str, segments: list[dict[str, Any]]) -> VideoTranscript:
    meta = resolve_video_id(video_id)
    if meta.kind == "clip" and meta.parent_slug:
        return _update_clip_transcript(meta, video_id, segments)
    slug = meta.slug
    if not load_segments(slug):
        raise FileNotFoundError("Transcript not found - run metadata first")
    save_segments(slug, segments, original=False)
    original: list[dict[str, Any]] = []
    orig_path = segments_original_path(slug)
    if orig_path.is_file():
        original = json.loads(orig_path.read_text(encoding="utf-8"))
    return VideoTranscript(video_id=slug, segments=segments, segments_original=original)
