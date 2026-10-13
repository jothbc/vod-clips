"""DB persistence for background jobs: survive restarts, list, and dedupe.

The JobManager keeps live job objects in memory for execution, but mirrors
their state into the ``jobs`` and ``job_events`` tables. This lets the UI list
active and recent jobs, reattach after a reload, and skip launching a duplicate
of an equivalent job that is already queued or running.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from reels.db import init_db
from reels.db.connection import connection

ACTIVE_STATUSES = ("queued", "running", "awaiting_review")
TERMINAL_STATUSES = ("completed", "failed", "cancelled")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def compute_params_hash(video_id: str, feature: str, params: dict[str, Any]) -> str:
    payload = {"video_id": video_id or "", "feature": feature, "params": params or {}}
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def insert_job(
    *,
    job_id: str,
    video_id: str,
    feature: str,
    params: dict[str, Any],
    params_hash: str,
    status: str,
    output_dir: str,
    created_at: str,
) -> None:
    init_db()
    with connection() as con:
        con.execute(
            """
            INSERT OR REPLACE INTO jobs (
                id, video_id, feature, params_json, params_hash, status,
                progress_percent, phase, message, result_video_id, output_dir, error,
                created_at, started_at, finished_at
            ) VALUES (?, ?, ?, ?, ?, ?, 0, 'queued', '', NULL, ?, '', ?, NULL, NULL)
            """,
            (
                job_id,
                video_id or None,
                feature,
                json.dumps(params, default=str),
                params_hash,
                status,
                output_dir,
                created_at,
            ),
        )


def update_job(
    *,
    job_id: str,
    status: str,
    percent: float,
    phase: str,
    message: str,
    error: str | None,
    result_video_id: str | None,
) -> None:
    init_db()
    now = _utc_now()
    started = now if status == "running" else None
    finished = now if status in TERMINAL_STATUSES else None
    with connection() as con:
        con.execute(
            """
            UPDATE jobs SET
                status = ?, progress_percent = ?, phase = ?, message = ?, error = ?,
                result_video_id = ?,
                started_at = COALESCE(started_at, ?),
                finished_at = CASE WHEN ? IN ('completed','failed','cancelled') THEN ? ELSE finished_at END
            WHERE id = ?
            """,
            (
                status,
                percent,
                phase,
                message,
                error or "",
                result_video_id,
                started,
                status,
                finished,
                job_id,
            ),
        )


def add_event(job_id: str, phase: str, percent: float, message: str) -> None:
    init_db()
    with connection() as con:
        con.execute(
            "INSERT INTO job_events (job_id, phase, percent, message, created_at) VALUES (?, ?, ?, ?, ?)",
            (job_id, phase, percent, message, _utc_now()),
        )


def find_active_duplicate(video_id: str, feature: str, params_hash: str) -> str | None:
    """Return the id of a queued/running job with the same signature, if any."""
    init_db()
    with connection() as con:
        row = con.execute(
            """
            SELECT id FROM jobs
            WHERE feature = ? AND params_hash = ? AND status IN ('queued', 'running')
            ORDER BY created_at
            LIMIT 1
            """,
            (feature, params_hash),
        ).fetchone()
    return row["id"] if row else None


def get_job(job_id: str) -> dict[str, Any] | None:
    init_db()
    with connection() as con:
        row = con.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return dict(row) if row else None


def list_jobs(*, status: str | None = None, video_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    init_db()
    clauses: list[str] = []
    args: list[Any] = []
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        if statuses:
            clauses.append(f"status IN ({','.join('?' for _ in statuses)})")
            args.extend(statuses)
    if video_id:
        clauses.append("video_id = ?")
        args.append(video_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    args.append(limit)
    with connection() as con:
        rows = con.execute(
            f"SELECT * FROM jobs {where} ORDER BY created_at DESC LIMIT ?", args
        ).fetchall()
    return [dict(r) for r in rows]


def reconcile_orphans() -> int:
    """Mark jobs left running/queued by a previous process as interrupted.

    Called once at startup: the in-memory JobManager is empty, so any active job
    in the DB is stale and cannot resume.
    """
    init_db()
    now = _utc_now()
    with connection() as con:
        cur = con.execute(
            """
            UPDATE jobs
            SET status = 'failed',
                error = 'Interrupted by server restart',
                message = 'Interrupted by server restart',
                finished_at = ?
            WHERE status IN ('running', 'queued')
            """,
            (now,),
        )
        return cur.rowcount


def output_dirs_for_video(video_id: str) -> list[str]:
    """Output folders for jobs tied to a video, including jobs that produced it."""
    if not video_id:
        return []
    init_db()
    with connection() as con:
        rows = con.execute(
            """
            SELECT output_dir FROM jobs
            WHERE video_id = ? OR result_video_id = ?
            """,
            (video_id, video_id),
        ).fetchall()
    return [row["output_dir"] for row in rows if row["output_dir"]]


def delete_jobs_for_video(video_id: str) -> None:
    """Drop job rows for a video. ``job_events`` cascade with the job row."""
    if not video_id:
        return
    init_db()
    with connection() as con:
        con.execute(
            "DELETE FROM jobs WHERE video_id = ? OR result_video_id = ?",
            (video_id, video_id),
        )


def list_events(job_id: str) -> list[dict[str, Any]]:
    init_db()
    with connection() as con:
        rows = con.execute(
            "SELECT phase, percent, message, created_at FROM job_events WHERE job_id = ? ORDER BY id",
            (job_id,),
        ).fetchall()
    return [dict(r) for r in rows]
