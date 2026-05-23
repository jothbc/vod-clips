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

    root = tmp_path / "proj"
    (root / "config").mkdir(parents=True)
    (root / "config" / "default.yaml").write_text("preset: default\n", encoding="utf-8")

    monkeypatch.setattr(storage_mod, "project_root", lambda: root)
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
    assert str(temp_vods_dir()) in data["path"] or "vods" in data["path"]


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
