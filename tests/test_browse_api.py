"""Upload and storage cleanup API tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reels.api.app import create_app
from reels.storage import temp_outputs_dir, temp_vods_dir


@pytest.fixture
def client(monkeypatch, tmp_path):
    import reels.storage as storage_mod
    import reels.video_store as vs_mod
    from reels.models import VideoInfo

    root = tmp_path / "proj"
    (root / "config").mkdir(parents=True)
    (root / "config" / "default.yaml").write_text("preset: default\n", encoding="utf-8")

    monkeypatch.setattr(storage_mod, "project_root", lambda: root)
    monkeypatch.setattr(
        vs_mod,
        "probe_video",
        lambda path: VideoInfo(
            path=str(path),
            duration=60.0,
            width=1280,
            height=720,
            fps=30.0,
            size_bytes=path.stat().st_size if path.is_file() else 0,
        ),
    )
    return TestClient(create_app())


def test_upload_mp4_stream(client, tmp_path):
    r = client.post(
        "/api/upload",
        files={"file": ("vod.mp4", b"\x00" * 5000, "video/mp4")},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["size_bytes"] == 5000
    assert Path(data["path"]).exists()
    assert "video" in data["path"]
    assert data.get("video_id")


def test_list_stored_vods_empty(client):
    r = client.get("/api/vods")
    assert r.status_code == 200
    data = r.json()
    assert data["vods"] == []
    assert "vods" in data["dir"]


def test_list_and_delete_stored_vod(client, tmp_path):
    # Legacy /api/vods lists temp/vods only — seed a file there directly.
    vod = temp_vods_dir() / "legacy_test.mp4"
    vod.write_bytes(b"\x00" * 2048)
    stored_path = str(vod.resolve())

    listed = client.get("/api/vods")
    assert listed.status_code == 200
    items = listed.json()["vods"]
    assert any(v["path"] == stored_path for v in items)
    item = next(v for v in items if v["path"] == stored_path)
    assert item["size_bytes"] == 2048
    assert item["filename"].endswith("legacy_test.mp4")

    # Delete by path.
    deleted = client.delete(f"/api/vods?path={stored_path}")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True

    # Gone from the listing.
    listed2 = client.get("/api/vods")
    assert all(v["path"] != stored_path for v in listed2.json()["vods"])


def test_delete_stored_vod_rejects_path_outside(client, tmp_path):
    outside = tmp_path / "evil.mp4"
    outside.write_bytes(b"x")
    r = client.delete(f"/api/vods?path={outside}")
    assert r.status_code == 400


def test_delete_stored_vod_missing_404(client):
    r = client.delete("/api/vods?path=/nonexistent/temp/vods/missing.mp4")
    # Either rejected for being outside temp/vods (400) or not found (404).
    assert r.status_code in (400, 404)


def test_clear_job_storage(client, monkeypatch, tmp_path):
    import reels.jobs as jobs_mod
    from reels.jobs import JobManager, JobState, JobStatus

    root = tmp_path / "proj"
    vods = root / "temp" / "vods"
    outputs = root / "temp" / "outputs"
    vods.mkdir(parents=True)
    outputs.mkdir(parents=True)

    vod = vods / "abc_vod.mp4"
    vod.write_bytes(b"x" * 100)
    out = outputs / "job-1"
    (out / "youtube").mkdir(parents=True)
    (out / "youtube" / "01_clip.mp4").write_bytes(b"y" * 50)

    import reels.storage as storage_mod

    monkeypatch.setattr(storage_mod, "project_root", lambda: root)
    monkeypatch.setattr(storage_mod, "temp_root", lambda: root / "temp")
    monkeypatch.setattr(storage_mod, "temp_vods_dir", lambda: vods.resolve())
    monkeypatch.setattr(storage_mod, "temp_outputs_dir", lambda: outputs.resolve())

    jobs_mod._manager = JobManager()
    mgr = jobs_mod.get_job_manager()
    mgr._jobs["job-1"] = JobState(
        id="job-1",
        status=JobStatus.COMPLETED,
        video_path=str(vod.resolve()),
        output_dir=str(out.resolve()),
        uploaded_vod=True,
    )
    mgr._running = False

    api_client = TestClient(create_app())
    r = api_client.post("/api/jobs/job-1/clear")
    assert r.status_code == 200
    data = r.json()
    assert data["vod_deleted"] is True
    assert data["output_deleted"] is True
    assert not vod.exists()
    assert not out.exists()
