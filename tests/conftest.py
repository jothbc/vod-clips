"""Ensure src/ is on path when running pytest without editable install."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest


@pytest.fixture(autouse=True)
def _isolate_reels_db(tmp_path, monkeypatch):
    """Point the unified SQLite DB at a per-test file so rows never leak between tests."""
    import importlib

    connection_mod = importlib.import_module("reels.db.connection")
    migrate_mod = importlib.import_module("reels.db.migrate")

    db_file = tmp_path / "reels_test.db"
    monkeypatch.setattr(connection_mod, "db_path", lambda: db_file)
    migrate_mod.reset_init_flag()
    yield
    migrate_mod.reset_init_flag()
