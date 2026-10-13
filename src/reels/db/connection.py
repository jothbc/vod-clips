"""SQLite connection helpers for the unified reels database."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from reels.storage import temp_root

DB_NAME = "reels.db"


def db_path() -> Path:
    return temp_root() / DB_NAME


@contextmanager
def connection():
    """Open a connection with foreign keys enforced and commit on success."""
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    try:
        yield con
        con.commit()
    finally:
        con.close()
