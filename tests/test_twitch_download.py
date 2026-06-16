"""Tests for Twitch VOD URL parsing and download helpers."""

from __future__ import annotations

import pytest

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


def test_require_yt_dlp_raises_when_missing(monkeypatch):
    monkeypatch.setattr("reels.twitch.download.shutil.which", lambda _: None)
    with pytest.raises(TwitchDownloadError, match="yt-dlp not found"):
        require_yt_dlp()
