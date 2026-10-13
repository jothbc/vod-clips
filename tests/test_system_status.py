"""Tests for system status API."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from reels.api.app import create_app


@pytest.fixture
def client(monkeypatch, tmp_path):
    import reels.storage as storage_mod

    root = tmp_path / "proj"
    (root / "config").mkdir(parents=True)
    (root / "config" / "default.yaml").write_text("preset: default\n", encoding="utf-8")
    monkeypatch.setattr(storage_mod, "project_root", lambda: root)
    return TestClient(create_app())


def test_system_status_endpoint(client):
    with patch("reels.system_status._cpu_metrics", return_value={"percent": 10.0, "count": 4}):
        with patch("reels.system_status._memory_metrics", return_value={"total_mb": 8000, "used_mb": 4000, "percent": 50.0}):
            with patch("reels.system_status._gpu_metrics", return_value=None):
                r = client.get("/api/v2/system")
    assert r.status_code == 200
    data = r.json()
    assert "whisper" in data
    assert "cuda" in data
    assert data["cpu"]["count"] == 4
    assert data["metrics_partial"] is False


def test_active_job_null_when_idle(client):
    r = client.get("/api/v2/system")
    assert r.status_code == 200
    assert r.json()["active_job"] is None
