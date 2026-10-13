"""Runtime system status for v2 UI (CPU, GPU, CUDA, models, active job)."""

from __future__ import annotations

import shutil
import subprocess
from typing import Any

from reels.config import load_config
from reels.cuda_env import cuda_libs_available, setup_cuda_library_path
from reels.subprocess_util import verify_tool
from reels.transcribe import _resolve_whisper_backend
from reels.twitch.download import require_yt_dlp
from reels.vlm.ollama import OllamaClient


def _cpu_metrics() -> dict[str, Any] | None:
    try:
        import psutil

        return {
            "percent": psutil.cpu_percent(interval=0.1),
            "count": psutil.cpu_count(logical=True) or 0,
        }
    except Exception:
        return None


def _memory_metrics() -> dict[str, Any] | None:
    try:
        import psutil

        mem = psutil.virtual_memory()
        return {
            "total_mb": round(mem.total / (1024**2)),
            "used_mb": round(mem.used / (1024**2)),
            "percent": mem.percent,
        }
    except Exception:
        return None


def _gpu_metrics() -> dict[str, Any] | None:
    smi = shutil.which("nvidia-smi")
    if not smi:
        return None
    try:
        result = subprocess.run(
            [
                smi,
                "--query-gpu=name,memory.total,memory.used,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        line = result.stdout.strip().splitlines()[0]
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            return None
        name, total, used, util = parts[0], parts[1], parts[2], parts[3]
        return {
            "name": name,
            "memory_total_mb": int(float(total)),
            "memory_used_mb": int(float(used)),
            "utilization_percent": float(util) if util not in ("[N/A]", "N/A") else None,
        }
    except Exception:
        return None


def _nvenc_available() -> bool:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    try:
        result = subprocess.run(
            [ffmpeg, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return "h264_nvenc" in (result.stdout or "")
    except Exception:
        return False


def nvenc_available() -> bool:
    """True when ffmpeg reports the h264_nvenc encoder."""
    return _nvenc_available()


def _whisper_effective_device(config) -> str:
    device, _ = _resolve_whisper_backend(config)
    if device == "cuda":
        try:
            setup_cuda_library_path()
            if cuda_libs_available():
                return "cuda"
        except Exception:
            pass
        return "cpu"
    return device


def _active_job_snapshot() -> dict[str, Any] | None:
    from reels.jobs import get_job_manager

    state = get_job_manager().active_job()
    if state is None:
        return None
    return {
        "id": state.id,
        "feature": state.feature,
        "phase": state.phase,
        "percent": state.percent,
        "message": state.message,
        "status": state.status,
    }


def collect_system_status(preset: str = "twitch_gaming") -> dict[str, Any]:
    config = load_config(preset)
    ffmpeg_ok = verify_tool("ffmpeg") and verify_tool("ffprobe")
    yt_dlp_ok = False
    try:
        require_yt_dlp()
        yt_dlp_ok = True
    except Exception:
        pass

    client = OllamaClient(config)
    setup_cuda_library_path()
    cuda_ok = cuda_libs_available()
    device, compute = _resolve_whisper_backend(config)
    effective = _whisper_effective_device(config)

    cpu = _cpu_metrics()
    memory = _memory_metrics()
    metrics_partial = cpu is None or memory is None

    return {
        "ffmpeg": ffmpeg_ok,
        "yt_dlp": yt_dlp_ok,
        "ollama": {
            "available": client.is_available(),
            "host": config.ollama.resolved_host(),
            "vision_model": config.ollama.vision_model,
            "merge_model": config.ollama.merge_model,
        },
        "whisper": {
            "configured_device": device,
            "effective_device": effective,
            "model": config.hardware.whisper_model,
            "compute_type": compute if effective == "cuda" else "int8",
        },
        "cuda": {
            "libs_available": cuda_ok,
            "nvenc_available": _nvenc_available(),
        },
        "gpu": _gpu_metrics(),
        "cpu": cpu,
        "memory": memory,
        "metrics_partial": metrics_partial,
        "active_job": _active_job_snapshot(),
        "preset": preset,
    }
