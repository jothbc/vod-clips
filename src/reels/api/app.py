"""FastAPI application."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from reels.api.schemas import UploadResponse
from reels.api.upload import save_upload_file
from reels.api.publish_wallet import router as publish_wallet_router
from reels.api.videos import router as v2_router
from reels.caption_fonts import list_caption_fonts, resolve_font_path
from reels.config import load_config
from reels.export import require_ffmpeg
from reels.logging_config import setup_logging
from reels.twitch.download import TwitchDownloadError, normalize_twitch_vod_url, require_yt_dlp
from reels.twitch.manager import TwitchDownloadRequest, get_twitch_download_manager
from reels.vlm.ollama import OllamaClient


class TwitchDownloadBody(BaseModel):
    url: str


class TwitchDownloadBatchBody(BaseModel):
    urls: list[str] = Field(default_factory=list)


def create_app() -> FastAPI:
    log_path = setup_logging()
    app = FastAPI(title="Reels", description="Twitch VOD -> YouTube + Reels clips")
    app.state.log_file = str(log_path)

    from reels.db import init_db
    from reels.twitch.download import clear_av_ssl_env
    from reels.video_store import sync_from_filesystem

    cleared = clear_av_ssl_env()
    if cleared:
        logging.getLogger(__name__).info(
            "Cleared AV SSL env vars that break HTTPS downloads: %s", ", ".join(cleared)
        )
    try:
        from reels.http_util import uses_system_trust_store

        if uses_system_trust_store():
            logging.getLogger(__name__).info("HTTPS clients using OS certificate store (truststore)")
    except Exception:
        logging.getLogger(__name__).debug("truststore probe failed", exc_info=True)
    init_db()
    try:
        sync_from_filesystem()
    except Exception:
        logging.getLogger(__name__).warning("Video DB backfill failed at startup", exc_info=True)
    try:
        from reels import job_store

        job_store.reconcile_orphans()
    except Exception:
        logging.getLogger(__name__).warning("Job reconcile failed at startup", exc_info=True)

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
    app.include_router(publish_wallet_router)

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

    web_dist = Path(__file__).resolve().parents[3] / "web" / "dist"
    if web_dist.is_dir():
        app.mount("/", StaticFiles(directory=str(web_dist), html=True), name="static")

    return app
