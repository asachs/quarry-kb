"""Hermetic tests for 0.6: instagram media/carousels, asset storage, ingest-time link
candidates, and scoped / auto-indexing finish. No network, no ffmpeg/tesseract/qmd."""

import datetime
import os
import subprocess
from pathlib import Path

import pytest

from quarry import config, discovery, finish, git, ingest, manifest, transcribe
from quarry.adapters import instagram, registry
from quarry.adapters.base import FetchResult
from quarry.adapters.instagram import InstagramAdapter
from quarry.cli import main
from quarry.errors import ConfigError, QuarryError

# --- helpers ------------------------------------------------------------------


def _ig(media=True, ocr=True, frame_interval=2, max_frames=40, keep_video=True):
    a = InstagramAdapter()
    a.cfg = type(
        "Cfg",
        (),
        {
            "instagram": config.InstagramConfig(
                media=media, ocr=ocr, frame_interval=frame_interval, max_frames=max_frames,
                keep_video=keep_video,
            )
        },
    )()
    return a


def _carousel_info(n=3):
    return {
        "_type": "playlist",
        "description": "Ten repos worth saving\nmore caption",
        "uploader": "the_coder",
        "upload_date": "20260912",
        "entries": [
            {
                "id": f"S{i}",
                "thumbnails": [
                    {"url": f"https://cdn/x{i}_small.jpg", "width": 150, "height": 150},
                    {"url": f"https://cdn/x{i}_big.jpg", "width": 1080, "height": 1350},
                ],
            }
            for i in range(1, n + 1)
        ],
    }


def _fake_download(url, dest):
    Path(dest).write_bytes(b"jpg:" + url.encode())
    return True


# --- instagram helpers --------------------------------------------------------


def test_post_date_variants():
    today = datetime.date.today().isoformat()
    assert instagram.post_date({"upload_date": "20260912"}) == "2026-09-12"
    assert instagram.post_date({"timestamp": 1757664000}) == "2025-09-12"
    assert instagram.post_date({}) == today
    assert instagram.post_date({"upload_date": "bad"}) == today


def test_best_image_url_prefers_largest_and_falls_back():
    entry = _carousel_info(1)["entries"][0]
    assert instagram.best_image_url(entry) == "https://cdn/x1_big.jpg"
    assert instagram.best_image_url({"thumbnail": "https://cdn/t.jpg"}) == "https://cdn/t.jpg"
    assert instagram.best_image_url({}) is None


def test_is_carousel():
    assert instagram.is_carousel({"_type": "playlist"})
    assert instagram.is_carousel({"entries": [{}]})
    assert not instagram.is_carousel({"description": "reel"})


def test_dedupe_ocr_drops_repeats_and_noise():
    items = [("0:00", "HELLO  world"), ("0:02", "hello world".upper()), ("0:04", "  "),
             ("0:06", "a."), ("0:08", "next caption"), ("0:10", "next caption")]
    assert instagram.dedupe_ocr(items) == [("0:00", "HELLO world"), ("0:08", "next caption")]


# --- instagram fetch: carousels -------------------------------------------------


def test_carousel_with_media_downloads_slides_and_ocrs(monkeypatch):
    a = _ig()
    monkeypatch.setattr(a, "_info", lambda url: _carousel_info(3))
    monkeypatch.setattr(a, "_download", _fake_download)
    monkeypatch.setattr(a, "_tool", lambda name: True)
    monkeypatch.setattr(a, "_ocr", lambda p: f"text of {Path(p).name}\n")
    r = a.fetch("https://www.instagram.com/p/ABC/")
    assert sorted(r.assets) == ["slide_01.jpg", "slide_02.jpg", "slide_03.jpg"]
    assert Path(r.assets["slide_02.jpg"]).read_bytes() == b"jpg:https://cdn/x2_big.jpg"
    assert r.metadata["date"] == "2026-09-12"
    assert r.metadata["kind"] == "carousel of 3 slides"
    assert "## On-screen text (OCR)" in r.content
    assert "- **slide 02**: text of slide_02.jpg" in r.content
    assert r.tmpdir and os.path.isdir(r.tmpdir)


def test_carousel_without_media_is_caption_only(monkeypatch):
    a = _ig(media=False)
    monkeypatch.setattr(a, "_info", lambda url: _carousel_info(2))
    r = a.fetch("https://www.instagram.com/p/ABC/")
    assert r.assets == {} and r.tmpdir is None
    assert "Ten repos worth saving" in r.content
    assert r.metadata["kind"] == "carousel of 2 slides"


def test_carousel_author_from_first_entry_and_failed_slide_noted(monkeypatch):
    info = _carousel_info(2)
    del info["uploader"]
    info["entries"][0]["uploader"] = "slide_author"
    info["entries"].append({"id": "noimg"})  # no thumbnail -> skipped silently
    a = _ig(ocr=False)
    monkeypatch.setattr(a, "_info", lambda url: info)

    def flaky(url, dest):
        if "x2" in url:
            raise OSError("boom")
        return _fake_download(url, dest)

    monkeypatch.setattr(a, "_download", flaky)
    r = a.fetch("https://www.instagram.com/p/ABC/")
    assert r.metadata["author"] == "slide_author"
    assert list(r.assets) == ["slide_01.jpg"]
    assert "slide 2: download failed" in r.content
    assert "On-screen text" not in r.content


# --- instagram fetch: reels -----------------------------------------------------


def test_reel_with_media_frames_ocr_and_transcript(monkeypatch, tmp_path):
    a = _ig(frame_interval=2, max_frames=3)
    monkeypatch.setattr(a, "_info", lambda url: {"description": "cap", "uploader": "u",
                                                "upload_date": "20261001"})

    def video(url, d):
        p = Path(d) / "video.mp4"
        p.write_bytes(b"mp4")
        return str(p)

    def frames(v, d, every):
        out = []
        for i in range(5):
            f = Path(d) / f"frame_{i:03d}.jpg"
            f.write_bytes(b"f")
            out.append((i * every, str(f)))
        return out

    texts = iter(["Title card", "Title card", "", "Step two", "Step three"])
    monkeypatch.setattr(a, "_video", video)
    monkeypatch.setattr(a, "_duration", lambda v: 30.0)  # 30 s / 3 frames -> every 10 s
    seen = {}
    monkeypatch.setattr(a, "_frames", lambda v, d, every: seen.setdefault("every", every)
                        and frames(v, d, every))
    monkeypatch.setattr(a, "_tool", lambda name: True)
    monkeypatch.setattr(a, "_ocr", lambda p: next(texts))
    monkeypatch.setattr(transcribe, "available", lambda: True)
    monkeypatch.setattr(transcribe, "transcribe", lambda p: f"spoken from {Path(p).name}")
    r = a.fetch("https://www.instagram.com/reel/XYZ/")
    assert seen["every"] == 10.0
    assert sorted(r.assets) == ["frame_0m00s.jpg", "frame_0m10s.jpg", "frame_0m20s.jpg",
                                "video.mp4"]
    assert "spoken from video.mp4" in r.content  # transcribed from the saved video
    assert "- **0:00**: Title card" in r.content
    assert r.content.count("Title card") == 1
    assert r.metadata["kind"] == "video" and r.metadata["date"] == "2026-10-01"


def test_reel_video_failure_falls_back_to_audio(monkeypatch):
    a = _ig()
    monkeypatch.setattr(a, "_info", lambda url: {"description": "cap", "uploader": "u"})
    monkeypatch.setattr(a, "_video", lambda url, d: (_ for _ in ()).throw(OSError("blocked")))
    monkeypatch.setattr(transcribe, "available", lambda: True)
    monkeypatch.setattr(a, "_audio", lambda url, d: "/tmp/a.wav")
    monkeypatch.setattr(transcribe, "transcribe", lambda p: "audio words")
    r = a.fetch("https://www.instagram.com/reel/XYZ/")
    assert r.assets == {}
    assert "video download failed" in r.content and "audio words" in r.content


def test_reel_video_not_kept_by_default_setting(monkeypatch):
    a = _ig(keep_video=False)
    monkeypatch.setattr(a, "_info", lambda url: {"description": "cap"})

    def video(url, d):
        p = Path(d) / "video.mp4"
        p.write_bytes(b"mp4")
        return str(p)

    monkeypatch.setattr(a, "_video", video)
    monkeypatch.setattr(a, "_tool", lambda name: False)
    monkeypatch.setattr(transcribe, "available", lambda: True)
    monkeypatch.setattr(transcribe, "transcribe", lambda p: "from the video")
    r = a.fetch("https://www.instagram.com/reel/XYZ/")
    assert r.assets == {} and "from the video" in r.content
    assert config.InstagramConfig().keep_video is False


def test_reel_frames_skipped_without_ffmpeg(monkeypatch):
    a = _ig()
    monkeypatch.setattr(a, "_info", lambda url: {"description": "cap"})

    def video(url, d):
        p = Path(d) / "video.mp4"
        p.write_bytes(b"mp4")
        return str(p)

    monkeypatch.setattr(a, "_video", video)
    monkeypatch.setattr(a, "_tool", lambda name: False)
    monkeypatch.setattr(transcribe, "available", lambda: False)
    r = a.fetch("https://www.instagram.com/reel/XYZ/")
    assert list(r.assets) == ["video.mp4"]


def test_nothing_extracted_message(monkeypatch):
    a = _ig(media=False)
    monkeypatch.setattr(a, "_info", lambda url: {})
    monkeypatch.setattr(transcribe, "available", lambda: False)
    r = a.fetch("https://www.instagram.com/reel/XYZ/")
    assert "no caption, audio or on-screen text" in r.content


def test_adapter_reads_instagram_settings_from_config(cfg):
    a = registry.resolve_adapter(cfg, "https://www.instagram.com/reel/XYZ/")
    assert a._settings().media is False  # default: opt-in
    assert InstagramAdapter()._settings() == config.InstagramConfig()


# --- ingest: asset storage ---------------------------------------------------------


class AssetAdapter:
    name = "fake"

    def __init__(self, tmpdir: Path):
        self.tmpdir = tmpdir

    def matches(self, url):
        return True

    def fetch(self, url):
        self.tmpdir.mkdir(parents=True, exist_ok=True)
        (self.tmpdir / "slide_01.jpg").write_bytes(b"one")
        (self.tmpdir / "video.mp4").write_bytes(b"vid")
        return FetchResult(
            content="# T\n\n## Caption\nhello\n",
            metadata={"title": "My Post", "date": "2026-09-12", "url": url, "source_id": "P1"},
            assets={"slide_01.jpg": str(self.tmpdir / "slide_01.jpg"),
                    "video.mp4": str(self.tmpdir / "video.mp4")},
            tmpdir=str(self.tmpdir),
        )


def test_ingest_copies_assets_and_lists_them(cfg, monkeypatch, tmp_path):
    scratch = tmp_path / "scratch"
    monkeypatch.setattr(registry, "resolve_adapter", lambda c, u: AssetAdapter(scratch))
    res = ingest.run(cfg, "https://example.com/p")
    m = res["manifest"]
    assert m["assets"] == [
        "raw/2026/09/2026-09-12_my-post/slide_01.jpg",
        "raw/2026/09/2026-09-12_my-post/video.mp4",
    ]
    assert (cfg.root / m["assets"][0]).read_bytes() == b"one"
    raw = (cfg.root / res["raw_path"]).read_text()
    assert "## Media" in raw and "- [slide_01.jpg](2026-09-12_my-post/slide_01.jpg)" in raw
    assert not scratch.exists()  # adapter scratch dir cleaned up
    assert m["related_candidates"] == []


def test_ingest_cleans_tmpdir_even_on_error(cfg, monkeypatch, tmp_path):
    scratch = tmp_path / "scratch"
    monkeypatch.setattr(registry, "resolve_adapter", lambda c, u: AssetAdapter(scratch))
    ingest.run(cfg, "https://example.com/p")
    with pytest.raises(QuarryError, match="raw already exists"):
        ingest.run(cfg, "https://example.com/p")
    assert not scratch.exists()


def test_assets_layout_is_configurable(chtmp, monkeypatch, tmp_path):
    (chtmp / "quarry.toml").write_text('[ingest]\nassets_layout = "media/{source_id}"\n')
    c = config.load(chtmp)
    monkeypatch.setattr(registry, "resolve_adapter", lambda cf, u: AssetAdapter(tmp_path / "s"))
    m = ingest.run(c, "https://example.com/p")["manifest"]
    assert m["assets"][0] == "raw/media/P1/slide_01.jpg"


# --- discovery: ingest candidates ---------------------------------------------------


def test_keywords_ranks_distinctive_words():
    kws = discovery.keywords("The Atmos clock: clock runs on temperature #watch @jlc https://x.y")
    assert kws[0] == "clock"
    assert "the" not in kws and "watch" not in kws and "jlc" not in kws
    assert "temperature" in kws
    assert discovery.keywords("the brain's reserve, brain")[0] == "brain"


def test_prose_strips_quarry_scaffolding():
    raw = "# Title\n\n## On-screen text\n- **slide 01**: cerebellum facts\n[x.jpg](a/x.jpg)\n"
    prose = discovery._prose(raw)
    assert "slide" not in prose and "Title" not in prose and "jpg" not in prose
    assert "cerebellum facts" in prose


class FakeBackend:
    def __init__(self, search, hits):
        self.search = search
        self.hits = hits
        self.queries = []
        self.refreshed = False

    def available(self):
        return True

    def refresh(self, cwd=None):
        self.refreshed = True

    def query(self, text, cwd=None):
        self.queries.append(text)
        return self.hits.get(text, [])


def _wiki_article(root: Path, rel: str, title: str):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\ntitle: {title}\n---\n\nbody\n")


def test_ingest_candidates_bm25_sums_per_keyword(chtmp, monkeypatch):
    (chtmp / "quarry.toml").write_text(
        '[ingest]\nrelated_candidates = 2\n[discovery]\nsearch = "search"\nrefresh = true\n'
    )
    c = config.load(chtmp)
    _wiki_article(chtmp, "wiki/a.md", "Alpha")
    _wiki_article(chtmp, "wiki/b.md", "Beta")
    _wiki_article(chtmp, "wiki/c.md", "Gamma")
    be = FakeBackend("search", {
        "clock": [(50, "wiki/a.md"), (40, "wiki/b.md"), (90, "wiki/gone.md"),
                  (95, "wiki/index.md"), (30, "wiki/c.md")],
        "temperature": [(45, "wiki/b.md"), (20, "wiki/gone.md"), (60, "wiki/index.md")],
        "swiss": [(10, "wiki/a.md"), (5, "wiki/c.md")],
    })
    monkeypatch.setattr(discovery, "get_backend", lambda cfg: be)
    out = discovery.ingest_candidates(c, "clock temperature swiss", "")
    assert be.refreshed
    # index and missing files excluded; 2+ keyword matches required with 3 keywords
    assert [o["path"] for o in out] == ["wiki/b.md", "wiki/a.md"]
    assert out[0] == {"score": 85, "path": "wiki/b.md", "title": "Beta"}
    single = discovery.ingest_candidates(c, "clock", "")  # one keyword: one match suffices
    assert [o["path"] for o in single] == ["wiki/a.md", "wiki/b.md"]


def test_ingest_candidates_semantic_single_query(chtmp, monkeypatch):
    (chtmp / "quarry.toml").write_text("[ingest]\nrelated_candidates = 5\n")
    c = config.load(chtmp)
    _wiki_article(chtmp, "wiki/a.md", "Alpha")

    class Sem(FakeBackend):
        def query(self, text, cwd=None):
            self.queries.append(text)
            return [(70, "wiki/a.md"), (60, "wiki/a.md")]

    be = Sem("query", {})
    monkeypatch.setattr(discovery, "get_backend", lambda cfg: be)
    out = discovery.ingest_candidates(c, "Title", "body text")
    assert len(be.queries) == 1 and not be.refreshed
    assert out == [{"score": 70, "path": "wiki/a.md", "title": "Alpha"}]


def test_ingest_candidates_off_or_unavailable(cfg, chtmp, monkeypatch):
    assert discovery.ingest_candidates(cfg, "t", "c") == []  # related_candidates = 0
    (chtmp / "quarry.toml").write_text("[ingest]\nrelated_candidates = 3\n")
    assert discovery.ingest_candidates(config.load(chtmp), "t", "c") == []  # qmd absent


def test_qmd_backend_uses_configured_subcommand_and_refresh(monkeypatch):
    calls = []
    monkeypatch.setattr(discovery, "_run_qmd", lambda q, sub, text, cwd: calls.append(sub) or "")
    ran = []
    monkeypatch.setattr(discovery.subprocess, "run", lambda args, **k: ran.append(args))
    be = discovery.QmdBackend("/bin/qmd", "wiki", "search")
    be.query("x")
    be.refresh()
    assert calls == ["search"] and ran == [["/bin/qmd", "update"]]
    discovery.QmdBackend(None).refresh()  # no qmd: no-op
    assert discovery.NoneBackend().refresh() is None


def test_get_backend_passes_search_mode(chtmp, monkeypatch):
    (chtmp / "quarry.toml").write_text('[discovery]\nsearch = "vsearch"\n')
    monkeypatch.setattr(discovery, "find_qmd", lambda: "/bin/qmd")
    assert discovery.get_backend(config.load(chtmp)).search == "vsearch"


@pytest.mark.parametrize("toml,msg", [
    ('[discovery]\nsearch = "fuzzy"\n', "search"),
    ('[finish]\nstage = "some"\n', "stage"),
])
def test_new_enums_validated(chtmp, toml, msg):
    (chtmp / "quarry.toml").write_text(toml)
    with pytest.raises(ConfigError, match=msg):
        config.load(chtmp)


# --- finish: scoped staging, citation lookup, auto-index ----------------------------

SLUG = "2026-09-12_my-post"
RAW = "raw/2026/09/2026-09-12_my-post.md"
ASSET = "raw/2026/09/2026-09-12_my-post/slide_01.jpg"
ART = "wiki/tools/my-post.md"


def _git(root, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True)


def _store(root: Path, toml: str = "", target: str | None = ART) -> config.Config:
    (root / "quarry.toml").write_text("[store]\n" + toml)
    c = config.load(root)
    (root / RAW).parent.mkdir(parents=True, exist_ok=True)
    (root / RAW).write_text("raw\n")
    (root / "wiki").mkdir(exist_ok=True)
    (root / "wiki" / "index.md").write_text(
        "# Index\n\n## Tools\n\n- [Hammer](tools/hammer.md)\n- [Saw](tools/saw.md)\n\n"
        "## Food\n\n- [Soup](food/soup.md)\n"
    )
    for rel in ("wiki/tools/hammer.md", "wiki/tools/saw.md", "wiki/food/soup.md"):
        _wiki_article(root, rel, Path(rel).stem.title())
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@e.com")
    _git(root, "config", "user.name", "T")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    (root / RAW).write_text("raw v2\n")
    (root / ASSET).parent.mkdir(parents=True, exist_ok=True)
    (root / ASSET).write_text("img")
    m = manifest.build(slug=SLUG, source_url="https://x", adapter="fake", raw_path=RAW,
                       content="raw", target_wiki_path=target,
                       required_frontmatter=c.frontmatter.required, metadata={},
                       assets=[ASSET])
    manifest.write(c, SLUG, m)
    return c


def _article(root: Path, rel=ART, summary=""):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    extra = f"summary: {summary}\n" if summary else ""
    p.write_text(
        f"---\ntitle: My Post\n{extra}sources:\n  - {RAW}\n---\n\nSee [Hammer](hammer.md).\n"
    )


def test_finish_scoped_commits_only_this_ingest(tmp_path):
    c = _store(tmp_path)
    _article(tmp_path)
    (tmp_path / "wiki/tools/hammer.md").write_text(
        "---\ntitle: Hammer\n---\n\nbody\n\n- [My Post](my-post.md)\n")  # cross-link: in scope
    (tmp_path / "wiki/food/soup.md").write_text("---\ntitle: Soup\n---\n\nedited elsewhere\n")
    (tmp_path / "raw/2026/09/other-ingest.md").write_text("someone else's raw\n")
    res = finish.run(c, SLUG)
    assert res["committed"]
    assert res["staged"] == sorted([ART, RAW, ASSET, "wiki/tools/hammer.md"])
    left = _git(tmp_path, "status", "--porcelain").stdout
    assert "wiki/food/soup.md" in left and "other-ingest.md" in left


def test_finish_stage_all_sweeps_everything(tmp_path):
    c = _store(tmp_path, '[finish]\nstage = "all"\n')
    _article(tmp_path)
    (tmp_path / "wiki/food/soup.md").write_text("edited\n")
    assert finish.run(c, SLUG)["committed"]
    assert _git(tmp_path, "status", "--porcelain").stdout == ""


def test_finish_finds_article_by_citation(tmp_path):
    c = _store(tmp_path)
    _article(tmp_path, rel="wiki/tools/shorter-name.md")
    assert finish.run(c, SLUG)["article"] == "wiki/tools/shorter-name.md"


def test_finish_ambiguous_citation_errors(tmp_path):
    c = _store(tmp_path)
    _article(tmp_path, rel="wiki/tools/one.md")
    _article(tmp_path, rel="wiki/tools/two.md")
    with pytest.raises(QuarryError, match="several articles cite"):
        finish.run(c, SLUG)


def test_finish_no_target_and_no_citation(tmp_path):
    c = _store(tmp_path, target=None)
    with pytest.raises(QuarryError, match="no article path"):
        finish.run(c, SLUG)


def test_finish_explicit_missing_article(tmp_path):
    c = _store(tmp_path)
    with pytest.raises(QuarryError, match="wiki article not found: wiki/nope.md"):
        finish.run(c, SLUG, article="wiki/nope.md")


def test_finish_auto_index_places_entry_under_matching_heading(tmp_path):
    c = _store(tmp_path, "[finish]\nauto_index = true\n")
    _article(tmp_path, summary="a post about tools")
    res = finish.run(c, SLUG)
    assert res["indexed"]
    idx = (tmp_path / "wiki/index.md").read_text().splitlines()
    i = idx.index("- [My Post](tools/my-post.md) — a post about tools")
    assert idx[i - 1] == "- [Saw](tools/saw.md)" and "wiki/index.md" in res["staged"]
    assert not finish.add_index_entry(c, ART)  # already indexed -> no-op


def test_auto_index_appends_when_no_heading_matches(tmp_path):
    c = _store(tmp_path, "[finish]\nauto_index = true\n")
    _article(tmp_path, rel="wiki/new-topic/thing.md")
    assert finish.add_index_entry(c, "wiki/new-topic/thing.md")
    index = (tmp_path / "wiki/index.md").read_text()
    assert index.endswith("\n\n- [My Post](new-topic/thing.md)\n")


def test_auto_index_disabled_without_index(tmp_path):
    c = _store(tmp_path, '[lint]\nindex_file = ""\n')
    assert not finish.add_index_entry(c, ART)
    (tmp_path / "quarry.toml").write_text('[lint]\nindex_file = "missing.md"\n')
    assert not finish.add_index_entry(config.load(tmp_path), ART)


def test_finish_nothing_to_commit(tmp_path):
    c = _store(tmp_path)
    _article(tmp_path)
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "already")
    assert finish.run(c, SLUG)["committed"] is False


def test_changed_paths_handles_renames_and_deletes(tmp_path):
    _store(tmp_path)
    _git(tmp_path, "mv", "wiki/tools/saw.md", "wiki/tools/saw2.md")
    (tmp_path / "wiki/food/soup.md").unlink()
    got = git.changed_paths(tmp_path)
    assert "wiki/tools/saw2.md" in got and "wiki/tools/saw.md" not in got
    assert "wiki/food/soup.md" not in got and RAW in got
    assert git.commit_paths(tmp_path, [], "m") is False


# --- CLI output -----------------------------------------------------------------


def test_cli_ingest_prints_media_and_candidates(cfg, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(registry, "resolve_adapter", lambda c, u: AssetAdapter(tmp_path / "s"))
    monkeypatch.setattr(discovery, "ingest_candidates",
                        lambda c, t, b: [{"score": 80, "path": "wiki/a.md", "title": "Alpha"}])
    assert main(["ingest", "https://example.com/p"]) == 0
    out = capsys.readouterr().out
    assert "source date:      2026-09-12" in out
    assert "media (2):" in out and "raw/2026/09/2026-09-12_my-post/" in out
    assert "80  wiki/a.md  — Alpha" in out


def test_cli_finish_reports_index_and_files(tmp_path, monkeypatch, capsys):
    _store(tmp_path, "[finish]\nauto_index = true\n")
    _article(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert main(["finish", SLUG]) == 0
    out = capsys.readouterr().out
    assert "added to index.md" in out and "committed 4 file(s)" in out
