"""Shared pytest fixtures."""

from pathlib import Path

import pytest


@pytest.fixture
def chtmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Change into a fresh temp dir for the duration of the test."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def cfg(chtmp: Path):
    """A loaded Config backed by the default scaffolded quarry.toml in a temp dir."""
    from quarry import config

    config.init()
    return config.load(chtmp)


@pytest.fixture(autouse=True)
def _hermetic_qmd(monkeypatch: pytest.MonkeyPatch):
    """Hermetic by default: never reach a real qmd on the dev machine (ISC-88).

    Tests that want a working backend monkeypatch find_qmd / dedup_hits themselves.
    """
    from quarry import discovery

    monkeypatch.setattr(discovery, "find_qmd", lambda: None)
