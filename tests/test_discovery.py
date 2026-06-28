"""Tests for discovery — ISC-61, 62, 63, 64, 65, 66, 67, 68, 69."""

from pathlib import Path

import pytest

from quarry import config, discovery
from quarry.cli import main
from quarry.errors import QuarryError

_QMD_OUT = """\
Results:
qmd://wiki/ai/alpha.md
  Score: 92%
qmd://wiki/ai/beta.md
  Score: 81%
qmd://wiki/misc/gamma.md
  Score: 40%
"""


class FakeBackend:
    def __init__(self, hits):
        self._hits = hits

    def available(self) -> bool:
        return True

    def query(self, text, cwd=None):
        return list(self._hits)


def _write(p: Path, body: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


# --- parsing (ISC-68) -------------------------------------------------------


def test_parse_qmd_hits():
    assert discovery.parse_qmd_hits(_QMD_OUT) == [
        (92, "wiki/ai/alpha.md"),
        (81, "wiki/ai/beta.md"),
        (40, "wiki/misc/gamma.md"),
    ]


def test_parse_qmd_hits_empty():
    assert discovery.parse_qmd_hits("nothing here\n") == []


# --- backend selection / availability (ISC-61, 62) --------------------------


def test_none_backend_unavailable():
    b = discovery.NoneBackend()
    assert b.available() is False
    assert b.query("x") == []


def test_check_disabled_when_backend_none(chtmp: Path):
    (chtmp / "quarry.toml").write_text('[discovery]\nbackend = "none"\n')
    _, status = discovery.check(config.load(chtmp))
    assert status == discovery.DISABLED


def test_check_missing_when_qmd_absent(cfg, monkeypatch):
    """ISC-61: qmd backend selected but tool absent -> MISSING."""
    monkeypatch.setattr(discovery, "find_qmd", lambda: None)
    _, status = discovery.check(cfg)
    assert status == discovery.MISSING


def test_check_ok_when_qmd_present(cfg, monkeypatch):
    monkeypatch.setattr(discovery, "find_qmd", lambda: "/fake/bin/qmd")
    backend, status = discovery.check(cfg)
    assert status == discovery.OK
    assert backend.available()


# --- dedup ------------------------------------------------------------------


def test_dedup_hits_filters_threshold(cfg, monkeypatch):
    monkeypatch.setattr(discovery, "find_qmd", lambda: "/fake/qmd")
    monkeypatch.setattr(
        discovery,
        "parse_qmd_hits",
        lambda out, collection="wiki": [(90, "wiki/a.md"), (50, "wiki/b.md")],
    )
    monkeypatch.setattr(discovery, "_run_qmd", lambda *a, **k: "")
    hits = discovery.dedup_hits(cfg, "Some Title")  # threshold default 85
    assert hits == [(90, "wiki/a.md")]


def test_dedup_hits_empty_when_unavailable(cfg, monkeypatch):
    monkeypatch.setattr(discovery, "find_qmd", lambda: None)
    assert discovery.dedup_hits(cfg, "x") == []


# --- related (ISC-63, 64) ---------------------------------------------------


def test_related_excludes_self_and_linked(cfg):
    wiki = cfg.root / "wiki"
    _write(wiki / "a.md", "---\ntitle: A\nrelated:\n  - b.md\n---\n\nbody of a\n")
    _write(wiki / "b.md", "---\ntitle: B\n---\n\nbody of b\n")
    _write(wiki / "c.md", "---\ntitle: C\n---\n\nbody of c\n")
    backend = FakeBackend([(90, "wiki/b.md"), (80, "wiki/c.md"), (70, "wiki/a.md")])
    fresh = discovery.related(cfg, "wiki/a.md", backend)
    assert fresh == [(80, "wiki/c.md")]  # self (a) + already-linked (b) excluded


def test_related_resolves_by_name_fragment(cfg):
    wiki = cfg.root / "wiki"
    _write(wiki / "topic" / "deep-note.md", "---\ntitle: Deep\n---\n\nbody\n")
    backend = FakeBackend([(50, "wiki/other.md")])
    fresh = discovery.related(cfg, "deep-note", backend)
    assert fresh == [(50, "wiki/other.md")]


# --- densify (ISC-65, 66, 67) -----------------------------------------------


def test_mutual_unlinked_pairs():
    nbrs = {
        "wiki/a.md": [(90, "wiki/b.md")],
        "wiki/b.md": [(88, "wiki/a.md")],
        "wiki/c.md": [(50, "wiki/a.md")],  # not mutual
    }
    links = {"wiki/a.md": set(), "wiki/b.md": set(), "wiki/c.md": set()}
    pairs = discovery.mutual_unlinked_pairs(nbrs, links)
    assert pairs == [(("wiki/a.md", "wiki/b.md"), 178)]


def test_densify_pairs_and_apply(cfg, monkeypatch):
    wiki = cfg.root / "wiki"
    _write(wiki / "a.md", "---\ntitle: A\n---\n\nbody a\n")
    _write(wiki / "b.md", "---\ntitle: B\n---\n\nbody b\n")

    def fake_query(text, cwd=None):
        # both articles list each other as top neighbour
        return [(90, "wiki/a.md"), (90, "wiki/b.md")]

    backend = FakeBackend([])
    monkeypatch.setattr(backend, "query", fake_query)
    pairs = discovery.densify_pairs(cfg, topk=6, backend=backend)
    assert pairs and pairs[0][0] == ("wiki/a.md", "wiki/b.md")

    added = discovery.apply_pairs(cfg, pairs)
    assert added == 2  # bidirectional
    assert "## See also" in (wiki / "a.md").read_text()
    assert "## See also" in (wiki / "b.md").read_text()
    # idempotent: re-applying adds nothing
    assert discovery.apply_pairs(cfg, pairs) == 0


def test_densify_topk_limits_neighbours(cfg, monkeypatch):
    """ISC-67: topk caps the neighbour list per article."""
    wiki = cfg.root / "wiki"
    _write(wiki / "a.md", "---\ntitle: A\n---\n\nbody\n")
    backend = FakeBackend([(90, "wiki/x.md"), (80, "wiki/y.md"), (70, "wiki/z.md")])
    captured = {}

    real = discovery.mutual_unlinked_pairs

    def spy(nbrs, links):
        captured["nbrs"] = nbrs
        return real(nbrs, links)

    monkeypatch.setattr(discovery, "mutual_unlinked_pairs", spy)
    discovery.densify_pairs(cfg, topk=2, backend=backend)
    assert len(captured["nbrs"]["wiki/a.md"]) == 2


# --- CLI graceful paths (ISC-62, 69) ----------------------------------------


def test_related_cli_disabled_exits_zero(chtmp: Path, capsys):
    (chtmp / "quarry.toml").write_text('[discovery]\nbackend = "none"\n')
    assert main(["related", "wiki/a.md"]) == 0
    assert "disabled" in capsys.readouterr().out


def test_related_cli_missing_qmd_exits_one(cfg, monkeypatch, capsys):
    """ISC-69: qmd configured but absent -> clean non-zero with install hint."""
    monkeypatch.setattr(discovery, "find_qmd", lambda: None)
    assert main(["related", "wiki/a.md"]) == 1
    assert "qmd not found" in capsys.readouterr().err


def test_densify_cli_missing_qmd_exits_one(cfg, monkeypatch, capsys):
    monkeypatch.setattr(discovery, "find_qmd", lambda: None)
    assert main(["densify"]) == 1
    assert "qmd not found" in capsys.readouterr().err


def test_related_cli_success(cfg, monkeypatch, capsys):
    _write(cfg.root / "wiki" / "a.md", "---\ntitle: A\n---\n\nbody\n")
    monkeypatch.setattr(discovery, "find_qmd", lambda: "/fake/qmd")
    monkeypatch.setattr(discovery, "_run_qmd", lambda *a, **k: _QMD_OUT)
    assert main(["related", "wiki/a.md"]) == 0
    assert "92%" in capsys.readouterr().out


def test_densify_cli_success_and_apply(cfg, monkeypatch, capsys):
    wiki = cfg.root / "wiki"
    _write(wiki / "a.md", "---\ntitle: A\n---\n\nbody a\n")
    _write(wiki / "b.md", "---\ntitle: B\n---\n\nbody b\n")
    out = "qmd://wiki/a.md\n  Score: 90%\nqmd://wiki/b.md\n  Score: 90%\n"
    monkeypatch.setattr(discovery, "find_qmd", lambda: "/fake/qmd")
    monkeypatch.setattr(discovery, "_run_qmd", lambda *a, **k: out)
    assert main(["densify"]) == 0
    assert "<->" in capsys.readouterr().out
    assert main(["densify", "--apply"]) == 0
    assert "## See also" in (wiki / "a.md").read_text()


def test_related_article_not_found(cfg):
    with pytest.raises(QuarryError, match="article not found"):
        discovery.related(cfg, "nonexistent-article", FakeBackend([]))
