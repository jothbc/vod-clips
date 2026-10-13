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


def test_build_yt_dlp_args_ffmpeg_downloader_skips_concurrent():
    from reels.twitch.download import build_yt_dlp_args

    args = build_yt_dlp_args(
        "yt-dlp",
        "https://www.twitch.tv/videos/1",
        Path("out.mp4"),
        downloader="ffmpeg",
    )
    assert "--downloader" in args
    assert args[args.index("--downloader") + 1] == "ffmpeg"
    assert "--concurrent-fragments" not in args


def test_parse_yt_dlp_progress_percent():
    from reels.twitch.download import parse_yt_dlp_progress_percent

    assert parse_yt_dlp_progress_percent("[download]  45.2% of ~ 1.89GiB at  12.34MiB/s") == 45.2
    assert parse_yt_dlp_progress_percent("not progress") is None


def test_sanitize_ssl_env_strips_avast_keylog(monkeypatch):
    from reels.twitch.download import clear_av_ssl_env, sanitize_ssl_env

    monkeypatch.setenv("SSLKEYLOGFILE", r"\\.\aswMonFltProxy\deadbeef")
    monkeypatch.setenv("KEEP_ME", "1")
    cleaned = sanitize_ssl_env()
    assert "SSLKEYLOGFILE" not in cleaned
    assert cleaned.get("KEEP_ME") == "1"

    removed = clear_av_ssl_env()
    assert "SSLKEYLOGFILE" in removed
    assert "SSLKEYLOGFILE" not in __import__("os").environ


def test_download_twitch_vod_includes_yt_dlp_output_on_failure(monkeypatch, tmp_path):
    from reels.twitch.download import download_twitch_vod

    captured: dict = {}

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

    def fake_popen(*a, **k):
        captured.update(k)
        return FakeProc()

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    out = tmp_path / "out.mp4"
    with pytest.raises(TwitchDownloadError, match="something broke"):
        download_twitch_vod(
            "https://www.twitch.tv/videos/1234567890",
            out,
            yt_dlp="yt-dlp",
        )
    assert "env" in captured


def test_download_retries_with_ffmpeg_on_init_after_media(monkeypatch, tmp_path):
    from reels.twitch.download import download_twitch_vod

    calls: list[list[str]] = []
    out = tmp_path / "out.mp4"

    class FakeProc:
        def __init__(self, lines: list[str], code: int):
            self._lines = iter(lines)
            self._code = code

        @property
        def stdout(self):
            return self._lines

        def wait(self):
            return self._code

        def kill(self):
            pass

        def terminate(self):
            pass

    def fake_popen(args, **k):
        calls.append(list(args))
        if len(calls) == 1:
            return FakeProc(
                ["ERROR: Initialization fragment found after media fragments, unable to download"],
                1,
            )
        out.write_bytes(b"ok")
        return FakeProc(["[download] 100%"], 0)

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    progress: list[str] = []
    result = download_twitch_vod(
        "https://www.twitch.tv/videos/1234567890",
        out,
        yt_dlp="yt-dlp",
        on_progress=progress.append,
    )
    assert result == out.resolve()
    assert len(calls) == 2
    assert "--concurrent-fragments" in calls[0]
    assert "--downloader" not in calls[0]
    assert calls[1][calls[1].index("--downloader") + 1] == "ffmpeg"
    assert "--concurrent-fragments" not in calls[1]
    assert any("retrying with --downloader ffmpeg" in line for line in progress)


def test_is_fragmented_mp4_detects_hls_brands(tmp_path):
    from reels.twitch.download import _is_fragmented_mp4

    frag = tmp_path / "frag.mp4"
    # Minimal fake header with dash/hlsf brands and a moof marker
    header = bytearray(64)
    header[4:8] = b"ftyp"
    header[8:12] = b"mp42"
    header[16:48] = b"isommp42dashavc1iso6hlsf" + b"\x00" * 8
    frag.write_bytes(bytes(header) + b"....moof....")
    assert _is_fragmented_mp4(frag) is True

    prog = tmp_path / "prog.mp4"
    header2 = bytearray(64)
    header2[4:8] = b"ftyp"
    header2[8:12] = b"isom"
    header2[16:32] = b"isomiso2avc1mp41"
    prog.write_bytes(bytes(header2) + b"....moov....")
    assert _is_fragmented_mp4(prog) is False
