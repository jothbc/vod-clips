"""faster-whisper transcription on proxy audio."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from reels.config import AppConfig
from reels.cuda_env import setup_cuda_library_path

logger = logging.getLogger(__name__)

# Errors when CUDA libs (e.g. libcublas.so.12) are missing in WSL
_CUDA_LOAD_MARKERS = (
    "libcublas",
    "libcudnn",
    "cuda",
    "cublas",
    "cudnn",
    "cudnn_ops",
    "could not load",
    "cannot be loaded",
)


def _is_cuda_runtime_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(m in msg for m in _CUDA_LOAD_MARKERS)


def _resolve_whisper_backend(config: AppConfig) -> tuple[str, str]:
    """Pick device/compute_type; honor REELS_WHISPER_DEVICE env override."""
    env_device = os.environ.get("REELS_WHISPER_DEVICE", "").strip().lower()
    if env_device in ("cpu", "cuda"):
        device = env_device
    else:
        device = config.hardware.whisper_device

    if device == "cuda":
        compute = config.hardware.whisper_compute_type
    else:
        compute = "int8"
    return device, compute


def _run_transcribe(
    wav_path: Path,
    model_name: str,
    device: str,
    compute_type: str,
) -> list[dict[str, Any]]:
    if device == "cuda":
        setup_cuda_library_path()

    from faster_whisper import WhisperModel

    model = WhisperModel(model_name, device=device, compute_type=compute_type)
    segments_iter, _info = model.transcribe(
        str(wav_path),
        beam_size=5,
        vad_filter=True,
    )

    segments: list[dict[str, Any]] = []
    for seg in segments_iter:
        segments.append(
            {
                "start": seg.start,
                "end": seg.end,
                "text": seg.text.strip(),
            }
        )
    return segments


def transcribe_audio(
    wav_path: Path,
    config: AppConfig,
    *,
    warnings: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Transcribe WAV with faster-whisper; fall back to CPU if CUDA libs are missing."""
    model_name = config.hardware.whisper_model
    device, compute_type = _resolve_whisper_backend(config)

    if device == "cuda":
        try:
            return _run_transcribe(wav_path, model_name, "cuda", compute_type)
        except Exception as e:
            if not _is_cuda_runtime_error(e):
                raise
            msg = (
                f"Whisper CUDA unavailable ({e}). Falling back to CPU — "
                "install CUDA 12 + cuBLAS in WSL or set REELS_WHISPER_DEVICE=cpu."
            )
            logger.warning(msg)
            if warnings is not None:
                warnings.append(msg)

    return _run_transcribe(wav_path, model_name, "cpu", "int8")
