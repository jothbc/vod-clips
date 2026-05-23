"""Proxy generation modes."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from reels.config import AppConfig, ProxyConfig
from reels.models import VideoInfo
from reels.proxy import cleanup_proxy, generate_proxy, proxy_paths


def _video_info(path: Path) -> VideoInfo:
    return VideoInfo(
        path=str(path),
        duration=120.0,
        width=1920,
        height=1080,
        fps=30.0,
        codec="h264",
        size_bytes=1_000_000,
    )


@patch("reels.proxy._run")
@patch("reels.proxy.check_disk_space")
def test_audio_only_skips_video_encode(mock_disk: MagicMock, mock_run: MagicMock, tmp_path: Path) -> None:
    source = tmp_path / "vod.mp4"
    source.write_bytes(b"fake")
    out = tmp_path / "out"
    config = AppConfig(proxy=ProxyConfig(video_mode="audio_only"))
    video_path, audio_path = generate_proxy(
        source, out, config, _video_info(source), skip_if_exists=False
    )
    assert video_path.resolve() == source.resolve()
    assert audio_path.name.endswith("_audio_16k.wav")
    mock_run.assert_called_once()
    assert "-vn" in mock_run.call_args[0][0]


@patch("reels.proxy._run")
@patch("reels.proxy.check_disk_space")
def test_audio_only_reuses_wav(mock_disk: MagicMock, mock_run: MagicMock, tmp_path: Path) -> None:
    source = tmp_path / "vod.mp4"
    source.write_bytes(b"fake")
    out = tmp_path / "out"
    out.mkdir()
    _, audio_path = proxy_paths(out, source.stem)
    audio_path.write_bytes(b"wav")
    config = AppConfig(proxy=ProxyConfig(video_mode="audio_only"))
    video_path, returned_audio = generate_proxy(
        source, out, config, _video_info(source), skip_if_exists=True
    )
    assert video_path == source.resolve()
    assert returned_audio == audio_path
    mock_run.assert_not_called()


def test_cleanup_never_deletes_source_vod(tmp_path: Path) -> None:
    source = tmp_path / "vod.mp4"
    source.write_bytes(b"x")
    out = tmp_path / "out"
    out.mkdir()
    proxy, audio = proxy_paths(out, source.stem)
    proxy.write_bytes(b"proxy")
    audio.write_bytes(b"audio")
    cleanup_proxy(out, source.stem, source_video=source)
    assert source.exists()
    assert not proxy.exists()
    assert not audio.exists()
