"""Cross-platform subprocess helpers for ffmpeg/ffprobe."""

from __future__ import annotations

import shutil
import subprocess
import sys
from typing import Sequence

_WINDOWS_RC_HINTS: dict[int, str] = {
    0xC0000017: (
        "Insufficient memory to start ffmpeg/ffprobe (Windows 0xC0000017). "
        "Close other apps (browser, games, Ollama), then retry. "
        "If it persists, increase the Windows page file."
    ),
    0xC0000135: (
        "ffmpeg/ffprobe failed to load a required DLL (0xC0000135). "
        "Reinstall ffmpeg: winget install Gyan.FFmpeg"
    ),
    0xC0000142: (
        "ffmpeg/ffprobe failed to initialize (0xC0000142). "
        "Reinstall ffmpeg: winget install Gyan.FFmpeg"
    ),
}


class ToolError(RuntimeError):
    pass


def _unsigned_rc(code: int) -> int:
    return int(code) & 0xFFFFFFFF


def explain_returncode(code: int) -> str | None:
    if code == 0:
        return None
    hint = _WINDOWS_RC_HINTS.get(_unsigned_rc(code))
    if hint:
        return hint
    return f"Process exited with code {code} (0x{_unsigned_rc(code):08X})"


def require_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise ToolError(f"{name} not found in PATH")
    return path


def _startupinfo() -> subprocess.STARTUPINFO | None:
    if sys.platform != "win32":
        return None
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = subprocess.SW_HIDE
    return info


def run_tool(
    cmd: Sequence[str],
    *,
    label: str = "tool",
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run an external tool; resolve bare names via PATH and hide console on Windows."""
    argv = list(cmd)
    if argv and "/" not in argv[0] and "\\" not in argv[0]:
        argv[0] = require_tool(argv[0])

    kwargs: dict = {
        "capture_output": True,
        "text": True,
        "check": False,
    }
    if sys.platform == "win32":
        kwargs["startupinfo"] = _startupinfo()
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

    try:
        result = subprocess.run(argv, timeout=timeout, **kwargs)
    except FileNotFoundError as e:
        raise ToolError(f"{label}: executable not found ({argv[0]})") from e
    except subprocess.TimeoutExpired as e:
        raise ToolError(f"{label}: timed out after {timeout}s") from e

    if result.returncode != 0:
        hint = explain_returncode(result.returncode)
        tail = (result.stderr or result.stdout or "").strip()[-1500:]
        msg = hint or f"{label} failed"
        if tail:
            msg = f"{msg}: {tail}"
        raise ToolError(msg)
    return result


def verify_tool(name: str) -> bool:
    try:
        run_tool([name, "-version"], label=name, timeout=30)
        return True
    except ToolError:
        return False


def check_spawn_headroom(min_free_mb: int = 1200) -> None:
    """Fail early with a clear message when RAM is too low to spawn ffmpeg."""
    try:
        import psutil
    except ImportError:
        return

    available_mb = psutil.virtual_memory().available // (1024 * 1024)
    if available_mb < min_free_mb:
        raise ToolError(
            f"Only {available_mb} MB RAM available; need at least ~{min_free_mb} MB "
            "to run ffmpeg/ffprobe. Close other applications and retry."
        )
