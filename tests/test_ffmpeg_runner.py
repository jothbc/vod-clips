"""Tests for ffmpeg progress helper and NVENC resolution."""

from __future__ import annotations

from reels.config import AppConfig, HardwareConfig
from reels.export import resolve_export_nvenc
from reels.ffmpeg_runner import _parse_out_time_us


def test_parse_out_time_us():
    assert _parse_out_time_us("out_time_us=5000000") == 5_000_000
    assert _parse_out_time_us("out_time_us=N/A") is None
    assert _parse_out_time_us("progress=continue") is None


def test_resolve_export_nvenc_explicit():
    config = AppConfig()
    assert resolve_export_nvenc(config, True) is True
    assert resolve_export_nvenc(config, False) is False


def test_resolve_export_nvenc_from_config(monkeypatch):
    config = AppConfig(hardware=HardwareConfig(ffmpeg_video_encoder="h264_nvenc"))
    monkeypatch.setattr("reels.system_status.nvenc_available", lambda: False)
    assert resolve_export_nvenc(config, None) is True
