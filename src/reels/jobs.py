"""Background job runner for web UI."""

from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

from reels.captions import build_caption_segments, load_captions, write_captions
from reels.captions_render import write_ass_file
from reels.cleanup import (
    build_edl,
    keep_spans_after_cuts,
    load_edl,
    propose_llm_cuts,
    verify_cuts,
    write_edl,
)
from reels.config import AnalysisMode, AppConfig, load_config
from reels.export import export_selected, load_export_profiles, require_ffmpeg
from reels.export_resolution import ExportResolution, resolve_reels_size, resolve_youtube_size
from reels.highlights import load_highlights
from reels.models import CaptionsDocument, PublishDocument, PublishItem
from reels.pipeline import analyze_vod, resolve_output_dir, run_pipeline
from reels.progress import FEATURE_PHASE_WEIGHTS, PHASE_WEIGHTS, CallbackProgressReporter, ProgressEvent
from reels.probe import probe_video
from reels.publish import (
    generate_metadata,
    load_publish,
    parse_publish_context,
    slug_from_path,
    write_publish,
)
from reels.proxy import generate_proxy
from reels.storage import cleanup_job_files, is_under_temp_vods, job_output_dir
from reels.video_store import analysis_dir, clip_dir, source_path
from reels.video_transcript import load_or_transcribe
from reels.thumbnail import overlay_title_on_image, target_dimensions
from reels.transcribe import transcribe_audio
from reels.vlm.ollama import OllamaClient


class JobStatus(str):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_REVIEW = "awaiting_review"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CreateJobRequest(BaseModel):
    video_path: str
    feature: str = "reels"
    preset: str = "twitch_gaming"
    mode: AnalysisMode = "auto"
    max_clips: int | None = None
    use_nvenc: bool = False
    cleanup: bool = False
    resume: bool = False
    output_dir: str | None = None
    ollama_model: str | None = None
    export_clips: bool = False
    params: dict[str, Any] = Field(default_factory=dict)
    previous_job_id: str | None = None


class ExportJobRequest(BaseModel):
    highlight_indices: list[int]
    use_nvenc: bool = False
    youtube_resolution: dict[str, int] | None = None
    reels_resolution: dict[str, int] | None = None


class RenderJobBody(BaseModel):
    cut_indices: list[int] = Field(default_factory=list)
    formats: list[str] | None = None
    use_nvenc: bool = False


class RenderCaptionsBody(BaseModel):
    segments: list[dict[str, Any]] | None = None
    font_id: str | None = None
    use_nvenc: bool = False
    output_format: str = "native"


class ResetSessionRequest(BaseModel):
    previous_job_id: str | None = None
    cleanup_previous: bool = True


class JobState(BaseModel):
    id: str
    status: str = JobStatus.QUEUED
    video_path: str
    output_dir: str = ""
    feature: str = "reels"
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
    clips_exported: bool = False
    result_clip_id: str | None = None
    result_video_id: str | None = None
    trim_output_path: str | None = None
    trim_finalized: bool = False
    uploaded_vod: bool = False
    cleaned_up: bool = False
    cancel_requested: bool = False
    created_at: str = ""
    updated_at: str = ""
    log: list[str] = Field(default_factory=list)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_job_error_log(output_dir: Path, job_id: str, error: BaseException, tb: str) -> None:
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "job_error.log"
        path.write_text(f"job_id={job_id}\nerror={error!r}\n\n{tb}", encoding="utf-8")
    except OSError as e:
        logger.warning("Could not write job_error.log: %s", e)


def _append_activity_log(output_dir: Path, line: str) -> None:
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "activity.log"
        with path.open("a", encoding="utf-8") as f:
            f.write(f"{_utc_now()} {line}\n")
    except OSError:
        pass


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


def _build_span_encode_cmd(
    source_video: Path,
    start: float,
    end: float,
    output_path: Path,
    *,
    codec: str,
    enc_args: list[str],
    crop_filter: str | None,
    threads: int,
) -> list[str]:
    """Command to encode a single span; keeps memory bounded to one segment."""
    duration = max(0.01, end - start)
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        str(start),
        "-i",
        str(source_video),
        "-t",
        str(duration),
    ]
    if crop_filter:
        cmd.extend(["-vf", crop_filter])
    cmd.extend(
        [
            "-c:v",
            codec,
            *enc_args,
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-threads",
            str(max(1, threads)),
            "-max_muxing_queue_size",
            "1024",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )
    return cmd


def _export_kept_spans(
    source_video: Path,
    keep_spans: list[tuple[float, float]],
    output_path: Path,
    *,
    crop_filter: str | None = None,
    use_nvenc: bool = False,
    config: AppConfig,
    on_progress: Callable[[float], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> None:
    """Encode each span independently, then concat with stream copy (low RAM)."""
    from reels.export import load_export_profiles, select_video_encoder
    from reels.ffmpeg_runner import run_ffmpeg

    require_ffmpeg()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not keep_spans:
        raise ValueError("No content to export")

    profiles = load_export_profiles()
    codec, enc_args = select_video_encoder(profiles.youtube, config, use_nvenc)
    threads = max(1, min(6, int(getattr(config.hardware, "ffmpeg_threads", 4) or 4)))
    total_duration = sum(max(0.01, end - start) for start, end in keep_spans)

    if len(keep_spans) == 1:
        start, end = keep_spans[0]
        cmd = _build_span_encode_cmd(
            source_video,
            start,
            end,
            output_path,
            codec=codec,
            enc_args=enc_args,
            crop_filter=crop_filter,
            threads=threads,
        )
        run_ffmpeg(
            cmd,
            expected_duration_sec=total_duration,
            on_progress=on_progress,
            cancel_event=cancel_event,
        )
        return

    work_dir = output_path.parent / f".{output_path.stem}_parts"
    work_dir.mkdir(parents=True, exist_ok=True)
    part_paths: list[Path] = []
    accumulated = 0.0
    try:
        for i, (start, end) in enumerate(keep_spans):
            if cancel_event and cancel_event.is_set():
                raise RuntimeError("Cancelled")
            span_dur = max(0.01, end - start)
            part = work_dir / f"part_{i:04d}.mp4"
            base = accumulated

            def on_part_progress(frac: float, base=base, span_dur=span_dur) -> None:
                if on_progress is None:
                    return
                done = base + span_dur * frac
                on_progress(min(1.0, done / total_duration))

            cmd = _build_span_encode_cmd(
                source_video,
                start,
                end,
                part,
                codec=codec,
                enc_args=enc_args,
                crop_filter=crop_filter,
                threads=threads,
            )
            run_ffmpeg(
                cmd,
                expected_duration_sec=span_dur,
                on_progress=on_part_progress if on_progress else None,
                cancel_event=cancel_event,
            )
            part_paths.append(part)
            accumulated += span_dur

        list_file = work_dir / "concat.txt"
        list_file.write_text(
            "\n".join(f"file '{p.as_posix()}'" for p in part_paths) + "\n",
            encoding="utf-8",
        )
        concat_cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
        run_ffmpeg(
            concat_cmd,
            expected_duration_sec=total_duration,
            on_progress=None,
            cancel_event=cancel_event,
        )
        if on_progress is not None:
            on_progress(1.0)
    finally:
        for p in part_paths:
            try:
                p.unlink()
            except OSError:
                pass
        try:
            (work_dir / "concat.txt").unlink()
        except OSError:
            pass
        try:
            work_dir.rmdir()
        except OSError:
            pass


class JobManager:
    """In-memory job store; one active pipeline at a time."""

    def __init__(self) -> None:
        self._jobs: dict[str, JobState] = {}
        self._events: dict[str, list[ProgressEvent]] = {}
        self._lock = threading.Lock()
        self._running = False
        self._current_job_id: str | None = None
        self._cancel_events: dict[str, threading.Event] = {}
        self._subscribers: dict[str, list[Callable[[JobState], None]]] = {}

    def create_job(self, req: CreateJobRequest) -> JobState:
        if req.previous_job_id:
            try:
                self.clear_job_storage(req.previous_job_id)
            except (KeyError, RuntimeError):
                pass

        with self._lock:
            if self._running:
                raise RuntimeError("Another job is already running. Wait for it to finish.")

            if req.feature == "publish":
                video_paths = req.params.get("video_paths") or [req.video_path]
                video = validate_video_path(str(video_paths[0]))
            else:
                video = validate_video_path(req.video_path)

            job_id = str(uuid.uuid4())
            if req.output_dir:
                base = Path(req.output_dir).resolve()
                if req.feature in ("v2_cleanup", "v2_captions"):
                    out = base / job_id
                else:
                    out = base
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
                feature=req.feature,
                preset=req.preset,
                mode=req.mode,
                uploaded_vod=is_under_temp_vods(video),
                created_at=now,
                updated_at=now,
            )
            self._jobs[job_id] = state
            self._events[job_id] = []
            self._cancel_events[job_id] = threading.Event()
            self._running = True
            self._current_job_id = job_id

        thread = threading.Thread(
            target=self._run_job,
            args=(job_id, video, out, req),
            daemon=True,
        )
        thread.start()
        return state

    def get_job(self, job_id: str) -> JobState | None:
        return self._jobs.get(job_id)

    def active_job(self) -> JobState | None:
        with self._lock:
            if self._current_job_id:
                return self._jobs.get(self._current_job_id)
        return None

    def cancel_job(self, job_id: str) -> JobState:
        with self._lock:
            state = self._jobs.get(job_id)
            if state is None:
                raise KeyError(f"Job not found: {job_id}")
            event = self._cancel_events.get(job_id)
            if event:
                event.set()
            state.cancel_requested = True
            state.phase = "cancelling"
            state.message = "Cancellation requested"
            state.updated_at = _utc_now()
            return state

    def reset_session(
        self,
        previous_job_id: str | None = None,
        cleanup_previous: bool = True,
    ) -> dict:
        with self._lock:
            if self._current_job_id:
                event = self._cancel_events.get(self._current_job_id)
                if event:
                    event.set()
                state = self._jobs.get(self._current_job_id)
                if state:
                    state.cancel_requested = True
                    state.phase = "cancelling"

        if previous_job_id and cleanup_previous:
            try:
                self.clear_job_storage(previous_job_id)
            except (KeyError, RuntimeError):
                pass

        return {"cancelled": True}

    def export_job(self, job_id: str, req: ExportJobRequest) -> JobState:
        with self._lock:
            state = self._jobs.get(job_id)
            if state is None:
                raise KeyError(f"Job not found: {job_id}")
            if state.status != JobStatus.COMPLETED:
                raise RuntimeError("Job must be completed before export")
            if self._running:
                raise RuntimeError("Another job is already running")

        out = Path(state.output_dir)
        highlights_path = out / "highlights.json"
        if highlights_path.is_file():
            doc = load_highlights(highlights_path)
            video_path = Path(doc.source_video)
        else:
            video_path = Path(state.video_path)
        info = probe_video(video_path)
        if req.youtube_resolution:
            resolve_youtube_size(
                ExportResolution(**req.youtube_resolution),
                info.width,
                info.height,
            )
        if req.reels_resolution:
            resolve_reels_size(
                ExportResolution(**req.reels_resolution),
                info.width,
                info.height,
            )

        with self._lock:
            self._running = True
            self._current_job_id = job_id
            state.status = JobStatus.RUNNING
            state.phase = "export"
            state.percent = 0.0
            state.message = "Exporting clips..."
            state.updated_at = _utc_now()

        thread = threading.Thread(
            target=self._run_export,
            args=(job_id, req),
            daemon=True,
        )
        thread.start()
        return state

    def render_cleanup(self, job_id: str, body: RenderJobBody) -> JobState:
        with self._lock:
            state = self._jobs.get(job_id)
            if state is None:
                raise KeyError(f"Job not found: {job_id}")
            if self._running:
                raise RuntimeError("Another job is already running")

            self._running = True
            self._current_job_id = job_id
            state.status = JobStatus.RUNNING
            state.phase = "render"
            state.percent = 0.0
            state.message = "Rendering final video..."
            state.updated_at = _utc_now()

        thread = threading.Thread(
            target=self._run_cleanup_render,
            args=(job_id, body),
            daemon=True,
        )
        thread.start()
        return state

    def render_captions(self, job_id: str, body: RenderCaptionsBody) -> JobState:
        with self._lock:
            state = self._jobs.get(job_id)
            if state is None:
                raise KeyError(f"Job not found: {job_id}")
            if self._running:
                raise RuntimeError("Another job is already running")

            self._running = True
            self._current_job_id = job_id
            state.status = JobStatus.RUNNING
            state.phase = "render"
            state.percent = 0.0
            state.message = "Rendering captioned video..."
            state.updated_at = _utc_now()

        thread = threading.Thread(
            target=self._run_captions_render,
            args=(job_id, body),
            daemon=True,
        )
        thread.start()
        return state

    def clear_job_storage(self, job_id: str) -> dict:
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

    def _finish_job(
        self,
        job_id: str,
        state: JobState,
        *,
        success: bool,
        message: str = "",
        error: str | None = None,
    ) -> None:
        if success:
            state.status = JobStatus.COMPLETED
            state.phase = "done"
            state.percent = 100.0
            state.message = message or "Done"
        else:
            state.status = JobStatus.FAILED if not state.cancel_requested else JobStatus.CANCELLED
            state.phase = "failed" if not state.cancel_requested else "cancelled"
            state.error = error
            state.message = error or message
        state.updated_at = _utc_now()
        _append_activity_log(Path(state.output_dir), state.message)
        with self._lock:
            self._running = False
            self._current_job_id = None
        self._notify(job_id, state)

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
        cancel_event = self._cancel_events[job_id]

        def on_event(event: ProgressEvent) -> None:
            with self._lock:
                self._update_from_event(state, event)
                self._events[job_id].append(event)
            self._notify(job_id, state)

        weights = FEATURE_PHASE_WEIGHTS.get(req.feature, PHASE_WEIGHTS)
        reporter = CallbackProgressReporter(on_event=on_event, phase_weights=weights)

        try:
            config = load_config(req.preset)
            config.analysis.mode = req.mode
            if req.max_clips is not None:
                config.clip.max_clips = req.max_clips
            if req.ollama_model:
                config.ollama.vision_model = req.ollama_model

            if req.feature == "cleanup":
                self._run_cleanup_analysis(
                    job_id, video, out, config, reporter, cancel_event, state
                )
            elif req.feature == "captions":
                self._run_captions_analysis(
                    job_id, video, out, config, reporter, cancel_event, state
                )
            elif req.feature == "publish":
                self._run_publish_analysis(job_id, out, config, reporter, req, state)
            elif req.feature == "v2_analyze":
                self._run_v2_analyze(
                    job_id, video, out, config, req, reporter, cancel_event, state
                )
            elif req.feature == "v2_export_clips":
                self._run_v2_export_clips(
                    job_id, video, out, config, req, reporter, cancel_event, state
                )
            elif req.feature == "v2_captions":
                self._run_v2_captions(
                    job_id, video, out, config, req, reporter, cancel_event, state
                )
            elif req.feature == "v2_cleanup":
                self._run_v2_cleanup_analysis(
                    job_id, video, out, config, req, reporter, cancel_event, state
                )
            elif req.feature == "v2_trim":
                self._run_v2_trim(
                    job_id, video, out, config, req, reporter, cancel_event, state
                )
            else:
                self._run_reels_analysis(
                    job_id, video, out, config, req, reporter, cancel_event, state
                )
        except Exception as e:
            if cancel_event.is_set() or state.cancel_requested:
                self._finish_job(job_id, state, success=False, error="Cancelled")
                return
            tb = traceback.format_exc()
            logger.error("Job %s failed: %s\n%s", job_id, e, tb)
            _write_job_error_log(out, job_id, e, tb)
            state.error = str(e)
            self._append_log(state, f"ERROR: {e}")
            self._finish_job(job_id, state, success=False, error=str(e))
        finally:
            if state.status == JobStatus.RUNNING:
                with self._lock:
                    self._running = False
                    self._current_job_id = None

    def _run_reels_analysis(
        self,
        job_id: str,
        video: Path,
        out: Path,
        config: AppConfig,
        req: CreateJobRequest,
        reporter: CallbackProgressReporter,
        cancel_event: threading.Event,
        state: JobState,
    ) -> None:
        reporter.report("probe", message="Probing video...")
        info = probe_video(video)
        reporter.mark_phase_complete("probe")
        if cancel_event.is_set():
            raise RuntimeError("Cancelled")

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

        doc = load_highlights(out / "highlights.json")
        state.highlight_count = len(doc.highlights)
        state.warnings = list(doc.warnings)
        self._finish_job(
            job_id,
            state,
            success=True,
            message=f"Done — {len(doc.highlights)} highlights",
        )

    def _transcribe_for_feature(
        self,
        video: Path,
        out: Path,
        config: AppConfig,
        reporter: CallbackProgressReporter,
        cancel_event: threading.Event,
        state: JobState,
    ) -> tuple[Any, list[dict[str, Any]]]:
        reporter.report("probe", message="Probing video...")
        info = probe_video(video)
        reporter.mark_phase_complete("probe")
        if cancel_event.is_set():
            raise RuntimeError("Cancelled")

        reporter.report("proxy", message="Extracting audio...")
        _source, audio_path, _preview = generate_proxy(
            video, out, config, info, skip_if_exists=False
        )
        reporter.mark_phase_complete("proxy")
        if cancel_event.is_set():
            raise RuntimeError("Cancelled")

        warnings: list[str] = []
        reporter.report("transcribe", message="Transcribing (Whisper)...")
        segments = transcribe_audio(audio_path, config, warnings=warnings)
        reporter.mark_phase_complete("transcribe")
        state.warnings = warnings
        if cancel_event.is_set():
            raise RuntimeError("Cancelled")
        return info, segments

    def _run_cleanup_analysis(
        self,
        job_id: str,
        video: Path,
        out: Path,
        config: AppConfig,
        reporter: CallbackProgressReporter,
        cancel_event: threading.Event,
        state: JobState,
    ) -> None:
        info, segments = self._transcribe_for_feature(
            video, out, config, reporter, cancel_event, state
        )
        (out / "segments.json").write_text(json.dumps(segments), encoding="utf-8")

        reporter.report("edl", message="Building edit decision list...")
        client = OllamaClient(config)
        llm_available = client.is_available()
        proposed = propose_llm_cuts(client, config, segments) if config.cleanup.use_llm else []
        if proposed:
            reporter.report("verify", message="Verifying cuts with LLM...")
            proposed = verify_cuts(client, config, segments, proposed)
            reporter.mark_phase_complete("verify")

        doc = build_edl(segments, info.duration, config, proposed, llm_available)
        doc.source_video = str(video)
        write_edl(out / "edl.json", doc)
        reporter.mark_phase_complete("edl")

        self._finish_job(
            job_id,
            state,
            success=True,
            message=f"EDL ready — {len([s for s in doc.spans if s.kind == 'cut'])} proposed cuts",
        )

    def _run_captions_analysis(
        self,
        job_id: str,
        video: Path,
        out: Path,
        config: AppConfig,
        reporter: CallbackProgressReporter,
        cancel_event: threading.Event,
        state: JobState,
    ) -> None:
        _info, segments = self._transcribe_for_feature(
            video, out, config, reporter, cancel_event, state
        )

        reporter.report("segments", message="Building caption segments...")
        built = build_caption_segments(segments, config.captions)
        doc = CaptionsDocument(
            source_video=str(video),
            segments=built,
            segments_original=[s.model_copy(deep=True) for s in built],
            font_id=config.captions.default_font,
            warnings=list(state.warnings),
        )
        write_captions(out / "captions.json", doc)
        reporter.mark_phase_complete("segments")

        self._finish_job(job_id, state, success=True, message="Captions ready")

    def _run_publish_analysis(
        self,
        job_id: str,
        out: Path,
        config: AppConfig,
        reporter: CallbackProgressReporter,
        req: CreateJobRequest,
        state: JobState,
    ) -> None:
        video_paths = [validate_video_path(str(p)) for p in req.params.get("video_paths", [state.video_path])]
        platform = str(req.params.get("platform", "youtube"))
        ctx = parse_publish_context(req.params)
        client = OllamaClient(config)
        publish_root = out / "publish"
        items: list[PublishItem] = []
        warnings: list[str] = []

        for index, video in enumerate(video_paths):
            reporter.report("probe", message=f"Probing {video.name}...")
            info = probe_video(video)
            reporter.mark_phase_complete("probe")

            _source, audio_path, _preview = generate_proxy(
                video, out / f"item_{index}", config, info, skip_if_exists=True
            )
            reporter.report("transcribe", message="Transcribing...")
            segments = transcribe_audio(audio_path, config, warnings=warnings)
            reporter.mark_phase_complete("transcribe")

            reporter.report("metadata", message="Generating metadata...")
            metadata, _used_llm = generate_metadata(
                client, config, segments, platform, info, ctx
            )
            reporter.mark_phase_complete("metadata")

            slug = slug_from_path(video.name, index)
            item_dir = publish_root / slug
            item_dir.mkdir(parents=True, exist_ok=True)
            ts = float(metadata.get("thumbnail_second", info.duration * 0.3))
            frame_path = item_dir / "frame.jpg"
            thumb_path = item_dir / "thumbnail.jpg"
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-ss",
                    str(ts),
                    "-i",
                    str(video),
                    "-frames:v",
                    "1",
                    "-q:v",
                    "2",
                    str(frame_path),
                ],
                capture_output=True,
                check=False,
            )
            reporter.report("thumbnail", message="Creating thumbnail...")
            if frame_path.is_file():
                overlay_title_on_image(
                    frame_path,
                    str(metadata.get("title", video.stem)),
                    thumb_path,
                    config=config,
                    platform=platform,
                    work_dir=item_dir,
                    frame_height=info.height,
                )
            reporter.mark_phase_complete("thumbnail")

            items.append(
                PublishItem(
                    video_path=str(video),
                    source_label=video.name,
                    platform=platform,
                    title=str(metadata.get("title", video.stem)),
                    description=str(metadata.get("description", "")),
                    tags=list(metadata.get("tags") or []),
                    thumbnail_timestamp=ts,
                    thumbnail_path=str(thumb_path) if thumb_path.is_file() else "",
                )
            )

        doc = PublishDocument(
            platform=platform,
            content_type=ctx.content_type,
            game_name=ctx.game_name,
            video_context=ctx.video_context,
            channel_info=ctx.channel_info,
            items=items,
            warnings=warnings,
        )
        write_publish(publish_root / "manifest.json", doc)
        reporter.mark_phase_complete("manifest")
        state.warnings = warnings
        self._finish_job(job_id, state, success=True, message=f"Publish metadata for {len(items)} video(s)")

    def _run_export(self, job_id: str, req: ExportJobRequest) -> None:
        state = self._jobs[job_id]
        out = Path(state.output_dir)
        cancel_event = self._cancel_events.setdefault(job_id, threading.Event())

        def on_event(event: ProgressEvent) -> None:
            with self._lock:
                self._update_from_event(state, event)
            self._notify(job_id, state)

        reporter = CallbackProgressReporter(on_event=on_event)

        try:
            config = load_config(state.preset)
            doc = load_highlights(out / "highlights.json")
            video = Path(doc.source_video)
            info = probe_video(video)

            yt_size = None
            reels_size = None
            if req.youtube_resolution:
                yt_size = resolve_youtube_size(
                    ExportResolution(**req.youtube_resolution),
                    info.width,
                    info.height,
                )
            if req.reels_resolution:
                reels_size = resolve_reels_size(
                    ExportResolution(**req.reels_resolution),
                    info.width,
                    info.height,
                )

            export_selected(
                video,
                doc,
                req.highlight_indices,
                out,
                config,
                use_nvenc=req.use_nvenc,
                source_width=info.width,
                source_height=info.height,
                youtube_size=yt_size,
                reels_size=reels_size,
                reporter=reporter,
            )
            state.clips_exported = True
            self._finish_job(job_id, state, success=True, message="Export complete")
        except Exception as e:
            tb = traceback.format_exc()
            _write_job_error_log(out, job_id, e, tb)
            self._finish_job(job_id, state, success=False, error=str(e))

    def _run_cleanup_render(self, job_id: str, body: RenderJobBody) -> None:
        state = self._jobs[job_id]
        out = Path(state.output_dir)
        config = load_config(state.preset)
        profiles = load_export_profiles()

        try:
            edl = load_edl(out / "edl.json")
            video = Path(edl.source_video or state.video_path)
            info = probe_video(video)
            keep = keep_spans_after_cuts(edl, body.cut_indices)
            formats = body.formats or list(config.cleanup.formats)

            from reels.export import build_crop_filter, build_scale_filter
            from reels.export_resolution import default_reels_size, default_youtube_size

            rl_w, rl_h = default_reels_size(info.width, info.height)
            reels_profile = profiles.reels.model_copy(update={"width": rl_w, "height": rl_h})
            for fmt in formats:
                dest = out / fmt / "final.mp4"
                if fmt == "reels":
                    crop = build_crop_filter(info.width, info.height, reels_profile)
                    _export_kept_spans(
                        video,
                        keep,
                        dest,
                        crop_filter=crop,
                        use_nvenc=body.use_nvenc,
                        config=config,
                    )
                else:
                    yt_w, yt_h = default_youtube_size(info.width, info.height)
                    yt_profile = profiles.youtube.model_copy(update={"width": yt_w, "height": yt_h})
                    scale = build_scale_filter(info.width, info.height, yt_profile)
                    _export_kept_spans(
                        video,
                        keep,
                        dest,
                        crop_filter=scale if scale != "null" else None,
                        use_nvenc=body.use_nvenc,
                        config=config,
                    )

            self._finish_job(job_id, state, success=True, message="Final video rendered")
        except Exception as e:
            tb = traceback.format_exc()
            _write_job_error_log(out, job_id, e, tb)
            self._finish_job(job_id, state, success=False, error=str(e))

    def _run_captions_render(self, job_id: str, body: RenderCaptionsBody) -> None:
        state = self._jobs[job_id]
        out = Path(state.output_dir)
        config = load_config(state.preset)

        try:
            doc = load_captions(out / "captions.json")
            if body.segments:
                from reels.models import CaptionSegment

                doc.segments = [CaptionSegment.model_validate(s) for s in body.segments]
            if body.font_id:
                doc.font_id = body.font_id
                write_captions(out / "captions.json", doc)

            video = Path(doc.source_video or state.video_path)
            info = probe_video(video)
            ass_path = out / "captions.ass"
            from reels.caption_fonts import resolve_font_path

            font_path = resolve_font_path(doc.font_id)
            font_family = font_path.stem if font_path else "Arial"
            write_ass_file(
                doc,
                ass_path,
                video_width=info.width,
                video_height=info.height,
                font_family=font_family,
                config=config.captions,
            )
            output_path = out / "reels" / "captioned.mp4"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            from reels import captions_render

            captions_render.render_captioned_video(
                video,
                ass_path,
                output_path,
                font_id=doc.font_id,
                config=config,
                use_nvenc=body.use_nvenc,
            )
            self._finish_job(job_id, state, success=True, message="Captioned video ready")
        except Exception as e:
            tb = traceback.format_exc()
            _write_job_error_log(out, job_id, e, tb)
            self._finish_job(job_id, state, success=False, error=str(e))

    def _run_v2_analyze(
        self,
        job_id: str,
        video: Path,
        out: Path,
        config: AppConfig,
        req: CreateJobRequest,
        reporter: CallbackProgressReporter,
        cancel_event: threading.Event,
        state: JobState,
    ) -> None:
        from reels.export_resolution import default_reels_size, default_youtube_size, reels_presets, youtube_presets
        from reels.heuristic import rank_heuristic_windows
        from reels.highlights import gaming_highlights_from_windows, write_highlights
        from reels.models import HighlightsDocument
        from reels.proxy import generate_proxy
        from reels.video_store import audio_path as transcript_audio, highlights_path

        slug = str(req.params.get("video_slug", ""))
        if not slug:
            raise ValueError("video_slug required for v2_analyze")

        reporter.report("probe", message="Probing video...")
        info = probe_video(video)
        reporter.mark_phase_complete("probe")
        if cancel_event.is_set():
            raise RuntimeError("Cancelled")

        reporter.report("transcribe", message="Loading or transcribing...")
        _meta, segments = load_or_transcribe(slug, config, warnings=state.warnings)
        reporter.mark_phase_complete("transcribe")
        if cancel_event.is_set():
            raise RuntimeError("Cancelled")

        existing_audio = transcript_audio(slug)
        if existing_audio.is_file():
            reporter.report("proxy", message="Using existing transcript audio...")
            analysis_audio = existing_audio
            analysis_video = video
            reporter.mark_phase_complete("proxy")
        else:
            reporter.report("proxy", message="Extracting audio for analysis...")
            out.mkdir(parents=True, exist_ok=True)
            proxy_path, audio_path, _ = generate_proxy(video, out, config, info, skip_if_exists=True)
            analysis_audio = audio_path
            analysis_video = proxy_path if config.proxy.video_mode != "audio_only" else video
            reporter.mark_phase_complete("proxy")
        if cancel_event.is_set():
            raise RuntimeError("Cancelled")

        reporter.report("heuristic", message="Ranking highlight windows...")
        windows = rank_heuristic_windows(
            analysis_audio, analysis_video, info.duration, config, segments
        )
        highlights = gaming_highlights_from_windows(windows, config)
        doc = HighlightsDocument(
            source_video=str(video),
            preset=config.preset,
            mode="gaming",
            vlm_available=False,
            highlights=highlights,
        )
        hl_path = highlights_path(slug)
        write_highlights(hl_path, doc)
        state.highlight_count = len(highlights)
        reporter.mark_phase_complete("heuristic")
        self._finish_job(
            job_id,
            state,
            success=True,
            message=f"Analysis done — {len(highlights)} highlights",
        )

    def _run_v2_export_clips(
        self,
        job_id: str,
        video: Path,
        out: Path,
        config: AppConfig,
        req: CreateJobRequest,
        reporter: CallbackProgressReporter,
        cancel_event: threading.Event,
        state: JobState,
    ) -> None:
        from reels.export import export_clip, load_export_profiles
        from reels.export_resolution import default_reels_size, default_youtube_size
        from reels.models import ClipMetadata, Highlight
        from reels.video_store import clip_dir, save_clip_metadata

        slug = str(req.params.get("video_slug", ""))
        selections = req.params.get("selections") or []
        if not slug:
            raise ValueError("video_slug required for v2_export_clips")
        if not selections:
            raise ValueError("No clip selections provided")

        use_nvenc = bool(req.params.get("use_nvenc", req.use_nvenc))
        pre_pad = float(req.params.get("pre_pad_seconds", config.clip.pre_pad_seconds))
        post_pad = float(req.params.get("post_pad_seconds", config.clip.post_pad_seconds))

        reporter.report("probe", message="Probing video...")
        info = probe_video(video)
        reporter.mark_phase_complete("probe")
        if cancel_event.is_set():
            raise RuntimeError("Cancelled")

        profiles = load_export_profiles()
        yt_w, yt_h = default_youtube_size(info.width, info.height)
        rl_w, rl_h = default_reels_size(info.width, info.height)
        yt_profile = profiles.youtube.model_copy(update={"width": yt_w, "height": yt_h})
        reels_profile = profiles.reels.model_copy(update={"width": rl_w, "height": rl_h})

        total_steps = sum(
            1
            for sel in selections
            if sel.get("export_youtube") or sel.get("export_reels")
        )
        step = 0
        exported = 0

        for sel in selections:
            if cancel_event.is_set():
                raise RuntimeError("Cancelled")
            if not sel.get("export_youtube") and not sel.get("export_reels"):
                continue
            idx = int(sel.get("index", exported))
            start = max(0.0, float(sel.get("start", 0)) - pre_pad)
            end = float(sel.get("end", 0)) + post_pad
            title = str(sel.get("title", "Highlight"))
            clip_slug = f"clip_{idx:02d}"
            highlight = Highlight(start=start, end=end, score=0.0, title=title, reason="")
            out_dir = clip_dir(slug, clip_slug)
            formats: list[str] = []

            if sel.get("export_youtube"):
                step += 1
                reporter.report(
                    "export",
                    current=step,
                    total=total_steps,
                    message=f"Exporting YouTube clip {idx + 1}",
                )
                export_clip(
                    video,
                    highlight,
                    out_dir / "youtube.mp4",
                    yt_profile,
                    config,
                    use_nvenc=use_nvenc,
                    source_width=info.width,
                    source_height=info.height,
                )
                formats.append("youtube")

            if sel.get("export_reels"):
                step += 1
                reporter.report(
                    "export",
                    current=step,
                    total=total_steps,
                    message=f"Exporting Reels clip {idx + 1}",
                )
                export_clip(
                    video,
                    highlight,
                    out_dir / "reels.mp4",
                    reels_profile,
                    config,
                    use_nvenc=use_nvenc,
                    source_width=info.width,
                    source_height=info.height,
                )
                formats.append("reels")

            save_clip_metadata(
                slug,
                ClipMetadata(
                    clip_slug=clip_slug,
                    parent_slug=slug,
                    title=title,
                    start=start,
                    end=end,
                    formats=formats,
                ),
            )
            exported += 1

        state.clips_exported = exported > 0
        reporter.mark_phase_complete("export")
        self._finish_job(
            job_id,
            state,
            success=True,
            message=f"Exported {exported} clip(s)",
        )

    @staticmethod
    def _slug_from_v2_path(video: Path) -> str:
        if video.parent.name == "original" and video.name == "source.mp4":
            return video.parent.parent.name
        if video.name in ("youtube.mp4", "reels.mp4"):
            parts = video.parts
            try:
                clips_idx = parts.index("clips")
                return parts[clips_idx - 1]
            except ValueError:
                pass
        raise ValueError(f"Cannot resolve VOD slug from path: {video}")

    @staticmethod
    def _write_v2_job_context(out: Path, params: dict[str, Any]) -> None:
        out.mkdir(parents=True, exist_ok=True)
        (out / "v2_job_context.json").write_text(json.dumps(params), encoding="utf-8")

    @staticmethod
    def _load_v2_job_context(out: Path) -> dict[str, Any]:
        path = out / "v2_job_context.json"
        if not path.is_file():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def _v2_job_segments(
        self,
        req: CreateJobRequest,
        slug: str,
        config: AppConfig,
        state: JobState,
    ) -> list[dict[str, Any]]:
        from reels.video_transcript import segments_for_clip_job

        params = req.params
        source_clip = params.get("source_clip_slug")
        if source_clip:
            clip_start = float(params.get("clip_start", 0))
            clip_end = float(params.get("clip_end", clip_start))
            return segments_for_clip_job(
                slug,
                clip_start,
                clip_end,
                config,
                state.warnings,
                shift_to_zero=True,
            )
        _meta, segments = load_or_transcribe(slug, config, warnings=state.warnings)
        return segments

    @staticmethod
    def _register_v2_derivative_clip(
        parent_slug: str,
        ctx: dict[str, Any],
        *,
        suffix: str,
        title_suffix: str,
        source_feature: str,
        start: float,
        end: float,
        files: dict[str, Path],
    ) -> tuple[Any, str]:
        from reels.video_store import load_metadata, make_derived_clip_slug, register_clip_from_files

        source_clip = ctx.get("source_clip_slug")
        if source_clip:
            clip_slug = make_derived_clip_slug(parent_slug, str(source_clip), suffix)
            title_base = str(ctx.get("source_clip_title") or source_clip)
            title = f"{title_base} — {title_suffix}"
        else:
            clip_slug = None
            parent = load_metadata(parent_slug)
            title_base = parent.title if parent else parent_slug
            title = f"{title_suffix} — {title_base}"
        return register_clip_from_files(
            parent_slug,
            title=title,
            start=start,
            end=end,
            source_feature=source_feature,
            files=files,
            clip_slug=clip_slug,
        )

    @staticmethod
    def _apply_cleanup_overrides(config: AppConfig, params: dict[str, Any]) -> None:
        c = config.cleanup
        if params.get("min_gap_seconds") is not None:
            c.min_gap_seconds = float(params["min_gap_seconds"])
        if params.get("pad_seconds") is not None:
            c.pad_seconds = float(params["pad_seconds"])
        if params.get("use_silencedetect") is not None:
            c.use_silencedetect = bool(params["use_silencedetect"])
        if params.get("silence_noise_db") is not None:
            c.silence_noise_db = float(params["silence_noise_db"])
        if params.get("remove_fillers") is not None:
            c.remove_fillers = bool(params["remove_fillers"])
        if params.get("use_llm") is not None:
            c.use_llm = bool(params["use_llm"])
        formats: list[str] = []
        if params.get("export_youtube", True):
            formats.append("youtube")
        if params.get("export_reels", True):
            formats.append("reels")
        if formats:
            c.formats = formats

    @staticmethod
    def _apply_captions_overrides(config: AppConfig, params: dict[str, Any]) -> None:
        cap = config.captions
        if params.get("font_id"):
            cap.default_font = str(params["font_id"])
        if params.get("max_words_per_line") is not None:
            cap.max_words_per_line = int(params["max_words_per_line"])
        if params.get("word_gap_seconds") is not None:
            cap.word_gap_seconds = float(params["word_gap_seconds"])
        if params.get("bottom_margin_ratio") is not None:
            cap.bottom_margin_ratio = float(params["bottom_margin_ratio"])
        if params.get("font_size_ratio") is not None:
            cap.font_size_ratio = float(params["font_size_ratio"])
        if params.get("primary_colour"):
            cap.primary_colour = str(params["primary_colour"])
        if params.get("highlight_colour"):
            cap.highlight_colour = str(params["highlight_colour"])

    def _finish_awaiting_review(
        self,
        job_id: str,
        state: JobState,
        *,
        message: str = "Review proposed cuts",
    ) -> None:
        state.status = JobStatus.AWAITING_REVIEW
        state.phase = "review"
        state.percent = 100.0
        state.message = message
        state.updated_at = _utc_now()
        _append_activity_log(Path(state.output_dir), state.message)
        with self._lock:
            self._running = False
            self._current_job_id = None
        self._notify(job_id, state)

    def _run_v2_cleanup_analysis(
        self,
        job_id: str,
        video: Path,
        out: Path,
        config: AppConfig,
        req: CreateJobRequest,
        reporter: CallbackProgressReporter,
        cancel_event: threading.Event,
        state: JobState,
    ) -> None:
        slug = str(req.params.get("video_slug", "")) or self._slug_from_v2_path(video)
        self._apply_cleanup_overrides(config, req.params)
        out.mkdir(parents=True, exist_ok=True)
        self._write_v2_job_context(out, dict(req.params))

        reporter.report("probe", message="Probing video...")
        info = probe_video(video)
        reporter.mark_phase_complete("probe")
        if cancel_event.is_set():
            raise RuntimeError("Cancelled")

        reporter.report("transcribe", message="Loading transcript...")
        segments = self._v2_job_segments(req, slug, config, state)
        reporter.mark_phase_complete("transcribe")
        if cancel_event.is_set():
            raise RuntimeError("Cancelled")

        (out / "segments.json").write_text(json.dumps(segments), encoding="utf-8")
        reporter.report("edl", message="Building edit decision list...")
        client = OllamaClient(config)
        llm_available = client.is_available()
        proposed = propose_llm_cuts(client, config, segments) if config.cleanup.use_llm else []
        if proposed:
            reporter.report("verify", message="Verifying cuts with LLM...")
            proposed = verify_cuts(client, config, segments, proposed)
            reporter.mark_phase_complete("verify")

        doc = build_edl(segments, info.duration, config, proposed, llm_available)
        doc.source_video = str(video)
        write_edl(out / "edl.json", doc)
        reporter.mark_phase_complete("edl")

        cut_count = len([s for s in doc.spans if s.kind == "cut"])
        self._finish_awaiting_review(
            job_id,
            state,
            message=f"EDL ready — {cut_count} proposed cuts",
        )

    def render_v2_cleanup(self, job_id: str, body: RenderJobBody) -> JobState:
        with self._lock:
            state = self._jobs.get(job_id)
            if state is None:
                raise KeyError(f"Job not found: {job_id}")
            if state.feature != "v2_cleanup":
                raise RuntimeError("Not a v2 cleanup job")
            if state.status != JobStatus.AWAITING_REVIEW:
                raise RuntimeError("Job is not awaiting review")
            if self._running:
                raise RuntimeError("Another job is already running")

            self._running = True
            self._current_job_id = job_id
            state.status = JobStatus.RUNNING
            state.phase = "render"
            state.percent = 0.0
            state.message = "Rendering final video..."
            state.updated_at = _utc_now()

        thread = threading.Thread(
            target=self._run_v2_cleanup_render,
            args=(job_id, body),
            daemon=True,
        )
        thread.start()
        return state

    def _run_v2_cleanup_render(self, job_id: str, body: RenderJobBody) -> None:
        state = self._jobs[job_id]
        out = Path(state.output_dir)
        config = load_config(state.preset)

        try:
            edl = load_edl(out / "edl.json")
            video = Path(edl.source_video or state.video_path)
            slug = self._slug_from_v2_path(video)
            info = probe_video(video)
            keep = keep_spans_after_cuts(edl, body.cut_indices)
            formats = body.formats or list(config.cleanup.formats)

            from reels.export import build_crop_filter, build_scale_filter
            from reels.export_resolution import default_reels_size, default_youtube_size

            profiles = load_export_profiles()
            rl_w, rl_h = default_reels_size(info.width, info.height)
            reels_profile = profiles.reels.model_copy(update={"width": rl_w, "height": rl_h})
            for fmt in formats:
                dest = out / fmt / "final.mp4"
                if fmt == "reels":
                    crop = build_crop_filter(info.width, info.height, reels_profile)
                    _export_kept_spans(
                        video,
                        keep,
                        dest,
                        crop_filter=crop,
                        use_nvenc=body.use_nvenc,
                        config=config,
                    )
                else:
                    yt_w, yt_h = default_youtube_size(info.width, info.height)
                    yt_profile = profiles.youtube.model_copy(update={"width": yt_w, "height": yt_h})
                    scale = build_scale_filter(info.width, info.height, yt_profile)
                    _export_kept_spans(
                        video,
                        keep,
                        dest,
                        crop_filter=scale if scale != "null" else None,
                        use_nvenc=body.use_nvenc,
                        config=config,
                    )

            files: dict[str, Path] = {}
            for fmt in formats:
                p = out / fmt / "final.mp4"
                if p.is_file():
                    files[fmt] = p

            ctx = self._load_v2_job_context(out)
            clip_start = float(ctx.get("clip_start", 0))
            kept_duration = sum(e - s for s, e in keep)
            start = clip_start if ctx.get("source_clip_slug") else 0.0
            end = clip_start + kept_duration if ctx.get("source_clip_slug") else kept_duration
            _clip, clip_id = self._register_v2_derivative_clip(
                slug,
                ctx,
                suffix="skip_silence",
                title_suffix="sem silêncios",
                source_feature="cleanup",
                start=start,
                end=end,
                files=files,
            )
            state.result_clip_id = clip_id
            state.clips_exported = True
            self._finish_job(job_id, state, success=True, message="Cleanup clip saved to gallery")
        except Exception as e:
            tb = traceback.format_exc()
            _write_job_error_log(out, job_id, e, tb)
            self._finish_job(job_id, state, success=False, error=str(e))

    def _run_v2_captions(
        self,
        job_id: str,
        video: Path,
        out: Path,
        config: AppConfig,
        req: CreateJobRequest,
        reporter: CallbackProgressReporter,
        cancel_event: threading.Event,
        state: JobState,
    ) -> None:
        from reels.caption_fonts import resolve_font_path
        from reels import captions_render

        slug = str(req.params.get("video_slug", "")) or self._slug_from_v2_path(video)
        self._apply_captions_overrides(config, req.params)
        use_nvenc = bool(req.params.get("use_nvenc", req.use_nvenc))
        output_format = str(req.params.get("output_format", "reels"))
        out.mkdir(parents=True, exist_ok=True)
        self._write_v2_job_context(out, dict(req.params))

        reporter.report("transcribe", message="Loading transcript...")
        segments = self._v2_job_segments(req, slug, config, state)
        reporter.mark_phase_complete("transcribe")
        if cancel_event.is_set():
            raise RuntimeError("Cancelled")

        reporter.report("segments", message="Building caption segments...")
        built = build_caption_segments(segments, config.captions)
        font_id = str(req.params.get("font_id") or config.captions.default_font)
        doc = CaptionsDocument(
            source_video=str(video),
            segments=built,
            segments_original=[s.model_copy(deep=True) for s in built],
            font_id=font_id,
            warnings=list(state.warnings),
        )
        write_captions(out / "captions.json", doc)
        reporter.mark_phase_complete("segments")
        if cancel_event.is_set():
            raise RuntimeError("Cancelled")

        reporter.report("render", message="Burning captions into video...")
        info = probe_video(video)
        ass_path = out / "captions.ass"
        font_path = resolve_font_path(doc.font_id)
        font_family = font_path.stem if font_path else "Arial"
        write_ass_file(
            doc,
            ass_path,
            video_width=info.width,
            video_height=info.height,
            font_family=font_family,
            config=config.captions,
        )

        files: dict[str, Path] = {}
        if output_format in ("reels", "both"):
            reels_path = out / "reels" / "captioned.mp4"
            reels_path.parent.mkdir(parents=True, exist_ok=True)
            captions_render.render_captioned_video(
                video,
                ass_path,
                reels_path,
                font_id=doc.font_id,
                config=config,
                use_nvenc=use_nvenc,
            )
            files["reels"] = reels_path
        if output_format in ("youtube", "both"):
            yt_path = out / "youtube" / "captioned.mp4"
            yt_path.parent.mkdir(parents=True, exist_ok=True)
            captions_render.render_captioned_video(
                video,
                ass_path,
                yt_path,
                font_id=doc.font_id,
                config=config,
                use_nvenc=use_nvenc,
            )
            files["youtube"] = yt_path

        reporter.mark_phase_complete("render")
        ctx = self._load_v2_job_context(out)
        clip_start = float(ctx.get("clip_start", 0))
        duration = info.duration
        start = clip_start if ctx.get("source_clip_slug") else 0.0
        end = clip_start + duration if ctx.get("source_clip_slug") else duration
        _clip, clip_id = self._register_v2_derivative_clip(
            slug,
            ctx,
            suffix="with_legend",
            title_suffix="legendas",
            source_feature="captions",
            start=start,
            end=end,
            files=files,
        )
        state.result_clip_id = clip_id
        state.clips_exported = True
        self._finish_job(job_id, state, success=True, message="Captioned clip saved to gallery")

    def _run_v2_trim(
        self,
        job_id: str,
        video: Path,
        out: Path,
        config: AppConfig,
        req: CreateJobRequest,
        reporter: CallbackProgressReporter,
        cancel_event: threading.Event,
        state: JobState,
    ) -> None:
        from reels.export import build_scale_filter, resolve_export_nvenc
        from reels.export_resolution import default_youtube_size
        from reels.trim import validate_keep_spans
        from reels.video_store import load_metadata

        slug = str(req.params.get("video_slug", "")) or self._slug_from_v2_path(video)
        explicit_nvenc = req.params.get("use_nvenc")
        use_nvenc = resolve_export_nvenc(
            config,
            None if explicit_nvenc is None else bool(explicit_nvenc),
        )
        enc_label = "GPU/NVENC" if use_nvenc else "CPU"
        out.mkdir(parents=True, exist_ok=True)
        self._write_v2_job_context(out, dict(req.params))

        reporter.report("probe", message="Probing video…")
        info = probe_video(video)
        reporter.mark_phase_complete("probe")
        if cancel_event.is_set():
            raise RuntimeError("Cancelled")

        raw_spans = req.params.get("keep_spans") or []
        keep = validate_keep_spans(raw_spans, info.duration)

        def on_ff_progress(frac: float) -> None:
            pct = int(frac * 100)
            reporter.report(
                "render",
                current=int(frac * 1000),
                total=1000,
                message=f"Exporting trim ({enc_label})… {pct}%",
            )

        reporter.report("render", message=f"Exporting trim ({enc_label})… 0%", current=0, total=1000)
        source_clip = req.params.get("source_clip_slug")
        source_fmt = str(req.params.get("source_format") or "youtube")
        profiles = load_export_profiles()

        if source_clip:
            dest = out / source_fmt / "trimmed.mp4"
            _export_kept_spans(
                video,
                keep,
                dest,
                use_nvenc=use_nvenc,
                config=config,
                on_progress=on_ff_progress,
                cancel_event=cancel_event,
            )
        else:
            yt_w, yt_h = default_youtube_size(info.width, info.height)
            yt_profile = profiles.youtube.model_copy(update={"width": yt_w, "height": yt_h})
            scale = build_scale_filter(info.width, info.height, yt_profile)
            dest = out / "youtube" / "trimmed.mp4"
            _export_kept_spans(
                video,
                keep,
                dest,
                crop_filter=scale if scale != "null" else None,
                use_nvenc=use_nvenc,
                config=config,
                on_progress=on_ff_progress,
                cancel_event=cancel_event,
            )

        reporter.mark_phase_complete("render")
        ctx = self._load_v2_job_context(out)
        source_title = str(ctx.get("source_clip_title") or source_clip or "")
        if not source_title:
            parent = load_metadata(slug)
            source_title = parent.title if parent else slug
        title = f"recorte — {source_title}"
        slug_base = f"{slug}_recorte" if not source_clip else f"{slug}_{source_clip}_recorte"

        state.trim_output_path = str(dest)
        state.trim_finalized = False
        state.result_video_id = None
        state.result_clip_id = None
        ctx["trim_output_path"] = str(dest)
        ctx["trim_slug_base"] = slug_base
        ctx["trim_title"] = title
        self._write_v2_job_context(out, ctx)
        self._finish_job(
            job_id,
            state,
            success=True,
            message="Recorte pronto — escolha como salvar",
        )

    def finalize_v2_trim(self, job_id: str, mode: str) -> dict[str, Any]:
        from reels.video_store import (
            load_metadata,
            register_trim_as_vod,
            replace_clip_source,
            replace_original_vod_source,
            resolve_video_id,
        )

        state = self.get_job(job_id)
        if not state:
            raise ValueError("Job not found")
        if state.feature != "v2_trim":
            raise ValueError("Not a trim job")
        if state.status != JobStatus.COMPLETED:
            raise ValueError("Trim job is not complete")
        if state.trim_finalized:
            raise ValueError("Trim already finalized")
        trim_path = Path(state.trim_output_path or "")
        if not trim_path.is_file():
            out = Path(state.output_dir)
            ctx = self._load_v2_job_context(out)
            trim_path = Path(str(ctx.get("trim_output_path", "")))
        if not trim_path.is_file():
            raise ValueError("Trim output not found")

        out = Path(state.output_dir)
        ctx = self._load_v2_job_context(out)
        source_video_id = str(ctx.get("source_video_id") or "")
        if not source_video_id:
            raise ValueError("Missing source video for trim finalize")

        meta = resolve_video_id(source_video_id)
        if mode == "new_vod":
            title = str(ctx.get("trim_title") or "recorte")
            slug_base = str(ctx.get("trim_slug_base") or "recorte")
            _vod, vod_id = register_trim_as_vod(trim_path, title=title, slug_base=slug_base)
            state.result_video_id = vod_id
            state.result_clip_id = vod_id
        elif mode == "replace":
            if meta.kind == "clip" and meta.parent_slug and meta.clip_slug:
                fmt = str(ctx.get("source_format") or "youtube")
                _clip, vid = replace_clip_source(
                    meta.parent_slug,
                    meta.clip_slug,
                    fmt,
                    trim_path,
                )
                state.result_video_id = vid
                state.result_clip_id = vid
            elif meta.kind == "original":
                updated = replace_original_vod_source(meta.slug, trim_path)
                state.result_video_id = updated.slug
                state.result_clip_id = updated.slug
            else:
                raise ValueError("Cannot replace this video type")
        else:
            raise ValueError(f"Unknown trim finalize mode: {mode}")

        state.trim_finalized = True
        state.message = "Recorte salvo"
        state.updated_at = _utc_now()
        with self._lock:
            pass
        self._notify(job_id, state)
        return {
            "job_id": job_id,
            "mode": mode,
            "video_id": state.result_video_id,
        }

    def iter_events(self, job_id: str, poll_interval: float = 0.5) -> Iterator[JobState]:
        last_len = 0
        while True:
            state = self.get_job(job_id)
            if state is None:
                break
            yield state
            if state.status in (
                JobStatus.COMPLETED,
                JobStatus.FAILED,
                JobStatus.CANCELLED,
                JobStatus.AWAITING_REVIEW,
            ):
                break
            with self._lock:
                ev_len = len(self._events.get(job_id, []))
            if ev_len == last_len:
                time.sleep(poll_interval)
            last_len = ev_len


_manager: JobManager | None = None


def get_job_manager() -> JobManager:
    global _manager
    if _manager is None:
        _manager = JobManager()
    return _manager
