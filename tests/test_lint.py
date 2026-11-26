"""Tests for lint — ISC-49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 101, 102, 103."""

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


# --- ISC-103: dated raw captures must follow [store] raw_layout -------------


def test_misfiled_raw_detects_loose_dated_captures(cfg):
    """A dated capture in the raw root is flagged when the layout nests by year/month."""
    _w(cfg.root / "raw" / "2026-08-18_loose-capture.md", "x\n")
    _w(cfg.root / "raw" / "2026" / "08" / "2026-08-18_filed.md", "x\n")
    _w(cfg.root / "raw" / "notebooklm-undated.md", "x\n")
    _w(cfg.root / "raw" / "apple-notes" / "Some Note.md", "x\n")
    _w(cfg.root / "wiki" / "a.md", "---\ntitle: A\n---\n\nbody\n")
    r = lint.run(cfg)
    assert r.misfiled_raw == ["raw/2026-08-18_loose-capture.md"]
    assert "--- MISFILED RAW" in r.report


def test_misfiled_raw_silent_on_flat_layout(chtmp: Path):
    """A flat raw_layout means loose files are correct — nothing to flag."""
    (chtmp / "quarry.toml").write_text('[store]\nraw_layout = "{slug}.{ext}"\n')
    c = config.load(chtmp)
    _w(c.root / "raw" / "2026-08-18_loose-capture.md", "x\n")
    _w(c.root / "wiki" / "a.md", "---\ntitle: A\n---\n\nbody\n")
    assert lint.run(c).misfiled_raw == []


def test_misfiled_raw_toggleable(chtmp: Path):
    (chtmp / "quarry.toml").write_text("[lint]\nraw_layout = false\n")
    c = config.load(chtmp)
    _w(c.root / "raw" / "2026-08-18_loose-capture.md", "x\n")
    _w(c.root / "wiki" / "a.md", "---\ntitle: A\n---\n\nbody\n")
    assert lint.run(c).misfiled_raw == []


# --- ISC-101: only scheme-qualified targets are treated as external ----------


def test_http_prefixed_filename_is_a_local_link(cfg):
    """A relative link to `http-status-codes.md` is local, not an external URL."""
    wiki = cfg.root / "wiki"
    _w(wiki / "web.md", "---\ntitle: Web\n---\n\nsee [Codes](http-status-codes.md)\n")
    _w(wiki / "http-status-codes.md", "---\ntitle: Codes\n---\n\nbody\n")
    r = lint.run(cfg)
    assert "http-status-codes.md" not in r.orphans
    assert "web.md" not in r.no_outgoing
    assert r.broken == []


def test_real_external_urls_are_still_skipped(cfg):
    """http://, https://, mailto: and anchors stay out of the link graph."""
    wiki = cfg.root / "wiki"
    body = (
        "---\ntitle: A\n---\n\n"
        "[x](https://example.com/a.md) [y](http://example.com/b.md) "
        "[z](mailto:a@example.com) [w](#section)\n"
    )
    _w(wiki / "a.md", body)
    r = lint.run(cfg)
    assert r.broken == []
    assert "a.md" in r.no_outgoing


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


# --- ISC-102: inflection and directory sources ------------------------------


def test_groundedness_matches_across_inflection(chtmp: Path):
    """`Firewall Builds` is grounded by a source saying "firewall ... builds look strong"."""
    body = "**Firewall Build** matters. **Ancient Summoners** too. **Mighty Throw** does not."
    r = lint.run(_grounded_store(chtmp, body))
    flagged = [t for _, t in r.ungrounded]
    assert "Firewall Build" not in flagged
    assert "Ancient Summoners" not in flagged  # source has "ancient summoner"
    assert "Mighty Throw" in flagged  # genuinely absent — still caught


def test_groundedness_reads_directory_sources(chtmp: Path):
    """A cited directory contributes the words of the text files inside it."""
    (chtmp / "quarry.toml").write_text("[lint]\ngroundedness = true\n")
    c = config.load(chtmp)
    _w(c.root / "raw" / "notes" / "a.md", "The Pelican Signet was handed over.\n")
    _w(c.root / "raw" / "notes" / "b.txt", "Mighty Throw appears here.\n")
    _w(
        c.root / "wiki" / "g.md",
        "---\ntitle: G\nsources:\n  - raw/notes/\n---\n\n"
        "**Signet of the Pelican** and **Mighty Throw** and **Absent Relic**.\n",
    )
    flagged = [t for _, t in lint.run(c).ungrounded]
    assert "Signet of the Pelican" not in flagged
    assert "Mighty Throw" not in flagged
    assert "Absent Relic" in flagged


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


# --- related / frontmatter / wikilinks (0.7.0) --------------------------------


def _art(c, rel: str, fm: str, body: str = "Body.\n"):
    _w(c.root / "wiki" / rel, f"---\n{fm}\n---\n\n{body}")


def test_related_entries_must_resolve_under_wiki_root(cfg):
    _art(cfg, "a/one.md", "title: One")
    _w(cfg.root / "wiki" / "b" / "keep.md", "x")
    _art(
        cfg,
        "a/two.md",
        "title: Two\nrelated:\n"
        "  - a/one.md\n"  # ok
        "  - b/\n"  # ok: an existing wiki folder
        "  - wiki/a/one.md\n"
        "  - ../a/one.md\n"
        "  - one.md\n"
        "  - a/one\n"
        "  - '[One](a/one.md)'\n"
        "  - nope/\n"
        "  - 7",
    )
    bad = [e for a, e in lint.run(cfg).bad_related if a == "a/two.md"]
    assert bad == sorted(
        ["wiki/a/one.md", "../a/one.md", "one.md", "a/one", "[One](a/one.md)", "nope/", "7"]
    )


def test_related_accepts_a_single_string_and_inline_list(cfg):
    _art(cfg, "a/one.md", "title: One\nrelated: a/two.md")
    _art(cfg, "a/two.md", "title: Two\nrelated: [a/one.md, wiki/a/one.md]")
    assert lint.run(cfg).bad_related == [("a/two.md", "wiki/a/one.md")]


def test_related_check_toggleable_and_gateable(chtmp: Path):
    _w(chtmp / "quarry.toml", '[lint]\nrelated_check = false\nfail_on = ["related"]\n')
    c = config.load(chtmp)
    _art(c, "a.md", "title: A\nrelated:\n  - ghost.md")
    r = lint.run(c)
    assert r.bad_related == [] and not r.fails(c.lint.fail_on)
    _w(chtmp / "quarry.toml", '[lint]\nfail_on = ["related"]\n')
    c = config.load(chtmp)
    r = lint.run(c)
    assert r.bad_related == [("a.md", "ghost.md")]
    assert r.fails(c.lint.fail_on) and r.summary(c.lint.fail_on) == "1 related"
    assert "--- UNRESOLVED RELATED" in r.report and "  a.md -> ghost.md" in r.report


def test_bad_frontmatter_is_reported_not_swallowed(cfg):
    _art(cfg, "ok.md", "title: OK")
    _w(cfg.root / "wiki" / "none.md", "Just text.\n")
    _w(cfg.root / "wiki" / "open.md", "---\ntitle: Open\n\nNever closed.\n")
    _w(cfg.root / "wiki" / "list.md", "---\n- a\n- b\n---\n\nBody.\n")
    _art(cfg, "stray.md", "title: Stray\nupdated: 2026-01-01\nx\n  - raw/a.md\nrelated:\n  - ok.md")
    _art(cfg, "quote.md", 'title: Q\nsummary: "he said "hi" to them"')
    got = dict(lint.run(cfg).bad_frontmatter)
    assert set(got) == {"none.md", "open.md", "list.md", "stray.md", "quote.md"}
    assert got["none.md"] == "no frontmatter block"
    assert got["open.md"] == "frontmatter block is not closed"
    assert got["list.md"] == "frontmatter is not a key: value mapping"
    assert "frontmatter line" in got["stray.md"] and "frontmatter line" in got["quote.md"]


def test_frontmatter_check_toggleable_and_gateable(chtmp: Path):
    _w(chtmp / "quarry.toml", '[lint]\nfail_on = ["frontmatter"]\n')
    c = config.load(chtmp)
    _w(c.root / "wiki" / "none.md", "Just text.\n")
    r = lint.run(c)
    assert r.fails(c.lint.fail_on)
    assert "Bad frontmatter:       1" in r.report and "--- BAD FRONTMATTER" in r.report
    _w(chtmp / "quarry.toml", "[lint]\nfrontmatter_check = false\n")
    assert lint.run(config.load(chtmp)).bad_frontmatter == []


def test_wikilinks_counted_outside_code(cfg):
    _art(
        cfg,
        "w.md",
        "title: W\nsummary: 'frontmatter [[not-counted]]'",
        "See [[other-article]] and [[folder/thing|Thing]].\n\n"
        "The syntax is `[[like this]]`.\n\n```\n[[in-a-fence]]\n```\n\n"
        "~~~text\n[[tilde-fence]]\n~~~\n\nA nested list [[1, 2], [3]] is not one.\n",
    )
    _art(cfg, "clean.md", "title: Clean", "A [real](w.md) link.\n")
    r = lint.run(cfg)
    assert r.wikilinks == [("w.md", 2)]
    assert "Wikilinks:             2" in r.report and "    2  w.md" in r.report


def test_wikilinks_toggleable_and_gateable(chtmp: Path):
    _w(chtmp / "quarry.toml", '[lint]\nfail_on = ["wikilinks"]\n')
    c = config.load(chtmp)
    _art(c, "w.md", "title: W", "[[x]]\n")
    assert lint.run(c).fails(c.lint.fail_on)
    _w(chtmp / "quarry.toml", "[lint]\nwikilinks = false\n")
    assert lint.run(config.load(chtmp)).wikilinks == []


def test_orphan_report_says_when_a_related_backlink_exists(cfg):
    _art(cfg, "hub.md", "title: Hub\nrelated:\n  - lonely.md\n  - hub.md", "[Other](other.md)\n")
    _art(cfg, "other.md", "title: Other\nrelated:\n  - lonely.md", "[Hub](hub.md)\n")
    _art(cfg, "lonely.md", "title: Lonely")
    _art(cfg, "island.md", "title: Island")
    r = lint.run(cfg)
    assert r.orphans == ["island.md", "lonely.md"]
    assert r.orphan_related == {"island.md": 0, "lonely.md": 2}
    assert "  lonely.md  (in 2 related: lists, no body link)" in r.report
    assert "  island.md\n" in r.report


def test_orphan_related_singular(cfg):
    _art(cfg, "hub.md", "title: Hub\nrelated:\n  - lonely.md")
    _art(cfg, "lonely.md", "title: Lonely")
    assert "  lonely.md  (in 1 related: list, no body link)" in lint.run(cfg).report


def test_clean_store_report_has_no_new_sections(cfg):
    _art(cfg, "a.md", "title: A\nrelated:\n  - b.md", "[B](b.md)\n")
    _art(cfg, "b.md", "title: B\nrelated:\n  - a.md", "[A](a.md)\n")
    r = lint.run(cfg)
    assert (r.bad_related, r.bad_frontmatter, r.wikilinks) == ([], [], [])
    for marker in ("Bad frontmatter", "Unresolved related", "Wikilinks", "related: list"):
        assert marker not in r.report


def test_groundedness_matches_hashtags_and_handles(chtmp: Path):
    """`**Bambu Lab**` is grounded by `#bambulab`; `**Chapter One**` by an @handle."""
    c = _grounded_store(chtmp, "Printed on a **Bambu Lab** at **Chapter One**. **Prusa Core** no.")
    _w(c.root / "raw" / "vid.md", "great print #bambulab #makerworld @chapterone_dublin\n")
    assert [t for _, t in lint.run(c).ungrounded] == ["Prusa Core"]


def test_groundedness_matches_short_token_names_as_a_phrase(chtmp: Path):
    """A name with no content words (`NW-L1 V2`) is matched as a phrase, not flagged."""
    c = _grounded_store(chtmp, "The **NW-L1 V2** scanner, not the **XQ-9 Z3**.")
    _w(c.root / "raw" / "vid.md", "The NW-L1 V2 build package is out.\n")
    assert [t for _, t in lint.run(c).ungrounded] == ["XQ-9 Z3"]


def test_groundedness_glued_match_needs_a_real_name(chtmp: Path):
    """Short glued strings don't ground on a coincidental substring of a tag."""
    c = _grounded_store(chtmp, "**Go Up** now.")
    _w(c.root / "raw" / "vid.md", "nothing relevant #lineageoupdate\n")
    assert [t for _, t in lint.run(c).ungrounded] == ["Go Up"]


# --- verification status for visual sources (0.8.0) ---------------------------


def _visual_store(chtmp: Path, fm_extra: str = "", *, check: bool = True, fail: bool = False):
    _w(
        chtmp / "quarry.toml",
        f"[lint]\nverification_check = {'true' if check else 'false'}\n"
        + ('fail_on = ["verification"]\n' if fail else ""),
    )
    c = config.load(chtmp)
    _w(c.root / "raw" / "reel.md", "caption\n")
    _w(c.root / "raw" / "reel" / "frame_0m00s.JPG", "x")
    _w(c.root / "raw" / "plain.md", "text only\n")
    _w(c.root / "raw" / "notes" / "a.txt", "a directory with no images\n")
    _w(c.root / "raw" / "notes.md", "text\n")
    _w(c.root / "wiki" / "v.md", f"---\ntitle: V\nsources:\n  - raw/reel.md\n{fm_extra}---\n\nB.\n")
    plain = "---\ntitle: P\nsources:\n  - raw/plain.md\n  - raw/notes.md\n---\n\nB.\n"
    _w(c.root / "wiki" / "p.md", plain)
    return c


def test_visual_sources_are_those_with_images_beside_them(chtmp: Path):
    c = _visual_store(chtmp)
    assert lint.visual_sources(c.root / "wiki" / "v.md", c) == ["raw/reel.md"]
    assert lint.visual_sources(c.root / "wiki" / "p.md", c) == []


def test_verification_missing_status_is_flagged_only_for_visual_sources(chtmp: Path):
    r = lint.run(_visual_store(chtmp))
    assert [a for a, _ in r.bad_verification] == ["v.md"]
    assert "start at `unverified`" in r.bad_verification[0][1]
    assert "--- VERIFICATION STATUS" in r.report and "Verification status:   1" in r.report


def test_verification_unverified_passes_and_is_counted(chtmp: Path):
    r = lint.run(_visual_store(chtmp, "verification: unverified\n"))
    assert r.bad_verification == [] and r.unverified == ["v.md"]
    assert "Unverified (visual):   1" in r.report and "--- VERIFICATION STATUS" not in r.report


def test_verification_verified_needs_a_record(chtmp: Path):
    r = lint.run(_visual_store(chtmp, "verification: verified\nverified_on: 2026-11-26\n"))
    assert r.bad_verification == [("v.md", "verified without a record (verified_by missing)")]
    ok = "verification: verified\nverified_on: 2026-11-26\nverified_by: frame audit\n"
    r = lint.run(_visual_store(chtmp, ok))
    assert r.bad_verification == [] and r.unverified == []


def test_verification_rejects_unknown_status(chtmp: Path):
    r = lint.run(_visual_store(chtmp, "verification: probably\n"))
    assert "is not one of unverified, verified" in r.bad_verification[0][1]


def test_verification_off_by_default_and_gateable(chtmp: Path):
    assert lint.run(_visual_store(chtmp, check=False)).bad_verification == []
    c = _visual_store(chtmp, fail=True)
    r = lint.run(c)
    assert r.fails(c.lint.fail_on) and r.summary(c.lint.fail_on) == "1 verification"
