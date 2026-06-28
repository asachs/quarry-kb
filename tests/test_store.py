"""Tests for store paths & templating — ISC-20, 22, 23, 24, 25."""

import datetime as dt
from pathlib import Path

import pytest

from quarry import config, store
from quarry.errors import ConfigError

DATE = dt.date(2026, 6, 28)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Hello World", "hello-world"),
        ("  Trimmed  ", "trimmed"),
        ("Pythön & Café!", "python-cafe"),
        ("under_score me", "under-score-me"),
        ("", "untitled"),
        ("!!!", "untitled"),
    ],
)
def test_slugify(text: str, expected: str):
    assert store.slugify(text) == expected


def test_dir_resolution_under_root(cfg):
    assert store.wiki_dir(cfg) == cfg.root / "wiki"
    assert store.raw_dir(cfg) == cfg.root / "raw"
    assert store.manifest_dir(cfg) == cfg.root / ".quarry"


def test_make_slug_default_template(cfg):
    """ISC-25: the [ingest] slug template drives the slug."""
    assert store.make_slug(cfg, title="Hello World", date=DATE) == "2026-06-28_hello-world"


def test_make_slug_custom_template(chtmp: Path):
    (chtmp / "quarry.toml").write_text('[ingest]\nslug = "{kebab_title}-{year}"\n')
    c = config.load(chtmp)
    assert store.make_slug(c, title="My Note", date=DATE) == "my-note-2026"


def test_make_slug_rejects_slug_token(chtmp: Path):
    """{slug} in the slug template is a config error, not a recursion."""
    (chtmp / "quarry.toml").write_text('[ingest]\nslug = "{slug}-x"\n')
    c = config.load(chtmp)
    with pytest.raises(ConfigError, match=r"\[ingest\] slug: unknown token \{slug\}"):
        store.make_slug(c, title="t", date=DATE)


def test_make_raw_path_default_layout(cfg):
    p = store.make_raw_path(cfg, title="Hello World", date=DATE, slug="2026-06-28_hello-world")
    assert p == cfg.root / "raw" / "2026" / "06" / "2026-06-28_hello-world.md"


@pytest.mark.parametrize(
    "layout,expected_rel",
    [
        ("{date}_{slug}.{ext}", "2026-06-28_2026-06-28_hello-world.md"),
        ("{year}/{kebab_title}.{ext}", "2026/hello-world.md"),
        ("flat-{slug}.{ext}", "flat-2026-06-28_hello-world.md"),
    ],
)
def test_make_raw_path_matrix(chtmp: Path, layout: str, expected_rel: str):
    """ISC-24: a different raw_layout produces a different path."""
    (chtmp / "quarry.toml").write_text(f'[store]\nraw_layout = "{layout}"\n')
    c = config.load(chtmp)
    p = store.make_raw_path(c, title="Hello World", date=DATE, slug="2026-06-28_hello-world")
    assert p == c.root / "raw" / expected_rel


def test_all_tokens_expand(chtmp: Path):
    """ISC-23: every documented token expands in raw_layout."""
    layout = "{year}/{month}/{date}/{topic}/{source_id}/{kebab_title}_{slug}.{ext}"
    (chtmp / "quarry.toml").write_text(f'[store]\nraw_layout = "{layout}"\n')
    c = config.load(chtmp)
    p = store.make_raw_path(
        c,
        title="Hello World",
        date=DATE,
        slug="the-slug",
        ext="txt",
        topic="ai",
        source_id="vid123",
    )
    expected = (
        c.root / "raw" / "2026" / "06" / "2026-06-28" / "ai" / "vid123"
        / "hello-world_the-slug.txt"
    )
    assert p == expected


def test_unknown_token_errors(chtmp: Path):
    (chtmp / "quarry.toml").write_text('[store]\nraw_layout = "{bogus}.md"\n')
    c = config.load(chtmp)
    with pytest.raises(ConfigError, match=r"raw_layout: unknown token \{bogus\}"):
        store.make_raw_path(c, title="t", date=DATE, slug="s")


def test_raw_relpath(cfg):
    p = store.make_raw_path(cfg, title="T", date=DATE, slug="s")
    assert store.raw_relpath(cfg, p) == "raw/2026/06/s.md"


def test_root_discovery_nested_non_git(tmp_path: Path):
    """ISC-20 / ISC-22: root is found by walk-up from a nested, non-git dir."""
    (tmp_path / "quarry.toml").write_text("[store]\n")
    nested = tmp_path / "deep" / "nested"
    nested.mkdir(parents=True)
    assert not (tmp_path / ".git").exists()  # no git anywhere
    c = config.load(nested)
    assert c.root == tmp_path.resolve()
    assert store.wiki_dir(c) == tmp_path.resolve() / "wiki"
