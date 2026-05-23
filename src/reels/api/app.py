"""FastAPI application."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from reels.api.clips import list_clips
from reels.logging_config import setup_logging
from reels.api.schemas import (
    CleanupResponse,
    ClipsResponse,
    CreateJobResponse,
    HealthResponse,
    UploadResponse,
)
from reels.api.upload import save_upload_file
from reels.config import load_config
from reels.export import require_ffmpeg
from reels.highlights import load_highlights
from reels.jobs import CreateJobRequest, JobManager, JobStatus, get_job_manager
from reels.vlm.ollama import OllamaClient


def create_app() -> FastAPI:
    log_path = setup_logging()
    app = FastAPI(title="Reels", description="Twitch VOD → YouTube + Reels clips")
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

    @app.get("/api/health")
    def health() -> dict:
        ffmpeg_ok = False
        try:
            require_ffmpeg()
            ffmpeg_ok = True
        except Exception:
            pass
        config = load_config("twitch_gaming")
        client = OllamaClient(config)
        return {
            "ffmpeg": ffmpeg_ok,
            "ollama": client.is_available(),
            "ollama_host": config.ollama.resolved_host(),
            "log_file": app.state.log_file,
        }

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
            dest, name, size = await save_upload_file(file)
            return UploadResponse(path=str(dest), filename=name, size_bytes=size)
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

    @app.get("/api/jobs/{job_id}/events")
    def job_events(job_id: str) -> StreamingResponse:
        if not manager.get_job(job_id):
            raise HTTPException(status_code=404, detail="Job not found")

        def generate():
            for state in manager.iter_events(job_id, poll_interval=0.4):
                payload = json.dumps(state.model_dump())
                yield f"data: {payload}\n\n"
                if state.status in (JobStatus.COMPLETED, JobStatus.FAILED):
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
        return load_highlights(path).model_dump()

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

    @app.get("/media/{job_id}/{format}/{filename}")
    def serve_media(job_id: str, format: str, filename: str) -> FileResponse:
        if format not in ("youtube", "reels"):
            raise HTTPException(status_code=400, detail="format must be youtube or reels")
        state = manager.get_job(job_id)
        if not state:
            raise HTTPException(status_code=404, detail="Job not found")
        path = Path(state.output_dir) / format / filename
        if not path.resolve().is_file():
            raise HTTPException(status_code=404, detail="File not found")
        # Prevent path escape
        base = Path(state.output_dir).resolve()
        if not path.resolve().is_relative_to(base):
            raise HTTPException(status_code=403, detail="Forbidden")
        return FileResponse(path, media_type="video/mp4")

    # Optional production static UI
    web_dist = Path(__file__).resolve().parents[3] / "web" / "dist"
    if web_dist.is_dir():
        app.mount("/", StaticFiles(directory=str(web_dist), html=True), name="static")

    return app
