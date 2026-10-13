"""Twitch VOD URL parsing and yt-dlp download helpers."""

from __future__ import annotations

import os
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

# Twitch HLS playlists sometimes insert a new init segment after media fragments
# (discontinuities). yt-dlp's hlsnative aborts; ffmpeg can still remux them.
_INIT_AFTER_MEDIA_RE = re.compile(
    r"Initialization fragment found after media fragments",
    re.IGNORECASE,
)

# Avast (and similar AV) inject SSLKEYLOGFILE pointing at a kernel filter device.
# When that device is closed/unprivileged, urllib/requests raise PermissionError and
# yt-dlp falls back to websockets with the confusing "Unsupported url scheme: https".
_AV_SSL_MARKERS = ("aswMonFltProxy", "avast", "avgssl", "aswSSL")
_SSL_ENV_KEYS = (
    "SSLKEYLOGFILE",
    "SSL_CERT_FILE",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
)


class TwitchDownloadError(Exception):
    """Raised when a Twitch download cannot be started or completed."""


def _is_av_ssl_hijack(value: str) -> bool:
    lowered = value.lower().replace("\\", "/")
    return any(marker in lowered for marker in _AV_SSL_MARKERS)


def sanitize_ssl_env(env: dict[str, str] | None = None) -> dict[str, str]:
    """Return a copy of env with AV HTTPS-interception variables removed."""
    out = dict(os.environ if env is None else env)
    for key in _SSL_ENV_KEYS:
        value = out.get(key, "")
        if value and _is_av_ssl_hijack(value):
            out.pop(key, None)
        elif key == "SSLKEYLOGFILE" and value.startswith("\\\\.\\"):
            # Named device path (\\.\Something) — not a real key log file.
            out.pop(key, None)
    return out


def clear_av_ssl_env() -> list[str]:
    """Strip AV SSL hijacks from the current process environ. Returns removed keys."""
    removed: list[str] = []
    for key in _SSL_ENV_KEYS:
        value = os.environ.get(key, "")
        if not value:
            continue
        if _is_av_ssl_hijack(value) or (key == "SSLKEYLOGFILE" and value.startswith("\\\\.\\")):
            os.environ.pop(key, None)
            removed.append(key)
    return removed


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
    downloader: str | None = None,
) -> list[str]:
    """Build yt-dlp CLI args with parallel HLS fragment downloads."""
    args = [
        yt_dlp,
        "--no-part",
        "--retries",
        str(DEFAULT_RETRIES),
        "--fragment-retries",
        str(DEFAULT_FRAGMENT_RETRIES),
    ]
    if downloader:
        args.extend(["--downloader", downloader])
    else:
        args.extend(["--concurrent-fragments", str(max(1, concurrent_fragments))])
    args.extend(
        [
            "-f",
            "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "--merge-output-format",
            "mp4",
            "-o",
            str(output_path),
            url,
        ]
    )
    return args


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


def _is_init_after_media_error(lines: list[str]) -> bool:
    return any(_INIT_AFTER_MEDIA_RE.search(ln) for ln in lines)


def _clear_partial_output(output_path: Path) -> None:
    """Remove incomplete yt-dlp artifacts before a retry."""
    for path in (output_path, Path(f"{output_path}.ytdl")):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def _run_yt_dlp(
    args: list[str],
    *,
    on_progress: Callable[[str], None] | None = None,
    cancel_event=None,
) -> tuple[int, list[str]]:
    """Run yt-dlp and stream stdout lines. Returns (exit_code, lines)."""
    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=sanitize_ssl_env(),
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
    return code, lines


def _is_fragmented_mp4(path: Path) -> bool:
    """True when the file looks like fMP4/HLS (not browser-friendly progressive)."""
    try:
        with path.open("rb") as f:
            head = f.read(4096)
    except OSError:
        return False
    if b"moof" in head:
        return True
    brands = head[8:48] if len(head) >= 48 else head
    return any(marker in brands for marker in (b"dash", b"hlsf", b"iso6", b"msdh", b"msix"))


def remux_to_progressive_mp4(
    path: Path,
    *,
    on_progress: Callable[[str], None] | None = None,
    cancel_event=None,
) -> Path:
    """Remux fMP4 into a progressive MP4 with moov at the start (browser playable)."""
    from reels.export import require_ffmpeg

    if not path.is_file():
        raise TwitchDownloadError(f"Expected output missing: {path}")
    if not _is_fragmented_mp4(path):
        return path.resolve()

    ffmpeg = require_ffmpeg()
    tmp = path.with_suffix(".progressive.mp4")
    if tmp.exists():
        tmp.unlink()
    if on_progress is not None:
        on_progress("Remuxing fragmented MP4 for browser playback…")
    args = [
        ffmpeg,
        "-y",
        "-i",
        str(path),
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(tmp),
    ]
    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=sanitize_ssl_env(),
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
            if on_progress is not None and ("time=" in stripped or "Lsize=" in stripped):
                on_progress(stripped)
        code = proc.wait()
    except Exception:
        proc.kill()
        proc.wait()
        tmp.unlink(missing_ok=True)
        raise
    if code != 0 or not tmp.is_file() or tmp.stat().st_size < 1000:
        tmp.unlink(missing_ok=True)
        raise TwitchDownloadError(
            _summarize_yt_dlp_output(lines, code) if lines else f"ffmpeg remux failed ({code})"
        )
    path.unlink(missing_ok=True)
    tmp.replace(path)
    return path.resolve()


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
    used_ffmpeg_downloader = False
    code, lines = _run_yt_dlp(args, on_progress=on_progress, cancel_event=cancel_event)
    if code != 0 and _is_init_after_media_error(lines):
        if on_progress is not None:
            on_progress(
                "hlsnative failed (init after media fragments); retrying with --downloader ffmpeg"
            )
        _clear_partial_output(output_path)
        ffmpeg_args = build_yt_dlp_args(
            executable,
            canonical,
            output_path,
            concurrent_fragments=concurrent_fragments,
            downloader="ffmpeg",
        )
        code, lines = _run_yt_dlp(
            ffmpeg_args, on_progress=on_progress, cancel_event=cancel_event
        )
        used_ffmpeg_downloader = True
    if code != 0:
        raise TwitchDownloadError(_summarize_yt_dlp_output(lines, code))
    if not output_path.is_file():
        raise TwitchDownloadError(f"Expected output missing: {output_path}")
    if used_ffmpeg_downloader or _is_fragmented_mp4(output_path):
        remux_to_progressive_mp4(
            output_path, on_progress=on_progress, cancel_event=cancel_event
        )
    return output_path.resolve()
