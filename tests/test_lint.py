"""Tests for lint — ISC-49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60."""

from pathlib import Path

from quarry import config, lint
from quarry.cli import main

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "lint_store"
GOLDEN = Path(__file__).resolve().parent / "fixtures" / "lint_report.golden.txt"


def _w(path: Path, body: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


# --- golden (ISC-60) --------------------------------------------------------


def test_golden_report():
    cfg = config.load(FIXTURE)
    assert lint.run(cfg).report == GOLDEN.read_text()


# --- individual checks against the fixture ----------------------------------


def test_fixture_detects_issues():
    """ISC-49/50/51/58: structured result lists the right issues."""
    r = lint.run(config.load(FIXTURE))
    assert r.broken == [("ai/alpha.md", "ai/ghost.md")]  # ISC-49
    assert r.missing == [("ai/beta.md", "raw/missing.md")]  # ISC-50
    assert r.orphans == ["misc/gamma.md"]  # ISC-51
    assert r.not_indexed == ["ai/beta.md", "misc/gamma.md"]  # ISC-55
    assert r.total_articles == 3


def test_report_has_density_top_and_category():
    """ISC-52/53/54: density, top-connected, and category health appear."""
    report = lint.run(config.load(FIXTURE)).report
    assert "Avg outgoing links:" in report  # ISC-52
    assert "--- TOP CONNECTED ---" in report  # ISC-53
    assert "--- CATEGORY HEALTH ---" in report  # ISC-54


# --- ISC-51: frontmatter related does NOT create inbound --------------------


def test_orphans_are_body_inbound_only(cfg):
    wiki = cfg.root / "wiki"
    _w(wiki / "a.md", "---\ntitle: A\nrelated:\n  - b.md\n---\n\nbody, no links\n")
    _w(wiki / "b.md", "---\ntitle: B\n---\n\nbody\n")
    r = lint.run(cfg)
    # a's `related: [b.md]` must NOT save b from being an orphan
    assert "b.md" in r.orphans
    assert "a.md" in r.orphans


# --- ISC-56: index_file = "" disables the not-in-index check -----------------


def test_empty_index_disables_check(chtmp: Path):
    (chtmp / "quarry.toml").write_text('[lint]\nindex_file = ""\n')
    c = config.load(chtmp)
    _w(c.root / "wiki" / "a.md", "---\ntitle: A\n---\n\nbody\n")
    assert lint.run(c).not_indexed == []


# --- ISC-59: each check is toggleable ---------------------------------------


def test_broken_check_toggleable(chtmp: Path):
    (chtmp / "quarry.toml").write_text("[lint]\nbroken_links = false\n")
    c = config.load(chtmp)
    _w(c.root / "wiki" / "a.md", "---\ntitle: A\n---\n\n[X](ghost.md)\n")
    assert lint.run(c).broken == []


def test_sources_check_toggleable(chtmp: Path):
    (chtmp / "quarry.toml").write_text("[lint]\nrequire_sources_on_disk = false\n")
    c = config.load(chtmp)
    _w(c.root / "wiki" / "a.md", "---\ntitle: A\nsources:\n  - raw/gone.md\n---\n\nbody\n")
    assert lint.run(c).missing == []


# --- ISC-57: fail_on drives the verdict + CLI exit code ---------------------


def test_fails_respects_fail_on():
    r = lint.run(config.load(FIXTURE))
    assert r.fails(["broken_links"]) is True
    assert r.fails(["missing_sources"]) is True
    assert r.fails([]) is False
    assert r.fails(["orphans"]) is True


def test_lint_cli_exit_nonzero_on_failure(chtmp: Path, capsys):
    (chtmp / "quarry.toml").write_text(
        '[lint]\nfail_on = ["broken_links"]\n'
    )
    c = config.load(chtmp)
    _w(c.root / "wiki" / "a.md", "---\ntitle: A\n---\n\n[X](ghost.md)\n")
    assert main(["lint"]) == 1
    assert "BROKEN LINKS" in capsys.readouterr().out


def test_lint_cli_exit_zero_when_clean(chtmp: Path):
    (chtmp / "quarry.toml").write_text('[lint]\nfail_on = ["broken_links"]\n')
    c = config.load(chtmp)
    _w(c.root / "wiki" / "a.md", "---\ntitle: A\n---\n\nclean body\n")
    assert main(["lint"]) == 0
