"""DB-backed registry for videos, relations, aliases and per-video transcripts.

The SQLite database (``temp/reels.db``) is the source of truth for video
identity and metadata. The filesystem still holds the media, keyed by a stable
``storage_root`` (the folder name under ``temp/video/``). The display ``slug``
lives in the DB and can be renamed without moving files, because every job,
publish record and legacy id resolves through this registry.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from reels.db import init_db
from reels.db.connection import connection
from reels.models import VideoKind, WebcamRegion


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_video_id() -> str:
    return uuid.uuid4().hex


class VideoRecord(BaseModel):
    id: str
    slug: str
    parent_id: str | None = None
    kind: VideoKind = "original"
    title: str = ""
    format: str | None = None
    formats_available: list[str] = Field(default_factory=list)
    source_feature: str | None = None
    start_sec: float | None = None
    end_sec: float | None = None
    duration: float = 0.0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    codec: str = ""
    size_bytes: int = 0
    source_filename: str = ""
    webcam_region: WebcamRegion | None = None
    published: bool = False
    published_at: str | None = None
    storage_root: str = ""
    created_at: str = ""
    updated_at: str = ""
    uploaded_at: str = ""


def _row_to_record(row) -> VideoRecord:
    region = None
    if row["webcam_region"]:
        try:
            region = WebcamRegion.model_validate_json(row["webcam_region"])
        except Exception:
            region = None
    uploaded = row["uploaded_at"] if "uploaded_at" in row.keys() else row["created_at"]
    return VideoRecord(
        id=row["id"],
        slug=row["slug"],
        parent_id=row["parent_id"],
        kind=row["kind"],
        title=row["title"],
        format=row["format"],
        formats_available=json.loads(row["formats_available"] or "[]"),
        source_feature=row["source_feature"],
        start_sec=row["start_sec"],
        end_sec=row["end_sec"],
        duration=row["duration"],
        width=row["width"],
        height=row["height"],
        fps=row["fps"],
        codec=row["codec"],
        size_bytes=row["size_bytes"],
        source_filename=row["source_filename"],
        webcam_region=region,
        published=bool(row["published"]),
        published_at=row["published_at"],
        storage_root=row["storage_root"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        uploaded_at=uploaded or row["created_at"],
    )


def get_by_id(video_id: str) -> VideoRecord | None:
    init_db()
    with connection() as con:
        row = con.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()
        return _row_to_record(row) if row else None


def get_by_slug(slug: str) -> VideoRecord | None:
    init_db()
    with connection() as con:
        row = con.execute("SELECT * FROM videos WHERE slug = ?", (slug,)).fetchone()
        return _row_to_record(row) if row else None


def resolve(id_or_alias: str) -> VideoRecord | None:
    """Resolve a UUID, current slug, or legacy alias to a video record."""
    init_db()
    with connection() as con:
        row = con.execute("SELECT * FROM videos WHERE id = ? OR slug = ?", (id_or_alias, id_or_alias)).fetchone()
        if row:
            return _row_to_record(row)
        alias = con.execute("SELECT video_id FROM video_aliases WHERE alias = ?", (id_or_alias,)).fetchone()
        if alias:
            row = con.execute("SELECT * FROM videos WHERE id = ?", (alias["video_id"],)).fetchone()
            return _row_to_record(row) if row else None
    return None


def add_alias(alias: str, video_id: str) -> None:
    if not alias or not video_id:
        return
    init_db()
    with connection() as con:
        con.execute(
            "INSERT OR REPLACE INTO video_aliases (alias, video_id) VALUES (?, ?)",
            (alias, video_id),
        )


def upsert_video(
    *,
    slug: str,
    storage_root: str,
    kind: VideoKind = "original",
    title: str = "",
    parent_id: str | None = None,
    fmt: str | None = None,
    formats_available: list[str] | None = None,
    source_feature: str | None = None,
    start_sec: float | None = None,
    end_sec: float | None = None,
    duration: float = 0.0,
    width: int = 0,
    height: int = 0,
    fps: float = 0.0,
    codec: str = "",
    size_bytes: int = 0,
    source_filename: str = "",
    webcam_region: WebcamRegion | None = None,
    video_id: str | None = None,
    aliases: list[str] | None = None,
    uploaded_at: str | None = None,
) -> VideoRecord:
    """Insert or update a video row keyed by slug. Returns the stored record."""
    init_db()
    now = _utc_now()
    upload_ts = uploaded_at or now
    region_json = webcam_region.model_dump_json() if webcam_region else None
    fmts = json.dumps(formats_available or [])
    with connection() as con:
        existing = con.execute("SELECT * FROM videos WHERE slug = ?", (slug,)).fetchone()
        if existing:
            vid = existing["id"]
            con.execute(
                """
                UPDATE videos SET
                    kind = ?, title = ?, parent_id = ?, format = ?, formats_available = ?,
                    source_feature = ?, start_sec = ?, end_sec = ?, duration = ?, width = ?,
                    height = ?, fps = ?, codec = ?, size_bytes = ?, source_filename = ?,
                    webcam_region = ?, storage_root = ?, updated_at = ?,
                    uploaded_at = COALESCE(?, uploaded_at)
                WHERE id = ?
                """,
                (
                    kind, title, parent_id, fmt, fmts, source_feature, start_sec, end_sec,
                    duration, width, height, fps, codec, size_bytes, source_filename,
                    region_json, storage_root, now, upload_ts if uploaded_at else None, vid,
                ),
            )
        else:
            vid = video_id or new_video_id()
            con.execute(
                """
                INSERT INTO videos (
                    id, slug, parent_id, kind, title, format, formats_available, source_feature,
                    start_sec, end_sec, duration, width, height, fps, codec, size_bytes,
                    source_filename, webcam_region, published, published_at, storage_root,
                    created_at, updated_at, uploaded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, ?, ?, ?, ?)
                """,
                (
                    vid, slug, parent_id, kind, title, fmt, fmts, source_feature,
                    start_sec, end_sec, duration, width, height, fps, codec, size_bytes,
                    source_filename, region_json, storage_root, now, now, upload_ts,
                ),
            )
        for alias in aliases or []:
            if alias and alias != slug:
                con.execute(
                    "INSERT OR REPLACE INTO video_aliases (alias, video_id) VALUES (?, ?)",
                    (alias, vid),
                )
        row = con.execute("SELECT * FROM videos WHERE id = ?", (vid,)).fetchone()
    return _row_to_record(row)


def rename_video(video_id: str, *, slug: str | None = None, title: str | None = None) -> VideoRecord:
    """Rename display slug and/or title without moving files. Old slug becomes an alias."""
    init_db()
    record = resolve(video_id)
    if record is None:
        raise FileNotFoundError(f"Video not found: {video_id}")
    now = _utc_now()
    with connection() as con:
        if slug and slug != record.slug:
            clash = con.execute("SELECT id FROM videos WHERE slug = ? AND id != ?", (slug, record.id)).fetchone()
            if clash:
                raise ValueError(f"Slug already in use: {slug}")
            con.execute(
                "INSERT OR REPLACE INTO video_aliases (alias, video_id) VALUES (?, ?)",
                (record.slug, record.id),
            )
            con.execute("DELETE FROM video_aliases WHERE alias = ?", (slug,))
            con.execute("UPDATE videos SET slug = ?, updated_at = ? WHERE id = ?", (slug, now, record.id))
        if title is not None:
            con.execute("UPDATE videos SET title = ?, updated_at = ? WHERE id = ?", (title, now, record.id))
        row = con.execute("SELECT * FROM videos WHERE id = ?", (record.id,)).fetchone()
    return _row_to_record(row)


def set_published(video_id: str, published: bool, *, at: str | None = None) -> None:
    init_db()
    record = resolve(video_id)
    if record is None:
        return
    with connection() as con:
        con.execute(
            "UPDATE videos SET published = ?, published_at = ?, updated_at = ? WHERE id = ?",
            (1 if published else 0, at or (_utc_now() if published else None), _utc_now(), record.id),
        )


def set_webcam_region(video_id: str, region: WebcamRegion | None) -> None:
    init_db()
    record = resolve(video_id)
    if record is None:
        return
    with connection() as con:
        con.execute(
            "UPDATE videos SET webcam_region = ?, updated_at = ? WHERE id = ?",
            (region.model_dump_json() if region else None, _utc_now(), record.id),
        )


def children(parent_id: str) -> list[VideoRecord]:
    init_db()
    with connection() as con:
        rows = con.execute(
            "SELECT * FROM videos WHERE parent_id = ? ORDER BY start_sec, created_at", (parent_id,)
        ).fetchall()
    return [_row_to_record(r) for r in rows]


def list_videos(kind: VideoKind | None = None) -> list[VideoRecord]:
    init_db()
    with connection() as con:
        if kind:
            rows = con.execute(
                "SELECT * FROM videos WHERE kind = ? ORDER BY created_at DESC", (kind,)
            ).fetchall()
        else:
            rows = con.execute("SELECT * FROM videos ORDER BY created_at DESC").fetchall()
    return [_row_to_record(r) for r in rows]


def delete_video(video_id: str) -> None:
    init_db()
    record = resolve(video_id)
    if record is None:
        return
    with connection() as con:
        con.execute("DELETE FROM videos WHERE id = ?", (record.id,))


# --- Transcripts -----------------------------------------------------------


def save_transcript(
    video_id: str,
    segments: list[dict[str, Any]],
    segments_original: list[dict[str, Any]] | None = None,
) -> None:
    init_db()
    record = resolve(video_id)
    if record is None:
        return
    with connection() as con:
        con.execute(
            """
            INSERT INTO transcripts (video_id, segments_json, segments_original_json, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(video_id) DO UPDATE SET
                segments_json = excluded.segments_json,
                segments_original_json = excluded.segments_original_json,
                updated_at = excluded.updated_at
            """,
            (
                record.id,
                json.dumps(segments, ensure_ascii=False),
                json.dumps(segments_original, ensure_ascii=False) if segments_original is not None else None,
                _utc_now(),
            ),
        )


def load_transcript(video_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | None:
    init_db()
    record = resolve(video_id)
    if record is None:
        return None
    with connection() as con:
        row = con.execute("SELECT * FROM transcripts WHERE video_id = ?", (record.id,)).fetchone()
    if not row:
        return None
    segments = json.loads(row["segments_json"] or "[]")
    original = json.loads(row["segments_original_json"]) if row["segments_original_json"] else []
    return segments, original


def count_children(parent_id: str) -> int:
    init_db()
    with connection() as con:
        row = con.execute("SELECT COUNT(*) AS n FROM videos WHERE parent_id = ?", (parent_id,)).fetchone()
    return int(row["n"]) if row else 0


def search_records(query: str, limit: int = 24) -> list[VideoRecord]:
    """Case-insensitive title/slug search across VODs and clips."""
    q = query.strip().lower()
    if not q:
        return []
    init_db()
    like = f"%{q}%"
    with connection() as con:
        rows = con.execute(
            """
            SELECT v.* FROM videos v
            LEFT JOIN video_aliases a ON a.video_id = v.id
            WHERE LOWER(v.title) LIKE ? OR LOWER(v.slug) LIKE ? OR LOWER(a.alias) LIKE ?
            ORDER BY v.uploaded_at DESC, v.created_at DESC
            LIMIT ?
            """,
            (like, like, like, limit * 3),
        ).fetchall()
    seen: set[str] = set()
    out: list[VideoRecord] = []
    for row in rows:
        rec = _row_to_record(row)
        if rec.id in seen:
            continue
        seen.add(rec.id)
        out.append(rec)
        if len(out) >= limit:
            break
    return out


def has_transcript(video_id: str) -> bool:
    init_db()
    record = resolve(video_id)
    if record is None:
        return False
    with connection() as con:
        row = con.execute("SELECT 1 FROM transcripts WHERE video_id = ?", (record.id,)).fetchone()
    return row is not None
