"""In-memory publish deploy progress tracking."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

DeployState = Literal["running", "completed", "failed"]

_lock = threading.Lock()
_deployments: dict[str, "DeployRecord"] = {}


@dataclass
class DeployRecord:
    id: str
    status: DeployState = "running"
    phase: str = "prepare"
    percent: float = 0.0
    message: str = "Preparando envio…"
    result: dict[str, Any] = field(default_factory=dict)
    error: str = ""


def create_deploy() -> DeployRecord:
    rec = DeployRecord(id=uuid.uuid4().hex[:12])
    with _lock:
        _deployments[rec.id] = rec
    return rec


def get_deploy(deploy_id: str) -> DeployRecord | None:
    with _lock:
        return _deployments.get(deploy_id)


def update_deploy(
    deploy_id: str,
    *,
    status: DeployState | None = None,
    phase: str | None = None,
    percent: float | None = None,
    message: str | None = None,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    with _lock:
        rec = _deployments.get(deploy_id)
        if not rec:
            return
        if status is not None:
            rec.status = status
        if phase is not None:
            rec.phase = phase
        if percent is not None:
            rec.percent = max(0.0, min(100.0, percent))
        if message is not None:
            rec.message = message
        if result is not None:
            rec.result = result
        if error is not None:
            rec.error = error


def deploy_to_dict(rec: DeployRecord) -> dict[str, Any]:
    out: dict[str, Any] = {
        "deploy_id": rec.id,
        "status": rec.status,
        "phase": rec.phase,
        "percent": rec.percent,
        "message": rec.message,
    }
    if rec.status == "completed":
        out.update(rec.result)
    if rec.status == "failed":
        out["error"] = rec.error
    return out
