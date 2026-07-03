"""Progress reporting for CLI (Rich) and web UI (callbacks)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol

# Relative weights for global percent (sum = 100)
PHASE_WEIGHTS: dict[str, int] = {
    "probe": 2,
    "proxy": 8,
    "transcribe": 25,
    "scenes": 5,
    "heuristic": 10,
    "vlm": 35,
    "export": 15,
}

REELS_PHASE_WEIGHTS: dict[str, int] = {
    "probe": 2,
    "proxy": 8,
    "transcribe": 25,
    "scenes": 5,
    "heuristic": 10,
    "vlm": 35,
    "export": 15,
}

CLEANUP_PHASE_WEIGHTS: dict[str, int] = {
    "probe": 3,
    "transcribe": 35,
    "edl": 22,
    "verify": 15,
    "render": 25,
}

CAPTIONS_PHASE_WEIGHTS: dict[str, int] = {
    "probe": 5,
    "transcribe": 40,
    "segments": 20,
    "render": 35,
}

PUBLISH_PHASE_WEIGHTS: dict[str, int] = {
    "probe": 5,
    "transcribe": 25,
    "metadata": 30,
    "thumbnail": 25,
    "manifest": 15,
}

TRIM_PHASE_WEIGHTS: dict[str, int] = {
    "probe": 5,
    "render": 95,
}

FEATURE_PHASE_WEIGHTS: dict[str, dict[str, int]] = {
    "v2_cleanup": CLEANUP_PHASE_WEIGHTS,
    "v2_captions": CAPTIONS_PHASE_WEIGHTS,
    "v2_trim": TRIM_PHASE_WEIGHTS,
    "publish": PUBLISH_PHASE_WEIGHTS,
}


@dataclass
class ProgressEvent:
    phase: str
    current: int = 0
    total: int | None = None
    message: str = ""
    percent: float = 0.0


class ProgressReporter(Protocol):
    def report(
        self,
        phase: str,
        current: int = 0,
        total: int | None = None,
        message: str = "",
    ) -> None: ...


@dataclass
class CallbackProgressReporter:
    """Invokes a callback with ProgressEvent (used by JobManager / SSE)."""

    on_event: Callable[[ProgressEvent], None]
    phase_weights: dict[str, int] = field(default_factory=lambda: dict(PHASE_WEIGHTS))
    _phase_done: dict[str, bool] = field(default_factory=dict)
    _vlm_current: int = 0
    _vlm_total: int = 0
    _export_current: int = 0
    _export_total: int = 0

    def report(
        self,
        phase: str,
        current: int = 0,
        total: int | None = None,
        message: str = "",
    ) -> None:
        if phase == "vlm" and total:
            self._vlm_current = current
            self._vlm_total = total
        elif phase == "export" and total:
            self._export_current = current
            self._export_total = total
        elif total is None and current >= (total or 1):
            self._phase_done[phase] = True

        if total is None and message and phase not in ("vlm", "export"):
            if "done" in message.lower() or current >= 1:
                self._phase_done[phase] = True

        percent = _compute_percent(
            phase,
            current,
            total,
            self._phase_done,
            self._vlm_current,
            self._vlm_total,
            self._export_current,
            self._export_total,
            self.phase_weights,
        )
        event = ProgressEvent(
            phase=phase,
            current=current,
            total=total,
            message=message,
            percent=percent,
        )
        self.on_event(event)

    def mark_phase_complete(self, phase: str) -> None:
        self._phase_done[phase] = True
        self.report(phase, current=1, total=1, message=f"{phase} complete")


def _compute_percent(
    phase: str,
    current: int,
    total: int | None,
    phase_done: dict[str, bool],
    vlm_current: int,
    vlm_total: int,
    export_current: int,
    export_total: int,
    phase_weights: dict[str, int] | None = None,
) -> float:
    weights = phase_weights or PHASE_WEIGHTS
    done_weight = sum(
        w for p, w in weights.items() if phase_done.get(p) and p != phase
    )
    if phase in phase_done and phase_done[phase]:
        done_weight += weights.get(phase, 0)

    weight = weights.get(phase, 0)
    if phase == "vlm" and vlm_total > 0:
        frac = vlm_current / vlm_total
        return min(99.0, done_weight + weight * frac)
    if phase == "export" and export_total > 0:
        frac = export_current / export_total
        return min(99.0, done_weight + weight * frac)
    if total and total > 0:
        frac = min(1.0, current / total)
        return min(99.0, done_weight + weight * frac)
    if phase_done.get(phase):
        return min(99.0, done_weight + weight)
    return float(done_weight)


class RichProgressReporter:
    """Wraps rich Progress tasks; used when reporter is None in CLI."""

    def __init__(self, progress, tasks: dict[str, int]) -> None:
        self._progress = progress
        self._tasks = tasks

    def report(
        self,
        phase: str,
        current: int = 0,
        total: int | None = None,
        message: str = "",
    ) -> None:
        tid = self._tasks.get(phase)
        if tid is None:
            return
        desc = message or phase
        if total and total > 0:
            desc = f"{desc} ({current}/{total})"
        self._progress.update(tid, description=desc)
        if total and current >= total:
            self._progress.update(tid, completed=True)

    @staticmethod
    def noop_report(
        phase: str,
        current: int = 0,
        total: int | None = None,
        message: str = "",
    ) -> None:
        pass
