"""Tests for pending / status — what is captured but not compiled."""

import json
from pathlib import Path

from quarry import config, manifest, pending
from quarry.cli import main

URL = "https://www.instagram.com/reel/ABC123/?igsh=xyz"


def _store(root: Path) -> config.Config:
    (root / "quarry.toml").write_text("[store]\n")
    (root / "wiki" / "t").mkdir(parents=True)
    (root / "raw" / "2026" / "11").mkdir(parents=True)
    return config.load(root)


def _capture(cfg, slug: str, url: str, *, with_manifest=True) -> str:
    rel = f"raw/2026/11/{slug}.md"
    (cfg.root / rel).write_text(f"---\nsource: {url}\ndate: 2026-11-26\n---\n\nbody\n")
    if with_manifest:
        m = manifest.build(
            slug=slug,
            source_url=url,
            adapter="fake",
            raw_path=rel,
            content="body",
            target_wiki_path=None,
            required_frontmatter=cfg.frontmatter.required,
            metadata={},
        )
        manifest.write(cfg, slug, m)
    return rel


def _article(cfg, name: str, raw_rel: str) -> None:
    (cfg.root / "wiki" / "t" / name).write_text(
        f"---\ntitle: T\nsources:\n  - {raw_rel}\n---\n\ntext\n"
    )


def test_normalize_url_drops_share_noise_keeps_identity():
    n = pending.normalize_url
    assert n(URL) == n("https://instagram.com/reel/ABC123")
    assert n("http://Example.com/a/#frag") == "https://example.com/a"
    assert n("https://youtube.com/watch?v=1&si=zz") != n("https://youtube.com/watch?v=2")
    assert n("https://youtube.com/watch?v=1&si=zz") == n("https://www.youtube.com/watch?v=1")


def test_pending_lists_only_uncited_captures(chtmp: Path):
    cfg = _store(chtmp)
    done = _capture(cfg, "2026-11-26_done", "https://example.com/done")
    _capture(cfg, "2026-11-26_owed", URL)
    _article(cfg, "done.md", done)
    rows = pending.pending(cfg)
    assert [r["slug"] for r in rows] == ["2026-11-26_owed"]
    assert rows[0]["source_url"] == URL


def test_pending_ignores_manifest_whose_raw_is_gone(chtmp: Path):
    cfg = _store(chtmp)
    rel = _capture(cfg, "2026-11-26_gone", URL)
    (cfg.root / rel).unlink()
    assert pending.pending(cfg) == []


def test_pending_survives_bad_manifest_and_article(chtmp: Path):
    cfg = _store(chtmp)
    _capture(cfg, "2026-11-26_owed", URL)
    (manifest.manifest_path(cfg, "broken")).write_text("{not json")
    (cfg.root / "wiki" / "t" / "bad.md").write_text('---\ntitle: "a\n---\n')
    assert len(pending.pending(cfg)) == 1


def test_status_absent_captured_compiled(chtmp: Path):
    cfg = _store(chtmp)
    assert pending.status(cfg, URL)["state"] == pending.ABSENT
    rel = _capture(cfg, "2026-11-26_owed", URL)
    res = pending.status(cfg, "https://instagram.com/reel/ABC123/")
    assert res["state"] == pending.CAPTURED and res["slugs"] == ["2026-11-26_owed"]
    _article(cfg, "a.md", rel)
    res = pending.status(cfg, URL)
    assert res["state"] == pending.COMPILED and res["articles"] == ["wiki/t/a.md"]


def test_status_counts_a_raw_without_a_manifest(chtmp: Path):
    cfg = _store(chtmp)
    rel = _capture(cfg, "2026-11-26_by-hand", URL, with_manifest=False)
    res = pending.status(cfg, URL)
    assert res["state"] == pending.CAPTURED and res["raw_paths"] == [rel] and res["slugs"] == []
    (cfg.root / "raw" / "2026" / "11" / "nofm.md").write_text("no frontmatter\n")
    assert pending.status(cfg, "https://example.com/none")["state"] == pending.ABSENT


def test_cli_pending_and_status(chtmp: Path, capsys):
    cfg = _store(chtmp)
    assert main(["pending"]) == 0
    assert "nothing pending" in capsys.readouterr().out
    rel = _capture(cfg, "2026-11-26_owed", URL)
    assert main(["pending"]) == 0
    assert "2026-11-26_owed" in capsys.readouterr().out
    assert main(["pending", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["raw_path"] == rel
    assert main(["status", URL]) == 0
    assert capsys.readouterr().out.startswith("captured:")
    _article(cfg, "a.md", rel)
    assert main(["status", URL, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "compiled"
    assert main(["status", URL]) == 0
    assert "article: wiki/t/a.md" in capsys.readouterr().out
