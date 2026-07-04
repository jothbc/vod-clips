"""FFmpeg export for YouTube 16:9 and Reels 9:16."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from reels.config import AppConfig, ExportProfile, ExportProfiles, load_export_profiles
from reels.models import Highlight, HighlightsDocument, WebcamRegion
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


def resolve_export_nvenc(config: AppConfig, explicit: bool | None = None) -> bool:
    """Pick NVENC when explicitly requested, configured, or hardware supports it."""
    if explicit is True:
        return True
    if explicit is False:
        return False
    if config.hardware.ffmpeg_video_encoder == "h264_nvenc":
        return True
    from reels.system_status import nvenc_available

    return nvenc_available()


def build_crop_filter(
    source_width: int,
    source_height: int,
    profile: ExportProfile,
) -> str:
    """Center crop to a 9:16 region that fits inside the source frame."""
    crop_h = min(profile.height, source_height)
    if crop_h % 2:
        crop_h -= 1
    crop_w = min(profile.width, (crop_h * 9 + 15) // 16)
    if crop_w % 2:
        crop_w -= 1
    if crop_w > source_width:
        crop_w = source_width if source_width % 2 == 0 else source_width - 1
        crop_h = (crop_w * 16 + 8) // 9
        if crop_h % 2:
            crop_h -= 1
        crop_h = min(crop_h, source_height)
    x = max(0, (source_width - crop_w) // 2)
    y = max(0, (source_height - crop_h) // 2)
    return f"crop={crop_w}:{crop_h}:{x}:{y}"


def build_scale_filter(
    source_width: int,
    source_height: int,
    profile: ExportProfile,
) -> str:
    """Scale down to target size without padding; never upscale."""
    target_w = min(source_width, profile.width)
    target_h = min(source_height, profile.height)
    if target_w % 2:
        target_w -= 1
    if target_h % 2:
        target_h -= 1
    return f"scale={target_w}:{target_h}"


def _even(n: int) -> int:
    return max(2, n - (n % 2))


def compute_reels_webcam_layout(
    source_width: int,
    source_height: int,
    out_width: int,
    out_height: int,
    region: WebcamRegion,
    *,
    max_webcam_height_ratio: float = 0.45,
) -> tuple[int, int, int, int, int, int, int, int, int, int, int]:
    """Return cam crop, cam out size, main crop, main out size (all even)."""
    x1, y1, x2, y2 = region.x1, region.y1, region.x2, region.y2
    cam_w = _even(x2 - x1)
    cam_h = _even(y2 - y1)
    out_w = _even(out_width)
    out_h = _even(out_height)
    h_cam = _even(int(out_w * cam_h / max(1, cam_w)))
    max_h_cam = _even(int(out_h * max_webcam_height_ratio))
    if h_cam > max_h_cam:
        h_cam = max_h_cam
    h_main = _even(out_h - h_cam)
    if h_main < 32:
        raise ExportError("Webcam region leaves too little space for gameplay")

    ar = out_w / h_main
    if source_width / source_height > ar:
        main_crop_h = _even(source_height)
        main_crop_w = _even(int(main_crop_h * ar))
    else:
        main_crop_w = _even(source_width)
        main_crop_h = _even(int(main_crop_w / ar))
    main_x = max(0, (source_width - main_crop_w) // 2)
    main_y = max(0, (source_height - main_crop_h) // 2)
    return x1, y1, cam_w, cam_h, main_crop_w, main_crop_h, main_x, main_y, out_w, h_cam, h_main


def build_reels_webcam_filter_complex(
    source_width: int,
    source_height: int,
    out_width: int,
    out_height: int,
    region: WebcamRegion,
) -> str:
    """Stack webcam strip on top of center-cropped gameplay for 9:16 output."""
    x1, y1, cw, ch, mw, mh, mx, my, out_w, h_cam, h_main = compute_reels_webcam_layout(
        source_width, source_height, out_width, out_height, region
    )
    return (
        f"[0:v]crop={cw}:{ch}:{x1}:{y1},scale={out_w}:{h_cam}[cam];"
        f"[0:v]crop={mw}:{mh}:{mx}:{my},scale={out_w}:{h_main}:force_original_aspect_ratio=increase,"
        f"crop={out_w}:{h_main}[main];"
        f"[cam][main]vstack=inputs=2[vout]"
    )


def export_reels_clip(
    source_video: Path,
    highlight: Highlight,
    output_path: Path,
    profile: ExportProfile,
    config: AppConfig,
    *,
    region: WebcamRegion,
    use_nvenc: bool = False,
    source_width: int = 1920,
    source_height: int = 1080,
    max_duration: float | None = None,
) -> None:
    """Cut highlight and export stacked reels layout with webcam on top."""
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
    fc = build_reels_webcam_filter_complex(
        source_width, source_height, profile.width, profile.height, region
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        str(highlight.start),
        "-i",
        str(source_video),
        "-t",
        str(duration),
        "-filter_complex",
        fc,
        "-map",
        "[vout]",
        "-map",
        "0:a?",
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
        raise ExportError(f"Reels webcam export failed for {output_path.name}: {result.stderr[-1500:]}")


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
    from reels.export_resolution import default_reels_size, default_youtube_size

    yt_w, yt_h = default_youtube_size(source_width, source_height)
    rl_w, rl_h = default_reels_size(source_width, source_height)
    yt_profile = profiles.youtube.model_copy(update={"width": yt_w, "height": yt_h})
    reels_profile = profiles.reels.model_copy(update={"width": rl_w, "height": rl_h})
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
            yt_profile,
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
            reels_profile,
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


def export_selected(
    source_video: Path,
    doc: HighlightsDocument,
    highlight_indices: list[int],
    output_dir: Path,
    config: AppConfig,
    *,
    profiles: ExportProfiles | None = None,
    use_nvenc: bool = False,
    source_width: int = 1920,
    source_height: int = 1080,
    youtube_size: tuple[int, int] | None = None,
    reels_size: tuple[int, int] | None = None,
    reporter: ProgressReporter | None = None,
) -> list[Path]:
    """Export only selected highlights with dynamic resolution profiles."""
    profiles = profiles or load_export_profiles()
    yt_profile = profiles.youtube.model_copy(
        update={
            "width": youtube_size[0] if youtube_size else profiles.youtube.width,
            "height": youtube_size[1] if youtube_size else profiles.youtube.height,
        }
    )
    reels_profile = profiles.reels.model_copy(
        update={
            "width": reels_size[0] if reels_size else profiles.reels.width,
            "height": reels_size[1] if reels_size else profiles.reels.height,
        }
    )

    written: list[Path] = []
    selected = [doc.highlights[i] for i in highlight_indices if 0 <= i < len(doc.highlights)]
    total_steps = max(len(selected) * 2, 1)
    step = 0

    for i, hl in enumerate(selected):
        safe_title = _safe_filename(hl.title, highlight_indices[i])
        step += 1
        if reporter:
            reporter.report(
                "export",
                current=step,
                total=total_steps,
                message=f"YouTube clip {i + 1}/{len(selected)}",
            )
        yt_path = output_dir / "youtube" / f"{safe_title}.mp4"
        export_clip(
            source_video,
            hl,
            yt_path,
            yt_profile,
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
                message=f"Reels clip {i + 1}/{len(selected)}",
            )
        reels_path = output_dir / "reels" / f"{safe_title}.mp4"
        export_clip(
            source_video,
            hl,
            reels_path,
            reels_profile,
            config,
            use_nvenc=use_nvenc,
            source_width=source_width,
            source_height=source_height,
            max_duration=config.clip.max_duration_reels,
        )
        written.append(reels_path)

    if reporter and selected:
        reporter.report("export", current=total_steps, total=total_steps, message="Export complete")
        if hasattr(reporter, "mark_phase_complete"):
            reporter.mark_phase_complete("export")  # type: ignore[attr-defined]

    return written


def _safe_filename(title: str, index: int) -> str:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in title)[:60]
    return f"{index:02d}_{safe or 'clip'}"
