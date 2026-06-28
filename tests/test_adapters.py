"""Tests for adapters + registry — ISC-31, 40, 70, 71, 72, 73, 74, 75, 76, 77, 78."""

import datetime as dt
import sys
from pathlib import Path

import pytest

from quarry import config
from quarry.adapters import registry
from quarry.adapters.base import Adapter, FetchResult
from quarry.adapters.web import WebAdapter
from quarry.adapters.youtube import YouTubeAdapter
from quarry.errors import QuarryError

VID = "abcdefghijk"  # 11-char id


# --- registry ---------------------------------------------------------------


def test_discovered_includes_builtins():
    d = registry.discovered_adapters()
    assert "youtube" in d and "web" in d


def test_list_adapters_marks_enabled(chtmp: Path):
    """ISC-70: listing marks which adapters are enabled."""
    (chtmp / "quarry.toml").write_text('[adapters]\nenabled = ["web"]\n')
    rows = dict(registry.list_adapters(config.load(chtmp)))
    assert rows["web"] is True
    assert rows["youtube"] is False


def test_resolve_matches_first_enabled(cfg):
    """ISC-31: resolve returns the first enabled adapter whose matches() is true."""
    assert registry.resolve_adapter(cfg, f"https://youtu.be/{VID}").name == "youtube"
    assert registry.resolve_adapter(cfg, "https://example.com/post").name == "web"


def test_resolve_respects_enabled_allowlist(chtmp: Path):
    """ISC-71: a disabled adapter is not used even when it would match."""
    (chtmp / "quarry.toml").write_text('[adapters]\nenabled = ["web"]\n')
    cfg = config.load(chtmp)
    ad = registry.resolve_adapter(cfg, f"https://youtu.be/{VID}")
    assert ad.name == "web"  # youtube gated out; web catches the http url


def test_resolve_no_match_raises(chtmp: Path):
    (chtmp / "quarry.toml").write_text('[adapters]\nenabled = ["youtube"]\n')
    with pytest.raises(QuarryError, match="no adapter matches"):
        registry.resolve_adapter(config.load(chtmp), "ftp://nope")


def test_enabled_but_unregistered_is_skipped(chtmp: Path):
    (chtmp / "quarry.toml").write_text('[adapters]\nenabled = ["ghost", "web"]\n')
    ad = registry.resolve_adapter(config.load(chtmp), "https://example.com")
    assert ad.name == "web"


def test_entry_point_discovery(monkeypatch):
    """ISC-72: third-party adapters are discovered via the entry-point group."""

    class Plugin(Adapter):
        name = "pdf"

        def matches(self, url: str) -> bool:
            return url.endswith(".pdf")

        def fetch(self, url: str) -> FetchResult:
            return FetchResult(content="x")

    class FakeEP:
        name = "pdf"

        def load(self):
            return Plugin

    monkeypatch.setattr(registry, "entry_points", lambda group: [FakeEP()])
    assert registry.discovered_adapters()["pdf"] is Plugin


def test_entry_point_broken_plugin_skipped(monkeypatch):
    class FakeEP:
        name = "broken"

        def load(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(registry, "entry_points", lambda group: [FakeEP()])
    d = registry.discovered_adapters()
    assert "broken" not in d and "web" in d


# --- fetch wrapper (ISC-40) -------------------------------------------------


def test_fetch_wraps_adapter_exception():
    class Boom(Adapter):
        name = "boom"

        def matches(self, url: str) -> bool:
            return True

        def fetch(self, url: str) -> FetchResult:
            raise ValueError("kaboom")

    with pytest.raises(QuarryError, match="boom adapter failed: kaboom"):
        registry.fetch(Boom(), "x")


def test_fetch_passes_quarry_error_through():
    class Boom(Adapter):
        name = "boom"

        def matches(self, url: str) -> bool:
            return True

        def fetch(self, url: str) -> FetchResult:
            raise QuarryError("clean message")

    with pytest.raises(QuarryError, match="clean message"):
        registry.fetch(Boom(), "x")


# --- youtube (ISC-73, 74, 78) -----------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        f"https://www.youtube.com/watch?v={VID}",
        f"https://youtu.be/{VID}",
        f"https://www.youtube.com/shorts/{VID}",
        f"https://www.youtube.com/embed/{VID}",
    ],
)
def test_youtube_video_id(url: str):
    """ISC-73: id parsed from watch / youtu.be / shorts / embed forms."""
    assert YouTubeAdapter().video_id(url) == VID


def test_youtube_video_id_unparseable():
    with pytest.raises(QuarryError, match="could not parse"):
        YouTubeAdapter().video_id("https://youtube.com/nope")


def test_youtube_matches():
    a = YouTubeAdapter()
    assert a.matches("https://youtu.be/x")
    assert not a.matches("https://example.com")


def test_youtube_fetch_from_cassette(monkeypatch):
    """ISC-74: fetch assembles content + metadata from recorded responses."""
    a = YouTubeAdapter()
    monkeypatch.setattr(
        a, "_fetch_oembed", lambda url: {"title": "Great Talk", "author_name": "Speaker"}
    )
    monkeypatch.setattr(a, "_fetch_transcript", lambda vid: "the transcript text")
    r = a.fetch(f"https://youtu.be/{VID}")
    assert r.content == "the transcript text"
    assert r.metadata["title"] == "Great Talk"
    assert r.metadata["author"] == "Speaker"
    assert r.metadata["source_id"] == VID
    assert r.metadata["url"].endswith(VID)
    dt.date.fromisoformat(r.metadata["date"])  # valid ISO date


def test_youtube_oembed_failure_falls_back(monkeypatch):
    a = YouTubeAdapter()

    def boom(url):
        raise OSError("no net")

    monkeypatch.setattr(a, "_fetch_oembed", boom)
    monkeypatch.setattr(a, "_fetch_transcript", lambda vid: "txt")
    r = a.fetch(f"https://youtu.be/{VID}")
    assert r.metadata["title"] == f"youtube-{VID}"
    assert r.metadata["author"] == "unknown"


def test_youtube_missing_extra(monkeypatch):
    """ISC-78: a missing extra yields a clean install hint, not ImportError."""
    monkeypatch.setitem(sys.modules, "youtube_transcript_api", None)
    with pytest.raises(QuarryError, match=r"\[youtube\] extra"):
        YouTubeAdapter()._fetch_transcript(VID)


# --- web (ISC-75, 76, 78) ---------------------------------------------------

_FIXTURE_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head><title>Why Quarry Exists</title><meta name="author" content="A. Sachs"></head>
<body>
<nav>home · about · contact</nav>
<article>
<h1>Why Quarry Exists</h1>
<p>Quarry is a knowledge-ingestion harness that owns the deterministic half of
turning a source into a linked wiki article. It never calls a language model.</p>
<p>The two-call seam separates fetching raw material from finishing the article,
so the irreducibly generative step is the only thing left to a human or an agent.</p>
<p>Because every convention is configuration, the same harness works across very
different wikis without forking the code or editing the core modules at all.</p>
</article>
<footer>copyright nobody</footer>
</body>
</html>
"""


def test_web_matches():
    a = WebAdapter()
    assert a.matches("https://example.com")
    assert not a.matches("ftp://x")


def test_web_extracts_from_fixture(monkeypatch):
    """ISC-75/-76: hermetic extraction of content + metadata from fixture HTML."""
    pytest.importorskip("trafilatura")
    a = WebAdapter()
    monkeypatch.setattr(a, "_download", lambda url: _FIXTURE_HTML)
    r = a.fetch("https://example.com/great-article")
    assert "quarry" in r.content.lower()
    assert r.metadata["url"] == "https://example.com/great-article"
    assert r.metadata["source_id"] == "example.com"
    assert r.metadata["title"]
    dt.date.fromisoformat(r.metadata["date"])


def test_web_empty_extraction_raises(monkeypatch):
    pytest.importorskip("trafilatura")
    a = WebAdapter()
    monkeypatch.setattr(a, "_download", lambda url: "<html><body></body></html>")
    with pytest.raises(QuarryError, match="could not extract"):
        a.fetch("https://example.com/empty")


def test_web_missing_extra(monkeypatch):
    """ISC-78: missing [web] extra yields a clean install hint."""
    monkeypatch.setitem(sys.modules, "trafilatura", None)
    with pytest.raises(QuarryError, match=r"\[web\] extra"):
        WebAdapter()._extract("<html></html>", "https://x")


# --- adapters CLI (ISC-70) --------------------------------------------------


def test_adapters_command_lists(cfg, capsys):
    from quarry.cli import main

    assert main(["adapters"]) == 0
    out = capsys.readouterr().out
    assert "youtube" in out and "web" in out and "enabled" in out


# --- integration (ISC-77) — excluded from default runs ----------------------


@pytest.mark.integration
def test_youtube_live():
    r = YouTubeAdapter().fetch("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert r.content


@pytest.mark.integration
def test_web_live():
    r = WebAdapter().fetch("https://example.com")
    assert r.content
