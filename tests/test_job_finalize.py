"""Job completion must reach 100% and phase done (not stuck at 99%)."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from reels.api.app import create_app
from reels.jobs import JobManager, JobState, JobStatus


def test_render_captions_finishes_at_100_percent(tmp_path):
    import reels.jobs as jobs_mod

    jobs_mod._manager = JobManager()
    mgr = jobs_mod.get_job_manager()

    vod = tmp_path / "vod.mp4"
    vod.write_bytes(b"x" * 100)
    out = tmp_path / "out"
    out.mkdir()

    from reels.captions import write_captions
    from reels.models import CaptionSegment, CaptionsDocument

    write_captions(
        out / "captions.json",
        CaptionsDocument(
            source_video=str(vod),
            segments=[CaptionSegment(index=0, start=0, end=1, text="hi")],
        ),
    )

    job_id = "finalize-test"
    mgr._jobs[job_id] = JobState(
        id=job_id,
        status=JobStatus.COMPLETED,
        video_path=str(vod),
        output_dir=str(out),
        feature="captions",
        preset="default",
    )
    mgr._running = False

    with patch("reels.jobs.probe_video") as mock_probe, patch(
        "reels.captions_render.render_captioned_video"
    ) as mock_render:
        mock_probe.return_value = type("I", (), {"width": 1920, "height": 1080})()
        mock_render.side_effect = lambda *_a, **_k: (out / "captioned.mp4").write_bytes(b"x" * 5000)

        client = TestClient(create_app())
        r = client.post(
            f"/api/jobs/{job_id}/render-captions",
            json={"font_id": "montserrat-bold"},
        )
        assert r.status_code == 200

        deadline = time.time() + 5
        while time.time() < deadline:
            state = mgr.get_job(job_id)
            if state and state.status in (JobStatus.COMPLETED, JobStatus.FAILED):
                if state.status == JobStatus.COMPLETED:
                    break
                raise AssertionError(state.error)
            time.sleep(0.05)

    state = mgr.get_job(job_id)
    assert state is not None
    assert state.percent == 100.0
    assert state.phase == "done"
    assert (out / "activity.log").is_file()
