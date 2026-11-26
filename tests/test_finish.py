"""Tests for finish — ISC-41, 42, 43, 44, 45, 46, 47, 48."""

import subprocess
from pathlib import Path

import pytest

from quarry import config, finish, git, manifest
from quarry.cli import main
from quarry.errors import QuarryError

SLUG = "2026-06-28_my-title"
RAW_REL = "raw/2026/06/2026-06-28_my-title.md"
TARGET = "wiki/ai/my-title.md"


def _build_store(root: Path, *, target=TARGET, with_git=True) -> config.Config:
    (root / "quarry.toml").write_text("[store]\n")
    cfg = config.load(root)
    raw = root / RAW_REL
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text("raw content\n")
    (root / "wiki").mkdir(exist_ok=True)
    m = manifest.build(
        slug=SLUG,
        source_url="https://example.com/x",
        adapter="fake",
        raw_path=RAW_REL,
        content="raw content",
        target_wiki_path=target,
        required_frontmatter=cfg.frontmatter.required,
        metadata={},
    )
    manifest.write(cfg, SLUG, m)
    if with_git:
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.email", "t@e.com"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=root, check=True)
    return cfg


def _write_article(cfg, *, cite=RAW_REL, body="Article body.\n"):
    art = cfg.root / TARGET
    art.parent.mkdir(parents=True, exist_ok=True)
    art.write_text(f"---\ntitle: My Title\nsources:\n  - {cite}\n---\n\n{body}")


@pytest.fixture
def store(tmp_path: Path):
    return _build_store(tmp_path)


def test_finish_commits_without_push(store, monkeypatch):
    """ISC-45/46/47: commit happens, no push, message from template."""
    _write_article(store)
    pushed = {"n": 0}
    monkeypatch.setattr(git, "push", lambda root: pushed.__setitem__("n", pushed["n"] + 1))
    res = finish.run(store, SLUG)
    assert res["committed"] is True and res["pushed"] is False
    assert pushed["n"] == 0
    msg = subprocess.run(
        ["git", "log", "-1", "--format=%s"], cwd=store.root, capture_output=True, text=True
    ).stdout.strip()
    assert msg == f"wiki: {SLUG}"  # commit_template


def test_finish_pushes_when_opted_in(store, monkeypatch):
    """ISC-46: --push triggers a push."""
    _write_article(store)
    pushed = {"n": 0}
    monkeypatch.setattr(git, "push", lambda root: pushed.__setitem__("n", pushed["n"] + 1))
    res = finish.run(store, SLUG, push=True)
    assert res["pushed"] is True and pushed["n"] == 1


def test_finish_missing_article(store):
    """ISC-41: no article written -> abort."""
    with pytest.raises(QuarryError, match="wiki article not found"):
        finish.run(store, SLUG)


def test_finish_no_article_path(tmp_path: Path):
    """ISC-41: manifest without a target and no --article -> abort."""
    cfg = _build_store(tmp_path, target=None)
    with pytest.raises(QuarryError, match="no article path"):
        finish.run(cfg, SLUG)


def test_finish_provenance_failure(store):
    """ISC-42: article that doesn't cite the source is rejected."""
    _write_article(store, cite="raw/something-else.md")
    with pytest.raises(QuarryError, match="provenance check failed"):
        finish.run(store, SLUG)


def test_finish_aborts_on_lint_failure(store):
    """ISC-43/44: a broken link makes lint fail, aborting finish."""
    _write_article(store, body="[x](ghost.md)\n")
    with pytest.raises(QuarryError, match="lint failed"):
        finish.run(store, SLUG)


def test_finish_missing_manifest(store):
    """ISC-30/41: unknown slug -> clean error."""
    with pytest.raises(QuarryError, match="no compile-manifest"):
        finish.run(store, "ghost-slug")


def test_finish_non_git_graceful(tmp_path: Path):
    """ISC-48: a non-git store skips commit without crashing."""
    cfg = _build_store(tmp_path, with_git=False)
    _write_article(cfg)
    res = finish.run(cfg, SLUG)
    assert res["committed"] is False


def test_finish_via_cli(store, monkeypatch, capsys):
    _write_article(store)
    monkeypatch.setattr(git, "push", lambda root: None)
    monkeypatch.chdir(store.root)
    assert main(["finish", SLUG]) == 0
    assert "provenance verified" in capsys.readouterr().out


# --- auto_verification (0.8.0) -------------------------------------------------


def _visual_finish_store(root: Path, extra_fm: str = "", *, auto: bool = True) -> config.Config:
    cfg = _build_store(root)
    (root / "quarry.toml").write_text(
        f"[store]\n[finish]\nauto_verification = {'true' if auto else 'false'}\n"
        '[lint]\nverification_check = true\nfail_on = ["verification"]\n'
    )
    cfg = config.load(root)
    frames = (root / RAW_REL).with_suffix("")
    frames.mkdir()
    (frames / "frame_0m00s.jpg").write_text("x")
    art = root / TARGET
    art.parent.mkdir(parents=True, exist_ok=True)
    art.write_text(
        f"---\ntitle: T\nupdated: 2026-06-28\nsources:\n  - {RAW_REL}\n"
        f"related: []\n{extra_fm}---\n\n# T\n\nBody.\n"
    )
    return cfg


def test_finish_marks_visual_source_article_unverified(tmp_path: Path):
    cfg = _visual_finish_store(tmp_path)
    res = finish.run(cfg, SLUG)
    text = (tmp_path / TARGET).read_text()
    assert res["marked_unverified"] is True and res["committed"] is True
    assert "related: []\nverification: unverified\n---\n\n# T" in text
    shown = subprocess.run(
        ["git", "show", f"HEAD:{TARGET}"], cwd=tmp_path, capture_output=True, text=True
    ).stdout
    assert "verification: unverified" in shown  # the stamp is part of the commit


def test_finish_never_overwrites_an_existing_status(tmp_path: Path):
    fm = "verification: verified\nverified_on: 2026-06-28\nverified_by: me\n"
    cfg = _visual_finish_store(tmp_path, fm)
    res = finish.run(cfg, SLUG)
    assert res["marked_unverified"] is False
    assert (tmp_path / TARGET).read_text().count("verification:") == 1


def test_finish_leaves_text_only_sources_alone(tmp_path: Path):
    cfg = _visual_finish_store(tmp_path)
    (tmp_path / RAW_REL).with_suffix("").joinpath("frame_0m00s.jpg").unlink()
    assert finish.run(cfg, SLUG)["marked_unverified"] is False
    assert "verification" not in (tmp_path / TARGET).read_text()


def test_finish_without_auto_verification_fails_the_gate(tmp_path: Path):
    cfg = _visual_finish_store(tmp_path, auto=False)
    with pytest.raises(QuarryError, match="1 verification"):
        finish.run(cfg, SLUG)


def test_finish_cli_explains_the_stamp(tmp_path: Path, monkeypatch, capsys):
    _visual_finish_store(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert main(["finish", SLUG]) == 0
    out = capsys.readouterr().out
    assert "marked `verification: unverified`" in out and "verified_on" in out
