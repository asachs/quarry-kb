"""Tests for YAML frontmatter parsing."""

from quarry import frontmatter


def test_parses_scalars_and_lists():
    text = (
        "---\n"
        "title: Hello\n"
        "updated: 2026-06-28\n"
        "sources:\n  - raw/a.md\n  - raw/b.md\n"
        "related:\n  - wiki/x.md\n"
        "---\n\nbody\n"
    )
    fm = frontmatter.parse(text)
    assert fm["title"] == "Hello"
    assert fm["sources"] == ["raw/a.md", "raw/b.md"]
    assert fm["related"] == ["wiki/x.md"]


def test_inline_list():
    fm = frontmatter.parse('---\nsources: ["raw/a.md", "raw/b.md"]\n---\n\nx')
    assert fm["sources"] == ["raw/a.md", "raw/b.md"]


def test_no_frontmatter_returns_empty():
    assert frontmatter.parse("just a body, no fences\n") == {}


def test_unterminated_returns_empty():
    assert frontmatter.parse("---\ntitle: x\nno closing fence\n") == {}


def test_malformed_yaml_returns_empty():
    # unbalanced bracket -> YAMLError -> {}
    assert frontmatter.parse("---\nsources: [unclosed\n---\n\nbody") == {}


def test_non_mapping_returns_empty():
    # a top-level list is valid YAML but not a frontmatter mapping
    assert frontmatter.parse("---\n- a\n- b\n---\n\nbody") == {}
