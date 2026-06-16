"""Reels library API tests."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reels.api.app import create_app
from reels.api.media_serve import is_readable_clip


@pytest.fixture
def library_env(monkeypatch, tmp_path):
    import reels.jobs as jobs_mod
    import reels.storage as storage_mod
    import reels.twitch.manager as twitch_mod

    root = tmp_path / "proj"
    outputs = root / "temp" / "outputs"
    outputs.mkdir(parents=True)
    (root / "config").mkdir(parents=True)
    (root / "config" / "default.yaml").write_text("preset: default\n", encoding="utf-8")

    monkeypatch.setattr(storage_mod, "project_root", lambda: root)
    monkeypatch.setattr(storage_mod, "temp_root", lambda: root / "temp")
    monkeypatch.setattr(storage_mod, "temp_outputs_dir", lambda: outputs.resolve())

    jobs_mod._manager = jobs_mod.JobManager()
    twitch_mod.reset_twitch_download_manager(max_concurrent=2, skip_existing=True)

    client = TestClient(create_app())
    yield client, outputs
    jobs_mod.get_job_manager()._running = False


def _write_highlights(out_dir: Path, source_video: str = "/tmp/stream.mp4") -> None:
    doc = {
        "source_video": source_video,
        "highlights": [
            {
                "start": 0,
                "end": 5,
                "score": 0.9,
                "title": "Test Clip",
                "reason": "test",
                "source": "heuristic",
            }
        ],
        "warnings": [],
    }
    (out_dir / "highlights.json").write_text(json.dumps(doc), encoding="utf-8")


def _write_exported_clip(out_dir: Path, name: str = "00_Test_Clip.mp4", size: int = 5000) -> Path:
    yt = out_dir / "youtube"
    yt.mkdir(parents=True, exist_ok=True)
    clip = yt / name
    clip.write_bytes(b"x" * size)
    return clip


def test_library_lists_job_with_exported_clips(library_env):
    client, outputs = library_env
    job_dir = outputs / "job-exported"
    job_dir.mkdir()
    _write_highlights(job_dir, "/vods/my_stream.mp4")
    _write_exported_clip(job_dir)

    r = client.get("/api/reels/library")
    assert r.status_code == 200
    data = r.json()
    assert len(data["jobs"]) == 1
    job = data["jobs"][0]
    assert job["job_id"] == "job-exported"
    assert job["source_video"] == "my_stream.mp4"
    assert job["clip_count"] == 1
    assert job["clips"][0]["youtube_url"] == "/media/job-exported/youtube/00_Test_Clip.mp4"


def test_library_orders_jobs_by_modified_desc(library_env):
    client, outputs = library_env

    older = outputs / "job-older"
    older.mkdir()
    _write_highlights(older, "/vods/older.mp4")
    clip_old = _write_exported_clip(older, "00_Test_Clip.mp4")
    old_mtime = time.time() - 3600
    Path(clip_old).touch()
    import os

    os.utime(clip_old, (old_mtime, old_mtime))

    newer = outputs / "job-newer"
    newer.mkdir()
    _write_highlights(newer, "/vods/newer.mp4")
    _write_exported_clip(newer, "00_Test_Clip.mp4")

    r = client.get("/api/reels/library")
    ids = [j["job_id"] for j in r.json()["jobs"]]
    assert ids == ["job-newer", "job-older"]


def test_library_skips_analysis_only_job(library_env):
    client, outputs = library_env
    job_dir = outputs / "job-analysis-only"
    job_dir.mkdir()
    _write_highlights(job_dir)

    r = client.get("/api/reels/library")
    assert r.json()["jobs"] == []


def test_media_serves_clip_without_active_job(library_env):
    client, outputs = library_env
    job_dir = outputs / "offline-job"
    job_dir.mkdir()
    _write_highlights(job_dir)
    _write_exported_clip(job_dir)

    r = client.get("/media/offline-job/youtube/00_Test_Clip.mp4")
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("video/mp4")


def test_delete_reel_job_removes_folder(library_env):
    client, outputs = library_env
    job_dir = outputs / "job-delete-me"
    job_dir.mkdir()
    _write_highlights(job_dir)
    _write_exported_clip(job_dir)

    r = client.delete("/api/reels/library/job-delete-me")
    assert r.status_code == 200
    assert r.json()["deleted"] is True
    assert not job_dir.exists()

    listed = client.get("/api/reels/library")
    assert all(j["job_id"] != "job-delete-me" for j in listed.json()["jobs"])


def test_delete_reel_job_output_rejects_invalid_id(library_env):
    from reels.storage import delete_reel_job_output

    with pytest.raises(ValueError, match="Invalid job id"):
        delete_reel_job_output("../outside")


def test_delete_reel_job_missing_404(library_env):
    client, _outputs = library_env
    r = client.delete("/api/reels/library/does-not-exist")
    assert r.status_code == 404


def test_pickable_clips_lists_exported_files(library_env):
    client, outputs = library_env
    job_dir = outputs / "job-pickable"
    job_dir.mkdir()
    _write_highlights(job_dir, "/vods/stream.mp4")
    _write_exported_clip(job_dir, "00_Test_Clip.mp4")

    r = client.get("/api/reels/pickable-clips")
    assert r.status_code == 200
    clips = r.json()["clips"]
    assert len(clips) == 1
    assert clips[0]["title"] == "Test Clip"
    assert clips[0]["format"] == "youtube"
    assert Path(clips[0]["path"]).is_file()


def test_pickable_clips_skips_analysis_only(library_env):
    client, outputs = library_env
    job_dir = outputs / "job-no-clips"
    job_dir.mkdir()
    _write_highlights(job_dir)

    r = client.get("/api/reels/pickable-clips")
    assert r.json()["clips"] == []


def test_readable_clip_threshold():
    path = Path("/tmp/nonexistent.mp4")
    assert is_readable_clip(path) is False
