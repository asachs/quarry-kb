"""Link relevance: a link is weak when neither article is near the other."""

from pathlib import Path

from quarry import config, relevance
from quarry.cli import main

TOPICS = {
    "bread": "sourdough starter flour hydration crumb oven loaf proofing gluten bake",
    "bikes": "derailleur cassette chainring cadence tyre saddle gravel frame spokes ride",
    "sql": "postgres index query planner vacuum transaction isolation join schema btree",
}


def _wiki(root: Path, extra_links: dict[str, list[str]] | None = None, per_topic=20):
    (root / "quarry.toml").write_text("[lint]\nlink_relevance = true\nweak_link_rank = 10\n")
    wiki = root / "wiki"
    for topic, words in TOPICS.items():
        (wiki / topic).mkdir(parents=True)
        vocab = words.split()
        for i in range(per_topic):
            name = f"{topic}/{topic}-{i:02d}.md"
            body = " ".join(vocab[(i + k) % len(vocab)] for k in range(8)) + f" note{i}"
            links = (extra_links or {}).get(name, [])
            rel = "".join(f"  - {x}\n" for x in links)
            see = "".join(f"- [see](../{x}) about {TOPICS[x.split('/')[0]]}\n" for x in links)
            (wiki / name).write_text(
                f"---\ntitle: {topic} {i}\nsources: []\nrelated:\n{rel or '  []'}\n---\n\n"
                f"{body}\n\n## See also\n\n{see}"
            )
    (wiki / "index.md").write_text("# index\n")
    return config.load(root)


def test_same_topic_link_is_fine_and_cross_topic_link_is_weak(chtmp: Path):
    cfg = _wiki(chtmp, {"bread/bread-00.md": ["bread/bread-01.md", "sql/sql-05.md"]})
    idx = relevance.build(cfg)
    assert idx.pair_rank("bread/bread-00.md", "bread/bread-01.md") <= 10
    assert idx.pair_rank("bread/bread-00.md", "sql/sql-05.md") > 10
    weak = relevance.weak_links(idx, 10)
    assert [(a, b) for _, a, b in weak] == [("bread/bread-00.md", "sql/sql-05.md")]


def test_a_links_own_description_does_not_make_the_pair_look_related(chtmp: Path):
    # the See-also line for the sql article repeats sql vocabulary inside the bread article
    cfg = _wiki(chtmp, {"bread/bread-00.md": ["sql/sql-05.md"]})
    idx = relevance.build(cfg)
    assert "postgres" not in idx.vectors["bread/bread-00.md"]
    assert idx.pair_rank("bread/bread-00.md", "sql/sql-05.md") > 10


def test_for_article_reports_direction_and_offers_only_mutual_neighbours(chtmp: Path):
    cfg = _wiki(
        chtmp,
        {"bread/bread-00.md": ["sql/sql-05.md"], "bikes/bikes-03.md": ["bread/bread-00.md"]},
    )
    idx = relevance.build(cfg)
    rep = relevance.for_article(idx, "bread/bread-00.md", 10)
    assert {(d, o) for _, d, o in rep["weak"]} == {
        ("out", "sql/sql-05.md"),
        ("in", "bikes/bikes-03.md"),
    }
    assert rep["closest_unlinked"] and all(c.startswith("bread/") for c in rep["closest_unlinked"])
    assert relevance.for_article(idx, "nope.md", 10) == {"weak": [], "closest_unlinked": []}


def test_index_file_and_unparseable_frontmatter_are_tolerated(chtmp: Path):
    cfg = _wiki(chtmp)
    (chtmp / "wiki" / "bread" / "broken.md").write_text('---\ntitle: "a\n---\nflour loaf oven\n')
    (chtmp / "wiki" / "bread" / "bare.md").write_text("flour loaf oven, no frontmatter\n")
    idx = relevance.build(cfg)
    assert "index.md" not in idx.vectors
    assert "bread/broken.md" in idx.vectors and "bread/bare.md" in idx.vectors
    assert relevance.wiki_rel(cfg, "wiki/bread/bare.md") == "bread/bare.md"
    assert relevance.wiki_rel(cfg, "bread/bare.md") == "bread/bare.md"


def test_cli_links_and_lint_summary(chtmp: Path, capsys):
    _wiki(chtmp, {"bread/bread-00.md": ["sql/sql-05.md", "bread/bread-01.md"]})
    assert main(["links"]) == 0
    out = capsys.readouterr().out
    assert "1 of 2 links rank beyond 10" in out and "bread/bread-00.md -> sql/sql-05.md" in out
    assert main(["links", "wiki/bread/bread-00.md"]) == 0
    out = capsys.readouterr().out
    assert "1 cross-link(s) look weak" in out and "links to wiki/sql/sql-05.md" in out
    assert "closest articles not linked" in out
    assert main(["links", "wiki/bread/bread-07.md"]) == 0
    assert "no weak links" in capsys.readouterr().out
    assert main(["links", "wiki/missing.md"]) == 1
    capsys.readouterr()
    assert main(["links", "--rank", "1000"]) == 0
    assert "0 of 2 links" in capsys.readouterr().out
    assert main(["links", "--limit", "0"]) == 0
    assert "1 more" in capsys.readouterr().out
    main(["lint"])
    assert "Weak links:            1" in capsys.readouterr().out
