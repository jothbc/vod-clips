"""Per-video storage under temp/video/{slug}/."""

from __future__ import annotations

import json
import re
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path

from reels.models import ClipMetadata, VideoIndex, VideoKind, VideoMetadata
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
    parent_candidate = base
    # clip slugs are unique per parent; caller passes parent_slug when checking
    return f"{base}_{index:02d}"


def load_metadata(slug: str) -> VideoMetadata | None:
    path = metadata_path(slug)
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return VideoMetadata.model_validate(data)


def save_metadata(meta: VideoMetadata) -> None:
    d = original_dir(meta.slug)
    d.mkdir(parents=True, exist_ok=True)
    metadata_path(meta.slug).write_text(
        meta.model_dump_json(indent=2),
        encoding="utf-8",
    )


def has_transcript(slug: str) -> bool:
    return segments_path(slug).is_file()


def count_clips(slug: str) -> int:
    root = clips_root(slug)
    if not root.is_dir():
        return 0
    return sum(1 for p in root.iterdir() if p.is_dir() and (p / "meta.json").is_file())


def make_clip_id(parent_slug: str, clip_slug: str) -> str:
    return f"{parent_slug}{CLIP_ID_SEP}{clip_slug}"


def parse_clip_id(video_id: str) -> tuple[str, str] | None:
    if CLIP_ID_SEP not in video_id:
        return None
    parent, clip_slug = video_id.split(CLIP_ID_SEP, 1)
    if not parent or not clip_slug:
        return None
    return parent, clip_slug


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
    root = videos_root()
    if not root.is_dir():
        return items
    for path in root.iterdir():
        if not path.is_dir():
            continue
        meta = load_metadata(path.name)
        if meta is None or meta.kind != "original":
            continue
        if not source_path(path.name).is_file():
            continue
        items.append(to_index(meta))
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

    for orig in list_original_videos():
        if _text_matches(orig.title, q) or _text_matches(orig.id, q):
            if orig.id not in seen:
                results.append(orig)
                seen.add(orig.id)

        clip_root = clips_root(orig.id)
        if not clip_root.is_dir():
            continue
        for clip_path in sorted(clip_root.iterdir()):
            if not clip_path.is_dir():
                continue
            cm_path = clip_path / "meta.json"
            if not cm_path.is_file():
                continue
            cm = ClipMetadata.model_validate(json.loads(cm_path.read_text(encoding="utf-8")))
            clip_id = make_clip_id(orig.id, cm.clip_slug)
            title = cm.title or cm.clip_slug
            if not (
                _text_matches(title, q)
                or _text_matches(cm.clip_slug, q)
                or _text_matches(clip_id, q)
                or _text_matches(orig.id, q)
            ):
                continue
            if clip_id in seen:
                continue
            fmt = cm.formats[0] if cm.formats else "youtube"
            results.append(
                VideoIndex(
                    id=clip_id,
                    title=title,
                    kind="clip",
                    duration=max(0.0, cm.end - cm.start),
                    width=0,
                    height=0,
                    has_transcript=False,
                    clip_count=0,
                    parent_id=orig.id,
                    format=fmt,
                    start=cm.start,
                    end=cm.end,
                    formats=list(cm.formats),
                    uploaded_at=orig.uploaded_at,
                )
            )
            seen.add(clip_id)

    return results[:limit]


def list_recent_clips(limit: int = 12) -> list[VideoIndex]:
    clips: list[VideoIndex] = []
    for orig in list_original_videos():
        meta = load_metadata(orig.id)
        if meta is None:
            continue
        clip_root = clips_root(orig.id)
        if not clip_root.is_dir():
            continue
        for clip_path in sorted(clip_root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if not clip_path.is_dir():
                continue
            cm_path = clip_path / "meta.json"
            if not cm_path.is_file():
                continue
            cm = ClipMetadata.model_validate(json.loads(cm_path.read_text(encoding="utf-8")))
            clip_id = make_clip_id(orig.id, cm.clip_slug)
            duration = max(0.0, cm.end - cm.start)
            for fmt in cm.formats or ["youtube"]:
                if not (clip_path / f"{fmt}.mp4").is_file():
                    continue
                clips.append(
                    VideoIndex(
                        id=clip_id,
                        title=cm.title or cm.clip_slug,
                        kind="clip",
                        duration=duration,
                        width=0,
                        height=0,
                        has_transcript=False,
                        clip_count=0,
                        parent_id=orig.id,
                        format=fmt,
                        formats=list(cm.formats),
                        uploaded_at=meta.uploaded_at,
                    )
                )
    clips.sort(key=lambda c: (c.uploaded_at, c.id, c.format or ""), reverse=True)
    return clips[:limit]


def get_video(slug: str) -> VideoMetadata | None:
    if parse_clip_id(slug):
        return None
    meta = load_metadata(slug)
    if meta is None:
        return None
    if meta.kind == "clip" and meta.parent_slug:
        if not clip_dir(meta.parent_slug, meta.clip_slug or slug).exists():
            return None
    elif not source_path(slug).is_file():
        return None
    return meta


def resolve_video_id(video_id: str) -> VideoMetadata:
    """Resolve slug or composite clip id parent::clip_slug."""
    meta = get_video(video_id)
    if meta is not None:
        return meta
    parsed = parse_clip_id(video_id)
    if parsed:
        parent, clip_slug = parsed
        cm_path = clip_meta_path(parent, clip_slug)
        if not cm_path.is_file():
            raise FileNotFoundError(f"Clip not found: {video_id}")
        cm = ClipMetadata.model_validate(json.loads(cm_path.read_text(encoding="utf-8")))
        parent_meta = load_metadata(parent)
        if parent_meta is None:
            raise FileNotFoundError(f"Parent not found: {parent}")
        return VideoMetadata(
            slug=video_id,
            title=cm.title or clip_slug,
            kind="clip",
            parent_slug=parent,
            clip_slug=clip_slug,
            start=cm.start,
            end=cm.end,
            duration=max(0.0, cm.end - cm.start),
            formats=cm.formats,
            source_filename=cm.title,
            uploaded_at=parent_meta.uploaded_at,
        )
    raise FileNotFoundError(f"Video not found: {video_id}")


def related_videos(video_id: str) -> list[VideoIndex]:
    meta = resolve_video_id(video_id)
    if meta.kind == "original":
        clip_root = clips_root(meta.slug)
        clip_entries: list[tuple[ClipMetadata, VideoIndex]] = []
        if clip_root.is_dir():
            for clip_path in clip_root.iterdir():
                if not clip_path.is_dir():
                    continue
                cm_path = clip_path / "meta.json"
                if not cm_path.is_file():
                    continue
                cm = ClipMetadata.model_validate(json.loads(cm_path.read_text(encoding="utf-8")))
                clip_id = make_clip_id(meta.slug, cm.clip_slug)
                fmt = cm.formats[0] if cm.formats else "youtube"
                clip_entries.append(
                    (
                        cm,
                        VideoIndex(
                            id=clip_id,
                            title=cm.title or cm.clip_slug,
                            kind="clip",
                            duration=max(0.0, cm.end - cm.start),
                            width=0,
                            height=0,
                            has_transcript=False,
                            clip_count=0,
                            parent_id=meta.slug,
                            format=fmt,
                            start=cm.start,
                            end=cm.end,
                            formats=list(cm.formats),
                        ),
                    )
                )
        clip_entries.sort(key=lambda pair: pair[0].start)
        return [idx for _, idx in clip_entries]
    if meta.parent_slug:
        parent = get_video(meta.parent_slug)
        if parent:
            return [to_index(parent)]
    return []


def gallery_tree() -> list[dict]:
    tree: list[dict] = []
    for orig in list_original_videos():
        clips: list[dict] = []
        clip_root = clips_root(orig.id)
        if clip_root.is_dir():
            for clip_path in sorted(clip_root.iterdir()):
                if not clip_path.is_dir():
                    continue
                cm_path = clip_path / "meta.json"
                if not cm_path.is_file():
                    continue
                cm = ClipMetadata.model_validate(json.loads(cm_path.read_text(encoding="utf-8")))
                clip_id = make_clip_id(orig.id, cm.clip_slug)
                urls: dict[str, str] = {}
                for fmt in cm.formats:
                    p = clip_path / f"{fmt}.mp4"
                    if p.is_file():
                        urls[fmt] = stream_url_for(clip_id, fmt)
                clips.append(
                    {
                        "id": clip_id,
                        "clip_slug": cm.clip_slug,
                        "title": cm.title or cm.clip_slug,
                        "formats": cm.formats,
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
    path = d / "meta.json"
    path.write_text(clip.model_dump_json(indent=2), encoding="utf-8")
    return d


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
    meta_path = clip_meta_path(parent_slug, clip_slug)
    if not meta_path.is_file():
        raise ValueError(f"Clip not found: {parent_slug}/{clip_slug}")
    clip = ClipMetadata.model_validate(json.loads(meta_path.read_text(encoding="utf-8")))
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
    return delete_path(video_dir(slug))


def delete_clip(parent_slug: str, clip_slug: str) -> int:
    return delete_path(clip_dir(parent_slug, clip_slug))


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

