"""Twitch VOD URL parsing and yt-dlp download helpers."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

from reels.storage import temp_vods_dir  # re-exported for tests/monkeypatch

TWITCH_VOD_RE = re.compile(
    r"^https?://(?:www\.)?twitch\.tv/videos/(?P<id>\d+)/?$",
    re.IGNORECASE,
)

DEFAULT_CONCURRENT_FRAGMENTS = 32
DEFAULT_FRAGMENT_RETRIES = 10
DEFAULT_RETRIES = 10

_YT_DLP_PERCENT_RE = re.compile(r"\[download\].*?([\d.]+)%")


class TwitchDownloadError(Exception):
    """Raised when a Twitch download cannot be started or completed."""


def parse_twitch_vod_url(url: str) -> str:
    """Extract numeric VOD id from a Twitch VOD URL."""
    match = TWITCH_VOD_RE.match(url.strip())
    if not match:
        raise ValueError(f"Not a Twitch VOD URL: {url!r}")
    return match.group("id")


def normalize_twitch_vod_url(url: str) -> str:
    """Return canonical Twitch VOD URL for dedupe and yt-dlp."""
    video_id = parse_twitch_vod_url(url)
    return f"https://www.twitch.tv/videos/{video_id}"


def require_yt_dlp() -> str:
    """Return yt-dlp executable path or raise."""
    path = shutil.which("yt-dlp")
    if path:
        return path
    # pip install yt-dlp places the binary next to the active Python (venv Scripts/).
    venv_bin = Path(sys.executable).resolve().parent / (
        "yt-dlp.exe" if sys.platform == "win32" else "yt-dlp"
    )
    if venv_bin.is_file():
        return str(venv_bin)
    raise TwitchDownloadError(
        "yt-dlp not found — install with: pip install yt-dlp (or pip install -e \".[twitch]\")"
    )


def vod_output_path(video_id: str, vods_dir: Path | None = None) -> Path:
    """Predict output file path for a Twitch VOD id."""
    if vods_dir is None:
        from reels.video_store import original_dir, source_path, twitch_slug

        slug = twitch_slug(video_id)
        original_dir(slug).mkdir(parents=True, exist_ok=True)
        return source_path(slug)
    return vods_dir / f"twitch_vod_{video_id}.mp4"


def parse_yt_dlp_progress_percent(line: str) -> float | None:
    """Extract download percent from yt-dlp progress lines."""
    if "[download]" not in line:
        return None
    match = _YT_DLP_PERCENT_RE.search(line)
    if not match:
        return None
    try:
        return min(100.0, max(0.0, float(match.group(1))))
    except ValueError:
        return None


def build_yt_dlp_args(
    yt_dlp: str,
    url: str,
    output_path: Path,
    *,
    concurrent_fragments: int = DEFAULT_CONCURRENT_FRAGMENTS,
) -> list[str]:
    """Build yt-dlp CLI args with parallel HLS fragment downloads."""
    return [
        yt_dlp,
        "--no-part",
        "--retries",
        str(DEFAULT_RETRIES),
        "--fragment-retries",
        str(DEFAULT_FRAGMENT_RETRIES),
        "--concurrent-fragments",
        str(max(1, concurrent_fragments)),
        "-f",
        "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "--merge-output-format",
        "mp4",
        "-o",
        str(output_path),
        url,
    ]


def _summarize_yt_dlp_output(lines: list[str], exit_code: int) -> str:
    """Pick the most useful error line(s) from yt-dlp stdout/stderr merge."""
    error_lines = [
        ln.strip()
        for ln in lines
        if ln.strip() and ("ERROR:" in ln.upper() or ln.strip().upper().startswith("ERROR"))
    ]
    if error_lines:
        return error_lines[-1][:800]
    tail = "\n".join(ln for ln in lines[-10:] if ln.strip()).strip()
    if tail:
        return tail[-800:]
    return f"yt-dlp exited with code {exit_code}"


def download_twitch_vod(
    url: str,
    output_path: Path,
    *,
    yt_dlp: str | None = None,
    concurrent_fragments: int = DEFAULT_CONCURRENT_FRAGMENTS,
    on_progress: Callable[[str], None] | None = None,
    cancel_event=None,
) -> Path:
    """Download one Twitch VOD to output_path using yt-dlp."""
    executable = yt_dlp or require_yt_dlp()
    canonical = normalize_twitch_vod_url(url)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    args = build_yt_dlp_args(
        executable,
        canonical,
        output_path,
        concurrent_fragments=concurrent_fragments,
    )
    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    lines: list[str] = []
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            if cancel_event is not None and cancel_event.is_set():
                proc.terminate()
                raise TwitchDownloadError("Download cancelled")
            stripped = line.rstrip()
            lines.append(stripped)
            if on_progress is not None:
                on_progress(stripped)
        code = proc.wait()
    except Exception:
        proc.kill()
        proc.wait()
        raise
    if code != 0:
        raise TwitchDownloadError(_summarize_yt_dlp_output(lines, code))
    if not output_path.is_file():
        raise TwitchDownloadError(f"Expected output missing: {output_path}")
    return output_path.resolve()
