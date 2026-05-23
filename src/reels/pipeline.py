"""End-to-end analysis and export pipeline."""

from __future__ import annotations

import json
import logging
import traceback
from pathlib import Path
from typing import Any

from rich.console import Console

logger = logging.getLogger(__name__)
from rich.progress import Progress, SpinnerColumn, TextColumn

from reels.chunking import detect_scenes, prefilter_windows
from reels.config import AnalysisMode, AppConfig
from reels.heuristic import rank_heuristic_windows
from reels.highlights import (
    gaming_highlights_from_windows,
    merge_auto_highlights,
    write_highlights,
)
from reels.models import HighlightsDocument, PipelineState, VideoInfo, WindowScore
from reels.probe import probe_video
from reels.progress import ProgressReporter
from reels.proxy import cleanup_proxy, generate_proxy
from reels.state import load_state, save_state
from reels.transcribe import transcribe_audio
from reels.vlm.ollama import OllamaClient, OllamaError, analyze_window

console = Console()


def _proxy_phase_message(config: AppConfig) -> str:
    if config.proxy.video_mode == "audio_only":
        return "Extracting audio for analysis..."
    if config.proxy.video_mode == "copy":
        return "Remuxing video (stream copy)..."
    return "Generating proxy video..."


def resolve_output_dir(video_path: Path, output: Path | None) -> Path:
    if output:
        return output.resolve()
    return (video_path.parent / f"{video_path.stem}_reels").resolve()


def _report(
    reporter: ProgressReporter | None,
    phase: str,
    current: int = 0,
    total: int | None = None,
    message: str = "",
    *,
    complete: bool = False,
) -> None:
    if reporter is None:
        return
    if complete:
        reporter.report(phase, current=1, total=1, message=message or f"{phase} complete")
        if hasattr(reporter, "mark_phase_complete"):
            reporter.mark_phase_complete(phase)  # type: ignore[attr-defined]
    else:
        reporter.report(phase, current=current, total=total, message=message)


def analyze_vod(
    video_path: Path,
    config: AppConfig,
    output_dir: Path,
    mode: AnalysisMode | None = None,
    *,
    resume: bool = False,
    reporter: ProgressReporter | None = None,
    video_info: VideoInfo | None = None,
) -> HighlightsDocument:
    """Run analysis pipeline; writes highlights.json and state.json."""
    mode = mode or config.analysis.mode
    output_dir.mkdir(parents=True, exist_ok=True)

    if video_info is None:
        _report(reporter, "probe", message="Probing video...")
        video = probe_video(video_path)
        _report(reporter, "probe", complete=True)
    else:
        video = video_info

    state = load_state(output_dir, video.path)
    if resume and state.proxy_path:
        console.print("[dim]Resuming from checkpoint[/dim]")

    warnings: list[str] = []
    use_rich = reporter is None

    def run_steps() -> tuple[list[dict[str, Any]], list, PipelineState, Path, Path]:
        nonlocal state

        _report(
            reporter,
            "proxy",
            message=_proxy_phase_message(config),
        )
        proxy_path, audio_path = generate_proxy(
            video_path, output_dir, config, video, skip_if_exists=resume
        )
        state.proxy_path = str(proxy_path)
        state.audio_wav_path = str(audio_path)
        state.phase = "proxy"
        save_state(output_dir, state)
        _report(reporter, "proxy", complete=True)

        segments: list[dict[str, Any]] = []
        if mode in ("auto", "gaming", "multimodal"):
            seg_path = output_dir / "segments.json"
            if resume and state.transcribe_done and seg_path.exists():
                segments = json.loads(seg_path.read_text(encoding="utf-8"))
            elif not state.transcribe_done:
                _report(reporter, "transcribe", message="Transcribing (Whisper)...")
                segments = transcribe_audio(audio_path, config, warnings=warnings)
                seg_path.write_text(json.dumps(segments), encoding="utf-8")
                state.transcribe_done = True
                save_state(output_dir, state)
                _report(reporter, "transcribe", complete=True)
            elif seg_path.exists():
                segments = json.loads(seg_path.read_text(encoding="utf-8"))

        _report(reporter, "scenes", message="Detecting scenes...")
        try:
            scenes = detect_scenes(proxy_path)
            state.scenes_done = True
        except Exception:
            scenes = []
        save_state(output_dir, state)
        _report(reporter, "scenes", complete=True)

        _report(reporter, "heuristic", message="Ranking heuristic signals...")
        windows = rank_heuristic_windows(
            audio_path,
            proxy_path,
            video.duration,
            config,
            segments=segments,
            scenes=scenes,
        )
        state.heuristic_done = True
        save_state(output_dir, state)
        _report(reporter, "heuristic", complete=True)
        return segments, windows, state, proxy_path, audio_path

    if use_rich:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            t_proxy = progress.add_task(_proxy_phase_message(config), total=None)
            t_whisper = progress.add_task("Transcribing...", total=None)
            t_scenes = progress.add_task("Detecting scenes...", total=None)
            t_heur = progress.add_task("Ranking heuristic...", total=None)

            progress.update(t_proxy, description=_proxy_phase_message(config))
            proxy_path, audio_path = generate_proxy(
                video_path, output_dir, config, video, skip_if_exists=resume
            )
            state.proxy_path = str(proxy_path)
            state.audio_wav_path = str(audio_path)
            save_state(output_dir, state)
            progress.update(t_proxy, completed=True)

            segments = []
            if mode in ("auto", "gaming", "multimodal"):
                seg_path = output_dir / "segments.json"
                if resume and state.transcribe_done and seg_path.exists():
                    segments = json.loads(seg_path.read_text(encoding="utf-8"))
                elif not state.transcribe_done:
                    progress.update(t_whisper, description="Transcribing (Whisper)...")
                    segments = transcribe_audio(audio_path, config, warnings=warnings)
                    seg_path.write_text(json.dumps(segments), encoding="utf-8")
                    state.transcribe_done = True
                    save_state(output_dir, state)
                    progress.update(t_whisper, completed=True)
                elif seg_path.exists():
                    segments = json.loads(seg_path.read_text(encoding="utf-8"))

            progress.update(t_scenes, description="Detecting scenes...")
            try:
                scenes = detect_scenes(proxy_path)
                state.scenes_done = True
            except Exception:
                scenes = []
            save_state(output_dir, state)
            progress.update(t_scenes, completed=True)

            progress.update(t_heur, description="Ranking heuristic signals...")
            windows = rank_heuristic_windows(
                audio_path,
                proxy_path,
                video.duration,
                config,
                segments=segments,
                scenes=scenes,
            )
            state.heuristic_done = True
            save_state(output_dir, state)
            progress.update(t_heur, completed=True)
    else:
        segments, windows, state, proxy_path, _ = run_steps()

    vlm_available = True
    vlm_results: dict[str, dict] = {}

    if mode == "gaming":
        highlights = gaming_highlights_from_windows(windows, config)
        doc = HighlightsDocument(
            source_video=video.path,
            preset=config.preset,
            mode=mode,
            vlm_available=False,
            warnings=warnings,
            highlights=highlights,
        )
        write_highlights(output_dir / "highlights.json", doc)
        return doc

    if mode in ("multimodal", "auto"):
        client = OllamaClient(config)
        if not client.is_available():
            vlm_available = False
            warnings.append(
                "Ollama unavailable — falling back to gaming heuristic only. "
                f"Check config ollama.host ({client.base_url}) and that Ollama is running."
            )
            if mode == "multimodal":
                highlights = gaming_highlights_from_windows(windows, config)
                doc = HighlightsDocument(
                    source_video=video.path,
                    preset=config.preset,
                    mode=mode,
                    vlm_available=False,
                    warnings=warnings,
                    highlights=highlights,
                )
                write_highlights(output_dir / "highlights.json", doc)
                return doc
        else:
            candidates = _vlm_candidate_windows(windows, config, video.duration)
            vlm_results = _run_vlm_windows(
                client,
                config,
                proxy_path,
                candidates,
                segments,
                output_dir,
                state,
                resume=resume,
                reporter=reporter,
            )

    if mode == "multimodal" and vlm_available:
        highlights = _vlm_only_highlights(vlm_results, windows, config)
    elif mode == "auto" and vlm_available and vlm_results:
        highlights = merge_auto_highlights(windows, vlm_results, config, vlm_available=True)
    else:
        if mode == "auto" and not vlm_available:
            warnings.append("Auto mode: VLM skipped, using heuristic highlights.")
        highlights = gaming_highlights_from_windows(windows, config)

    doc = HighlightsDocument(
        source_video=video.path,
        preset=config.preset,
        mode=mode,
        vlm_available=vlm_available,
        warnings=warnings,
        highlights=highlights,
    )
    write_highlights(output_dir / "highlights.json", doc)
    return doc


def _vlm_candidate_windows(
    windows: list[WindowScore],
    config: AppConfig,
    duration: float,
) -> list[tuple[float, float]]:
    scored = [(w.start, w.end, w.heuristic_score) for w in windows]
    return prefilter_windows(
        scored,
        config.analysis.prefilter_top_percent,
        config.analysis.max_vlm_windows,
    )


def _run_vlm_windows(
    client: OllamaClient,
    config: AppConfig,
    proxy_path: Path,
    candidates: list[tuple[float, float]],
    segments: list[dict[str, Any]],
    output_dir: Path,
    state: PipelineState,
    *,
    resume: bool,
    reporter: ProgressReporter | None = None,
) -> dict[str, dict]:
    results: dict[str, dict] = {}
    total = len(candidates)
    for idx, (start, end) in enumerate(candidates, start=1):
        key = state.window_key(start, end)
        _report(
            reporter,
            "vlm",
            current=idx,
            total=total,
            message=f"VLM window {idx}/{total}",
        )
        if resume and key in state.vlm_completed:
            ckpt = output_dir / "vlm" / f"{key}.json"
            if ckpt.exists():
                results[key] = json.loads(ckpt.read_text(encoding="utf-8"))
            continue

        transcript = _transcript_for_window(segments, start, end)
        try:
            data = analyze_window(client, config, proxy_path, start, end, transcript)
            results[key] = data
            state.vlm_completed.append(key)
            _save_vlm_checkpoint(output_dir, key, data)
            save_state(output_dir, state)
        except OllamaError as e:
            logger.warning("VLM window %s failed: %s", key, e)
            console.print(f"[yellow]VLM window {key} failed: {e}[/yellow]")
        except Exception as e:
            logger.exception("VLM window %s unexpected error", key)
            console.print(f"[yellow]VLM window {key} failed: {e}[/yellow]")
    if reporter and total > 0:
        _report(reporter, "vlm", complete=True)
    return results


def _save_vlm_checkpoint(output_dir: Path, key: str, data: dict) -> None:
    d = output_dir / "vlm"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{key}.json").write_text(json.dumps(data), encoding="utf-8")


def _transcript_for_window(
    segments: list[dict[str, Any]],
    start: float,
    end: float,
) -> str:
    parts = []
    for seg in segments:
        s, e = float(seg.get("start", 0)), float(seg.get("end", 0))
        if e >= start and s <= end:
            parts.append(seg.get("text", ""))
    return " ".join(parts).strip()


def _vlm_only_highlights(
    vlm_results: dict[str, dict],
    windows: list[WindowScore],
    config: AppConfig,
) -> list:
    from reels.models import Highlight

    highlights: list[Highlight] = []
    pre = config.clip.pre_pad_seconds
    post = config.clip.post_pad_seconds
    for key, data in sorted(vlm_results.items(), key=lambda x: -float(x[1].get("score", 0))):
        parts = key.split("-")
        if len(parts) != 2:
            continue
        start, end = float(parts[0]), float(parts[1])
        highlights.append(
            Highlight(
                start=max(0.0, start - pre),
                end=end + post,
                score=float(data.get("score", 0.5)),
                title=str(data.get("title", "Highlight")),
                reason=str(data.get("reason", "")),
                source="vlm",
            )
        )
    from reels.highlights import dedupe_highlights

    return dedupe_highlights(
        highlights,
        config.clip.dedupe_overlap_ratio,
        config.clip.merge_gap_seconds,
    )[: config.clip.max_clips]


def run_pipeline(
    video_path: Path,
    config: AppConfig,
    output_dir: Path | None = None,
    mode: AnalysisMode | None = None,
    *,
    resume: bool = False,
    use_nvenc: bool = False,
    cleanup: bool = False,
    reporter: ProgressReporter | None = None,
    skip_probe: bool = False,
    video_info: VideoInfo | None = None,
) -> Path:
    """Full run: analyze + export."""
    out = resolve_output_dir(video_path, output_dir)
    info = video_info
    if info is None and not skip_probe:
        _report(reporter, "probe", message="Probing video...")
        info = probe_video(video_path)
        _report(reporter, "probe", complete=True)

    doc = analyze_vod(
        video_path,
        config,
        out,
        mode=mode,
        resume=resume,
        reporter=reporter,
        video_info=info,
    )
    if info is None:
        info = probe_video(video_path)

    from reels.export import export_all

    export_all(
        video_path,
        doc,
        out,
        config,
        use_nvenc=use_nvenc,
        source_width=info.width,
        source_height=info.height,
        reporter=reporter,
    )
    if cleanup:
        cleanup_proxy(out, video_path.stem, source_video=video_path)
    return out
