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


# --- groundedness: anti-fabrication / anti-cross-source-bleed ---------------

_RAW = (
    "---\nsource: https://youtu.be/x\n---\n\n"
    "We kick off with the winners. Rogue with a death trap build. "
    "Barbarian uses minions ancient summoner. Sorcerer wants firewall, "
    "and the frost and ice builds look strong.\n"
)


def _grounded_store(chtmp: Path, body: str, *, on: bool = True, sources: str | None = None):
    (chtmp / "quarry.toml").write_text(
        f"[lint]\ngroundedness = {'true' if on else 'false'}\n"
    )
    c = config.load(chtmp)
    _w(c.root / "raw" / "vid.md", _RAW)
    src = sources if sources is not None else "  - raw/vid.md"
    _w(c.root / "wiki" / "g.md", f"---\ntitle: G\nsources:\n{src}\n---\n\n{body}\n")
    return c


def test_groundedness_flags_foreign_named_terms(chtmp: Path):
    """A bolded name whose words are all absent from the cited raw is flagged."""
    body = (
        "**Death Trap** is great. **Minions / ancient summoner** dominate. "
        "The **frost (ice)** builds are fine. But **Mighty Throw** and "
        "**Signet of the Pelican** are not in the source. Also **not** emphasis."
    )
    r = lint.run(_grounded_store(chtmp, body))
    flagged = [t for _, t in r.ungrounded]
    assert "Mighty Throw" in flagged
    assert "Signet of the Pelican" in flagged
    # grounded / synthesised / emphasis terms are NOT flagged
    assert "Death Trap" not in flagged
    assert "Minions / ancient summoner" not in flagged
    assert "frost (ice)" not in flagged
    assert "not" not in flagged


def test_groundedness_off_by_default(chtmp: Path):
    r = lint.run(_grounded_store(chtmp, "**Mighty Throw** rules.", on=False))
    assert r.ungrounded == []


def test_groundedness_skips_when_no_text_source(chtmp: Path):
    """No readable text source (e.g. only a PDF) -> can't verify, don't flag."""
    r = lint.run(_grounded_store(chtmp, "**Mighty Throw** rules.", sources="  - raw/scan.pdf"))
    assert r.ungrounded == []


def test_groundedness_gateable_via_fail_on(chtmp: Path):
    r = lint.run(_grounded_store(chtmp, "**Mighty Throw** rules."))
    assert r.ungrounded  # something flagged
    assert r.fails(["groundedness"]) is True
    assert r.fails(["broken_links"]) is False


def test_groundedness_report_section(chtmp: Path):
    report = lint.run(_grounded_store(chtmp, "**Mighty Throw** rules.")).report
    assert "Ungrounded terms:" in report
    assert "UNGROUNDED TERMS" in report
    assert "Mighty Throw" in report


def test_groundedness_ignores_labels_sentences_and_single_words(chtmp: Path):
    """Bold used for labels / emphasis / sentences must NOT be treated as named terms."""
    body = (
        "**Status:** ok. **Heat exposure.** matters. **Print** the part. "
        "**No slicer involved** here. **Pairs with [Ridley](r.md)** somehow."
    )
    r = lint.run(_grounded_store(chtmp, body))
    assert r.ungrounded == []  # none are multi-word Title-Case names
