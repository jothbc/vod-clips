"""REST API v2 — video-centric storage and actions."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from reels.caption_fonts import list_caption_fonts
from reels.cleanup import load_edl
from reels.config import load_config
from reels.export_resolution import default_reels_size, default_youtube_size, reels_presets, youtube_presets
from reels.highlights import load_highlights
from reels.jobs import CreateJobRequest, RenderJobBody, get_job_manager
from reels.probe import probe_video
from reels.system_status import collect_system_status
from reels.video_store import (
    CLIP_ID_SEP,
    analysis_dir,
    clear_webcam_region,
    clip_dir,
    clip_meta_path,
    clip_stream_urls,
    count_clips,
    delete_clip,
    delete_video,
    desktop_frame_path,
    gallery_tree,
    get_own_webcam_region,
    has_transcript,
    highlights_path,
    is_webcam_eligible,
    list_all_videos,
    list_recent_clips,
    load_metadata,
    make_clip_id,
    related_videos,
    resolve_video_id,
    resolve_webcam_region,
    save_clip_metadata,
    save_webcam_region,
    search_videos,
    source_path,
    stream_url_for,
    to_index,
    video_dir,
)
from reels.video_transcript import ensure_transcript, slice_segments_for_window, update_transcript

router = APIRouter(prefix="/api/v2", tags=["v2"])


def _start_v2_job(
    slug: str,
    feature: str,
    *,
    preset: str = "twitch_gaming",
    use_nvenc: bool = False,
    max_clips: int | None = None,
    params: dict[str, Any] | None = None,
    video_path: Path | None = None,
    output_dir: Path | None = None,
) -> dict:
    resolved_path = video_path or source_path(slug)
    if not resolved_path.is_file():
        raise HTTPException(status_code=404, detail="Source video not found")
    mgr = get_job_manager()
    job_params: dict[str, Any] = {"video_slug": slug}
    if params:
        job_params.update(params)
    out_dir = output_dir or analysis_dir(slug)
    try:
        state = mgr.create_job(
            CreateJobRequest(
                video_path=str(resolved_path),
                feature=feature,
                preset=preset,
                use_nvenc=use_nvenc,
                max_clips=max_clips,
                output_dir=str(out_dir),
                params=job_params,
            )
        )
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return {"video_id": slug, "job_id": state.id, "status": state.status}


def _resolve_v2_job_source(
    video_id: str,
    *,
    source_format: str | None = None,
) -> tuple[str, Path, dict[str, Any]]:
    """Resolve input video path and job params for VOD or clip-scoped derivative jobs."""
    meta = resolve_video_id(video_id)
    if meta.kind == "clip" and meta.parent_slug and meta.clip_slug:
        parent = meta.parent_slug
        formats = list(meta.formats or [])
        fmt = source_format if source_format in ("youtube", "reels") else None
        if fmt is None:
            fmt = formats[0] if formats else "youtube"
        video_path = clip_dir(parent, meta.clip_slug) / f"{fmt}.mp4"
        if not video_path.is_file():
            for alt in formats or ["youtube", "reels"]:
                candidate = clip_dir(parent, meta.clip_slug) / f"{alt}.mp4"
                if candidate.is_file():
                    fmt = alt
                    video_path = candidate
                    break
        if not video_path.is_file():
            raise HTTPException(status_code=404, detail="Clip video file not found")
        params: dict[str, Any] = {
            "video_slug": parent,
            "source_clip_slug": meta.clip_slug,
            "source_clip_title": meta.title,
            "source_format": fmt,
            "clip_start": meta.start or 0.0,
            "clip_end": meta.end or 0.0,
        }
        return parent, video_path, params
    slug = meta.slug if meta.kind == "original" else _resolve_original_slug(video_id)
    return slug, source_path(slug), {"video_slug": slug}


def _start_v2_feature_job(
    video_id: str,
    feature: str,
    *,
    preset: str = "default",
    use_nvenc: bool = False,
    params: dict[str, Any] | None = None,
) -> dict:
    body_params = dict(params or {})
    source_format = body_params.pop("source_format", None)
    parent_slug, video_path, base_params = _resolve_v2_job_source(
        video_id,
        source_format=source_format,
    )
    job_params = {**base_params, **body_params}
    out_dir = analysis_dir(parent_slug)
    if job_params.get("source_clip_slug"):
        suffix_map = {
            "v2_cleanup": "cleanup",
            "v2_captions": "captions",
            "v2_trim": "recorte",
            "v2_transform_reel": "reels",
        }
        suffix = suffix_map.get(feature, feature.replace("v2_", ""))
        out_dir = out_dir / "derivatives" / f"{job_params['source_clip_slug']}_{suffix}"
    elif feature == "v2_trim":
        import uuid

        trim_id = body_params.get("trim_session") or uuid.uuid4().hex[:8]
        job_params["trim_session"] = trim_id
        out_dir = out_dir / "derivatives" / f"trim_{trim_id}"
    elif feature == "v2_transform_reel":
        import uuid

        transform_id = body_params.get("transform_session") or uuid.uuid4().hex[:8]
        job_params["transform_session"] = transform_id
        out_dir = out_dir / "derivatives" / f"transform_reel_{transform_id}"
    result = _start_v2_job(
        parent_slug,
        feature,
        preset=preset,
        use_nvenc=use_nvenc,
        params=job_params,
        video_path=video_path,
        output_dir=out_dir,
    )
    result["video_id"] = video_id
    return result


def _highlights_payload(slug: str) -> dict:
    path = highlights_path(slug)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Highlights not ready")
    doc = load_highlights(path)
    video_path = source_path(slug)
    info = probe_video(video_path) if video_path.is_file() else None
    payload: dict[str, Any] = {
        "video_id": slug,
        "highlights": [
            {
                "index": i,
                "start": h.start,
                "end": h.end,
                "title": h.title,
                "score": h.score,
                "reason": h.reason,
            }
            for i, h in enumerate(doc.highlights)
        ],
    }
    if info:
        yt_w, yt_h = default_youtube_size(info.width, info.height)
        rl_w, rl_h = default_reels_size(info.width, info.height)
        payload.update(
            {
                "source_width": info.width,
                "source_height": info.height,
                "youtube_presets": [p.model_dump() for p in youtube_presets(info.width, info.height)],
                "reels_presets": [p.model_dump() for p in reels_presets(info.width, info.height)],
                "default_youtube": {"id": "native", "label": "Native", "width": yt_w, "height": yt_h},
                "default_reels": {
                    "id": "source_height",
                    "label": "Source height",
                    "width": rl_w,
                    "height": rl_h,
                },
            }
        )
    return payload


@router.get("/system")
def get_system_status(preset: str = "twitch_gaming") -> dict:
    return collect_system_status(preset)


class TranscriptPutBody(BaseModel):
    segments: list[dict[str, Any]]


class GenerateClipSelection(BaseModel):
    index: int
    start: float
    end: float
    title: str = "Highlight"
    export_youtube: bool = True
    export_reels: bool = True
    include_webcam: bool = False
    burn_captions: bool = False
    cleanup_silence: bool = False


class GenerateClipsBody(BaseModel):
    selections: list[GenerateClipSelection] = Field(default_factory=list)
    max_clips: int | None = None
    pre_pad_seconds: float | None = None
    post_pad_seconds: float | None = None
    min_duration: float | None = None
    use_nvenc: bool = False


class AnalyzeHighlightsBody(BaseModel):
    max_clips: int = Field(default=15, ge=1, le=50)


class ActionBody(BaseModel):
    preset: str = "twitch_gaming"
    use_nvenc: bool = False
    params: dict[str, Any] = Field(default_factory=dict)


class CaptionsJobBody(BaseModel):
    font_id: str = "montserrat-bold"
    max_words_per_line: int | None = None
    word_gap_seconds: float | None = None
    bottom_margin_ratio: float | None = None
    font_size_ratio: float | None = None
    primary_colour: str | None = None
    highlight_colour: str | None = None
    output_format: Literal["reels", "youtube", "both"] = "reels"
    source_format: Literal["reels", "youtube"] | None = None
    use_nvenc: bool = False


class CleanupJobBody(BaseModel):
    min_gap_seconds: float | None = None
    pad_seconds: float | None = None
    use_silencedetect: bool | None = None
    silence_noise_db: float | None = None
    remove_fillers: bool | None = None
    use_llm: bool | None = None
    export_youtube: bool = True
    export_reels: bool = True
    source_format: Literal["reels", "youtube"] | None = None
    use_nvenc: bool = False


class CleanupRenderBody(BaseModel):
    cut_indices: list[int] = Field(default_factory=list)
    export_youtube: bool = True
    export_reels: bool = True
    use_nvenc: bool = False


class TrimJobBody(BaseModel):
    keep_spans: list[list[float]] = Field(..., min_length=1)
    source_format: Literal["reels", "youtube"] | None = None
    use_nvenc: bool | None = None


class TrimFinalizeBody(BaseModel):
    mode: Literal["new_vod", "replace", "new_clip"]


class TransformReelBody(BaseModel):
    use_nvenc: bool | None = None
    include_webcam: bool = False


class WebcamRegionBody(BaseModel):
    x1: int
    y1: int
    x2: int
    y2: int
    frame_at: float = 0.0

    @field_validator("x1", "y1", "x2", "y2", mode="before")
    @classmethod
    def _coerce_bbox_int(cls, v: object) -> int:
        if isinstance(v, bool):
            raise ValueError("invalid coordinate")
        return int(round(float(v)))


class PublishJobBody(BaseModel):
    platform: Literal["youtube", "short_form"] = "youtube"
    content_type: Literal["game", "other"] = "game"
    game_name: str = ""
    video_context: str = ""
    channel_info: str = ""
    source_format: Literal["reels", "youtube"] | None = None
    preset: str = "default"
    use_nvenc: bool = False


def _publish_job_response(job_id: str) -> dict:
    from reels.publish import load_publish

    mgr = get_job_manager()
    state = mgr.get_job(job_id)
    if not state:
        raise HTTPException(status_code=404, detail="Job not found")
    path = Path(state.output_dir) / "publish" / "manifest.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Publish manifest not ready")
    doc = load_publish(path)
    items: list[dict[str, Any]] = []
    for i, item in enumerate(doc.items):
        row = item.model_dump()
        row["index"] = i
        row["thumbnail_url"] = (
            f"/api/v2/jobs/{job_id}/publish/{i}/thumbnail" if item.thumbnail_path else None
        )
        items.append(row)
    return {
        "job_id": job_id,
        "output_dir": state.output_dir,
        "platform": doc.platform,
        "content_type": doc.content_type,
        "game_name": doc.game_name,
        "video_context": doc.video_context,
        "channel_info": doc.channel_info,
        "items": items,
        "warnings": doc.warnings,
    }


def _webcam_fields(video_id: str) -> dict[str, Any]:
    own = get_own_webcam_region(video_id)
    resolved = resolve_webcam_region(video_id)
    eligible = is_webcam_eligible(video_id)
    frame_w = 0
    frame_h = 0
    if eligible:
        try:
            info = probe_video(desktop_frame_path(video_id))
            frame_w = int(info.width)
            frame_h = int(info.height)
        except Exception:
            pass
    return {
        "webcam_region": own.model_dump() if own else None,
        "webcam_region_resolved": resolved.model_dump() if resolved else None,
        "webcam_eligible": eligible,
        "has_webcam_region": resolved is not None,
        "desktop_frame_width": frame_w,
        "desktop_frame_height": frame_h,
    }


def _video_summary(meta, *, clip_count: int | None = None) -> dict:
    idx = to_index(meta)
    if clip_count is not None:
        idx.clip_count = clip_count
    return {
        **idx.model_dump(),
        "stream_url": stream_url_for(
            meta.slug if meta.kind == "original" else make_clip_id(meta.parent_slug or "", meta.clip_slug or "")
        ),
        "thumbnail_url": None,
    }


def _resolve_original_slug(video_id: str) -> str:
    meta = resolve_video_id(video_id)
    if meta.kind == "clip" and meta.parent_slug:
        return meta.parent_slug
    return meta.slug if meta.kind == "original" else (meta.parent_slug or video_id.split(CLIP_ID_SEP, 1)[0])


@router.get("/videos")
def list_videos(offset: int = 0, limit: int = 24) -> dict:
    items, total = list_all_videos(offset=offset, limit=limit)
    return {
        "videos": [
            {**v.model_dump(), "stream_url": stream_url_for(v.id), "thumbnail_url": None}
            for v in items
        ],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.get("/search")
def search(q: str = "", limit: int = 24) -> dict:
    items = search_videos(q, limit=limit)
    return {
        "query": q.strip(),
        "videos": [
            {
                **v.model_dump(),
                "stream_url": stream_url_for(v.id, v.format or "youtube") if v.kind == "clip" else stream_url_for(v.id),
                "thumbnail_url": None,
            }
            for v in items
        ],
        "total": len(items),
    }


@router.get("/clips")
def list_clips(limit: int = 12) -> dict:
    clips = list_recent_clips(limit=limit)
    result = []
    for c in clips:
        dur = c.duration
        m = int(dur // 60)
        s = int(dur % 60)
        result.append(
            {
                **c.model_dump(),
                "stream_url": stream_url_for(c.id, c.format or "youtube"),
                "thumbnail_url": None,
                "duration_label": f"{m}:{s:02d}",
            }
        )
    return {"clips": result}


@router.get("/gallery")
def gallery() -> dict:
    return {"videos": gallery_tree()}


@router.get("/videos/{video_id}")
def get_video_detail(video_id: str) -> dict:
    try:
        meta = resolve_video_id(video_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    slug = _resolve_original_slug(video_id)
    parent_meta = load_metadata(slug)
    data = _video_summary(meta, clip_count=count_clips(slug) if parent_meta else 0)
    if parent_meta:
        data.update(
            {
                "source_path": str(source_path(slug)),
                "fps": parent_meta.fps,
                "size_bytes": parent_meta.size_bytes,
            }
        )
    if meta.kind == "clip":
        data["parent_slug"] = meta.parent_slug
        data["clip_slug"] = meta.clip_slug
        data["start"] = meta.start
        data["end"] = meta.end
        if meta.parent_slug and meta.clip_slug:
            cm_path = clip_meta_path(meta.parent_slug, meta.clip_slug)
            if cm_path.is_file():
                import json

                cm = json.loads(cm_path.read_text(encoding="utf-8"))
                formats = cm.get("formats") or meta.formats or []
                data["formats"] = formats
                data["stream_urls"] = clip_stream_urls(meta.parent_slug, meta.clip_slug, formats)
                data["source_feature"] = cm.get("source_feature", "highlight")
                if formats:
                    data["stream_url"] = data["stream_urls"].get(
                        formats[0], stream_url_for(video_id, formats[0])
                    )
    vid = video_id if meta.kind == "clip" else meta.slug
    data.update(_webcam_fields(vid))
    return data


@router.get("/videos/{video_id}/frame")
def get_video_frame(video_id: str, at: float = 0.0) -> FileResponse:
    import subprocess

    if not is_webcam_eligible(video_id):
        raise HTTPException(status_code=400, detail="Webcam region is only for desktop-format videos")
    try:
        frame_video = desktop_frame_path(video_id)
        meta = resolve_video_id(video_id)
        duration = meta.duration or 0.0
        if duration <= 0:
            info = probe_video(frame_video)
            duration = info.duration
        ts = max(0.0, min(float(at), max(0.0, duration - 0.05)))
        cache_dir = analysis_dir(
            meta.parent_slug if meta.kind == "clip" and meta.parent_slug else meta.slug
        )
        cache_dir.mkdir(parents=True, exist_ok=True)
        out = cache_dir / f"webcam_frame_{int(ts * 1000)}.jpg"
        if not out.is_file():
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-ss",
                    str(ts),
                    "-i",
                    str(frame_video),
                    "-frames:v",
                    "1",
                    "-q:v",
                    "2",
                    str(out),
                ],
                capture_output=True,
                check=False,
            )
        if not out.is_file():
            raise HTTPException(status_code=500, detail="Could not extract frame")
        return FileResponse(out, media_type="image/jpeg")
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.put("/videos/{video_id}/webcam-region")
def put_webcam_region(video_id: str, body: WebcamRegionBody) -> dict:
    from reels.models import WebcamRegion

    if not is_webcam_eligible(video_id):
        raise HTTPException(status_code=400, detail="Webcam region is only for desktop-format videos")
    try:
        saved = save_webcam_region(
            video_id,
            WebcamRegion(
                x1=body.x1,
                y1=body.y1,
                x2=body.x2,
                y2=body.y2,
                frame_at=body.frame_at,
            ),
        )
        return {"webcam_region": saved.model_dump()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.delete("/videos/{video_id}/webcam-region")
def delete_webcam_region(video_id: str) -> dict:
    if not is_webcam_eligible(video_id):
        raise HTTPException(status_code=400, detail="Webcam region is only for desktop-format videos")
    try:
        clear_webcam_region(video_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"cleared": True}


@router.delete("/videos/{video_id}")
def delete_video_entry(video_id: str) -> dict:
    try:
        meta = resolve_video_id(video_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    if meta.kind == "clip" and meta.parent_slug and meta.clip_slug:
        bytes_freed = delete_clip(meta.parent_slug, meta.clip_slug)
        return {"deleted": True, "video_id": video_id, "bytes_freed": bytes_freed}
    slug = meta.slug if meta.kind == "original" else _resolve_original_slug(video_id)
    if not video_dir(slug).is_dir():
        raise HTTPException(status_code=404, detail="Video not found")
    bytes_freed = delete_video(slug)
    return {"deleted": True, "video_id": slug, "bytes_freed": bytes_freed}


@router.get("/videos/{video_id}/related")
def get_related(video_id: str) -> dict:
    try:
        items = related_videos(video_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {
        "items": [
            {**v.model_dump(), "stream_url": stream_url_for(v.id, v.format), "thumbnail_url": None}
            for v in items
        ]
    }


@router.post("/videos/{video_id}/metadata")
def post_metadata(video_id: str) -> dict:
    slug = _resolve_original_slug(video_id)
    warnings: list[str] = []

    def run() -> None:
        ensure_transcript(slug, warnings=warnings, force=True)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(timeout=600)
    if thread.is_alive():
        return {
            "video_id": slug,
            "status": "running",
            "has_transcript": has_transcript(slug),
            "message": "Metadata job still running",
        }
    return {
        "video_id": slug,
        "status": "completed",
        "has_transcript": has_transcript(slug),
        "warnings": warnings,
    }


@router.get("/videos/{video_id}/transcript")
def get_transcript(video_id: str) -> dict:
    try:
        meta = resolve_video_id(video_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    slug = _resolve_original_slug(video_id)
    path = video_dir(slug)
    if not path.is_dir():
        raise HTTPException(status_code=404, detail="Video not found")
    from reels.video_store import segments_original_path, segments_path

    seg_path = segments_path(slug)
    if not seg_path.is_file():
        raise HTTPException(status_code=404, detail="Transcript not ready")
    segments = json.loads(seg_path.read_text(encoding="utf-8"))
    original = []
    orig_path = segments_original_path(slug)
    if orig_path.is_file():
        original = json.loads(orig_path.read_text(encoding="utf-8"))

    if meta.kind == "clip" and meta.start is not None and meta.end is not None:
        segments = slice_segments_for_window(segments, meta.start, meta.end)
        original = slice_segments_for_window(original, meta.start, meta.end)

    return {
        "video_id": video_id,
        "segments": segments,
        "segments_original": original,
        "window": {"start": meta.start, "end": meta.end} if meta.kind == "clip" else None,
    }


@router.put("/videos/{video_id}/transcript")
def put_transcript(video_id: str, body: TranscriptPutBody) -> dict:
    try:
        doc = update_transcript(video_id, body.segments)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {
        "video_id": doc.video_id,
        "segments": doc.segments,
        "segments_original": doc.segments_original,
    }


@router.post("/videos/{video_id}/analyze-highlights", status_code=202)
def analyze_highlights(video_id: str, body: AnalyzeHighlightsBody | None = None) -> dict:
    slug = _resolve_original_slug(video_id)
    max_clips = body.max_clips if body else 15
    return _start_v2_job(slug, "v2_analyze", max_clips=max_clips)


@router.get("/videos/{video_id}/highlights")
def get_highlights(video_id: str) -> dict:
    slug = _resolve_original_slug(video_id)
    return _highlights_payload(slug)


@router.post("/videos/{video_id}/generate-clips", status_code=202)
def generate_clips(video_id: str, body: GenerateClipsBody) -> dict:
    slug = _resolve_original_slug(video_id)
    config = load_config("twitch_gaming")
    pre_pad = body.pre_pad_seconds if body.pre_pad_seconds is not None else config.clip.pre_pad_seconds
    post_pad = body.post_pad_seconds if body.post_pad_seconds is not None else config.clip.post_pad_seconds
    selections = [
        {
            "index": s.index,
            "start": s.start,
            "end": s.end,
            "title": s.title,
            "export_youtube": s.export_youtube,
            "export_reels": s.export_reels,
            "include_webcam": s.include_webcam,
        }
        for s in body.selections
    ]
    return _start_v2_job(
        slug,
        "v2_export_clips",
        use_nvenc=body.use_nvenc,
        params={
            "selections": selections,
            "pre_pad_seconds": pre_pad,
            "post_pad_seconds": post_pad,
        },
    )


@router.get("/config/captions")
def get_captions_config() -> dict:
    config = load_config("default")
    return {
        "defaults": config.captions.model_dump(),
        "fonts": list_caption_fonts(),
    }


@router.get("/config/cleanup")
def get_cleanup_config() -> dict:
    config = load_config("cleanup")
    return {"defaults": config.cleanup.model_dump()}


@router.post("/videos/{video_id}/cleanup", status_code=202)
def post_cleanup(video_id: str, body: CleanupJobBody) -> dict:
    return _start_v2_feature_job(
        video_id,
        "v2_cleanup",
        preset="cleanup",
        use_nvenc=body.use_nvenc,
        params=body.model_dump(exclude_none=True),
    )


@router.post("/videos/{video_id}/captions", status_code=202)
def post_captions(video_id: str, body: CaptionsJobBody) -> dict:
    return _start_v2_feature_job(
        video_id,
        "v2_captions",
        preset="default",
        use_nvenc=body.use_nvenc,
        params=body.model_dump(exclude_none=True),
    )


@router.post("/videos/{video_id}/trim", status_code=202)
def post_trim(video_id: str, body: TrimJobBody) -> dict:
    from reels.trim import validate_keep_spans

    _, video_path, _ = _resolve_v2_job_source(
        video_id,
        source_format=body.source_format,
    )
    if not video_path.is_file():
        raise HTTPException(status_code=404, detail="Source video not found")
    try:
        info = probe_video(video_path)
        validate_keep_spans(body.keep_spans, info.duration)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _start_v2_feature_job(
        video_id,
        "v2_trim",
        preset="default",
        use_nvenc=body.use_nvenc if body.use_nvenc is not None else False,
        params={**body.model_dump(exclude_none=True), "source_video_id": video_id},
    )


@router.get("/jobs/{job_id}/trim/preview")
def get_trim_preview(job_id: str) -> FileResponse:
    mgr = get_job_manager()
    state = mgr.get_job(job_id)
    if not state or state.feature != "v2_trim":
        raise HTTPException(status_code=404, detail="Trim job not found")
    path_str = state.trim_output_path
    if not path_str:
        ctx_path = Path(state.output_dir) / "v2_job_context.json"
        if ctx_path.is_file():
            ctx = json.loads(ctx_path.read_text(encoding="utf-8"))
            path_str = ctx.get("trim_output_path")
    if not path_str:
        raise HTTPException(status_code=404, detail="Trim preview not ready")
    path = Path(path_str)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Trim preview file missing")
    return FileResponse(path, media_type="video/mp4", filename="trim_preview.mp4")


@router.post("/jobs/{job_id}/trim/finalize")
def post_trim_finalize(job_id: str, body: TrimFinalizeBody) -> dict:
    mgr = get_job_manager()
    try:
        return mgr.finalize_v2_trim(job_id, body.mode)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/videos/{video_id}/transform-reel", status_code=202)
def post_transform_reel(video_id: str, body: TransformReelBody = TransformReelBody()) -> dict:
    from reels.video_store import clip_dir, resolve_video_id, source_path

    meta = resolve_video_id(video_id)
    if meta.kind == "clip":
        if not meta.parent_slug or not meta.clip_slug:
            raise HTTPException(status_code=400, detail="Invalid clip")
        youtube_path = clip_dir(meta.parent_slug, meta.clip_slug) / "youtube.mp4"
        if not youtube_path.is_file():
            raise HTTPException(status_code=400, detail="Clip has no desktop (youtube) format")
        params: dict[str, Any] = {"source_video_id": video_id, "source_format": "youtube"}
    elif meta.kind == "original":
        vod_src = source_path(meta.slug)
        if not vod_src.is_file():
            raise HTTPException(status_code=404, detail="Source video not found")
        if meta.width and meta.height and meta.width < meta.height:
            raise HTTPException(
                status_code=400,
                detail="VOD is already vertical; transform is for desktop (landscape) videos",
            )
        params = {"source_video_id": video_id}
    else:
        raise HTTPException(status_code=400, detail="Cannot transform this video type")
    return _start_v2_feature_job(
        video_id,
        "v2_transform_reel",
        preset="default",
        use_nvenc=body.use_nvenc if body.use_nvenc is not None else False,
        params={**params, "include_webcam": body.include_webcam},
    )


@router.get("/jobs/{job_id}/cleanup/edl")
def get_cleanup_edl(job_id: str) -> dict:
    mgr = get_job_manager()
    state = mgr.get_job(job_id)
    if not state:
        raise HTTPException(status_code=404, detail="Job not found")
    path = Path(state.output_dir) / "edl.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="EDL not ready")
    doc = load_edl(path)
    return {
        "job_id": job_id,
        "total_duration": doc.total_duration,
        "kept_duration": doc.kept_duration,
        "cut_duration": doc.cut_duration,
        "llm_available": doc.llm_available,
        "spans": [s.model_dump() for s in doc.spans],
    }


@router.post("/jobs/{job_id}/cleanup/render", status_code=202)
def post_cleanup_render(job_id: str, body: CleanupRenderBody) -> dict:
    mgr = get_job_manager()
    try:
        formats: list[str] = []
        if body.export_youtube:
            formats.append("youtube")
        if body.export_reels:
            formats.append("reels")
        if not formats:
            formats = list(load_config("cleanup").cleanup.formats)
        state = mgr.render_v2_cleanup(
            job_id,
            RenderJobBody(
                cut_indices=body.cut_indices,
                formats=formats,
                use_nvenc=body.use_nvenc,
            ),
        )
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return {"job_id": state.id, "status": state.status}


class PublishSessionBody(BaseModel):
    source_format: Literal["reels", "youtube"] | None = None


class PublishSuggestBody(BaseModel):
    field: Literal["title", "description", "tags", "thumbnail"]
    platform: Literal["youtube", "short_form"] = "youtube"
    content_type: Literal["game", "other"] = "game"
    game_name: str = ""
    video_context: str = ""
    channel_info: str = ""
    title: str = ""


class PublishDraftBody(BaseModel):
    title: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    platform: Literal["youtube", "short_form"] = "youtube"


@router.post("/videos/{video_id}/publish/session")
def post_publish_session(video_id: str, body: PublishSessionBody | None = None) -> dict:
    fmt = body.source_format if body else None
    try:
        _parent_slug, video_path, _params = _resolve_v2_job_source(video_id, source_format=fmt)
    except HTTPException:
        raise
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    if not video_path.is_file():
        raise HTTPException(status_code=404, detail="Source video not found")
    from reels.publish_session import create_session

    session = create_session(video_id=video_id, video_path=video_path)
    return {"session_id": session.id, "video_id": video_id}


@router.post("/publish/sessions/{session_id}/suggest")
def post_publish_suggest(session_id: str, body: PublishSuggestBody) -> dict:
    from reels.publish import PublishContext, suggest_publish_field
    from reels.publish_session import get_session, update_draft
    from reels.video_transcript import load_segments
    from reels.vlm.ollama import OllamaClient

    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    video_path = Path(session.video_path)
    if not video_path.is_file():
        raise HTTPException(status_code=404, detail="Source video not found")

    try:
        meta = resolve_video_id(session.video_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    slug = meta.slug if meta.kind == "original" else _resolve_original_slug(session.video_id)
    segments = load_segments(slug) or []
    if not segments:
        raise HTTPException(status_code=400, detail="Transcript not ready")
    if meta.kind == "clip" and meta.start is not None and meta.end is not None:
        segments = slice_segments_for_window(segments, meta.start, meta.end)

    config = load_config("default")
    info = probe_video(video_path)
    ctx = PublishContext(
        content_type=body.content_type,
        game_name=body.game_name,
        video_context=body.video_context,
        channel_info=body.channel_info,
    )
    client = OllamaClient(config)
    result = suggest_publish_field(
        body.field,
        client=client,
        config=config,
        segments=segments,
        platform=body.platform,
        info=info,
        context=ctx,
        title_hint=body.title.strip(),
    )

    if body.field == "thumbnail":
        from reels.publish import render_publish_thumbnail

        ts = float(result.get("thumbnail_second", info.duration * 0.3))
        title = body.title.strip() or video_path.stem
        thumb_dir = session.output_dir / "thumb"
        thumb_path, used_ts = render_publish_thumbnail(
            video_path,
            thumb_dir,
            title=title,
            platform=body.platform,
            config=config,
            timestamp=ts,
        )
        update_draft(
            session_id,
            thumbnail_path=str(thumb_path),
            thumbnail_timestamp=used_ts,
            platform=body.platform,
        )
        return {
            "field": body.field,
            "thumbnail_second": used_ts,
            "thumbnail_url": f"/api/v2/publish/sessions/{session_id}/thumbnail",
        }

    return {"field": body.field, **result}


@router.patch("/publish/sessions/{session_id}/draft")
def patch_publish_draft(session_id: str, body: PublishDraftBody) -> dict:
    from reels.publish_session import get_session, update_draft

    if not get_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    update_draft(
        session_id,
        title=body.title,
        description=body.description,
        tags=body.tags,
        platform=body.platform,
    )
    return {"session_id": session_id, "ok": True}


@router.get("/publish/sessions/{session_id}/thumbnail")
def get_publish_session_thumbnail(session_id: str) -> FileResponse:
    from reels.publish import load_publish
    from reels.publish_session import get_session

    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    manifest = session.output_dir / "manifest.json"
    if not manifest.is_file():
        raise HTTPException(status_code=404, detail="Draft not ready")
    doc = load_publish(manifest)
    if not doc.items or not doc.items[0].thumbnail_path:
        raise HTTPException(status_code=404, detail="Thumbnail not ready")
    thumb = Path(doc.items[0].thumbnail_path)
    if not thumb.is_file():
        raise HTTPException(status_code=404, detail="Thumbnail file missing")
    media = "image/jpeg"
    if thumb.suffix.lower() == ".png":
        media = "image/png"
    elif thumb.suffix.lower() == ".webp":
        media = "image/webp"
    return FileResponse(thumb, media_type=media, filename=thumb.name)


@router.post("/publish/sessions/{session_id}/thumbnail")
async def post_publish_session_thumbnail(
    session_id: str,
    file: UploadFile = File(...),
) -> dict:
    from reels.publish_session import get_session, update_draft

    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    content_type = (file.content_type or "").lower()
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Expected an image file")
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(raw) > 8 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Image too large (max 8 MB)")

    ext = ".jpg"
    if "png" in content_type:
        ext = ".png"
    elif "webp" in content_type:
        ext = ".webp"

    thumb_dir = session.output_dir / "thumb"
    thumb_dir.mkdir(parents=True, exist_ok=True)
    src_path = thumb_dir / f"upload{ext}"
    src_path.write_bytes(raw)
    final_path = thumb_dir / "thumbnail.jpg"
    if ext == ".jpg":
        final_path.write_bytes(raw)
    else:
        import subprocess

        result = subprocess.run(
            ["ffmpeg", "-y", "-i", str(src_path), "-q:v", "2", str(final_path)],
            capture_output=True,
            check=False,
        )
        if result.returncode != 0 or not final_path.is_file():
            final_path = src_path

    update_draft(
        session_id,
        thumbnail_path=str(final_path),
        thumbnail_timestamp=0.0,
    )
    return {
        "session_id": session_id,
        "thumbnail_url": f"/api/v2/publish/sessions/{session_id}/thumbnail",
    }


@router.post("/videos/{video_id}/publish", status_code=202)
def post_publish(video_id: str, body: PublishJobBody) -> dict:
    import uuid

    parent_slug, video_path, base_params = _resolve_v2_job_source(
        video_id,
        source_format=body.source_format,
    )
    if not video_path.is_file():
        raise HTTPException(status_code=404, detail="Source video not found")
    publish_id = uuid.uuid4().hex[:8]
    out_dir = analysis_dir(parent_slug) / "derivatives" / f"publish_{publish_id}"
    params: dict[str, Any] = {
        **base_params,
        "source_video_id": video_id,
        "video_paths": [str(video_path)],
        "platform": body.platform,
        "content_type": body.content_type,
        "game_name": body.game_name,
        "video_context": body.video_context,
        "channel_info": body.channel_info,
    }
    result = _start_v2_job(
        parent_slug,
        "publish",
        preset=body.preset,
        use_nvenc=body.use_nvenc,
        params=params,
        video_path=video_path,
        output_dir=out_dir,
    )
    result["video_id"] = video_id
    return result


@router.get("/jobs/{job_id}/publish")
def get_publish_job(job_id: str) -> dict:
    return _publish_job_response(job_id)


@router.get("/jobs/{job_id}/publish/{index}/thumbnail")
def get_publish_thumbnail(job_id: str, index: int) -> FileResponse:
    from reels.publish import load_publish

    mgr = get_job_manager()
    state = mgr.get_job(job_id)
    if not state:
        raise HTTPException(status_code=404, detail="Job not found")
    path = Path(state.output_dir) / "publish" / "manifest.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Publish manifest not ready")
    doc = load_publish(path)
    if index < 0 or index >= len(doc.items):
        raise HTTPException(status_code=404, detail="Publish item not found")
    item = doc.items[index]
    if not item.thumbnail_path:
        raise HTTPException(status_code=404, detail="Thumbnail not ready")
    thumb = Path(item.thumbnail_path)
    if not thumb.is_file():
        raise HTTPException(status_code=404, detail="Thumbnail file missing")
    return FileResponse(thumb, media_type="image/jpeg", filename=f"thumbnail_{index}.jpg")


@router.get("/media/{slug}/source.mp4")
def serve_source(slug: str) -> FileResponse:
    path = source_path(slug)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Video not found")
    return FileResponse(path, media_type="video/mp4", filename="source.mp4")


@router.get("/media/{parent_slug}/clips/{clip_slug}/{filename}")
def serve_clip(parent_slug: str, clip_slug: str, filename: str) -> FileResponse:
    if ".." in parent_slug or ".." in clip_slug or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid path")
    if filename not in ("youtube.mp4", "reels.mp4"):
        raise HTTPException(status_code=400, detail="Invalid clip file")
    path = clip_dir(parent_slug, clip_slug) / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Clip not found")
    return FileResponse(path, media_type="video/mp4", filename=filename)
