"""Tests for ingest — ISC-32, 33, 34, 35, 36, 37, 38, 39."""

from pathlib import Path

import pytest

from quarry import config, discovery, ingest, manifest
from quarry.adapters import registry
from quarry.adapters.base import FetchResult
from quarry.cli import main
from quarry.errors import QuarryError


class FakeAdapter:
    name = "fake"

    def matches(self, url: str) -> bool:
        return True

    def fetch(self, url: str) -> FetchResult:
        return FetchResult(
            content="the body text",
            metadata={
                "title": "My Title",
                "author": "me",
                "date": "2026-06-28",
                "url": url,
                "source_id": "sid123",
            },
        )


@pytest.fixture
def fake_adapter(monkeypatch):
    monkeypatch.setattr(registry, "resolve_adapter", lambda cfg, url: FakeAdapter())


def _cfg(chtmp: Path, on_duplicate: str = "refuse"):
    (chtmp / "quarry.toml").write_text(f'[ingest]\non_duplicate = "{on_duplicate}"\n')
    return config.load(chtmp)


def test_ingest_writes_raw_and_manifest(cfg, fake_adapter):
    """ISC-32: raw material + manifest are written."""
    res = ingest.run(cfg, "https://example.com/x")
    assert res["slug"] == "2026-06-28_my-title"
    raw = cfg.root / "raw" / "2026" / "06" / "2026-06-28_my-title.md"
    assert raw.is_file()
    content = raw.read_text()
    assert content.startswith("---\nsource: https://example.com/x\n")
    assert "the body text" in content
    m = manifest.load(cfg, res["slug"])
    assert m["adapter"] == "fake"
    assert m["content_sha256"] == manifest.sha256_text("the body text")
    assert m["must_cite_source"] == "raw/2026/06/2026-06-28_my-title.md"


def test_ingest_topic_sets_target(cfg, fake_adapter):
    """ISC-35: --topic populates target_wiki_path."""
    res = ingest.run(cfg, "https://example.com/x", topic="ai")
    assert res["target_wiki_path"] == "wiki/ai/my-title.md"
    assert manifest.load(cfg, res["slug"])["target_wiki_path"] == "wiki/ai/my-title.md"


def test_ingest_refuses_existing_raw(cfg, fake_adapter):
    """ISC-33: existing raw is not clobbered without --force."""
    ingest.run(cfg, "https://example.com/x")
    with pytest.raises(QuarryError, match="raw already exists"):
        ingest.run(cfg, "https://example.com/x")


def test_ingest_force_overwrites_raw(cfg, fake_adapter):
    ingest.run(cfg, "https://example.com/x")
    res = ingest.run(cfg, "https://example.com/x", force=True)  # no raise
    assert (cfg.root / res["raw_path"]).is_file()


def test_ingest_prints_compile_spec(cfg, fake_adapter, capsys):
    """ISC-34: ingest prints a compile-spec via the CLI."""
    assert main(["ingest", "https://example.com/x"]) == 0
    out = capsys.readouterr().out
    assert "COMPILE-SPEC" in out
    assert "2026-06-28_my-title" in out
    assert "MUST cite source" in out


# --- dedup pre-check (ISC-36, 37, 38, 39) -----------------------------------


def test_dedup_refuse_aborts(chtmp: Path, fake_adapter, monkeypatch):
    """ISC-36: on_duplicate=refuse aborts on a strong hit."""
    c = _cfg(chtmp, "refuse")
    monkeypatch.setattr(discovery, "dedup_hits", lambda cfg, title: [(91, "wiki/dup.md")])
    with pytest.raises(QuarryError, match="possible duplicate"):
        ingest.run(c, "https://example.com/x")


def test_dedup_warn_proceeds(chtmp: Path, fake_adapter, monkeypatch, capsys):
    """ISC-37: on_duplicate=warn warns but ingests."""
    c = _cfg(chtmp, "warn")
    monkeypatch.setattr(discovery, "dedup_hits", lambda cfg, title: [(91, "wiki/dup.md")])
    res = ingest.run(c, "https://example.com/x")
    assert (c.root / res["raw_path"]).is_file()
    assert "may already be covered" in capsys.readouterr().err


def test_dedup_allow_skips_check(chtmp: Path, fake_adapter, monkeypatch):
    """ISC-38: on_duplicate=allow ingests without even querying discovery."""
    c = _cfg(chtmp, "allow")
    called = {"n": 0}

    def spy(cfg, title):
        called["n"] += 1
        return [(99, "wiki/dup.md")]

    monkeypatch.setattr(discovery, "dedup_hits", spy)
    res = ingest.run(c, "https://example.com/x")
    assert (c.root / res["raw_path"]).is_file()
    assert called["n"] == 0


def test_force_bypasses_dedup(chtmp: Path, fake_adapter, monkeypatch):
    """ISC-39: --force skips the dedup pre-check entirely."""
    c = _cfg(chtmp, "refuse")

    def boom(cfg, title):
        raise AssertionError("dedup should be skipped under --force")

    monkeypatch.setattr(discovery, "dedup_hits", boom)
    res = ingest.run(c, "https://example.com/x", force=True)
    assert (c.root / res["raw_path"]).is_file()
