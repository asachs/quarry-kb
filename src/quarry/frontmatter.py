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
