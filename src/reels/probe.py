"""ffprobe wrapper for video metadata."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from reels.models import VideoInfo


class ProbeError(RuntimeError):
    pass


def require_ffprobe() -> str:
    path = shutil.which("ffprobe")
    if not path:
        raise ProbeError("ffprobe not found. Install ffmpeg: sudo apt install ffmpeg")
    return path


def probe_video(video_path: Path) -> VideoInfo:
    ffprobe = require_ffprobe()
    cmd = [
        ffprobe,
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(video_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise ProbeError(f"ffprobe failed: {result.stderr}")

    data = json.loads(result.stdout)
    fmt = data.get("format", {})
    duration = float(fmt.get("duration", 0))
    size_bytes = int(fmt.get("size", 0))

    video_stream = None
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            video_stream = stream
            break

    if not video_stream:
        raise ProbeError("No video stream found")

    width = int(video_stream.get("width", 0))
    height = int(video_stream.get("height", 0))
    fps_str = video_stream.get("r_frame_rate", "30/1")
    if "/" in fps_str:
        num, den = fps_str.split("/", 1)
        fps = float(num) / float(den) if float(den) else 30.0
    else:
        fps = float(fps_str)

    return VideoInfo(
        path=str(video_path.resolve()),
        duration=duration,
        width=width,
        height=height,
        fps=fps,
        codec=video_stream.get("codec_name", ""),
        size_bytes=size_bytes,
    )
