"""REST API v2 — video-centric storage and actions."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

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
    clip_dir,
    clip_meta_path,
    clip_stream_urls,
    count_clips,
    delete_clip,
    delete_video,
    gallery_tree,
    has_transcript,
    highlights_path,
    list_all_videos,
    list_recent_clips,
    load_metadata,
    make_clip_id,
    related_videos,
    resolve_video_id,
    save_clip_metadata,
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
        suffix_map = {"v2_cleanup": "cleanup", "v2_captions": "captions", "v2_trim": "recorte"}
        suffix = suffix_map.get(feature, feature.replace("v2_", ""))
        out_dir = out_dir / "derivatives" / f"{job_params['source_clip_slug']}_{suffix}"
    elif feature == "v2_trim":
        import uuid

        trim_id = body_params.get("trim_session") or uuid.uuid4().hex[:8]
        job_params["trim_session"] = trim_id
        out_dir = out_dir / "derivatives" / f"trim_{trim_id}"
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
    mode: Literal["new_vod", "replace"]


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
    return data


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


@router.post("/videos/{video_id}/publish")
def post_publish(video_id: str, body: ActionBody) -> dict:
    slug = _resolve_original_slug(video_id)
    path = str(source_path(slug))
    mgr = get_job_manager()
    state = mgr.create_job(
        CreateJobRequest(
            video_path=path,
            feature="publish",
            preset=body.preset,
            use_nvenc=body.use_nvenc,
            params=body.params,
        )
    )
    return {"job_id": state.id, "video_id": slug, "status": state.status}


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
