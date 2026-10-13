"""Minimal migration runner: applies numbered SQL files once, in order."""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from pathlib import Path

import reels.db.connection as _connection

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_init_lock = threading.Lock()
_initialized_paths: set[str] = set()


def _applied_versions(con) -> set[int]:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )
    rows = con.execute("SELECT version FROM schema_migrations").fetchall()
    return {int(row["version"]) for row in rows}


def _discover_migrations() -> list[tuple[int, Path]]:
    migrations: list[tuple[int, Path]] = []
    for path in sorted(_MIGRATIONS_DIR.glob("*.sql")):
        prefix = path.name.split("_", 1)[0]
        if not prefix.isdigit():
            continue
        migrations.append((int(prefix), path))
    migrations.sort(key=lambda item: item[0])
    return migrations


def run_migrations() -> None:
    """Apply any pending migrations. Idempotent."""
    with _connection.connection() as con:
        applied = _applied_versions(con)
        now = datetime.now(timezone.utc).isoformat()
        for version, path in _discover_migrations():
            if version in applied:
                continue
            con.executescript(path.read_text(encoding="utf-8"))
            con.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (version, now),
            )


def init_db() -> None:
    """Run migrations once per database file; safe to call from any entry point."""
    key = str(_connection.db_path().resolve())
    if key in _initialized_paths:
        return
    with _init_lock:
        if key in _initialized_paths:
            return
        run_migrations()
        _initialized_paths.add(key)


def reset_init_flag() -> None:
    """Force the next init_db() to re-run migrations (used by tests)."""
    _initialized_paths.clear()
