"""Proxy generation modes."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from reels.config import AppConfig, ProxyConfig
from reels.models import VideoInfo
from reels.proxy import cleanup_proxy, generate_proxy, preview_stream_path, proxy_paths


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
def test_audio_only_extracts_audio_no_preview_by_default(
    mock_disk: MagicMock, mock_run: MagicMock, tmp_path: Path
) -> None:
    source = tmp_path / "vod.mp4"
    source.write_bytes(b"fake")
    out = tmp_path / "out"
    # Default make_preview=False: serve original via range, no full-VOD remux.
    config = AppConfig(proxy=ProxyConfig(video_mode="audio_only"))
    source_path, audio_path, preview_path = generate_proxy(
        source, out, config, _video_info(source), skip_if_exists=False
    )
    assert source_path.resolve() == source.resolve()
    assert audio_path.name.endswith("_audio_16k.wav")
    # No remux: preview is the original file itself.
    assert preview_path.resolve() == source.resolve()
    assert mock_run.call_count == 1  # audio extract only
    assert "-vn" in mock_run.call_args_list[0][0][0]


@patch("reels.proxy._run")
@patch("reels.proxy.check_disk_space")
def test_audio_only_make_preview_remuxes(
    mock_disk: MagicMock, mock_run: MagicMock, tmp_path: Path
) -> None:
    source = tmp_path / "vod.mp4"
    source.write_bytes(b"fake")
    out = tmp_path / "out"
    config = AppConfig(proxy=ProxyConfig(video_mode="audio_only", make_preview=True))
    _source_path, _audio_path, preview_path = generate_proxy(
        source, out, config, _video_info(source), skip_if_exists=False
    )
    assert preview_path == preview_stream_path(out, source.stem)
    assert mock_run.call_count == 2  # audio + faststart remux
    assert "copy" in mock_run.call_args_list[1][0][0]


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
    source_path, returned_audio, preview_path = generate_proxy(
        source, out, config, _video_info(source), skip_if_exists=True
    )
    assert source_path == source.resolve()
    assert returned_audio == audio_path
    assert preview_path.resolve() == source.resolve()
    mock_run.assert_not_called()


def test_cleanup_never_deletes_source_vod(tmp_path: Path) -> None:
    source = tmp_path / "vod.mp4"
    source.write_bytes(b"x")
    out = tmp_path / "out"
    out.mkdir()
    proxy, audio = proxy_paths(out, source.stem)
    preview = preview_stream_path(out, source.stem)
    proxy.write_bytes(b"proxy")
    audio.write_bytes(b"audio")
    preview.write_bytes(b"preview")
    cleanup_proxy(out, source.stem, source_video=source)
    assert source.exists()
    assert not proxy.exists()
    assert not audio.exists()
    assert not preview.exists()
