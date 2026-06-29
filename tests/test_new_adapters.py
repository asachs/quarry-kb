"""Hermetic tests for adapters: github, pdf, instagram + youtube fallback."""

import sys

import pytest

from quarry import transcribe
from quarry.adapters import registry
from quarry.adapters.github import GitHubAdapter
from quarry.adapters.instagram import InstagramAdapter
from quarry.adapters.pdf import PdfAdapter
from quarry.adapters.youtube import YouTubeAdapter, _vtt_to_text
from quarry.errors import QuarryError


def _raises(exc):
    def _f(*_a, **_k):
        raise exc

    return _f


# --- registry resolution (default enabled now includes the new adapters) ----


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://github.com/asachs/quarry-kb", "github"),
        ("https://www.instagram.com/reel/XYZ/", "instagram"),
        ("https://example.com/paper.pdf", "pdf"),
        ("https://www.youtube.com/watch?v=abcdefghijk", "youtube"),
        ("https://example.com/article", "web"),
    ],
)
def test_resolve(cfg, url, expected):
    assert registry.resolve_adapter(cfg, url).name == expected


# --- github ------------------------------------------------------------------


def test_github_matches():
    a = GitHubAdapter()
    assert a.matches("https://github.com/o/r")
    assert not a.matches("https://gitlab.com/o/r")


def test_github_fetch(monkeypatch):
    a = GitHubAdapter()
    monkeypatch.setattr(a, "_ingest", lambda url: ("SUMMARY", "TREE", "CONTENT"))
    r = a.fetch("https://github.com/asachs/quarry-kb")
    assert r.metadata["title"] == "asachs/quarry-kb"
    assert r.metadata["author"] == "asachs"
    assert r.metadata["source_id"] == "asachs/quarry-kb"
    assert all(s in r.content for s in ("SUMMARY", "TREE", "CONTENT"))


def test_github_missing_extra(monkeypatch):
    monkeypatch.setitem(sys.modules, "gitingest", None)
    with pytest.raises(QuarryError, match=r"\[github\] extra"):
        GitHubAdapter()._ingest("https://github.com/o/r")


# --- pdf ---------------------------------------------------------------------


def test_pdf_matches():
    a = PdfAdapter()
    assert a.matches("https://x.com/f.pdf")
    assert a.matches("/tmp/local.pdf")
    assert not a.matches("https://x.com/page")


def test_pdf_fetch(monkeypatch, tmp_path):
    a = PdfAdapter()
    p = tmp_path / "doc.pdf"
    p.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(a, "_local_path", lambda url: (p, False))
    meta = {"title": "My Doc", "author": "Jane"}
    monkeypatch.setattr(a, "_to_markdown", lambda path: ("# Heading\n\nbody", meta))
    r = a.fetch(str(p))
    assert r.metadata["title"] == "My Doc"
    assert r.metadata["author"] == "Jane"
    assert "# Heading" in r.content


def test_pdf_empty_raises(monkeypatch, tmp_path):
    a = PdfAdapter()
    p = tmp_path / "s.pdf"
    p.write_bytes(b"%PDF")
    monkeypatch.setattr(a, "_local_path", lambda url: (p, False))
    monkeypatch.setattr(a, "_to_markdown", lambda path: ("", {}))
    with pytest.raises(QuarryError, match="no extractable text"):
        a.fetch(str(p))


def test_pdf_missing_extra(monkeypatch, tmp_path):
    for m in ("pymupdf", "pymupdf4llm"):
        monkeypatch.setitem(sys.modules, m, None)
    p = tmp_path / "s.pdf"
    p.write_bytes(b"%PDF")
    with pytest.raises(QuarryError, match=r"\[pdf\] extra"):
        PdfAdapter()._to_markdown(p)


# --- instagram ---------------------------------------------------------------


def test_instagram_matches():
    a = InstagramAdapter()
    assert a.matches("https://www.instagram.com/reel/ABC/")
    assert a.matches("https://instagram.com/p/XYZ/")
    assert not a.matches("https://instagram.com/someuser")


def test_instagram_caption_only(monkeypatch):
    a = InstagramAdapter()
    info = {"description": "My reel caption\nsecond line", "uploader": "creator"}
    monkeypatch.setattr(a, "_info", lambda url: info)
    monkeypatch.setattr(transcribe, "available", lambda: False)
    r = a.fetch("https://www.instagram.com/reel/ABC/")
    assert r.metadata["author"] == "creator"
    assert r.metadata["source_id"] == "ABC"
    assert r.metadata["title"] == "My reel caption"
    assert "My reel caption" in r.content


def test_instagram_login_required(monkeypatch):
    a = InstagramAdapter()
    monkeypatch.setattr(a, "_info", _raises(RuntimeError("You need to log in")))
    with pytest.raises(QuarryError, match="yt-dlp"):
        a.fetch("https://www.instagram.com/reel/ABC/")


def test_instagram_empty_media_response_classified(monkeypatch):
    """The real 2026 'empty media response' failure -> upgrade guidance (curl_cffi)."""
    a = InstagramAdapter()
    msg = "Instagram sent an empty media response. ... use --cookies-from-browser or --cookies"
    monkeypatch.setattr(a, "_info", _raises(RuntimeError(msg)))
    with pytest.raises(QuarryError, match="curl_cffi"):
        a.fetch("https://www.instagram.com/reel/ABC/")


def test_instagram_cookie_opts(monkeypatch):
    from quarry.adapters import instagram

    monkeypatch.delenv("QUARRY_INSTAGRAM_COOKIES", raising=False)
    monkeypatch.delenv("QUARRY_INSTAGRAM_COOKIES_FROM_BROWSER", raising=False)
    assert instagram._cookie_opts() == {}
    assert instagram.cookies_configured() is False

    monkeypatch.setenv("QUARRY_INSTAGRAM_COOKIES", "/tmp/ig.txt")
    assert instagram._cookie_opts() == {"cookiefile": "/tmp/ig.txt"}
    assert instagram.cookies_configured() is True

    monkeypatch.delenv("QUARRY_INSTAGRAM_COOKIES")
    monkeypatch.setenv("QUARRY_INSTAGRAM_COOKIES_FROM_BROWSER", "firefox:work")
    assert instagram._cookie_opts() == {"cookiesfrombrowser": ("firefox", "work", None, None)}


def test_instagram_audio_transcript(monkeypatch):
    a = InstagramAdapter()
    monkeypatch.setattr(a, "_info", lambda url: {"description": "cap", "uploader": "c"})
    monkeypatch.setattr(transcribe, "available", lambda: True)
    monkeypatch.setattr(a, "_audio", lambda url, d: "/tmp/a.wav")
    monkeypatch.setattr(transcribe, "transcribe", lambda p: "spoken words here")
    r = a.fetch("https://instagram.com/reel/ABC/")
    assert "spoken words here" in r.content


# --- youtube fallback chain --------------------------------------------------


def test_vtt_to_text():
    vtt = (
        "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHello <c>world</c>\n\n"
        "2\n00:00:02.000 --> 00:00:03.000\nHello <c>world</c>\nNext line\n"
    )
    assert _vtt_to_text(vtt) == "Hello world Next line"


def test_youtube_falls_back_to_subs(monkeypatch):
    a = YouTubeAdapter()
    monkeypatch.setattr(a, "_fetch_transcript", _raises(QuarryError("no captions")))
    monkeypatch.setattr(a, "_ytdlp_subs", lambda url: "subtitle transcript")
    out = a._transcript_with_fallback("https://youtu.be/abcdefghijk", "abcdefghijk")
    assert out == "subtitle transcript"


def test_youtube_falls_back_to_whisper(monkeypatch):
    a = YouTubeAdapter()
    monkeypatch.setattr(a, "_fetch_transcript", lambda vid: "")
    monkeypatch.setattr(a, "_ytdlp_subs", lambda url: "")
    monkeypatch.setattr(a, "_whisper_fallback", lambda url: "whispered text")
    assert a._transcript_with_fallback("u", "v") == "whispered text"


def test_youtube_all_fail(monkeypatch):
    a = YouTubeAdapter()
    for m in ("_fetch_transcript", "_ytdlp_subs", "_whisper_fallback"):
        monkeypatch.setattr(a, m, _raises(QuarryError("nope")))
    with pytest.raises(QuarryError, match="no transcript via captions"):
        a._transcript_with_fallback("u", "v")


def test_youtube_compose_description_only():
    out = YouTubeAdapter._compose("Links: example.com", "", [], "spoken transcript")
    assert out == "## Description\n\nLinks: example.com\n\n## Transcript\n\nspoken transcript"


def test_youtube_compose_bare_transcript_when_empty():
    # nothing extra -> bare transcript (back-compat, no headers)
    assert YouTubeAdapter._compose("", "", [], "just the transcript") == "just the transcript"


def test_youtube_compose_with_pinned_and_comments():
    out = YouTubeAdapter._compose("desc", "PINNED note", ["(9👍) great", "(3👍) ok"], "TX")
    assert "## Description\n\ndesc" in out
    assert "## Pinned comment\n\nPINNED note" in out
    assert "## Top comments (community — not the creator's claims)" in out
    assert "1. (9👍) great" in out and "2. (3👍) ok" in out
    assert out.endswith("## Transcript\n\nTX")


def test_youtube_select_comments_ranks_and_finds_pinned():
    comments = [
        {"text": "meh", "like_count": 2, "is_pinned": False},
        {"text": "creator note: errata here", "like_count": 0, "is_pinned": True},
        {"text": "top one", "like_count": 50, "is_pinned": False},
        {"text": "second", "like_count": 9, "is_pinned": False},
    ]
    pinned, top = YouTubeAdapter._select_comments(comments, top_n=2)
    assert "errata here" in pinned
    assert top == ["(50👍) top one", "(9👍) second"]  # ranked by likes, pinned excluded, capped


def test_youtube_fetch_folds_in_description(monkeypatch):
    a = YouTubeAdapter()
    monkeypatch.setattr(a, "_fetch_oembed", lambda url: {"title": "T", "author_name": "A"})
    monkeypatch.setattr(
        a, "_fetch_info", lambda url, wc, mc: {"description": "Chapter links + sources"}
    )
    monkeypatch.setattr(a, "_transcript_with_fallback", lambda url, vid: "the words")
    r = a.fetch("https://www.youtube.com/watch?v=abcdefghijk")
    assert "## Description\n\nChapter links + sources" in r.content
    assert "## Transcript\n\nthe words" in r.content
    assert r.metadata["title"] == "T"


def test_youtube_fetch_comments_gated_by_config(monkeypatch):
    from quarry.config import YoutubeConfig

    a = YouTubeAdapter()
    info = {
        "description": "d",
        "comments": [{"text": "hi", "like_count": 5, "is_pinned": False}],
    }
    monkeypatch.setattr(a, "_fetch_oembed", lambda url: {})
    monkeypatch.setattr(a, "_fetch_info", lambda url, wc, mc: info)
    monkeypatch.setattr(a, "_transcript_with_fallback", lambda url, vid: "tx")

    # comments disabled (no cfg) -> no comment sections
    r = a.fetch("https://youtu.be/abcdefghijk")
    assert "Top comments" not in r.content

    # comments enabled via cfg -> section appears

    class _Cfg:
        youtube = YoutubeConfig(comments=True, top_comments=5)

    a.cfg = _Cfg()
    r = a.fetch("https://youtu.be/abcdefghijk")
    assert "## Top comments" in r.content and "(5👍) hi" in r.content


def test_youtube_fetch_survives_info_failure(monkeypatch):
    a = YouTubeAdapter()
    monkeypatch.setattr(a, "_fetch_oembed", lambda url: {})
    monkeypatch.setattr(a, "_fetch_info", _raises(RuntimeError("yt-dlp boom")))
    monkeypatch.setattr(a, "_transcript_with_fallback", lambda url, vid: "transcript only")
    r = a.fetch("https://youtu.be/abcdefghijk")
    assert r.content == "transcript only"  # metadata/comments best-effort, doesn't break fetch


# --- integration (live, no-auth) — excluded from default runs ---------------


@pytest.mark.integration
def test_github_live():
    r = GitHubAdapter().fetch("https://github.com/octocat/Hello-World")
    assert r.metadata["source_id"] == "octocat/Hello-World"
    assert r.content
