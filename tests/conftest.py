"""Every test gets a fresh demo database in a temp folder. No test calls the real model."""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("PORTKEY_API_KEY", "test-key-not-used")  # the agent is built but its model is replaced

from app import config, db  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.sqlite3")
    db.init_db(with_sample=True)
    yield


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)
