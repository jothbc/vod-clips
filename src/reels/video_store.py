"""Per-video storage under temp/video/{slug}/."""

from __future__ import annotations

import json
import re
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path

from reels import video_repo
from reels.models import ClipMetadata, VideoIndex, VideoKind, VideoMetadata, WebcamRegion
from reels.probe import probe_video
from reels.storage import CHUNK_SIZE, MAX_UPLOAD_BYTES, delete_path, project_root, temp_root

VIDEO_SUBDIR = "video"
ORIGINAL_DIR = "original"
SOURCE_NAME = "source.mp4"
METADATA_NAME = "metadata.json"
TRANSCRIPT_DIR = "transcript"
SEGMENTS_NAME = "segments.json"
SEGMENTS_ORIGINAL_NAME = "segments_original.json"
AUDIO_NAME = "audio_16k.wav"
ANALYSIS_DIR = "analysis"
HIGHLIGHTS_NAME = "highlights.json"
CLIPS_DIR = "clips"
CLIP_ID_SEP = "::"

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,119}$")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def videos_root() -> Path:
    d = temp_root() / VIDEO_SUBDIR
    d.mkdir(parents=True, exist_ok=True)
    return d.resolve()


def video_dir(slug: str) -> Path:
    if not _SLUG_RE.match(slug):
        raise ValueError(f"Invalid video slug: {slug!r}")
    return videos_root() / slug


def original_dir(slug: str) -> Path:
    return video_dir(slug) / ORIGINAL_DIR


def source_path(slug: str) -> Path:
    return original_dir(slug) / SOURCE_NAME


def metadata_path(slug: str) -> Path:
    return original_dir(slug) / METADATA_NAME


def transcript_dir(slug: str) -> Path:
    return video_dir(slug) / TRANSCRIPT_DIR


def segments_path(slug: str) -> Path:
    return transcript_dir(slug) / SEGMENTS_NAME


def segments_original_path(slug: str) -> Path:
    return transcript_dir(slug) / SEGMENTS_ORIGINAL_NAME


def audio_path(slug: str) -> Path:
    return transcript_dir(slug) / AUDIO_NAME


def analysis_dir(slug: str) -> Path:
    return video_dir(slug) / ANALYSIS_DIR


def highlights_path(slug: str) -> Path:
    return analysis_dir(slug) / HIGHLIGHTS_NAME


def clips_root(slug: str) -> Path:
    return video_dir(slug) / CLIPS_DIR


def clip_dir(parent_slug: str, clip_slug: str) -> Path:
    if not _SLUG_RE.match(clip_slug):
        raise ValueError(f"Invalid clip slug: {clip_slug!r}")
    return clips_root(parent_slug) / clip_slug


def clip_meta_path(parent_slug: str, clip_slug: str) -> Path:
    return clip_dir(parent_slug, clip_slug) / "meta.json"


def is_under_videos(path: Path) -> bool:
    try:
        return path.resolve().is_relative_to(videos_root())
    except ValueError:
        return False


def sanitize_slug_base(name: str) -> str:
    base = Path(name).stem
    safe = "".join(c if c.isalnum() or c in "_-" else "_" for c in base).strip("_").lower()
    safe = safe[:80] or "video"
    return safe


def make_unique_slug(base: str) -> str:
    candidate = sanitize_slug_base(base)
    if not video_dir(candidate).exists():
        return candidate
    suffix = secrets.token_hex(2)
    return f"{candidate}_{suffix}"


def make_clip_slug(title: str, index: int) -> str:
    base = sanitize_slug_base(title)[:40] or f"clip_{index}"
    return f"{base}_{index:02d}"


def make_clip_id(parent_slug: str, clip_slug: str) -> str:
    return f"{parent_slug}{CLIP_ID_SEP}{clip_slug}"


def parse_clip_id(video_id: str) -> tuple[str, str] | None:
    if CLIP_ID_SEP not in video_id:
        return None
    parent, clip_slug = video_id.split(CLIP_ID_SEP, 1)
    if not parent or not clip_slug:
        return None
    return parent, clip_slug


def _parse_storage_parts(storage_root: str) -> tuple[str | None, str | None]:
    """Return (vod_slug, clip_slug) parsed from ``video/{vod}/clips/{clip}`` paths.

    Accepts relative roots and absolute Windows/POSIX paths that contain
    ``video/...`` somewhere in the hierarchy.
    """
    raw = (storage_root or "").replace("\\", "/")
    parts = [p for p in raw.split("/") if p]
    try:
        idx = parts.index(VIDEO_SUBDIR)
        parts = parts[idx:]
    except ValueError:
        return None, None
    if len(parts) >= 4 and parts[0] == VIDEO_SUBDIR and parts[2] == CLIPS_DIR:
        return parts[1], parts[3]
    if len(parts) >= 2 and parts[0] == VIDEO_SUBDIR:
        return parts[1], None
    return None, None


def _vod_slug_from_record(rec: video_repo.VideoRecord) -> str:
    vod, _ = _parse_storage_parts(rec.storage_root)
    return vod or rec.slug


def _clip_parts_from_record(rec: video_repo.VideoRecord) -> tuple[str, str]:
    vod, clip = _parse_storage_parts(rec.storage_root)
    if vod and clip:
        return vod, clip
    parsed = parse_clip_id(rec.slug)
    if parsed:
        return parsed
    return rec.slug, rec.slug


def _record_to_vod_meta(rec: video_repo.VideoRecord) -> VideoMetadata:
    slug = _vod_slug_from_record(rec)
    return VideoMetadata(
        slug=slug,
        title=rec.title or rec.source_filename or slug,
        kind="original",
        source_filename=rec.source_filename,
        duration=rec.duration,
        width=rec.width,
        height=rec.height,
        fps=rec.fps,
        codec=rec.codec,
        size_bytes=rec.size_bytes,
        uploaded_at=rec.uploaded_at or rec.created_at,
        webcam_region=rec.webcam_region,
        formats=list(rec.formats_available),
    )


def _record_to_clip_video_meta(rec: video_repo.VideoRecord) -> VideoMetadata:
    parent_slug, clip_slug = _clip_parts_from_record(rec)
    clip_id = make_clip_id(parent_slug, clip_slug)
    parent_rec = video_repo.resolve(parent_slug)
    uploaded = (parent_rec.uploaded_at or parent_rec.created_at) if parent_rec else rec.uploaded_at
    return VideoMetadata(
        slug=clip_id,
        title=rec.title or clip_slug,
        kind="clip",
        parent_slug=parent_slug,
        clip_slug=clip_slug,
        start=rec.start_sec or 0.0,
        end=rec.end_sec or 0.0,
        duration=rec.duration or max(0.0, (rec.end_sec or 0) - (rec.start_sec or 0)),
        formats=list(rec.formats_available),
        source_filename=rec.title,
        uploaded_at=uploaded or rec.created_at,
        webcam_region=rec.webcam_region,
    )


def _record_to_clip_meta(rec: video_repo.VideoRecord) -> ClipMetadata:
    parent_slug, clip_slug = _clip_parts_from_record(rec)
    feature = rec.source_feature or "highlight"
    return ClipMetadata(
        clip_slug=clip_slug,
        parent_slug=parent_slug,
        title=rec.title or clip_slug,
        start=rec.start_sec or 0.0,
        end=rec.end_sec or 0.0,
        formats=list(rec.formats_available),
        source_feature=feature,  # type: ignore[arg-type]
        webcam_region=rec.webcam_region,
    )


def _record_to_index(rec: video_repo.VideoRecord) -> VideoIndex:
    if rec.kind == "clip":
        parent_slug, clip_slug = _clip_parts_from_record(rec)
        clip_id = make_clip_id(parent_slug, clip_slug)
        fmt = rec.format or (rec.formats_available[0] if rec.formats_available else "youtube")
        return VideoIndex(
            id=clip_id,
            title=rec.title or clip_slug,
            kind="clip",
            duration=rec.duration or max(0.0, (rec.end_sec or 0) - (rec.start_sec or 0)),
            width=rec.width,
            height=rec.height,
            has_transcript=False,
            clip_count=0,
            parent_id=parent_slug,
            format=fmt,
            start=rec.start_sec,
            end=rec.end_sec,
            formats=list(rec.formats_available),
            uploaded_at=rec.uploaded_at or rec.created_at,
        )
    slug = _vod_slug_from_record(rec)
    return VideoIndex(
        id=slug,
        title=rec.title or rec.source_filename or slug,
        kind="original",
        duration=rec.duration,
        width=rec.width,
        height=rec.height,
        has_transcript=video_repo.has_transcript(slug),
        clip_count=video_repo.count_children(rec.id),
        format=rec.format,
        uploaded_at=rec.uploaded_at or rec.created_at,
    )


def _import_legacy_vod_json(slug: str) -> VideoMetadata | None:
    """Import metadata.json into the DB (startup backfill only)."""
    path = metadata_path(slug)
    if not path.is_file():
        return None
    meta = VideoMetadata.model_validate(json.loads(path.read_text(encoding="utf-8")))
    _register_vod_in_db(meta)
    return meta


def _import_legacy_clip_json(parent_slug: str, clip_slug: str) -> ClipMetadata | None:
    path = clip_meta_path(parent_slug, clip_slug)
    if not path.is_file():
        return None
    cm = ClipMetadata.model_validate(json.loads(path.read_text(encoding="utf-8")))
    _register_clip_in_db(parent_slug, cm)
    return cm


def load_metadata(slug: str) -> VideoMetadata | None:
    rec = video_repo.resolve(slug)
    if rec and rec.kind == "original":
        return _record_to_vod_meta(rec)
    if not parse_clip_id(slug):
        return _import_legacy_vod_json(slug)
    return None


def _vod_format(width: int, height: int) -> str | None:
    if width <= 0 or height <= 0:
        return None
    return "desktop" if width >= height else "mobile"


def _clip_format(formats: list[str]) -> str | None:
    if "youtube" in formats:
        return "desktop"
    if "reels" in formats:
        return "mobile"
    return None


def _register_vod_in_db(meta: VideoMetadata) -> None:
    """Write-through: keep the videos table in sync with a VOD's metadata.json."""
    try:
        video_repo.upsert_video(
            slug=meta.slug,
            storage_root=f"{VIDEO_SUBDIR}/{meta.slug}",
            kind="original",
            title=meta.title or meta.source_filename or meta.slug,
            fmt=_vod_format(meta.width, meta.height),
            duration=meta.duration,
            width=meta.width,
            height=meta.height,
            fps=meta.fps,
            codec=meta.codec,
            size_bytes=meta.size_bytes,
            source_filename=meta.source_filename,
            webcam_region=meta.webcam_region,
            aliases=[meta.slug],
            uploaded_at=meta.uploaded_at or None,
        )
    except Exception:
        # DB sync must never block filesystem writes.
        pass


def _register_clip_in_db(parent_slug: str, clip: ClipMetadata) -> None:
    try:
        parent = video_repo.resolve(parent_slug)
        parent_id = parent.id if parent else None
        clip_id = make_clip_id(parent_slug, clip.clip_slug)
        video_repo.upsert_video(
            slug=clip_id,
            storage_root=f"{VIDEO_SUBDIR}/{parent_slug}/{CLIPS_DIR}/{clip.clip_slug}",
            kind="clip",
            title=clip.title or clip.clip_slug,
            parent_id=parent_id,
            fmt=_clip_format(list(clip.formats)),
            formats_available=list(clip.formats),
            source_feature=clip.source_feature,
            start_sec=clip.start,
            end_sec=clip.end,
            duration=max(0.0, clip.end - clip.start),
            webcam_region=clip.webcam_region,
            aliases=[clip_id],
        )
    except Exception:
        pass


def save_metadata(meta: VideoMetadata) -> None:
    original_dir(meta.slug).mkdir(parents=True, exist_ok=True)
    video_repo.upsert_video(
        slug=meta.slug,
        storage_root=f"{VIDEO_SUBDIR}/{meta.slug}",
        kind="original",
        title=meta.title or meta.source_filename or meta.slug,
        fmt=_vod_format(meta.width, meta.height),
        duration=meta.duration,
        width=meta.width,
        height=meta.height,
        fps=meta.fps,
        codec=meta.codec,
        size_bytes=meta.size_bytes,
        source_filename=meta.source_filename,
        webcam_region=meta.webcam_region,
        aliases=[meta.slug],
        uploaded_at=meta.uploaded_at or _utc_now(),
    )


def has_transcript(slug: str) -> bool:
    return video_repo.has_transcript(slug)


def count_clips(slug: str) -> int:
    rec = video_repo.resolve(slug)
    if not rec:
        return 0
    return video_repo.count_children(rec.id)


def stream_url_for(slug: str, fmt: str | None = None) -> str:
    parsed = parse_clip_id(slug)
    if parsed:
        parent, clip_slug = parsed
        use_fmt = fmt if fmt in ("youtube", "reels") else "youtube"
        return f"/api/v2/media/{parent}/clips/{clip_slug}/{use_fmt}.mp4"
    if get_video(slug) is not None:
        return f"/api/v2/media/{slug}/source.mp4"
    if fmt in ("youtube", "reels"):
        meta = load_metadata(slug)
        if meta and meta.parent_slug and meta.clip_slug:
            return f"/api/v2/media/{meta.parent_slug}/clips/{meta.clip_slug}/{fmt}.mp4"
    return f"/api/v2/media/{slug}/source.mp4"


def to_index(meta: VideoMetadata) -> VideoIndex:
    original_slug = meta.parent_slug if meta.kind == "clip" and meta.parent_slug else meta.slug
    return VideoIndex(
        id=meta.slug,
        title=meta.title or meta.source_filename or meta.slug,
        kind=meta.kind,
        duration=meta.duration,
        width=meta.width,
        height=meta.height,
        has_transcript=has_transcript(original_slug),
        clip_count=count_clips(original_slug) if meta.kind == "original" else 0,
        parent_id=meta.parent_slug,
        format=meta.formats[0] if meta.formats else None,
        uploaded_at=meta.uploaded_at,
    )


def list_original_videos() -> list[VideoIndex]:
    items: list[VideoIndex] = []
    for rec in video_repo.list_videos(kind="original"):
        slug = _vod_slug_from_record(rec)
        if not source_path(slug).is_file():
            continue
        items.append(_record_to_index(rec))
    items.sort(key=lambda x: x.uploaded_at, reverse=True)
    return items


def list_all_videos(offset: int = 0, limit: int = 24) -> tuple[list[VideoIndex], int]:
    all_items = list_original_videos()
    total = len(all_items)
    return all_items[offset : offset + limit], total


def _text_matches(text: str, query: str) -> bool:
    return query in text.lower()


def search_videos(query: str, limit: int = 24) -> list[VideoIndex]:
    q = query.strip().lower()
    if not q:
        return []
    results: list[VideoIndex] = []
    seen: set[str] = set()
    for rec in video_repo.search_records(q, limit=limit * 2):
        if rec.kind == "original":
            slug = _vod_slug_from_record(rec)
            if not source_path(slug).is_file():
                continue
            idx = _record_to_index(rec)
        else:
            parent_slug, clip_slug = _clip_parts_from_record(rec)
            if not clip_dir(parent_slug, clip_slug).is_dir():
                continue
            idx = _record_to_index(rec)
        if idx.id in seen:
            continue
        seen.add(idx.id)
        results.append(idx)
        if len(results) >= limit:
            break
    return results


def list_recent_clips(limit: int = 12) -> list[VideoIndex]:
    clips: list[VideoIndex] = []
    for rec in video_repo.list_videos(kind="clip"):
        parent_slug, clip_slug = _clip_parts_from_record(rec)
        clip_path = clip_dir(parent_slug, clip_slug)
        if not clip_path.is_dir():
            continue
        parent_rec = video_repo.resolve(parent_slug)
        uploaded_at = (parent_rec.uploaded_at or parent_rec.created_at) if parent_rec else rec.uploaded_at
        formats = list(rec.formats_available) or ["youtube"]
        duration = rec.duration or max(0.0, (rec.end_sec or 0) - (rec.start_sec or 0))
        clip_id = make_clip_id(parent_slug, clip_slug)
        for fmt in formats:
            if not (clip_path / f"{fmt}.mp4").is_file():
                continue
            clips.append(
                VideoIndex(
                    id=clip_id,
                    title=rec.title or clip_slug,
                    kind="clip",
                    duration=duration,
                    width=rec.width,
                    height=rec.height,
                    has_transcript=False,
                    clip_count=0,
                    parent_id=parent_slug,
                    format=fmt,
                    formats=formats,
                    uploaded_at=uploaded_at or rec.created_at,
                )
            )
    clips.sort(key=lambda c: (c.uploaded_at, c.id, c.format or ""), reverse=True)
    return clips[:limit]


def get_video(slug: str) -> VideoMetadata | None:
    if parse_clip_id(slug):
        return None
    rec = video_repo.resolve(slug)
    if rec and rec.kind == "original":
        vod_slug = _vod_slug_from_record(rec)
        if not source_path(vod_slug).is_file():
            return None
        return _record_to_vod_meta(rec)
    legacy = _import_legacy_vod_json(slug)
    if legacy and source_path(slug).is_file():
        return legacy
    return None


def _to_storage_id(video_id: str) -> str:
    """Map a UUID, renamed slug, or legacy alias to the on-disk identifier.

    Falls back to the input unchanged when the id is not registered (e.g. a slug
    or composite ``parent::clip`` that predates the DB backfill).
    """
    try:
        rec = video_repo.resolve(video_id)
    except Exception:
        return video_id
    if rec is None:
        return video_id
    if rec.kind == "clip":
        vod, clip = _parse_storage_parts(rec.storage_root)
        if vod and clip:
            return make_clip_id(vod, clip)
        return rec.slug or video_id
    return _vod_slug_from_record(rec)


def resolve_video_id(video_id: str) -> VideoMetadata:
    """Resolve UUID, slug, legacy alias, or composite clip id parent::clip_slug."""
    storage_id = _to_storage_id(video_id)
    rec = video_repo.resolve(storage_id)
    if rec:
        if rec.kind == "original":
            vod_slug = _vod_slug_from_record(rec)
            if not source_path(vod_slug).is_file():
                raise FileNotFoundError(f"Video not found: {video_id}")
            return _record_to_vod_meta(rec)
        return _record_to_clip_video_meta(rec)
    parsed = parse_clip_id(storage_id)
    if parsed:
        parent, clip_slug = parsed
        cm = load_clip_metadata(parent, clip_slug)
        if cm is None:
            raise FileNotFoundError(f"Clip not found: {video_id}")
        parent_rec = video_repo.resolve(parent)
        uploaded = (parent_rec.uploaded_at or parent_rec.created_at) if parent_rec else ""
        return VideoMetadata(
            slug=storage_id,
            title=cm.title or clip_slug,
            kind="clip",
            parent_slug=parent,
            clip_slug=clip_slug,
            start=cm.start,
            end=cm.end,
            duration=max(0.0, cm.end - cm.start),
            formats=cm.formats,
            source_filename=cm.title,
            uploaded_at=uploaded,
            webcam_region=cm.webcam_region,
        )
    raise FileNotFoundError(f"Video not found: {video_id}")


def related_videos(video_id: str) -> list[VideoIndex]:
    meta = resolve_video_id(video_id)
    if meta.kind == "original":
        rec = video_repo.resolve(meta.slug)
        if not rec:
            return []
        children = video_repo.children(rec.id)
        children.sort(key=lambda c: c.start_sec or 0)
        return [_record_to_index(child) for child in children]
    if meta.parent_slug:
        parent = get_video(meta.parent_slug)
        if parent:
            return [to_index(parent)]
    return []


def gallery_tree() -> list[dict]:
    tree: list[dict] = []
    for orig in list_original_videos():
        rec = video_repo.resolve(orig.id)
        clips: list[dict] = []
        if rec:
            for child in video_repo.children(rec.id):
                parent_slug, clip_slug = _clip_parts_from_record(child)
                clip_id = make_clip_id(parent_slug, clip_slug)
                formats = list(child.formats_available)
                urls: dict[str, str] = {}
                base = clip_dir(parent_slug, clip_slug)
                for fmt in formats:
                    if (base / f"{fmt}.mp4").is_file():
                        urls[fmt] = stream_url_for(clip_id, fmt)
                clips.append(
                    {
                        "id": clip_id,
                        "clip_slug": clip_slug,
                        "title": child.title or clip_slug,
                        "formats": formats,
                        "stream_urls": urls,
                    }
                )
        tree.append(
            {
                "id": orig.id,
                "title": orig.title,
                "kind": "original",
                "stream_url": stream_url_for(orig.id),
                "clip_count": len(clips),
                "clips": clips,
            }
        )
    return tree


def create_original_from_path(
    src: Path,
    *,
    title: str | None = None,
    slug: str | None = None,
) -> VideoMetadata:
    if not src.is_file():
        raise FileNotFoundError(str(src))
    base_slug = slug or make_unique_slug(src.name)
    dest = source_path(base_slug)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.resolve() != dest.resolve():
        shutil.copy2(src, dest)
    info = probe_video(dest)
    meta = VideoMetadata(
        slug=base_slug,
        title=title or Path(src.name).stem,
        kind="original",
        source_filename=Path(src.name).name,
        duration=info.duration,
        width=info.width,
        height=info.height,
        fps=info.fps,
        codec=info.codec,
        size_bytes=info.size_bytes,
        uploaded_at=_utc_now(),
    )
    save_metadata(meta)
    return meta


async def stream_upload_to_video(file_obj, filename: str) -> tuple[VideoMetadata, int]:
    """Write upload stream to temp/video/{slug}/original/source.mp4."""
    slug = make_unique_slug(filename)
    dest = source_path(slug)
    dest.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with dest.open("wb") as out:
        while True:
            chunk = await file_obj.read(CHUNK_SIZE)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                delete_path(video_dir(slug))
                raise ValueError(
                    f"File exceeds maximum upload size ({MAX_UPLOAD_BYTES // (1024**3)} GB)"
                )
            out.write(chunk)
    info = probe_video(dest)
    meta = VideoMetadata(
        slug=slug,
        title=Path(filename).stem,
        kind="original",
        source_filename=Path(filename).name,
        duration=info.duration,
        width=info.width,
        height=info.height,
        fps=info.fps,
        codec=info.codec,
        size_bytes=info.size_bytes,
        uploaded_at=_utc_now(),
    )
    save_metadata(meta)
    return meta, total


def save_clip_metadata(parent_slug: str, clip: ClipMetadata) -> Path:
    d = clip_dir(parent_slug, clip.clip_slug)
    d.mkdir(parents=True, exist_ok=True)
    parent = video_repo.resolve(parent_slug)
    clip_id = make_clip_id(parent_slug, clip.clip_slug)
    video_repo.upsert_video(
        slug=clip_id,
        storage_root=f"{VIDEO_SUBDIR}/{parent_slug}/{CLIPS_DIR}/{clip.clip_slug}",
        kind="clip",
        title=clip.title or clip.clip_slug,
        parent_id=parent.id if parent else None,
        fmt=_clip_format(list(clip.formats)),
        formats_available=list(clip.formats),
        source_feature=clip.source_feature,
        start_sec=clip.start,
        end_sec=clip.end,
        duration=max(0.0, clip.end - clip.start),
        webcam_region=clip.webcam_region,
        aliases=[clip_id],
    )
    return d


def load_clip_metadata(parent_slug: str, clip_slug: str) -> ClipMetadata | None:
    clip_id = make_clip_id(parent_slug, clip_slug)
    rec = video_repo.resolve(clip_id)
    if rec and rec.kind == "clip":
        return _record_to_clip_meta(rec)
    return _import_legacy_clip_json(parent_slug, clip_slug)


def _even_dim(n: int) -> int:
    return max(2, n - (n % 2))


def validate_webcam_region(
    region: WebcamRegion,
    *,
    width: int,
    height: int,
) -> WebcamRegion:
    if width <= 0 or height <= 0:
        raise ValueError("Invalid source dimensions")
    min_size = 8
    x1 = max(0, min(int(round(region.x1)), width - min_size))
    y1 = max(0, min(int(round(region.y1)), height - min_size))
    x2 = max(x1 + min_size, min(int(round(region.x2)), width))
    y2 = max(y1 + min_size, min(int(round(region.y2)), height))
    x1 = x1 - (x1 % 2)
    y1 = y1 - (y1 % 2)
    x2 = x2 - (x2 % 2)
    y2 = y2 - (y2 % 2)
    if x2 <= x1:
        x2 = min(width, x1 + min_size)
        if x2 % 2:
            x2 -= 1
    if y2 <= y1:
        y2 = min(height, y1 + min_size)
        if y2 % 2:
            y2 -= 1
    if x2 > width:
        x2 = width - (width % 2)
    if y2 > height:
        y2 = height - (height % 2)
    if x2 <= x1 or y2 <= y1:
        raise ValueError("Region is too small for this frame")
    cw, ch = x2 - x1, y2 - y1
    if cw < min_size or ch < min_size:
        raise ValueError("Region is too small")
    return WebcamRegion(
        x1=x1,
        y1=y1,
        x2=x2,
        y2=y2,
        source_width=width,
        source_height=height,
        frame_at=max(0.0, region.frame_at),
    )


def desktop_frame_path(video_id: str) -> Path:
    """Path to the desktop-format mp4 used for webcam ROI (source or youtube clip)."""
    meta = resolve_video_id(video_id)
    if meta.kind == "clip" and meta.parent_slug and meta.clip_slug:
        yt = clip_dir(meta.parent_slug, meta.clip_slug) / "youtube.mp4"
        if yt.is_file():
            return yt
        raise FileNotFoundError("Clip has no desktop (youtube) format")
    path = source_path(meta.slug)
    if not path.is_file():
        raise FileNotFoundError("Source video not found")
    return path


def is_webcam_eligible(video_id: str) -> bool:
    try:
        meta = resolve_video_id(video_id)
    except FileNotFoundError:
        return False
    if meta.kind == "original":
        if meta.width > 0 and meta.height > 0:
            return meta.width >= meta.height
        path = source_path(meta.slug)
        if not path.is_file():
            return False
        info = probe_video(path)
        return info.width >= info.height
    if meta.kind == "clip" and meta.parent_slug and meta.clip_slug:
        formats = list(meta.formats or [])
        if "youtube" not in formats:
            cm = load_clip_metadata(meta.parent_slug, meta.clip_slug)
            if cm:
                formats = list(cm.formats or [])
        return "youtube" in formats and (clip_dir(meta.parent_slug, meta.clip_slug) / "youtube.mp4").is_file()
    return False


def resolve_webcam_region(video_id: str) -> WebcamRegion | None:
    """Return webcam bbox for this video, falling back to parent VOD for clips."""
    own = get_own_webcam_region(video_id)
    if own:
        return own
    try:
        meta = resolve_video_id(video_id)
    except FileNotFoundError:
        return None
    if meta.kind == "clip" and meta.parent_slug:
        parent = load_metadata(meta.parent_slug)
        if parent and parent.webcam_region:
            return parent.webcam_region
    return None


def save_webcam_region(video_id: str, region: WebcamRegion) -> WebcamRegion:
    meta = resolve_video_id(video_id)
    frame = desktop_frame_path(video_id)
    info = probe_video(frame)
    validated = validate_webcam_region(region, width=info.width, height=info.height)
    if meta.kind == "clip" and meta.parent_slug and meta.clip_slug:
        cm = load_clip_metadata(meta.parent_slug, meta.clip_slug)
        if cm is None:
            raise FileNotFoundError("Clip metadata not found")
        cm.webcam_region = validated
        save_clip_metadata(meta.parent_slug, cm)
        return validated
    if meta.kind != "original":
        raise ValueError("Cannot save webcam region for this video type")
    parent = load_metadata(meta.slug)
    if parent is None:
        raise FileNotFoundError("Video metadata not found")
    parent.webcam_region = validated
    save_metadata(parent)
    return validated


def clear_webcam_region(video_id: str) -> None:
    meta = resolve_video_id(video_id)
    if meta.kind == "clip" and meta.parent_slug and meta.clip_slug:
        cm = load_clip_metadata(meta.parent_slug, meta.clip_slug)
        if cm is None:
            return
        cm.webcam_region = None
        save_clip_metadata(meta.parent_slug, cm)
        return
    if meta.kind != "original":
        return
    parent = load_metadata(meta.slug)
    if parent is None:
        return
    parent.webcam_region = None
    save_metadata(parent)


def get_own_webcam_region(video_id: str) -> WebcamRegion | None:
    """Region stored on this video only (no parent fallback)."""
    try:
        meta = resolve_video_id(video_id)
    except FileNotFoundError:
        return None
    if meta.kind == "clip" and meta.parent_slug and meta.clip_slug:
        cm = load_clip_metadata(meta.parent_slug, meta.clip_slug)
        return cm.webcam_region if cm else None
    if meta.kind == "original":
        parent = load_metadata(meta.slug)
        return parent.webcam_region if parent else None
    return None


def make_derivative_clip_slug(parent_slug: str, prefix: str) -> str:
    root = clips_root(parent_slug)
    n = 1
    while True:
        slug = f"{prefix}_{n:02d}"
        if not (root / slug).is_dir():
            return slug
        n += 1


def make_derived_clip_slug(parent_slug: str, base_clip_slug: str | None, suffix: str) -> str:
    """Unique clip folder like clip_04_skip_silence or skip_silence_02 for VOD-level derivatives."""
    root_name = f"{base_clip_slug}_{suffix}" if base_clip_slug else suffix
    root = clips_root(parent_slug)
    if not (root / root_name).is_dir():
        return root_name
    n = 2
    while True:
        candidate = f"{root_name}_{n:02d}"
        if not (root / candidate).is_dir():
            return candidate
        n += 1


def clip_source_path(parent_slug: str, clip_slug: str, fmt: str = "youtube") -> Path:
    return clip_dir(parent_slug, clip_slug) / f"{fmt}.mp4"


def clip_stream_urls(parent_slug: str, clip_slug: str, formats: list[str]) -> dict[str, str]:
    urls: dict[str, str] = {}
    clip_id = make_clip_id(parent_slug, clip_slug)
    base = clip_dir(parent_slug, clip_slug)
    for fmt in formats:
        if (base / f"{fmt}.mp4").is_file():
            urls[fmt] = stream_url_for(clip_id, fmt)
    return urls


def register_clip_from_files(
    parent_slug: str,
    *,
    title: str,
    start: float,
    end: float,
    source_feature: str,
    files: dict[str, Path],
    clip_slug: str | None = None,
) -> tuple[ClipMetadata, str]:
    """Copy rendered mp4 files into clips/ and write meta.json. Returns metadata and composite id."""
    slug = clip_slug or make_derivative_clip_slug(parent_slug, source_feature[:7])
    dest_dir = clip_dir(parent_slug, slug)
    dest_dir.mkdir(parents=True, exist_ok=True)
    formats: list[str] = []
    for fmt, src in files.items():
        if not src.is_file():
            continue
        dest = dest_dir / f"{fmt}.mp4"
        shutil.copy2(src, dest)
        formats.append(fmt)
    if not formats:
        raise ValueError("No output files to register as clip")
    clip = ClipMetadata(
        clip_slug=slug,
        parent_slug=parent_slug,
        title=title,
        start=start,
        end=end,
        formats=formats,
        source_feature=source_feature,  # type: ignore[arg-type]
    )
    save_clip_metadata(parent_slug, clip)
    return clip, make_clip_id(parent_slug, slug)


def register_trim_as_vod(
    src: Path,
    *,
    title: str,
    slug_base: str | None = None,
) -> tuple[VideoMetadata, str]:
    """Copy trimmed output into a new standalone VOD (not a nested clip)."""
    slug = make_unique_slug(slug_base or f"{src.stem}_recorte")
    meta = create_original_from_path(src, title=title, slug=slug)
    return meta, meta.slug


def replace_original_vod_source(slug: str, src: Path) -> VideoMetadata:
    """Overwrite an existing VOD source file and refresh metadata."""
    if not src.is_file():
        raise FileNotFoundError(str(src))
    meta = load_metadata(slug)
    if meta is None or meta.kind != "original":
        raise ValueError(f"Not an original VOD: {slug}")
    dest = source_path(slug)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    info = probe_video(dest)
    meta.duration = info.duration
    meta.width = info.width
    meta.height = info.height
    meta.fps = info.fps
    meta.codec = info.codec
    meta.size_bytes = info.size_bytes
    save_metadata(meta)
    for path in (segments_path(slug), segments_original_path(slug), audio_path(slug)):
        if path.is_file():
            path.unlink()
    return meta


def replace_clip_source(
    parent_slug: str,
    clip_slug: str,
    fmt: str,
    src: Path,
) -> tuple[ClipMetadata, str]:
    """Overwrite a clip format file and refresh clip metadata."""
    if not src.is_file():
        raise FileNotFoundError(str(src))
    clip = load_clip_metadata(parent_slug, clip_slug)
    if clip is None:
        raise ValueError(f"Clip not found: {parent_slug}/{clip_slug}")
    dest = clip_dir(parent_slug, clip_slug) / f"{fmt}.mp4"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    info = probe_video(dest)
    clip.end = clip.start + info.duration
    if fmt not in clip.formats:
        clip.formats = [*clip.formats, fmt]
    save_clip_metadata(parent_slug, clip)
    return clip, make_clip_id(parent_slug, clip_slug)


def delete_video(slug: str) -> int:
    """Remove a VOD's files, then its database row.

    The row is removed only after the folder is gone, including when the folder
    was already deleted by hand. Raises OSError if any file is still on disk.
    """
    rec = video_repo.resolve(slug)
    storage_slug = _vod_slug_from_record(rec) if rec and rec.kind == "original" else slug
    target = video_dir(storage_slug)
    freed = _delete_tree(target)
    if rec is not None:
        freed += _purge_record_tree(rec, keep_under=target)
    return freed


def delete_clip(parent_slug: str, clip_slug: str) -> int:
    """Remove a clip's files, then its database row.

    A clip whose folder is already gone still drops the database row.
    Raises OSError if the clip folder is still on disk.
    """
    clip_id = make_clip_id(parent_slug, clip_slug)
    rec = video_repo.resolve(clip_id)
    target = clip_dir(parent_slug, clip_slug)
    freed = _delete_tree(target)
    if rec is not None:
        freed += _purge_external_job_outputs(rec.id, keep_under=target)
        video_repo.delete_video(rec.id)
    return freed


def _delete_tree(target: Path) -> int:
    if not target.exists():
        return 0
    freed = delete_path(target)
    if target.exists():
        raise OSError(f"Files still present: {target}")
    return freed


def _purge_record_tree(rec: video_repo.VideoRecord, *, keep_under: Path) -> int:
    """Delete external job outputs for a video and its clips, then the DB rows."""
    freed = 0
    ids = [rec.id]
    if rec.kind == "original":
        ids.extend(child.id for child in video_repo.children(rec.id))
    for video_id in ids:
        freed += _purge_external_job_outputs(video_id, keep_under=keep_under)
    video_repo.delete_video(rec.id)
    return freed


def _purge_external_job_outputs(video_id: str, *, keep_under: Path | None = None) -> int:
    """Delete job folders that live outside the video tree, then the job rows.

    Outputs inside ``keep_under`` are skipped: that tree is removed separately.
    Paths outside the project temp directory are left alone.
    """
    from reels import job_store

    freed = 0
    root = temp_root().resolve()
    keep = keep_under.resolve() if keep_under is not None else None
    for raw in job_store.output_dirs_for_video(video_id):
        try:
            resolved = Path(raw).resolve()
        except OSError:
            continue
        try:
            if not resolved.is_relative_to(root):
                continue
            if keep is not None and (resolved == keep or resolved.is_relative_to(keep)):
                continue
        except ValueError:
            continue
        if resolved.exists():
            freed += delete_path(resolved)
    job_store.delete_jobs_for_video(video_id)
    return freed


def prune_missing_videos() -> int:
    """Drop database rows whose storage folder is already gone.

    Manual deletes and a failed file removal used to leave rows behind. Rows
    whose folder still exists are kept, even if ``source.mp4`` is missing
    (a download may still be writing it).
    """
    removed = 0
    for rec in list(video_repo.list_videos()):
        if rec.kind == "clip":
            parent_slug, clip_slug = _clip_parts_from_record(rec)
            try:
                folder = clip_dir(parent_slug, clip_slug)
            except ValueError:
                folder = None
            if folder is not None and folder.is_dir():
                continue
            if video_repo.resolve(rec.id) is None:
                continue
            if folder is not None:
                _purge_external_job_outputs(rec.id, keep_under=folder)
            video_repo.delete_video(rec.id)
            removed += 1
            continue

        slug = _vod_slug_from_record(rec)
        try:
            folder = video_dir(slug)
        except ValueError:
            folder = None
        if folder is not None and folder.is_dir():
            continue
        if video_repo.resolve(rec.id) is None:
            continue
        _purge_record_tree(rec, keep_under=folder or videos_root())
        removed += 1
    return removed


def _sync_transcript_from_files(slug: str) -> None:
    """Backfill a VOD's transcript into the DB from its segments.json, if present."""
    seg_path = segments_path(slug)
    if not seg_path.is_file():
        return
    try:
        segments = json.loads(seg_path.read_text(encoding="utf-8"))
        original: list = []
        orig_path = segments_original_path(slug)
        if orig_path.is_file():
            original = json.loads(orig_path.read_text(encoding="utf-8"))
        video_repo.save_transcript(slug, segments, original)
    except Exception:
        pass


def _recover_orphan_clips(parent_slug: str) -> tuple[int, int, int]:
    """Register or remove clip dirs that lack meta.json / DB rows.

    Returns (clips_touched, orphans_recovered, orphans_removed).
    """
    known_formats = ("youtube", "reels")
    clips = 0
    recovered = 0
    removed = 0
    clip_root = clips_root(parent_slug)
    if not clip_root.is_dir():
        return 0, 0, 0
    for clip_path in clip_root.iterdir():
        if not clip_path.is_dir():
            continue
        cm_path = clip_path / "meta.json"
        if cm_path.is_file():
            try:
                cm = ClipMetadata.model_validate(json.loads(cm_path.read_text(encoding="utf-8")))
            except Exception:
                continue
            _register_clip_in_db(parent_slug, cm)
            clips += 1
            continue

        formats = [fmt for fmt in known_formats if (clip_path / f"{fmt}.mp4").is_file()]
        if not formats:
            delete_path(clip_path)
            removed += 1
            continue

        clip_id = make_clip_id(parent_slug, clip_path.name)
        if video_repo.resolve(clip_id):
            clips += 1
            continue

        primary = "youtube" if "youtube" in formats else formats[0]
        try:
            info = probe_video(clip_path / f"{primary}.mp4")
            title = re.sub(r"_+", " ", clip_path.name).strip() or clip_path.name
            cm = ClipMetadata(
                clip_slug=clip_path.name,
                parent_slug=parent_slug,
                title=title,
                start=0.0,
                end=float(info.duration or 0.0),
                formats=list(formats),
                source_feature="manual_clip",
            )
            save_clip_metadata(parent_slug, cm)
            clips += 1
            recovered += 1
        except Exception:
            delete_path(clip_path)
            removed += 1
    return clips, recovered, removed


def sync_from_filesystem() -> dict[str, int]:
    """Backfill the videos table from existing temp/video/{slug}/ folders.

    Idempotent: upserts one row per VOD and per clip. Reads legacy JSON only here.
    Clip folders with mp4 files but no meta.json / DB row are recovered (or removed if empty).
    """
    vods = 0
    clips = 0
    orphans_recovered = 0
    orphans_removed = 0
    orphans_pruned = prune_missing_videos()
    synced_slugs: set[str] = set()
    root = videos_root()
    if not root.is_dir():
        return {
            "vods": 0,
            "clips": 0,
            "orphans_recovered": 0,
            "orphans_removed": 0,
            "orphans_pruned": prune_missing_videos(),
        }

    # Pass 1: legacy metadata.json VODs.
    for path in root.iterdir():
        if not path.is_dir():
            continue
        meta_path = metadata_path(path.name)
        if not meta_path.is_file():
            continue
        try:
            meta = VideoMetadata.model_validate(json.loads(meta_path.read_text(encoding="utf-8")))
        except Exception:
            continue
        if meta.kind != "original":
            continue
        if not source_path(path.name).is_file():
            continue
        _register_vod_in_db(meta)
        _sync_transcript_from_files(path.name)
        vods += 1
        synced_slugs.add(path.name)
        c, rec, rem = _recover_orphan_clips(path.name)
        clips += c
        orphans_recovered += rec
        orphans_removed += rem

    # Pass 2: DB-registered VODs (and source.mp4 folders) that lack metadata.json.
    for rec in video_repo.list_videos(kind="original"):
        slug = _vod_slug_from_record(rec)
        if slug in synced_slugs:
            continue
        if not source_path(slug).is_file():
            continue
        synced_slugs.add(slug)
        vods += 1
        c, rec_n, rem = _recover_orphan_clips(slug)
        clips += c
        orphans_recovered += rec_n
        orphans_removed += rem

    return {
        "vods": vods,
        "clips": clips,
        "orphans_recovered": orphans_recovered,
        "orphans_removed": orphans_removed,
        "orphans_pruned": orphans_pruned,
    }


def twitch_slug(video_id: str) -> str:
    return f"twitch_{video_id}"


def vod_path_for_twitch(video_id: str) -> Path:
    slug = twitch_slug(video_id)
    return source_path(slug)


def ensure_metadata(slug: str, path: Path, *, title: str | None = None) -> VideoMetadata:
    """Probe and write metadata.json if missing (file already at path)."""
    existing = load_metadata(slug)
    if existing is not None:
        return existing
    info = probe_video(path)
    meta = VideoMetadata(
        slug=slug,
        title=title or slug,
        kind="original",
        source_filename=path.name,
        duration=info.duration,
        width=info.width,
        height=info.height,
        fps=info.fps,
        codec=info.codec,
        size_bytes=info.size_bytes,
        uploaded_at=_utc_now(),
    )
    save_metadata(meta)
    return meta

