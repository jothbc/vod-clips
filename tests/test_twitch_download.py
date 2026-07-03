"""Tests for Twitch VOD URL parsing and download helpers."""

from __future__ import annotations

import pytest
from pathlib import Path

from reels.twitch.download import (
    TwitchDownloadError,
    normalize_twitch_vod_url,
    parse_twitch_vod_url,
    require_yt_dlp,
)


def test_parse_twitch_vod_url():
    assert parse_twitch_vod_url("https://www.twitch.tv/videos/2783991554") == "2783991554"
    assert parse_twitch_vod_url("https://twitch.tv/videos/1234567890/") == "1234567890"


def test_normalize_twitch_vod_url():
    assert (
        normalize_twitch_vod_url("https://www.twitch.tv/videos/2783991554")
        == "https://www.twitch.tv/videos/2783991554"
    )


def test_parse_rejects_non_vod():
    with pytest.raises(ValueError):
        parse_twitch_vod_url("https://www.twitch.tv/somechannel")
    with pytest.raises(ValueError):
        parse_twitch_vod_url("")


def test_require_yt_dlp_raises_when_missing(monkeypatch, tmp_path):
    monkeypatch.setattr("reels.twitch.download.shutil.which", lambda _: None)
    monkeypatch.setattr("reels.twitch.download.sys.executable", str(tmp_path / "python.exe"))
    with pytest.raises(TwitchDownloadError, match="yt-dlp not found"):
        require_yt_dlp()


def test_summarize_yt_dlp_output_prefers_error_line():
    from reels.twitch.download import _summarize_yt_dlp_output

    lines = [
        "[twitch:vod] Downloading m3u8",
        "ERROR: [twitch:vod] Failed: SSL certificate verify failed",
    ]
    assert "SSL certificate verify failed" in _summarize_yt_dlp_output(lines, 1)


def test_build_yt_dlp_args_concurrent_fragments():
    from reels.twitch.download import build_yt_dlp_args

    args = build_yt_dlp_args("yt-dlp", "https://www.twitch.tv/videos/1", Path("out.mp4"), concurrent_fragments=64)
    idx = args.index("--concurrent-fragments")
    assert args[idx + 1] == "64"


def test_parse_yt_dlp_progress_percent():
    from reels.twitch.download import parse_yt_dlp_progress_percent

    assert parse_yt_dlp_progress_percent("[download]  45.2% of ~ 1.89GiB at  12.34MiB/s") == 45.2
    assert parse_yt_dlp_progress_percent("not progress") is None


def test_download_twitch_vod_includes_yt_dlp_output_on_failure(monkeypatch, tmp_path):
    from reels.twitch.download import download_twitch_vod

    class FakeProc:
        def __init__(self):
            self._lines = iter(["ERROR: something broke"])

        @property
        def stdout(self):
            return self._lines

        def wait(self):
            return 1

        def kill(self):
            pass

        def terminate(self):
            pass

    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: FakeProc())
    out = tmp_path / "out.mp4"
    with pytest.raises(TwitchDownloadError, match="something broke"):
        download_twitch_vod(
            "https://www.twitch.tv/videos/1234567890",
            out,
            yt_dlp="yt-dlp",
        )
