"""Whisper CUDA fallback tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from reels.config import load_config
from reels.transcribe import _is_cuda_runtime_error, transcribe_audio


def test_cuda_error_detection():
    assert _is_cuda_runtime_error(RuntimeError("Library libcublas.so.12 is not found"))
    assert not _is_cuda_runtime_error(RuntimeError("something else"))


def test_fallback_to_cpu_on_cublas_error(tmp_path):
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"\x00" * 100)
    config = load_config("default")

    calls: list[tuple[str, str]] = []

    def fake_run(path, model, device, compute, **kwargs):
        calls.append((device, compute))
        if device == "cuda":
            raise RuntimeError("Library libcublas.so.12 is not found or cannot be loaded")
        return [{"start": 0.0, "end": 1.0, "text": "hello"}]

    warnings: list[str] = []
    with patch("reels.transcribe._run_transcribe", side_effect=fake_run):
        with patch("reels.transcribe._resolve_whisper_backend", return_value=("cuda", "float16")):
            segs = transcribe_audio(wav, config, warnings=warnings)

    assert len(segs) == 1
    assert calls[0][0] == "cuda"
    assert calls[1] == ("cpu", "int8")
    assert any("CPU" in w for w in warnings)
