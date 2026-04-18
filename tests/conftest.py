"""Shared fixtures for the smart-compact test suite."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    """Absolute path to tests/fixtures."""
    return FIXTURES_DIR


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """Isolated project root with a .claude/ directory."""
    (tmp_path / ".claude").mkdir()
    return tmp_path


@pytest.fixture
def copy_fixture(tmp_path: Path):
    """Return a callable that copies a named fixture into tmp_path."""

    def _copy(name: str) -> Path:
        src = FIXTURES_DIR / name
        dst = tmp_path / name
        dst.write_text(src.read_text())
        return dst

    return _copy


@pytest.fixture
def make_payload():
    """Return a callable that produces a hook stdin JSON string."""

    def _make(**overrides) -> str:
        payload = {
            "session_id": "test-session-001",
            "hook_event_name": "PreCompact",
            "trigger": "auto",
        }
        payload.update(overrides)
        return json.dumps(payload)

    return _make
