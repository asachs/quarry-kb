"""Tests for `quarry init` scaffolding — ISC-9, 10, 11, 12."""

import tomllib
from pathlib import Path

import pytest

from quarry import config
from quarry.errors import QuarryError


def test_init_creates_config(chtmp: Path):
    """ISC-9: init writes a quarry.toml."""
    path = config.init()
    assert path == (chtmp / "quarry.toml")
    assert path.is_file()


def test_init_output_is_valid_toml(chtmp: Path):
    """The scaffolded file parses and loads cleanly with defaults."""
    config.init()
    cfg = config.load(chtmp)
    assert cfg.store.wiki == "wiki"
    assert cfg.ingest.on_duplicate == "refuse"
    assert cfg.discovery.dedup_threshold == 85


def test_init_template_is_fully_commented(chtmp: Path):
    """ISC-10: every config table carries an explanatory comment."""
    config.init()
    text = (chtmp / "quarry.toml").read_text()
    parsed = tomllib.loads(text)
    lines = text.splitlines()
    for table in parsed:
        idx = next(i for i, ln in enumerate(lines) if ln.strip() == f"[{table}]")
        window = lines[idx : idx + 6]
        assert any("#" in ln for ln in window), f"[{table}] table is uncommented"


def test_init_adds_gitignore(chtmp: Path):
    """ISC-11: init gitignores the manifest dir, creating .gitignore if absent."""
    config.init()
    gitignore = (chtmp / ".gitignore").read_text()
    assert ".quarry/" in gitignore.splitlines()


def test_init_appends_to_existing_gitignore_once(chtmp: Path):
    """Existing .gitignore is preserved; the line is added exactly once."""
    (chtmp / ".gitignore").write_text("__pycache__/\n")
    config.init(force=True)
    config._ensure_gitignore(chtmp)  # idempotent second call
    lines = (chtmp / ".gitignore").read_text().splitlines()
    assert "__pycache__/" in lines
    assert lines.count(".quarry/") == 1


def test_init_refuses_overwrite(chtmp: Path):
    """ISC-12: init refuses to clobber an existing quarry.toml."""
    config.init()
    with pytest.raises(QuarryError, match="already exists"):
        config.init()


def test_init_force_overwrites(chtmp: Path):
    """ISC-12: --force allows overwrite."""
    path = config.init()
    path.write_text("[store]\nwiki='custom'\n")
    config.init(force=True)
    assert "knowledge-ingestion harness configuration" in path.read_text()
