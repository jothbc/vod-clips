"""FastAPI application."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from reels.api.clips import list_clips
from reels.api.library import list_library_jobs, list_pickable_clips
from reels.api.media_serve import is_readable_clip, resolve_media_clip
from reels.api.schemas import (
    CleanupResponse,
    ClipsResponse,
    CreateJobResponse,
    UploadResponse,
)
from reels.api.upload import save_upload_file
from reels.api.videos import router as v2_router
from reels.caption_fonts import list_caption_fonts, resolve_font_path
from reels.captions import load_captions, write_captions
from reels.cleanup import load_edl
from reels.config import load_config
from reels.export import require_ffmpeg
from reels.export_resolution import (
    default_reels_size,
    default_youtube_size,
    reels_presets,
    youtube_presets,
)
from reels.features import list_feature_info
from reels.highlights import load_highlights
from reels.jobs import (
    CreateJobRequest,
    ExportJobRequest,
    JobManager,
    JobStatus,
    RenderCaptionsBody,
    RenderJobBody,
    ResetSessionRequest,
    get_job_manager,
)
from reels.logging_config import setup_logging
from reels.models import CaptionSegment, CaptionsDocument
from reels.probe import probe_video
from reels.publish import load_publish
from reels.storage import delete_reel_job_output, delete_stored_vod, list_stored_vods, temp_outputs_dir, temp_vods_dir
from reels.twitch.download import TwitchDownloadError, normalize_twitch_vod_url, require_yt_dlp
from reels.twitch.manager import TwitchDownloadManager, TwitchDownloadRequest, get_twitch_download_manager
from reels.vlm.ollama import OllamaClient


class TwitchDownloadBody(BaseModel):
    url: str


class TwitchDownloadBatchBody(BaseModel):
    urls: list[str] = Field(default_factory=list)


class SaveCaptionsBody(BaseModel):
    segments: list[dict]
    font_id: str | None = None


def create_app() -> FastAPI:
    log_path = setup_logging()
    app = FastAPI(title="Reels", description="Twitch VOD -> YouTube + Reels clips")
    app.state.log_file = str(log_path)
    manager = get_job_manager()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "http://127.0.0.1:8000",
            "http://localhost:8000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(v2_router)

    @app.get("/api/ready")
    def ready() -> dict:
        return {"ok": True}

    @app.get("/api/health")
    def health() -> dict:
        ffmpeg_ok = False
        yt_dlp_ok = False
        try:
            require_ffmpeg()
            ffmpeg_ok = True
        except Exception:
            pass
        try:
            require_yt_dlp()
            yt_dlp_ok = True
        except Exception:
            pass
        config = load_config("twitch_gaming")
        client = OllamaClient(config)
        return {
            "ffmpeg": ffmpeg_ok,
            "ollama": client.is_available(),
            "yt_dlp": yt_dlp_ok,
            "ollama_host": config.ollama.resolved_host(),
            "log_file": app.state.log_file,
        }

    @app.get("/api/features")
    def features() -> dict:
        return {"features": list_feature_info()}

    @app.post("/api/session/reset")
    def reset_session(body: ResetSessionRequest) -> dict:
        return manager.reset_session(
            previous_job_id=body.previous_job_id,
            cleanup_previous=body.cleanup_previous,
        )

    @app.get("/api/vods")
    def list_vods() -> dict:
        return {"dir": str(temp_vods_dir()), "vods": list_stored_vods()}

    @app.delete("/api/vods")
    def delete_vod(path: str = Query(...)) -> dict:
        try:
            return delete_stored_vod(path)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e

    @app.get("/api/reels/library")
    def reels_library() -> dict:
        return {"dir": str(temp_outputs_dir()), "jobs": list_library_jobs()}

    @app.get("/api/reels/pickable-clips")
    def pickable_clips() -> dict:
        return {"dir": str(temp_outputs_dir()), "clips": list_pickable_clips()}

    @app.delete("/api/reels/library/{job_id}")
    def delete_reel_job(job_id: str) -> dict:
        try:
            return delete_reel_job_output(job_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e

    @app.get("/api/captions/fonts")
    def caption_fonts() -> dict:
        return {"fonts": list_caption_fonts()}

    @app.get("/api/captions/fonts/{font_id}/preview")
    def caption_font_preview(font_id: str) -> FileResponse:
        path = resolve_font_path(font_id)
        if path is None or not path.is_file():
            raise HTTPException(status_code=404, detail="Font not found")
        return FileResponse(path, media_type="font/ttf")

    @app.post("/api/twitch/download")
    def twitch_download(body: TwitchDownloadBody) -> dict:
        try:
            require_yt_dlp()
            canonical = normalize_twitch_vod_url(body.url)
        except (TwitchDownloadError, ValueError) as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        state = get_twitch_download_manager().start(TwitchDownloadRequest(url=canonical))
        return {"download_id": state.id, **state.model_dump()}

    @app.post("/api/twitch/download/batch")
    def twitch_download_batch(body: TwitchDownloadBatchBody) -> dict:
        try:
            require_yt_dlp()
        except TwitchDownloadError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        mgr = get_twitch_download_manager()
        downloads = []
        ids = []
        for url in body.urls:
            try:
                canonical = normalize_twitch_vod_url(url)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e)) from e
            state = mgr.start(TwitchDownloadRequest(url=canonical))
            downloads.append(state.model_dump())
            ids.append(state.id)
        return {"download_ids": ids, "downloads": downloads}

    @app.get("/api/twitch/downloads")
    def twitch_downloads() -> dict:
        items = get_twitch_download_manager().list_all()
        return {"downloads": [s.model_dump() for s in items]}

    @app.get("/api/twitch/download/{download_id}")
    def twitch_download_get(download_id: str) -> dict:
        state = get_twitch_download_manager().get(download_id)
        if state is None:
            raise HTTPException(status_code=404, detail="Download not found")
        return state.model_dump()

    @app.post("/api/twitch/download/{download_id}/cancel")
    def twitch_download_cancel(download_id: str) -> dict:
        try:
            state = get_twitch_download_manager().cancel(download_id)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        return {"download_id": state.id, "status": state.status}

    @app.get("/api/twitch/download/{download_id}/events")
    def twitch_download_events(download_id: str) -> StreamingResponse:
        mgr = get_twitch_download_manager()
        if mgr.get(download_id) is None:
            raise HTTPException(status_code=404, detail="Download not found")

        def generate():
            for state in mgr.iter_events(download_id, poll_interval=0.4):
                yield f"data: {json.dumps(state.model_dump())}\n\n"
                if state.status in ("completed", "failed", "cancelled"):
                    break

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/jobs/{job_id}/error-log")
    def job_error_log(job_id: str) -> dict:
        state = manager.get_job(job_id)
        if not state:
            raise HTTPException(status_code=404, detail="Job not found")
        err_path = Path(state.output_dir) / "job_error.log"
        global_log = Path(app.state.log_file)
        return {
            "job_id": job_id,
            "job_error_log": str(err_path) if err_path.exists() else None,
            "job_error_tail": err_path.read_text(encoding="utf-8")[-8000:]
            if err_path.exists()
            else None,
            "global_log_file": str(global_log),
            "state_error": state.error,
            "state_log_tail": state.log[-30:] if state.log else [],
        }

    @app.post("/api/upload", response_model=UploadResponse)
    async def upload_vod(file: UploadFile = File(...)) -> UploadResponse:
        if not file.filename or not file.filename.lower().endswith(".mp4"):
            raise HTTPException(status_code=400, detail="Only .mp4 files are allowed")
        try:
            meta, name, size = await save_upload_file(file)
            from reels.video_store import source_path

            return UploadResponse(
                path=str(source_path(meta.slug)),
                filename=name,
                size_bytes=size,
                video_id=meta.slug,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.post("/api/jobs/{job_id}/clear", response_model=CleanupResponse)
    def clear_job_storage(job_id: str) -> CleanupResponse:
        try:
            result = manager.clear_job_storage(job_id)
            return CleanupResponse(**result)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        except RuntimeError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e

    @app.post("/api/jobs", response_model=CreateJobResponse)
    def create_job(req: CreateJobRequest) -> CreateJobResponse:
        try:
            state = manager.create_job(req)
            return CreateJobResponse(job_id=state.id)
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except RuntimeError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict:
        state = manager.get_job(job_id)
        if not state:
            raise HTTPException(status_code=404, detail="Job not found")
        return state.model_dump()

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: str) -> dict:
        try:
            state = manager.cancel_job(job_id)
            return state.model_dump()
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e

    @app.post("/api/jobs/{job_id}/export")
    def export_job(job_id: str, body: ExportJobRequest) -> dict:
        try:
            state = manager.export_job(job_id, body)
            return {"job_id": state.id, "status": state.status}
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except RuntimeError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e

    @app.post("/api/jobs/{job_id}/render")
    def render_cleanup(job_id: str, body: RenderJobBody) -> dict:
        try:
            state = manager.render_cleanup(job_id, body)
            return {"job_id": state.id, "status": state.status}
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        except RuntimeError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e

    @app.post("/api/jobs/{job_id}/render-captions")
    def render_captions(job_id: str, body: RenderCaptionsBody) -> dict:
        try:
            state = manager.render_captions(job_id, body)
            return {"job_id": state.id, "status": state.status}
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        except RuntimeError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e

    @app.get("/api/jobs/{job_id}/events")
    def job_events(job_id: str) -> StreamingResponse:
        if not manager.get_job(job_id):
            raise HTTPException(status_code=404, detail="Job not found")

        def generate():
            for state in manager.iter_events(job_id, poll_interval=0.4):
                payload = json.dumps(state.model_dump())
                yield f"data: {payload}\n\n"
                if state.status in (
                    JobStatus.COMPLETED,
                    JobStatus.FAILED,
                    JobStatus.CANCELLED,
                ):
                    break

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/jobs/{job_id}/highlights")
    def job_highlights(job_id: str) -> dict:
        state = manager.get_job(job_id)
        if not state:
            raise HTTPException(status_code=404, detail="Job not found")
        path = Path(state.output_dir) / "highlights.json"
        if not path.exists():
            raise HTTPException(status_code=404, detail="highlights.json not ready")
        doc = load_highlights(path)
        payload = doc.model_dump()
        payload["job_id"] = job_id
        payload["source_video_url"] = f"/api/jobs/{job_id}/source"
        payload["highlights"] = [
            {**hl.model_dump(), "index": i} for i, hl in enumerate(doc.highlights)
        ]
        try:
            info = probe_video(Path(doc.source_video))
            yt_w, yt_h = default_youtube_size(info.width, info.height)
            rl_w, rl_h = default_reels_size(info.width, info.height)
            payload["source_width"] = info.width
            payload["source_height"] = info.height
            payload["youtube_presets"] = [p.model_dump() for p in youtube_presets(info.width, info.height)]
            payload["reels_presets"] = [p.model_dump() for p in reels_presets(info.width, info.height)]
            payload["default_youtube"] = {
                "id": "native",
                "label": "Native",
                "width": yt_w,
                "height": yt_h,
            }
            payload["default_reels"] = {
                "id": "source_height",
                "label": "Source height",
                "width": rl_w,
                "height": rl_h,
            }
        except Exception:
            pass
        return payload

    @app.get("/api/jobs/{job_id}/edl")
    def job_edl(job_id: str) -> dict:
        state = manager.get_job(job_id)
        if not state:
            raise HTTPException(status_code=404, detail="Job not found")
        path = Path(state.output_dir) / "edl.json"
        if not path.exists():
            raise HTTPException(status_code=404, detail="EDL not ready")
        doc = load_edl(path)
        return {
            "job_id": job_id,
            "source_video_url": f"/api/jobs/{job_id}/source",
            "total_duration": doc.total_duration,
            "kept_duration": doc.kept_duration,
            "cut_duration": doc.cut_duration,
            "llm_available": doc.llm_available,
            "spans": [s.model_dump() for s in doc.spans],
        }

    @app.get("/api/jobs/{job_id}/final")
    def job_final(job_id: str) -> dict:
        state = manager.get_job(job_id)
        if not state:
            raise HTTPException(status_code=404, detail="Job not found")
        out = Path(state.output_dir)
        videos = []
        for fmt, label in (("youtube", "YouTube"), ("reels", "Reels")):
            fn = "final.mp4"
            path = out / fmt / fn
            if path.is_file():
                videos.append(
                    {
                        "format": fmt,
                        "url": f"/media/{job_id}/{fmt}/{fn}",
                        "filename": fn,
                    }
                )
        if not videos:
            raise HTTPException(status_code=404, detail="Final video not ready")
        return {"job_id": job_id, "output_dir": str(out), "videos": videos}

    @app.get("/api/jobs/{job_id}/captions")
    def job_captions_get(job_id: str) -> dict:
        state = manager.get_job(job_id)
        if not state:
            raise HTTPException(status_code=404, detail="Job not found")
        path = Path(state.output_dir) / "captions.json"
        if not path.exists():
            raise HTTPException(status_code=404, detail="Captions not ready")
        doc = load_captions(path)
        return {
            "job_id": job_id,
            "source_video_url": f"/api/jobs/{job_id}/source",
            "font_id": doc.font_id,
            "style": "karaoke",
            "segments": [s.model_dump() for s in doc.segments],
            "segments_original": [s.model_dump() for s in doc.segments_original],
            "warnings": doc.warnings,
        }

    @app.put("/api/jobs/{job_id}/captions")
    def job_captions_put(job_id: str, body: SaveCaptionsBody) -> dict:
        state = manager.get_job(job_id)
        if not state:
            raise HTTPException(status_code=404, detail="Job not found")
        path = Path(state.output_dir) / "captions.json"
        if not path.exists():
            raise HTTPException(status_code=404, detail="Captions not ready")
        doc = load_captions(path)
        doc.segments = [CaptionSegment.model_validate(s) for s in body.segments]
        if body.font_id:
            doc.font_id = body.font_id
        write_captions(path, doc)
        return {
            "job_id": job_id,
            "source_video_url": f"/api/jobs/{job_id}/source",
            "font_id": doc.font_id,
            "style": "karaoke",
            "segments": [s.model_dump() for s in doc.segments],
            "segments_original": [s.model_dump() for s in doc.segments_original],
            "warnings": doc.warnings,
        }

    @app.get("/api/jobs/{job_id}/captioned")
    def job_captioned(job_id: str) -> dict:
        state = manager.get_job(job_id)
        if not state:
            raise HTTPException(status_code=404, detail="Job not found")
        fn = "captioned.mp4"
        path = Path(state.output_dir) / "reels" / fn
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Captioned video not ready")
        return {
            "job_id": job_id,
            "output_dir": state.output_dir,
            "url": f"/media/{job_id}/reels/{fn}",
            "filename": fn,
        }

    @app.get("/api/jobs/{job_id}/publish")
    def job_publish(job_id: str) -> dict:
        state = manager.get_job(job_id)
        if not state:
            raise HTTPException(status_code=404, detail="Job not found")
        path = Path(state.output_dir) / "publish" / "manifest.json"
        if not path.exists():
            raise HTTPException(status_code=404, detail="Publish manifest not ready")
        doc = load_publish(path)
        items = []
        for i, item in enumerate(doc.items):
            row = item.model_dump()
            row["index"] = i
            row["thumbnail_url"] = (
                f"/api/jobs/{job_id}/publish/{i}/thumbnail"
                if item.thumbnail_path
                else None
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

    @app.get("/api/jobs/{job_id}/publish/{index}/thumbnail")
    def job_publish_thumbnail(job_id: str, index: int) -> FileResponse:
        state = manager.get_job(job_id)
        if not state:
            raise HTTPException(status_code=404, detail="Job not found")
        path = Path(state.output_dir) / "publish" / "manifest.json"
        if not path.exists():
            raise HTTPException(status_code=404, detail="Publish manifest not ready")
        doc = load_publish(path)
        if index < 0 or index >= len(doc.items):
            raise HTTPException(status_code=404, detail="Item not found")
        thumb = Path(doc.items[index].thumbnail_path)
        if not thumb.is_file():
            raise HTTPException(status_code=404, detail="Thumbnail not found")
        return FileResponse(thumb, media_type="image/jpeg")

    @app.get("/api/jobs/{job_id}/clips", response_model=ClipsResponse)
    def job_clips(job_id: str) -> ClipsResponse:
        state = manager.get_job(job_id)
        if not state:
            raise HTTPException(status_code=404, detail="Job not found")
        out = Path(state.output_dir)
        return ClipsResponse(
            job_id=job_id,
            output_dir=str(out),
            clips=list_clips(job_id, out),
        )

    @app.get("/api/jobs/{job_id}/source")
    def job_source(job_id: str) -> FileResponse:
        state = manager.get_job(job_id)
        if not state:
            raise HTTPException(status_code=404, detail="Job not found")
        path = Path(state.video_path)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Source video not found")
        return FileResponse(path, media_type="video/mp4")

    @app.get("/media/{job_id}/{format}/{filename}")
    def serve_media(job_id: str, format: str, filename: str) -> FileResponse:
        try:
            clip = resolve_media_clip(job_id, format, filename)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        if not is_readable_clip(clip):
            state = manager.get_job(job_id)
            if state:
                alt = Path(state.output_dir) / format / filename
                if alt.resolve().is_file():
                    clip = alt.resolve()
                else:
                    raise HTTPException(status_code=404, detail="File not found")
            else:
                raise HTTPException(status_code=404, detail="File not found")
        return FileResponse(clip, media_type="video/mp4")

    web_dist = Path(__file__).resolve().parents[3] / "web" / "dist"
    if web_dist.is_dir():
        app.mount("/", StaticFiles(directory=str(web_dist), html=True), name="static")

    return app
