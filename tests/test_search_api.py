"""Tests for GET /api/v2/search."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from reels.api.app import create_app
from reels.models import ClipMetadata, VideoMetadata
import reels.video_store as vs


@pytest.fixture
def client(monkeypatch, tmp_path):
    import reels.storage as storage_mod

    root = tmp_path / "proj"
    (root / "config").mkdir(parents=True)
    (root / "config" / "default.yaml").write_text("preset: default\n", encoding="utf-8")
    monkeypatch.setattr(storage_mod, "project_root", lambda: root)
    monkeypatch.setattr(vs, "videos_root", lambda: tmp_path / "video")
    vs.videos_root().mkdir(parents=True)
    return TestClient(create_app())


def _seed_vod(slug: str = "my_vod", title: str = "My VOD") -> None:
    vs.original_dir(slug).mkdir(parents=True)
    vs.source_path(slug).write_bytes(b"\x00" * 100)
    vs.save_metadata(
        VideoMetadata(slug=slug, title=title, kind="original", duration=120.0, size_bytes=100)
    )


def test_search_returns_matching_videos(client):
    _seed_vod("stream_june", "June Stream")
    vs.save_clip_metadata(
        "stream_june",
        ClipMetadata(
            clip_slug="clip_00",
            parent_slug="stream_june",
            title="Big Play",
            start=10.0,
            end=40.0,
            formats=["youtube"],
        ),
    )

    r = client.get("/api/v2/search", params={"q": "june"})
    assert r.status_code == 200
    data = r.json()
    assert data["query"] == "june"
    assert data["total"] >= 1
    assert any(v["kind"] == "original" for v in data["videos"])

    r2 = client.get("/api/v2/search", params={"q": "play"})
    assert r2.status_code == 200
    assert r2.json()["videos"][0]["kind"] == "clip"


def test_search_empty_query_returns_empty(client):
    _seed_vod()
    r = client.get("/api/v2/search", params={"q": "   "})
    assert r.status_code == 200
    assert r.json()["videos"] == []
