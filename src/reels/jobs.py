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


class RenderJobBody(BaseModel):
    cut_indices: list[int] = Field(default_factory=list)
    formats: list[str] | None = None
    use_nvenc: bool = False


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
    captions_output_path: str | None = None
    captions_finalized: bool = False
    cleanup_output_path: str | None = None
    cleanup_finalized: bool = False
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
    filter_complex: str | None = None,
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
    if filter_complex:
        cmd.extend(["-filter_complex", filter_complex, "-map", "[vout]", "-map", "0:a?"])
    elif crop_filter:
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


def _build_span_copy_cmd(
    source_video: Path,
    start: float,
    end: float,
    output_path: Path,
) -> list[str]:
    """Stream-copy a single span (keyframe-aligned cuts)."""
    duration = max(0.01, end - start)
    return [
        "ffmpeg",
        "-y",
        "-ss",
        str(start),
        "-i",
        str(source_video),
        "-t",
        str(duration),
        "-c",
        "copy",
        "-avoid_negative_ts",
        "make_zero",
        "-movflags",
        "+faststart",
        str(output_path),
    ]


def _cleanup_span_parts(work_dir: Path, part_paths: list[Path]) -> None:
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


def _export_kept_spans_copy(
    source_video: Path,
    keep_spans: list[tuple[float, float]],
    output_path: Path,
    *,
    on_progress: Callable[[float], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> None:
    """Stream-copy kept spans (no re-encode); multi-span uses concat demuxer."""
    from reels.ffmpeg_runner import run_ffmpeg

    require_ffmpeg()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not keep_spans:
        raise ValueError("No content to export")

    total_duration = sum(max(0.01, end - start) for start, end in keep_spans)

    if len(keep_spans) == 1:
        start, end = keep_spans[0]
        cmd = _build_span_copy_cmd(source_video, start, end, output_path)
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

            cmd = _build_span_copy_cmd(source_video, start, end, part)
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
        _cleanup_span_parts(work_dir, part_paths)


def _export_kept_spans(
    source_video: Path,
    keep_spans: list[tuple[float, float]],
    output_path: Path,
    *,
    crop_filter: str | None = None,
    filter_complex: str | None = None,
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
            filter_complex=filter_complex,
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
                filter_complex=filter_complex,
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
        _cleanup_span_parts(work_dir, part_paths)


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
        self._pending: list[tuple[str, Path, Path, CreateJobRequest]] = []
        self._job_video_ids: dict[str, str] = {}
        self._last_phase: dict[str, str] = {}

    # --- DB persistence -----------------------------------------------------

    @staticmethod
    def _resolve_job_video_id(req: CreateJobRequest) -> str:
        raw = str(req.params.get("source_video_id") or req.params.get("video_slug") or "")
        if not raw:
            return ""
        try:
            from reels import video_repo

            rec = video_repo.resolve(raw)
            return rec.id if rec else raw
        except Exception:
            return raw

    def _persist_state(self, state: JobState) -> None:
        try:
            from reels import job_store

            job_store.update_job(
                job_id=state.id,
                status=state.status,
                percent=state.percent,
                phase=state.phase,
                message=state.message,
                error=state.error,
                result_video_id=state.result_video_id,
            )
        except Exception:
            pass

    def _persist_event(self, job_id: str, event: ProgressEvent) -> None:
        try:
            from reels import job_store

            if self._last_phase.get(job_id) != event.phase:
                self._last_phase[job_id] = event.phase
                job_store.add_event(job_id, event.phase, event.percent, event.message)
        except Exception:
            pass

    def _drain(self) -> None:
        with self._lock:
            if self._running or not self._pending:
                return
            job_id, video, out, req = self._pending.pop(0)
            self._running = True
            self._current_job_id = job_id
        thread = threading.Thread(
            target=self._run_job,
            args=(job_id, video, out, req),
            daemon=True,
        )
        thread.start()

    def create_job(self, req: CreateJobRequest) -> JobState:
        video = validate_video_path(req.video_path)

        video_id = self._resolve_job_video_id(req)
        from reels import job_store

        params_hash = job_store.compute_params_hash(video_id, req.feature, req.params)

        with self._lock:
            dup_id = job_store.find_active_duplicate(video_id, req.feature, params_hash)
            if dup_id and dup_id in self._jobs and self._jobs[dup_id].status in (
                JobStatus.QUEUED,
                JobStatus.RUNNING,
            ):
                return self._jobs[dup_id]

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
            self._job_video_ids[job_id] = video_id
            self._pending.append((job_id, video, out, req))

        try:
            job_store.insert_job(
                job_id=job_id,
                video_id=video_id,
                feature=req.feature,
                params=req.params,
                params_hash=params_hash,
                status=JobStatus.QUEUED,
                output_dir=str(out),
                created_at=now,
            )
        except Exception:
            pass

        self._drain()
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
        self._persist_state(state)
        self._notify(job_id, state)
        self._drain()

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
            self._persist_state(state)
            self._persist_event(job_id, event)
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

            if req.feature == "v2_analyze":
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
            elif req.feature == "v2_transform_reel":
                self._run_v2_transform_reel(
                    job_id, video, out, config, req, reporter, cancel_event, state
                )
            elif req.feature == "v2_create_clip":
                self._run_v2_create_clip(
                    job_id, video, out, config, req, reporter, cancel_event, state
                )
            else:
                raise ValueError(f"Unknown job feature: {req.feature}")
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
        _meta, segments = load_or_transcribe(
            slug, config, warnings=state.warnings, persist=False, work_dir=out
        )
        reporter.mark_phase_complete("transcribe")
        if cancel_event.is_set():
            raise RuntimeError("Cancelled")

        existing_audio = out / "audio.wav"
        if not existing_audio.is_file():
            existing_audio = transcript_audio(slug)
        if existing_audio.is_file():
            reporter.report("proxy", message="Using transcript audio...")
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
        from reels.export import export_clip, export_reels_clip, load_export_profiles
        from reels.export_resolution import default_reels_size, default_youtube_size
        from reels.highlights import prune_exported_highlights
        from reels.models import ClipMetadata, Highlight
        from reels.video_store import clip_dir, highlights_path, resolve_webcam_region, save_clip_metadata

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
        webcam_region = resolve_webcam_region(slug)

        total_steps = sum(
            1
            for sel in selections
            if sel.get("export_youtube") or sel.get("export_reels")
        )
        step = 0
        exported = 0
        exported_indices: set[int] = set()

        def _unique_clip_slug(preferred_idx: int) -> str:
            candidate = f"clip_{preferred_idx:02d}"
            if not clip_dir(slug, candidate).exists():
                return candidate
            n = 0
            while True:
                candidate = f"clip_{n:02d}"
                if not clip_dir(slug, candidate).exists():
                    return candidate
                n += 1

        for sel in selections:
            if cancel_event.is_set():
                raise RuntimeError("Cancelled")
            if not sel.get("export_youtube") and not sel.get("export_reels"):
                continue
            idx = int(sel.get("index", exported))
            start = max(0.0, float(sel.get("start", 0)) - pre_pad)
            end = float(sel.get("end", 0)) + post_pad
            title = str(sel.get("title", "Highlight"))
            clip_slug = _unique_clip_slug(idx)
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
                include_webcam = bool(sel.get("include_webcam"))
                if include_webcam and webcam_region:
                    export_reels_clip(
                        video,
                        highlight,
                        out_dir / "reels.mp4",
                        reels_profile,
                        config,
                        region=webcam_region,
                        use_nvenc=use_nvenc,
                        source_width=info.width,
                        source_height=info.height,
                    )
                else:
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
            exported_indices.add(idx)
            exported += 1

        if exported_indices:
            prune_exported_highlights(highlights_path(slug), exported_indices)

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
        *,
        work_dir: Path | None = None,
    ) -> list[dict[str, Any]]:
        from reels.video_transcript import segments_for_clip_job

        params = req.params
        out = work_dir or Path(state.output_dir)
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
                work_dir=out,
            )
        _meta, segments = load_or_transcribe(
            slug, config, warnings=state.warnings, persist=False, work_dir=out
        )
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
        self._persist_state(state)
        self._notify(job_id, state)
        self._drain()

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
            primary = files.get("youtube") or files.get("reels") or next(iter(files.values()))
            state.cleanup_output_path = str(primary)
            state.cleanup_finalized = False
            state.result_clip_id = None
            state.result_video_id = None
            ctx["cleanup_files"] = {k: str(v) for k, v in files.items()}
            ctx["cleanup_output_path"] = str(primary)
            ctx["cleanup_start"] = start
            ctx["cleanup_end"] = end
            ctx["cleanup_title_suffix"] = "sem silêncios"
            ctx["cleanup_suffix"] = "skip_silence"
            self._write_v2_job_context(out, ctx)
            self._finish_job(
                job_id,
                state,
                success=True,
                message="Cleanup pronto — escolha como salvar",
            )
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
        primary = files.get("youtube") or files.get("reels") or next(iter(files.values()))
        state.captions_output_path = str(primary)
        state.captions_finalized = False
        state.result_clip_id = None
        state.result_video_id = None
        ctx["captions_files"] = {k: str(v) for k, v in files.items()}
        ctx["captions_output_path"] = str(primary)
        ctx["captions_start"] = start
        ctx["captions_end"] = end
        ctx["captions_title_suffix"] = "legendas"
        ctx["captions_suffix"] = "with_legend"
        self._write_v2_job_context(out, ctx)
        self._finish_job(
            job_id,
            state,
            success=True,
            message="Legendas prontas — escolha como salvar",
        )

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
        from reels.trim import is_simple_chronological_keep, validate_keep_spans
        from reels.video_store import load_metadata

        slug = str(req.params.get("video_slug", "")) or self._slug_from_v2_path(video)
        explicit_nvenc = req.params.get("use_nvenc")
        use_nvenc = resolve_export_nvenc(
            config,
            None if explicit_nvenc is None else bool(explicit_nvenc),
        )
        out.mkdir(parents=True, exist_ok=True)
        self._write_v2_job_context(out, dict(req.params))

        reporter.report("probe", message="Probing video…")
        info = probe_video(video)
        reporter.mark_phase_complete("probe")
        if cancel_event.is_set():
            raise RuntimeError("Cancelled")

        raw_spans = req.params.get("keep_spans") or []
        keep = validate_keep_spans(raw_spans, info.duration)
        use_copy = (
            not bool(req.params.get("force_reencode"))
            and is_simple_chronological_keep(keep)
        )
        trim_export_mode = "copy" if use_copy else "reencode"
        enc_label = "copy/fast" if use_copy else ("GPU/NVENC" if use_nvenc else "CPU")

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
            if use_copy:
                _export_kept_spans_copy(
                    video,
                    keep,
                    dest,
                    on_progress=on_ff_progress,
                    cancel_event=cancel_event,
                )
            else:
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
            dest = out / "youtube" / "trimmed.mp4"
            if use_copy:
                # Fast path keeps source resolution (no scale-to-profile).
                _export_kept_spans_copy(
                    video,
                    keep,
                    dest,
                    on_progress=on_ff_progress,
                    cancel_event=cancel_event,
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
        ctx["trim_export_mode"] = trim_export_mode
        self._write_v2_job_context(out, ctx)
        self._finish_job(
            job_id,
            state,
            success=True,
            message="Recorte pronto — escolha como salvar",
        )

    def _run_v2_transform_reel(
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
        from reels.export import build_crop_filter, build_reels_webcam_filter_complex, load_export_profiles, resolve_export_nvenc
        from reels.export_resolution import default_reels_size
        from reels.video_store import resolve_webcam_region

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

        profiles = load_export_profiles()
        rl_w, rl_h = default_reels_size(info.width, info.height)
        reels_profile = profiles.reels.model_copy(update={"width": rl_w, "height": rl_h})
        include_webcam = bool(req.params.get("include_webcam"))
        source_video_id = str(req.params.get("source_video_id", ""))
        webcam_region = resolve_webcam_region(source_video_id) if include_webcam and source_video_id else None
        if include_webcam and webcam_region:
            filter_complex = build_reels_webcam_filter_complex(
                info.width, info.height, rl_w, rl_h, webcam_region
            )
            crop = None
        else:
            filter_complex = None
            crop = build_crop_filter(info.width, info.height, reels_profile)
        dest = out / "reels" / "reels.mp4"
        keep = [(0.0, info.duration)]

        def on_ff_progress(frac: float) -> None:
            pct = int(frac * 100)
            reporter.report(
                "render",
                current=int(frac * 1000),
                total=1000,
                message=f"Transforming to reel ({enc_label})… {pct}%",
            )

        reporter.report("render", message=f"Transforming to reel ({enc_label})… 0%", current=0, total=1000)
        _export_kept_spans(
            video,
            keep,
            dest,
            crop_filter=crop,
            filter_complex=filter_complex,
            use_nvenc=use_nvenc,
            config=config,
            on_progress=on_ff_progress,
            cancel_event=cancel_event,
        )
        reporter.mark_phase_complete("render")

        ctx = self._load_v2_job_context(out)
        if ctx.get("source_clip_slug"):
            clip_start = float(ctx.get("clip_start", 0))
            clip_end = float(ctx.get("clip_end", clip_start + info.duration))
        else:
            clip_start = 0.0
            clip_end = info.duration
        _clip, clip_id = self._register_v2_derivative_clip(
            slug,
            ctx,
            suffix="reels",
            title_suffix="Reels",
            source_feature="reformat",
            start=clip_start,
            end=clip_end,
            files={"reels": dest},
        )
        state.result_clip_id = clip_id
        state.result_video_id = clip_id
        state.clips_exported = True
        self._finish_job(job_id, state, success=True, message="Reel clip saved to gallery")

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
        elif mode == "new_clip":
            parent_slug = meta.parent_slug or meta.slug
            raw_spans = ctx.get("keep_spans") or []
            kept_duration = sum(float(s[1]) - float(s[0]) for s in raw_spans)
            clip_start = float(ctx.get("clip_start", 0))
            if ctx.get("source_clip_slug"):
                start = clip_start
                end = clip_start + kept_duration
            else:
                start = 0.0
                end = kept_duration
            if ctx.get("source_clip_slug"):
                fmt = str(ctx.get("source_format") or "youtube")
            else:
                fmt = "youtube"
            _clip, clip_id = self._register_v2_derivative_clip(
                parent_slug,
                ctx,
                suffix="recorte",
                title_suffix="recorte",
                source_feature="trim",
                start=start,
                end=end,
                files={fmt: trim_path},
            )
            state.result_video_id = clip_id
            state.result_clip_id = clip_id
        else:
            raise ValueError(f"Unknown trim finalize mode: {mode}")

        state.trim_finalized = True
        state.message = "Recorte salvo"
        state.updated_at = _utc_now()
        self._persist_state(state)
        self._notify(job_id, state)
        return {
            "job_id": job_id,
            "mode": mode,
            "video_id": state.result_video_id,
        }

    def _finalize_staged_derivative(
        self,
        job_id: str,
        mode: str,
        *,
        feature: str,
        source_feature: str,
        output_path_attr: str,
        finalized_attr: str,
        files_ctx_key: str,
        output_path_ctx_key: str,
        start_ctx_key: str,
        end_ctx_key: str,
        suffix_ctx_key: str,
        title_suffix_ctx_key: str,
        default_suffix: str,
        default_title_suffix: str,
        done_message: str,
    ) -> dict[str, Any]:
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
        if state.feature != feature:
            raise ValueError(f"Not a {feature} job")
        if state.status != JobStatus.COMPLETED:
            raise ValueError("Job is not complete")
        if getattr(state, finalized_attr):
            raise ValueError("Already finalized")

        out = Path(state.output_dir)
        ctx = self._load_v2_job_context(out)
        path_str = getattr(state, output_path_attr) or ctx.get(output_path_ctx_key)
        primary = Path(str(path_str or ""))
        files_raw = ctx.get(files_ctx_key) or {}
        files: dict[str, Path] = {k: Path(v) for k, v in files_raw.items() if Path(v).is_file()}
        if not files and primary.is_file():
            files = {"youtube": primary}
        if not primary.is_file():
            primary = files.get("youtube") or files.get("reels") or next(iter(files.values()), Path(""))
        if not primary.is_file():
            raise ValueError("Staged output not found")

        source_video_id = str(ctx.get("source_video_id") or "")
        if not source_video_id:
            raise ValueError("Missing source video for finalize")
        meta = resolve_video_id(source_video_id)
        start = float(ctx.get(start_ctx_key, 0))
        end = float(ctx.get(end_ctx_key, start))
        suffix = str(ctx.get(suffix_ctx_key) or default_suffix)
        title_suffix = str(ctx.get(title_suffix_ctx_key) or default_title_suffix)

        if mode == "new_vod":
            parent = load_metadata(meta.parent_slug or meta.slug)
            title_base = parent.title if parent else (meta.parent_slug or meta.slug)
            title = f"{title_suffix} — {title_base}"
            slug_base = f"{meta.parent_slug or meta.slug}_{suffix}"
            _vod, vod_id = register_trim_as_vod(primary, title=title, slug_base=slug_base)
            state.result_video_id = vod_id
            state.result_clip_id = vod_id
        elif mode == "replace":
            if meta.kind == "clip" and meta.parent_slug and meta.clip_slug:
                fmt = str(ctx.get("source_format") or next(iter(files.keys()), "youtube"))
                replace_path = files.get(fmt) or primary
                _clip, vid = replace_clip_source(
                    meta.parent_slug,
                    meta.clip_slug,
                    fmt,
                    replace_path,
                )
                state.result_video_id = vid
                state.result_clip_id = vid
            elif meta.kind == "original":
                updated = replace_original_vod_source(meta.slug, primary)
                state.result_video_id = updated.slug
                state.result_clip_id = updated.slug
            else:
                raise ValueError("Cannot replace this video type")
        elif mode == "new_clip":
            parent_slug = meta.parent_slug or meta.slug
            _clip, clip_id = self._register_v2_derivative_clip(
                parent_slug,
                ctx,
                suffix=suffix,
                title_suffix=title_suffix,
                source_feature=source_feature,
                start=start,
                end=end,
                files=files,
            )
            state.result_video_id = clip_id
            state.result_clip_id = clip_id
        else:
            raise ValueError(f"Unknown finalize mode: {mode}")

        setattr(state, finalized_attr, True)
        state.clips_exported = True
        state.message = done_message
        state.updated_at = _utc_now()
        self._persist_state(state)
        self._notify(job_id, state)
        return {
            "job_id": job_id,
            "mode": mode,
            "video_id": state.result_video_id,
        }

    def finalize_v2_captions(self, job_id: str, mode: str) -> dict[str, Any]:
        return self._finalize_staged_derivative(
            job_id,
            mode,
            feature="v2_captions",
            source_feature="captions",
            output_path_attr="captions_output_path",
            finalized_attr="captions_finalized",
            files_ctx_key="captions_files",
            output_path_ctx_key="captions_output_path",
            start_ctx_key="captions_start",
            end_ctx_key="captions_end",
            suffix_ctx_key="captions_suffix",
            title_suffix_ctx_key="captions_title_suffix",
            default_suffix="with_legend",
            default_title_suffix="legendas",
            done_message="Legendas salvas",
        )

    def finalize_v2_cleanup(self, job_id: str, mode: str) -> dict[str, Any]:
        return self._finalize_staged_derivative(
            job_id,
            mode,
            feature="v2_cleanup",
            source_feature="cleanup",
            output_path_attr="cleanup_output_path",
            finalized_attr="cleanup_finalized",
            files_ctx_key="cleanup_files",
            output_path_ctx_key="cleanup_output_path",
            start_ctx_key="cleanup_start",
            end_ctx_key="cleanup_end",
            suffix_ctx_key="cleanup_suffix",
            title_suffix_ctx_key="cleanup_title_suffix",
            default_suffix="skip_silence",
            default_title_suffix="sem silêncios",
            done_message="Cleanup salvo",
        )

    def _run_v2_create_clip(
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
        from reels.export import resolve_export_nvenc
        from reels.video_store import load_metadata, register_clip_from_files

        slug = str(req.params.get("video_slug", "")) or self._slug_from_v2_path(video)
        start = float(req.params.get("start", 0))
        end = float(req.params.get("end", start))
        if end - start < 5.0 - 1e-6:
            raise ValueError("Clip duration must be at least 5 seconds")
        title = str(req.params.get("title") or "").strip()
        if not title:
            parent = load_metadata(slug)
            title = f"Clip — {parent.title if parent else slug}"
        burn_captions = bool(req.params.get("burn_captions", False))
        explicit_nvenc = req.params.get("use_nvenc")
        use_nvenc = resolve_export_nvenc(
            config,
            None if explicit_nvenc is None else bool(explicit_nvenc),
        )
        out.mkdir(parents=True, exist_ok=True)
        self._write_v2_job_context(out, dict(req.params))

        reporter.report("probe", message="Probing video…")
        info = probe_video(video)
        reporter.mark_phase_complete("probe")
        if cancel_event.is_set():
            raise RuntimeError("Cancelled")
        if start < 0 or end > info.duration + 0.5:
            raise ValueError("Clip window out of range")

        keep = [(start, end)]
        dest = out / "youtube" / "clip.mp4"

        def on_ff_progress(frac: float) -> None:
            pct = int(frac * 100)
            reporter.report(
                "export",
                current=int(frac * 1000),
                total=1000,
                message=f"Exporting clip… {pct}%",
            )

        reporter.report("export", message="Exporting clip… 0%", current=0, total=1000)
        _export_kept_spans_copy(
            video,
            keep,
            dest,
            on_progress=on_ff_progress,
            cancel_event=cancel_event,
        )
        reporter.mark_phase_complete("export")
        if cancel_event.is_set():
            raise RuntimeError("Cancelled")

        final_path = dest
        if burn_captions:
            reporter.report("transcribe", message="Transcribing clip window…")
            from reels.video_transcript import segments_for_clip_job

            segments = segments_for_clip_job(
                slug,
                start,
                end,
                config,
                state.warnings,
                shift_to_zero=True,
                work_dir=out,
            )
            reporter.mark_phase_complete("transcribe")
            if cancel_event.is_set():
                raise RuntimeError("Cancelled")

            reporter.report("captions", message="Burning captions…")
            built = build_caption_segments(segments, config.captions)
            font_id = str(req.params.get("font_id") or config.captions.default_font)
            doc = CaptionsDocument(
                source_video=str(dest),
                segments=built,
                segments_original=[s.model_copy(deep=True) for s in built],
                font_id=font_id,
                warnings=list(state.warnings),
            )
            write_captions(out / "captions.json", doc)
            clip_info = probe_video(dest)
            ass_path = out / "captions.ass"
            font_path = resolve_font_path(doc.font_id)
            font_family = font_path.stem if font_path else "Arial"
            write_ass_file(
                doc,
                ass_path,
                video_width=clip_info.width,
                video_height=clip_info.height,
                font_family=font_family,
                config=config.captions,
            )
            captioned = out / "youtube" / "clip_captioned.mp4"
            captions_render.render_captioned_video(
                dest,
                ass_path,
                captioned,
                font_id=doc.font_id,
                config=config,
                use_nvenc=use_nvenc,
            )
            final_path = captioned
            reporter.mark_phase_complete("captions")

        _clip, clip_id = register_clip_from_files(
            slug,
            title=title,
            start=start,
            end=end,
            source_feature="manual_clip",
            files={"youtube": final_path},
        )
        state.result_clip_id = clip_id
        state.result_video_id = clip_id
        state.clips_exported = True
        self._finish_job(job_id, state, success=True, message="Clip salvo na galeria")

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
