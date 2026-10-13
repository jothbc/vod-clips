"""Unified SQLite database for videos, transcripts, jobs and publish wallet."""

from __future__ import annotations

from reels.db.connection import db_path
from reels.db.migrate import init_db

__all__ = ["db_path", "init_db"]
