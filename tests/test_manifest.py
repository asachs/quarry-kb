"""Tests for the compile-manifest seam — ISC-26, 27, 28, 29, 30."""

import hashlib
import json

import pytest

from quarry import manifest
from quarry.errors import QuarryError


def _sample(content: str = "the fetched transcript text") -> dict:
    return manifest.build(
        slug="2026-06-28_hello",
        source_url="https://example.com/x",
        adapter="web",
        raw_path="raw/2026/06/2026-06-28_hello.md",
        content=content,
        target_wiki_path="wiki/ai/hello.md",
        required_frontmatter=["title", "updated", "sources", "related"],
        metadata={"title": "Hello", "author": "nobody"},
    )


def test_manifest_path_location(cfg):
    assert manifest.manifest_path(cfg, "the-slug") == cfg.root / ".quarry" / "the-slug.json"


def test_build_has_all_required_keys():
    """ISC-27: the manifest carries every required key."""
    m = _sample()
    assert set(manifest.REQUIRED_KEYS) <= set(m)
    assert m["must_cite_source"] == m["raw_path"]


def test_content_sha256_matches(cfg):
    """ISC-28: content_sha256 == sha256 of the fetched content."""
    content = "some unique content — with unicode"
    m = _sample(content)
    assert m["content_sha256"] == hashlib.sha256(content.encode("utf-8")).hexdigest()


def test_write_creates_json_at_manifest_path(cfg):
    """ISC-26: ingest writes {manifest_dir}/{slug}.json."""
    m = _sample()
    path = manifest.write(cfg, m["slug"], m)
    assert path == cfg.root / ".quarry" / "2026-06-28_hello.json"
    assert path.is_file()
    assert json.loads(path.read_text())["adapter"] == "web"


def test_roundtrip_equal(cfg):
    """ISC-29: write then load round-trips to an equal object."""
    m = _sample()
    manifest.write(cfg, m["slug"], m)
    assert manifest.load(cfg, m["slug"]) == m


def test_load_missing_raises(cfg):
    """ISC-30: load aborts cleanly when no manifest exists for the slug."""
    with pytest.raises(QuarryError, match="no compile-manifest for slug 'ghost'"):
        manifest.load(cfg, "ghost")
