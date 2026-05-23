"""FFmpeg export for YouTube 16:9 and Reels 9:16."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from reels.config import AppConfig, ExportProfile, ExportProfiles, load_export_profiles
from reels.models import Highlight, HighlightsDocument
from reels.progress import ProgressReporter


class ExportError(RuntimeError):
    pass


def require_ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise ExportError("ffmpeg not found")
    return path


def select_video_encoder(
    profile: ExportProfile,
    config: AppConfig,
    use_nvenc: bool,
) -> tuple[str, list[str]]:
    """Return codec name and extra encoder args."""
    encoder = config.hardware.ffmpeg_video_encoder
    if use_nvenc or encoder == "h264_nvenc":
        if shutil.which("ffmpeg"):
            # probe nvenc availability via ffmpeg -encoders is heavy; trust config
            return profile.nvenc_codec, [
                "-preset",
                profile.nvenc_preset,
                "-cq",
                str(profile.nvenc_cq),
            ]
    return profile.video_codec, ["-crf", str(profile.crf), "-preset", profile.preset]


def build_crop_filter(
    source_width: int,
    source_height: int,
    profile: ExportProfile,
) -> str:
    """Center crop landscape 1080p to 9:16 for Reels."""
    target_w = profile.width
    target_h = profile.height
    # crop to 9:16 from center then scale
    crop_w = source_height * 9 // 16
    if crop_w > source_width:
        crop_w = source_width
    x = (source_width - crop_w) // 2
    return (
        f"crop={crop_w}:{source_height}:{x}:0,"
        f"scale={target_w}:{target_h}"
    )


def build_scale_filter(
    source_width: int,
    source_height: int,
    profile: ExportProfile,
) -> str:
    return f"scale={profile.width}:{profile.height}:force_original_aspect_ratio=decrease,pad={profile.width}:{profile.height}:(ow-iw)/2:(oh-ih)/2"


def export_clip(
    source_video: Path,
    highlight: Highlight,
    output_path: Path,
    profile: ExportProfile,
    config: AppConfig,
    *,
    use_nvenc: bool = False,
    source_width: int = 1920,
    source_height: int = 1080,
    max_duration: float | None = None,
) -> None:
    """Cut one highlight from original VOD with seek (no full load in RAM)."""
    require_ffmpeg()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    duration = highlight.end - highlight.start
    cap = max_duration or profile.max_duration
    if duration > cap:
        highlight = Highlight(
            start=highlight.start,
            end=highlight.start + cap,
            score=highlight.score,
            title=highlight.title,
            reason=highlight.reason,
            source=highlight.source,
        )
        duration = cap

    codec, enc_args = select_video_encoder(profile, config, use_nvenc)

    if profile.crop_mode == "center":
        vf = build_crop_filter(source_width, source_height, profile)
    else:
        vf = build_scale_filter(source_width, source_height, profile)

    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        str(highlight.start),
        "-i",
        str(source_video),
        "-t",
        str(duration),
        "-vf",
        vf,
        "-c:v",
        codec,
        *enc_args,
        "-c:a",
        profile.audio_codec,
        "-b:a",
        profile.audio_bitrate,
        "-movflags",
        "+faststart",
        str(output_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise ExportError(f"Export failed for {output_path.name}: {result.stderr[-1500:]}")


def export_all(
    source_video: Path,
    doc: HighlightsDocument,
    output_dir: Path,
    config: AppConfig,
    *,
    profiles: ExportProfiles | None = None,
    use_nvenc: bool = False,
    source_width: int = 1920,
    source_height: int = 1080,
    reporter: ProgressReporter | None = None,
) -> list[Path]:
    """Export all highlights to youtube/ and reels/ subdirs."""
    profiles = profiles or load_export_profiles()
    written: list[Path] = []
    total_steps = max(len(doc.highlights) * 2, 1)
    step = 0

    for i, hl in enumerate(doc.highlights):
        safe_title = _safe_filename(hl.title, i)
        step += 1
        if reporter:
            reporter.report(
                "export",
                current=step,
                total=total_steps,
                message=f"YouTube clip {i + 1}/{len(doc.highlights)}",
            )
        yt_path = output_dir / "youtube" / f"{safe_title}.mp4"
        export_clip(
            source_video,
            hl,
            yt_path,
            profiles.youtube,
            config,
            use_nvenc=use_nvenc,
            source_width=source_width,
            source_height=source_height,
            max_duration=config.clip.max_duration_youtube,
        )
        written.append(yt_path)

        step += 1
        if reporter:
            reporter.report(
                "export",
                current=step,
                total=total_steps,
                message=f"Reels clip {i + 1}/{len(doc.highlights)}",
            )
        reels_path = output_dir / "reels" / f"{safe_title}.mp4"
        export_clip(
            source_video,
            hl,
            reels_path,
            profiles.reels,
            config,
            use_nvenc=use_nvenc,
            source_width=source_width,
            source_height=source_height,
            max_duration=config.clip.max_duration_reels,
        )
        written.append(reels_path)

    if reporter and doc.highlights:
        reporter.report("export", current=total_steps, total=total_steps, message="Export complete")
        if hasattr(reporter, "mark_phase_complete"):
            reporter.mark_phase_complete("export")  # type: ignore[attr-defined]

    return written


def _safe_filename(title: str, index: int) -> str:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in title)[:60]
    return f"{index:02d}_{safe or 'clip'}"
