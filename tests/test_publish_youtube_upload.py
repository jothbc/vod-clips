"""Resumable YouTube upload: chunk sizing, retry, resume, token refresh."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx

from reels import publish_youtube as yt


def test_upload_chunk_size_default_is_64mb(monkeypatch):
    monkeypatch.delenv("YOUTUBE_UPLOAD_CHUNK_MB", raising=False)
    assert yt.upload_chunk_size() == 64 * 1024 * 1024


def test_upload_chunk_size_env_override(monkeypatch):
    monkeypatch.setenv("YOUTUBE_UPLOAD_CHUNK_MB", "16")
    assert yt.upload_chunk_size() == 16 * 1024 * 1024


def test_upload_chunk_size_clamped_and_aligned(monkeypatch):
    monkeypatch.setenv("YOUTUBE_UPLOAD_CHUNK_MB", "99")
    assert yt.upload_chunk_size() == 64 * 1024 * 1024
    monkeypatch.setenv("YOUTUBE_UPLOAD_CHUNK_MB", "0")
    assert yt.upload_chunk_size() == 1 * 1024 * 1024


def test_parse_range_header():
    assert yt._parse_range_header("bytes=0-1048575") == 1048576
    assert yt._parse_range_header(None) == 0
    assert yt._parse_range_header("0-99") == 100


def _mock_response(status: int, *, headers: dict | None = None, json_body: dict | None = None):
    r = MagicMock(spec=httpx.Response)
    r.status_code = status
    r.headers = headers or {}
    r.content = b"{}" if json_body is not None else b""
    r.json.return_value = json_body or {}
    r.text = ""
    r.reason_phrase = "OK"
    return r


def test_upload_resumable_happy_path_two_chunks(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("YOUTUBE_UPLOAD_CHUNK_MB", "1")
    video = tmp_path / "clip.mp4"
    # 1.5 MiB → two chunks with 1 MiB size
    payload = b"a" * (1024 * 1024 + 512 * 1024)
    video.write_bytes(payload)

    puts: list[tuple[int, int]] = []

    def fake_put(url, headers=None, content=None):
        cr = (headers or {}).get("Content-Range", "")
        # skip status queries
        if content == b"" or (headers or {}).get("Content-Length") == "0":
            return _mock_response(308, headers={"Range": f"bytes=0-{puts[-1][1]}"}) if puts else _mock_response(
                308, headers={"Range": "bytes=0--1"}
            )
        # parse bytes start-end/total
        part = cr.split(" ")[1].split("/")[0]
        start_s, end_s = part.split("-")
        start, end = int(start_s), int(end_s)
        puts.append((start, end))
        assert content == payload[start : end + 1]
        if end + 1 >= len(payload):
            return _mock_response(200, json_body={"id": "ytabc"})
        return _mock_response(308)

    client = MagicMock()
    client.put.side_effect = fake_put
    client.__enter__ = lambda s: s
    client.__exit__ = MagicMock(return_value=False)

    progress: list[float] = []
    with patch.object(yt, "http_client", return_value=client):
        body = yt._upload_resumable("tok", "https://upload.example/u", video, on_progress=progress.append)

    assert body["id"] == "ytabc"
    assert puts[0] == (0, 1024 * 1024 - 1)
    assert puts[1][0] == 1024 * 1024
    assert puts[1][1] == len(payload) - 1
    assert progress[-1] == 1.0


def test_upload_resumable_retries_503_then_succeeds(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("YOUTUBE_UPLOAD_CHUNK_MB", "1")
    video = tmp_path / "clip.mp4"
    payload = b"b" * (512 * 1024)  # single chunk (smaller than 1 MiB)
    video.write_bytes(payload)

    calls = {"n": 0}

    def fake_put(url, headers=None, content=None):
        cr = (headers or {}).get("Content-Range", "")
        if content == b"" or cr.startswith("bytes */"):
            return _mock_response(308)  # nothing received yet
        calls["n"] += 1
        if calls["n"] == 1:
            return _mock_response(503)
        return _mock_response(200, json_body={"id": "yt1"})

    client = MagicMock()
    client.put.side_effect = fake_put
    client.__enter__ = lambda s: s
    client.__exit__ = MagicMock(return_value=False)

    with (
        patch.object(yt, "http_client", return_value=client),
        patch.object(yt.time, "sleep"),
    ):
        body = yt._upload_resumable("tok", "https://upload.example/u", video)

    assert body["id"] == "yt1"
    assert calls["n"] == 2


def test_upload_resumable_resumes_after_partial_accept(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("YOUTUBE_UPLOAD_CHUNK_MB", "1")
    video = tmp_path / "clip.mp4"
    payload = b"e" * (2 * 1024 * 1024)
    video.write_bytes(payload)

    chunk_puts = 0

    def fake_put(url, headers=None, content=None):
        nonlocal chunk_puts
        cr = (headers or {}).get("Content-Range", "")
        if content == b"" or cr.startswith("bytes */"):
            return _mock_response(308, headers={"Range": f"bytes=0-{1024 * 1024 - 1}"})
        chunk_puts += 1
        part = cr.split(" ")[1].split("/")[0]
        start = int(part.split("-")[0])
        end = int(part.split("-")[1])
        if start == 0 and chunk_puts == 1:
            return _mock_response(503)
        if end + 1 >= len(payload):
            return _mock_response(200, json_body={"id": "yt-resume"})
        return _mock_response(308)

    client = MagicMock()
    client.put.side_effect = fake_put
    client.__enter__ = lambda s: s
    client.__exit__ = MagicMock(return_value=False)

    with (
        patch.object(yt, "http_client", return_value=client),
        patch.object(yt.time, "sleep"),
    ):
        body = yt._upload_resumable("tok", "https://upload.example/u", video)

    assert body["id"] == "yt-resume"
    assert chunk_puts >= 2


def test_upload_resumable_refreshes_token_on_401(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("YOUTUBE_UPLOAD_CHUNK_MB", "1")
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"c" * 1000)

    tokens_seen: list[str] = []
    calls = {"n": 0}

    def fake_put(url, headers=None, content=None):
        calls["n"] += 1
        auth = (headers or {}).get("Authorization", "")
        tokens_seen.append(auth)
        if calls["n"] == 1:
            return _mock_response(401)
        return _mock_response(200, json_body={"id": "yt2"})

    client = MagicMock()
    client.put.side_effect = fake_put
    client.__enter__ = lambda s: s
    client.__exit__ = MagicMock(return_value=False)

    refresh = MagicMock(return_value="new-token")
    with patch.object(yt, "http_client", return_value=client):
        body = yt._upload_resumable(
            "old-token",
            "https://upload.example/u",
            video,
            refresh_access_token_fn=refresh,
        )

    assert body["id"] == "yt2"
    refresh.assert_called_once()
    assert tokens_seen[0] == "Bearer old-token"
    assert tokens_seen[1] == "Bearer new-token"


def test_upload_resumable_network_error_then_succeeds(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("YOUTUBE_UPLOAD_CHUNK_MB", "1")
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"d" * 500)

    calls = {"n": 0}

    def fake_put(url, headers=None, content=None):
        cr = (headers or {}).get("Content-Range", "")
        if content == b"" or (cr.startswith("bytes */")):
            return _mock_response(308, headers={"Range": "bytes=0--1"})
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("boom")
        return _mock_response(200, json_body={"id": "yt3"})

    client = MagicMock()
    client.put.side_effect = fake_put
    client.__enter__ = lambda s: s
    client.__exit__ = MagicMock(return_value=False)

    with (
        patch.object(yt, "http_client", return_value=client),
        patch.object(yt.time, "sleep"),
    ):
        body = yt._upload_resumable("tok", "https://upload.example/u", video)

    assert body["id"] == "yt3"
