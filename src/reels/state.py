"""Checkpoint state persistence for long VODs."""

from __future__ import annotations

import json
from pathlib import Path

from reels.models import PipelineState


def state_path(output_dir: Path) -> Path:
    return output_dir / "state.json"


def load_state(output_dir: Path, source_video: str) -> PipelineState:
    path = state_path(output_dir)
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        return PipelineState.model_validate(data)
    return PipelineState(source_video=source_video)


def save_state(output_dir: Path, state: PipelineState) -> None:
    path = state_path(output_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(state.model_dump_json(indent=2), encoding="utf-8")
