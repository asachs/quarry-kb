"""YAML frontmatter parsing — the one place PyYAML is load-bearing.

Frontmatter sits on the provenance-verification critical path (``finish`` reads an
article's ``sources``), so it is parsed with a real YAML parser rather than a regex
reader. Malformed frontmatter degrades to an empty mapping — callers treat a missing
field as absent, never crash.
"""

from __future__ import annotations

import yaml


def parse(text: str) -> dict:
    """Return the leading ``---`` YAML block as a dict (``{}`` if absent/malformed)."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    block = text[3:end]
    try:
        data = yaml.safe_load(block)
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def problem(text: str) -> str | None:
    """Why ``parse`` would return ``{}`` for ``text`` — ``None`` if it parses cleanly.

    ``parse`` deliberately degrades to an empty mapping so callers never crash; the
    lint uses this to surface the silent degradation (an article whose ``sources`` or
    ``related`` quietly vanished because one line of YAML was malformed).
    """
    if not text.startswith("---"):
        return "no frontmatter block"
    end = text.find("\n---", 3)
    if end == -1:
        return "frontmatter block is not closed"
    try:
        data = yaml.safe_load(text[3:end])
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        what = getattr(e, "problem", None) or "invalid YAML"
        return f"{what} (frontmatter line {mark.line + 1})" if mark else str(what)
    if not isinstance(data, dict):
        return "frontmatter is not a key: value mapping"
    return None
