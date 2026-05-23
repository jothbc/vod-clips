"""Proxy generation and disk space management."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from reels.config import AppConfig
from reels.models import VideoInfo


class ProxyError(RuntimeError):
    pass


def require_ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise ProxyError("ffmpeg not found. Install: sudo apt install ffmpeg")
    return path


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


def proxy_paths(output_dir: Path, video_stem: str) -> tuple[Path, Path]:
    proxy = output_dir / f"{video_stem}_proxy.mp4"
    audio = output_dir / f"{video_stem}_audio_16k.wav"
    return proxy, audio


def _extract_audio(video_path: Path, audio_path: Path, sample_rate: int) -> None:
    audio_cmd = [
        "ffmpeg",
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
) -> tuple[Path, Path]:
    """Prepare analysis inputs: 16 kHz mono WAV + video path for frame/scene work.

    Default ``audio_only`` skips video re-encode and uses the source file for
    motion, scene detection, and VLM frame grabs (export still uses original).
    """
    require_ffmpeg()
    output_dir.mkdir(parents=True, exist_ok=True)
    check_disk_space(video, output_dir, config)

    source = video_path.resolve()
    proxy_path, audio_path = proxy_paths(output_dir, video_path.stem)
    mode = config.proxy.video_mode
    ar = config.proxy.audio_sample_rate

    if mode == "audio_only":
        if skip_if_exists and audio_path.exists():
            return source, audio_path
        _extract_audio(source, audio_path, ar)
        return source, audio_path

    if skip_if_exists and proxy_path.exists() and audio_path.exists():
        return proxy_path, audio_path

    if mode == "copy":
        copy_cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(source),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(proxy_path),
        ]
        result = subprocess.run(copy_cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            mode = "transcode"
        else:
            if not audio_path.exists() or not skip_if_exists:
                _extract_audio(source, audio_path, ar)
            return proxy_path, audio_path

    height = config.hardware.proxy_height
    vbitrate = config.proxy.video_bitrate
    scale = f"scale=-2:{height}"
    proxy_cmd = [
        "ffmpeg",
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
    return proxy_path, audio_path


def cleanup_proxy(
    output_dir: Path,
    video_stem: str,
    *,
    source_video: Path | None = None,
) -> None:
    """Remove generated proxy MP4 and temp audio (never deletes source VOD)."""
    proxy, audio = proxy_paths(output_dir, video_stem)
    source = source_video.resolve() if source_video else None
    for path in (proxy, audio):
        if not path.exists():
            continue
        if source and path.resolve() == source:
            continue
        path.unlink()
    frames_dir = output_dir / f"{video_stem}_frames"
    if frames_dir.is_dir():
        shutil.rmtree(frames_dir, ignore_errors=True)


def _run(cmd: list[str], label: str) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise ProxyError(f"ffmpeg {label} failed: {result.stderr[-2000:]}")
