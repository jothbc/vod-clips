"""Proxy generation and disk space management."""

from __future__ import annotations

import shutil
from pathlib import Path

from reels.config import AppConfig
from reels.models import VideoInfo
from reels.subprocess_util import check_spawn_headroom, require_tool, run_tool


class ProxyError(RuntimeError):
    pass


def require_ffmpeg() -> str:
    return require_tool("ffmpeg")


def check_disk_space(video: VideoInfo, output_dir: Path, config: AppConfig) -> None:
    """Ensure enough free space (multiplier × VOD size)."""
    mode = config.proxy.video_mode
    multiplier = config.proxy.min_free_disk_multiplier
    if mode == "audio_only":
        # WAV + exports; no duplicate video file.
        multiplier = min(multiplier, 1.25)
    required = int(video.size_bytes * multiplier)
    usage = shutil.disk_usage(output_dir)
    if usage.free < required:
        raise ProxyError(
            f"Insufficient disk space: need ~{required / 1e9:.1f} GB free, "
            f"have {usage.free / 1e9:.1f} GB in {output_dir}"
        )


def preview_stream_path(output_dir: Path, video_stem: str) -> Path:
    return output_dir / f"{video_stem}_preview.mp4"


def proxy_paths(output_dir: Path, video_stem: str) -> tuple[Path, Path]:
    proxy = output_dir / f"{video_stem}_proxy.mp4"
    audio = output_dir / f"{video_stem}_audio_16k.wav"
    return proxy, audio


def _extract_audio(video_path: Path, audio_path: Path, sample_rate: int) -> None:
    ffmpeg = require_ffmpeg()
    audio_cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-c:a",
        "pcm_s16le",
        str(audio_path),
    ]
    _run(audio_cmd, "extract audio")


def generate_proxy(
    video_path: Path,
    output_dir: Path,
    config: AppConfig,
    video: VideoInfo,
    *,
    skip_if_exists: bool = True,
) -> tuple[Path, Path, Path]:
    """Prepare analysis inputs and optional browser preview remux.

    Returns (video_for_analysis, audio_wav, preview_for_streaming).
    """
    require_ffmpeg()
    check_spawn_headroom()
    output_dir.mkdir(parents=True, exist_ok=True)
    check_disk_space(video, output_dir, config)

    source = video_path.resolve()
    proxy_path, audio_path = proxy_paths(output_dir, video_path.stem)
    preview_path = preview_stream_path(output_dir, video_path.stem)
    mode = config.proxy.video_mode
    ar = config.proxy.audio_sample_rate

    if mode == "audio_only":
        if skip_if_exists and audio_path.exists():
            preview = preview_path if config.proxy.make_preview and preview_path.exists() else source
            return source, audio_path, preview
        _extract_audio(source, audio_path, ar)
        if config.proxy.make_preview:
            _remux_preview(source, preview_path)
            return source, audio_path, preview_path
        return source, audio_path, source

    if skip_if_exists and proxy_path.exists() and audio_path.exists():
        preview = preview_path if preview_path.exists() else proxy_path
        return proxy_path, audio_path, preview

    if mode == "copy":
        ffmpeg = require_ffmpeg()
        copy_cmd = [
            ffmpeg,
            "-y",
            "-i",
            str(source),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(proxy_path),
        ]
        try:
            run_tool(copy_cmd, label="ffmpeg copy")
        except Exception:
            mode = "transcode"
        else:
            if not audio_path.exists() or not skip_if_exists:
                _extract_audio(source, audio_path, ar)
            return proxy_path, audio_path, proxy_path

    height = config.hardware.proxy_height
    vbitrate = config.proxy.video_bitrate
    scale = f"scale=-2:{height}"
    ffmpeg = require_ffmpeg()
    proxy_cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(source),
        "-vf",
        scale,
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-b:v",
        vbitrate,
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        str(proxy_path),
    ]
    _run(proxy_cmd, "proxy video")
    _extract_audio(source, audio_path, ar)
    return proxy_path, audio_path, proxy_path


def _remux_preview(source: Path, preview_path: Path) -> None:
    ffmpeg = require_ffmpeg()
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(source),
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(preview_path),
    ]
    _run(cmd, "preview remux")


def cleanup_proxy(
    output_dir: Path,
    video_stem: str,
    *,
    source_video: Path | None = None,
) -> None:
    """Remove generated proxy MP4 and temp audio (never deletes source VOD)."""
    proxy, audio = proxy_paths(output_dir, video_stem)
    preview = preview_stream_path(output_dir, video_stem)
    source = source_video.resolve() if source_video else None
    for path in (proxy, audio, preview):
        if not path.exists():
            continue
        if source and path.resolve() == source:
            continue
        path.unlink()
    frames_dir = output_dir / f"{video_stem}_frames"
    if frames_dir.is_dir():
        shutil.rmtree(frames_dir, ignore_errors=True)


def _run(cmd: list[str], label: str) -> None:
    try:
        run_tool(cmd, label=f"ffmpeg {label}")
    except Exception as e:
        raise ProxyError(str(e)) from e
