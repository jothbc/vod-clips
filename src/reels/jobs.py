"""Background job runner for web UI."""

from __future__ import annotations

import logging
import threading
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

from reels.config import AnalysisMode, AppConfig, load_config
from reels.pipeline import resolve_output_dir, run_pipeline
from reels.progress import CallbackProgressReporter, ProgressEvent
from reels.probe import probe_video
from reels.storage import cleanup_job_files, is_under_temp_vods, job_output_dir


class JobStatus(str):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class CreateJobRequest(BaseModel):
    video_path: str
    preset: str = "twitch_gaming"
    mode: AnalysisMode = "auto"
    max_clips: int | None = None
    use_nvenc: bool = False
    cleanup: bool = False
    resume: bool = False
    output_dir: str | None = None
    ollama_model: str | None = None


class JobState(BaseModel):
    id: str
    status: str = JobStatus.QUEUED
    video_path: str
    output_dir: str = ""
    preset: str = "twitch_gaming"
    mode: str = "auto"
    phase: str = "queued"
    current: int = 0
    total: int | None = None
    message: str = ""
    percent: float = 0.0
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    highlight_count: int = 0
    uploaded_vod: bool = False
    cleaned_up: bool = False
    created_at: str = ""
    updated_at: str = ""
    log: list[str] = Field(default_factory=list)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_job_error_log(output_dir: Path, job_id: str, error: BaseException, tb: str) -> None:
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "job_error.log"
        path.write_text(
            f"job_id={job_id}\nerror={error!r}\n\n{tb}",
            encoding="utf-8",
        )
    except OSError as e:
        logger.warning("Could not write job_error.log: %s", e)


def validate_video_path(path_str: str) -> Path:
    """Validate local VOD path for web API."""
    raw = Path(path_str).expanduser()
    if not raw.is_absolute():
        raw = raw.resolve()
    else:
        raw = raw.resolve()

    if ".." in path_str.replace("\\", "/"):
        raise ValueError("Path must not contain '..'")

    if not raw.exists():
        raise FileNotFoundError(f"Video not found: {raw}")
    if not raw.is_file():
        raise ValueError(f"Not a file: {raw}")
    if raw.suffix.lower() != ".mp4":
        raise ValueError("Only .mp4 files are supported")

    return raw


class JobManager:
    """In-memory job store; one active pipeline at a time."""

    def __init__(self) -> None:
        self._jobs: dict[str, JobState] = {}
        self._events: dict[str, list[ProgressEvent]] = {}
        self._lock = threading.Lock()
        self._running = False
        self._subscribers: dict[str, list[Callable[[JobState], None]]] = {}

    def create_job(self, req: CreateJobRequest) -> JobState:
        with self._lock:
            if self._running:
                raise RuntimeError("Another job is already running. Wait for it to finish.")

            video = validate_video_path(req.video_path)
            job_id = str(uuid.uuid4())
            if req.output_dir:
                out = Path(req.output_dir).resolve()
            elif is_under_temp_vods(video):
                out = job_output_dir(job_id)
            else:
                out = resolve_output_dir(video, None)
            now = _utc_now()
            state = JobState(
                id=job_id,
                status=JobStatus.QUEUED,
                video_path=str(video),
                output_dir=str(out),
                preset=req.preset,
                mode=req.mode,
                uploaded_vod=is_under_temp_vods(video),
                created_at=now,
                updated_at=now,
            )
            self._jobs[job_id] = state
            self._events[job_id] = []
            self._running = True

        thread = threading.Thread(
            target=self._run_job,
            args=(job_id, video, out, req),
            daemon=True,
        )
        thread.start()
        return state

    def get_job(self, job_id: str) -> JobState | None:
        return self._jobs.get(job_id)

    def clear_job_storage(self, job_id: str) -> dict:
        """Remove temp VOD and output clips for a completed/failed job."""
        with self._lock:
            state = self._jobs.get(job_id)
            if not state:
                raise KeyError(f"Job not found: {job_id}")
            if state.cleaned_up:
                return {
                    "vod_deleted": False,
                    "output_deleted": False,
                    "bytes_freed": 0,
                    "already_cleaned": True,
                }
            if state.status == JobStatus.RUNNING:
                raise RuntimeError("Cannot clear storage while job is running")

        result = cleanup_job_files(state.video_path, state.output_dir)
        result["already_cleaned"] = False
        with self._lock:
            state.cleaned_up = True
            state.updated_at = _utc_now()
        return result

    def _notify(self, job_id: str, state: JobState) -> None:
        for cb in self._subscribers.get(job_id, []):
            try:
                cb(state)
            except Exception:
                pass

    def _append_log(self, state: JobState, line: str) -> None:
        state.log.append(line)
        if len(state.log) > 200:
            state.log = state.log[-200:]

    def _update_from_event(self, state: JobState, event: ProgressEvent) -> None:
        state.phase = event.phase
        state.current = event.current
        state.total = event.total
        state.message = event.message
        state.percent = round(event.percent, 1)
        state.updated_at = _utc_now()
        self._append_log(state, f"[{event.phase}] {event.message}")

    def _run_job(
        self,
        job_id: str,
        video: Path,
        out: Path,
        req: CreateJobRequest,
    ) -> None:
        state = self._jobs[job_id]
        state.status = JobStatus.RUNNING
        state.updated_at = _utc_now()

        def on_event(event: ProgressEvent) -> None:
            with self._lock:
                self._update_from_event(state, event)
                self._events[job_id].append(event)
            self._notify(job_id, state)

        reporter = CallbackProgressReporter(on_event=on_event)

        try:
            config = load_config(req.preset)
            config.analysis.mode = req.mode
            if req.max_clips is not None:
                config.clip.max_clips = req.max_clips
            if req.ollama_model:
                config.ollama.vision_model = req.ollama_model

            reporter.report("probe", message="Probing video...")
            info = probe_video(video)
            reporter.mark_phase_complete("probe")

            run_pipeline(
                video,
                config,
                out,
                mode=req.mode,
                resume=req.resume,
                use_nvenc=req.use_nvenc,
                cleanup=req.cleanup,
                reporter=reporter,
                skip_probe=True,
                video_info=info,
            )

            from reels.highlights import load_highlights

            doc = load_highlights(out / "highlights.json")
            state.highlight_count = len(doc.highlights)
            state.warnings = list(doc.warnings)
            state.status = JobStatus.COMPLETED
            state.phase = "done"
            state.percent = 100.0
            state.message = f"Done — {len(doc.highlights)} highlights exported"
        except Exception as e:
            tb = traceback.format_exc()
            logger.error("Job %s failed: %s\n%s", job_id, e, tb)
            _write_job_error_log(out, job_id, e, tb)
            state.status = JobStatus.FAILED
            state.error = str(e)
            state.phase = "failed"
            state.message = str(e)
            self._append_log(state, f"ERROR: {e}")
            self._append_log(state, f"See temp/logs/reels.log and {out}/job_error.log")
        finally:
            state.updated_at = _utc_now()
            with self._lock:
                self._running = False
            self._notify(job_id, state)

    def iter_events(self, job_id: str, poll_interval: float = 0.5) -> Iterator[JobState]:
        """Yield job state snapshots for SSE (poll until terminal)."""
        last_len = 0
        while True:
            state = self.get_job(job_id)
            if state is None:
                break
            yield state
            if state.status in (JobStatus.COMPLETED, JobStatus.FAILED):
                break
            with self._lock:
                ev_len = len(self._events.get(job_id, []))
            if ev_len == last_len:
                time.sleep(poll_interval)
            last_len = ev_len


# Singleton for FastAPI
_manager: JobManager | None = None


def get_job_manager() -> JobManager:
    global _manager
    if _manager is None:
        _manager = JobManager()
    return _manager
