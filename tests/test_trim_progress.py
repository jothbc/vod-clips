"""Progress percent weights for feature jobs."""

from reels.progress import TRIM_PHASE_WEIGHTS, _compute_percent


def test_trim_render_phase_not_stuck_at_probe_weight():
    phase_done = {"probe": True}
    pct = _compute_percent(
        "render",
        0,
        1,
        phase_done,
        0,
        0,
        0,
        0,
        TRIM_PHASE_WEIGHTS,
    )
    assert pct == TRIM_PHASE_WEIGHTS["probe"]
