"""Shared pytest fixtures."""

from pathlib import Path

import pytest


@pytest.fixture
def chtmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Change into a fresh temp dir for the duration of the test."""
    monkeypatch.chdir(tmp_path)
    return tmp_path
