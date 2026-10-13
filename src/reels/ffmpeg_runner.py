"""Run ffmpeg with optional progress callbacks and cancellation."""

from __future__ import annotations

import subprocess
import threading
from collections import deque
from collections.abc import Callable

from reels.export import require_ffmpeg


def _parse_out_time_us(line: str) -> int | None:
    if not line.startswith("out_time_us="):
        return None
    raw = line.split("=", 1)[1].strip()
    if raw in ("N/A", ""):
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _drain_stderr(pipe, buffer: deque[str]) -> None:
    try:
        for line in pipe:
            buffer.append(line)
    except (ValueError, OSError):
        pass


def run_ffmpeg(
    cmd: list[str],
    *,
    expected_duration_sec: float = 0.0,
    on_progress: Callable[[float], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> None:
    """Execute ffmpeg; stream encode progress when *on_progress* is set."""
    require_ffmpeg()
    duration_us = max(1.0, expected_duration_sec) * 1_000_000

    if on_progress is None and cancel_event is None:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"Render failed: {(result.stderr or result.stdout)[-1500:]}")
        return

    full_cmd = [cmd[0], "-hide_banner", "-loglevel", "error", "-progress", "pipe:1", "-nostats", *cmd[1:]]
    proc = subprocess.Popen(
        full_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    assert proc.stdout is not None and proc.stderr is not None

    # Drain stderr on a background thread so a chatty ffmpeg can't fill the pipe buffer.
    stderr_buffer: deque[str] = deque(maxlen=200)
    stderr_thread = threading.Thread(
        target=_drain_stderr, args=(proc.stderr, stderr_buffer), daemon=True
    )
    stderr_thread.start()

    last_frac = -1.0
    try:
        for line in proc.stdout:
            if cancel_event and cancel_event.is_set():
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2)
                raise RuntimeError("Cancelled")
            us = _parse_out_time_us(line.strip())
            if us is None or on_progress is None:
                continue
            frac = min(1.0, us / duration_us)
            if frac - last_frac >= 0.005 or frac >= 1.0:
                last_frac = frac
                on_progress(frac)
        code = proc.wait()
        stderr_thread.join(timeout=2)
        if code != 0:
            stderr_text = "".join(stderr_buffer)[-1500:]
            raise RuntimeError(f"Render failed: {stderr_text}")
        if on_progress is not None:
            on_progress(1.0)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=2)
