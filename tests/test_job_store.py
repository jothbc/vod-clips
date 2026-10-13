"""Tests for DB-backed job persistence: insert, update, dedupe, events, orphans."""

from __future__ import annotations

from reels import job_store


def _insert(job_id: str, *, video_id="v1", feature="v2_analyze", params=None, status="queued"):
    params = params or {"max_clips": 10}
    phash = job_store.compute_params_hash(video_id, feature, params)
    job_store.insert_job(
        job_id=job_id,
        video_id=video_id,
        feature=feature,
        params=params,
        params_hash=phash,
        status=status,
        output_dir="/tmp/out",
        created_at="2026-01-01T00:00:00+00:00",
    )
    return phash


def test_insert_and_get():
    _insert("job1")
    row = job_store.get_job("job1")
    assert row is not None
    assert row["status"] == "queued"
    assert row["feature"] == "v2_analyze"
    assert row["video_id"] == "v1"


def test_update_sets_started_and_finished():
    _insert("job2")
    job_store.update_job(
        job_id="job2", status="running", percent=10.0, phase="probe", message="probing",
        error=None, result_video_id=None,
    )
    row = job_store.get_job("job2")
    assert row["status"] == "running"
    assert row["started_at"] is not None
    assert row["finished_at"] is None

    job_store.update_job(
        job_id="job2", status="completed", percent=100.0, phase="done", message="done",
        error=None, result_video_id="clip-xyz",
    )
    row = job_store.get_job("job2")
    assert row["status"] == "completed"
    assert row["finished_at"] is not None
    assert row["result_video_id"] == "clip-xyz"


def test_dedupe_finds_active_equivalent():
    phash = _insert("job3", status="running")
    dup = job_store.find_active_duplicate("v1", "v2_analyze", phash)
    assert dup == "job3"
    # Different params -> different hash -> no dedupe.
    other = job_store.compute_params_hash("v1", "v2_analyze", {"max_clips": 99})
    assert job_store.find_active_duplicate("v1", "v2_analyze", other) is None


def test_dedupe_ignores_terminal_jobs():
    phash = _insert("job4", status="completed")
    assert job_store.find_active_duplicate("v1", "v2_analyze", phash) is None


def test_events_recorded_and_listed():
    _insert("job5")
    job_store.add_event("job5", "probe", 5.0, "probing")
    job_store.add_event("job5", "transcribe", 30.0, "transcribing")
    events = job_store.list_events("job5")
    assert [e["phase"] for e in events] == ["probe", "transcribe"]


def test_list_jobs_filters_by_status_and_video():
    _insert("a", video_id="vodA", status="running")
    _insert("b", video_id="vodB", status="completed", params={"max_clips": 3})
    running = job_store.list_jobs(status="running")
    assert [j["id"] for j in running] == ["a"]
    by_video = job_store.list_jobs(video_id="vodB")
    assert [j["id"] for j in by_video] == ["b"]


def test_reconcile_orphans_marks_active_failed():
    _insert("stuck", status="running")
    _insert("waiting", status="queued")
    _insert("done", status="completed", params={"max_clips": 1})
    count = job_store.reconcile_orphans()
    assert count == 2
    assert job_store.get_job("stuck")["status"] == "failed"
    assert job_store.get_job("waiting")["status"] == "failed"
    assert job_store.get_job("done")["status"] == "completed"
