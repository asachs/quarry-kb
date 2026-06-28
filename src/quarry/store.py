"""Store paths & templating — turns Config conventions into concrete paths.

The store root is discovered when the Config is loaded (walk-up to ``quarry.toml``).
This module resolves the wiki / raw / manifest directories beneath it and renders
the ``raw_layout`` and ``slug`` templates from their configured token sets. No
convention is hardcoded here — every value comes from the threaded Config.
"""

from __future__ import annotations

import datetime as _dt
import re
import unicodedata
from pathlib import Path

from quarry.config import Config
from quarry.errors import ConfigError

# Tokens available to the path/slug templates (documented in quarry.toml).
PATH_TOKENS = (
    "year",
    "month",
    "date",
    "slug",
    "kebab_title",
    "ext",
    "topic",
    "source_id",
)


def slugify(text: str) -> str:
    """ASCII kebab-case slug. Empty input collapses to ``untitled``."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    text = re.sub(r"[\s_-]+", "-", text)
    return text.strip("-") or "untitled"


# ---------------------------------------------------------------------------
# Directory resolution (all beneath the discovered store root)
# ---------------------------------------------------------------------------


def wiki_dir(cfg: Config) -> Path:
    return cfg.root / cfg.store.wiki


def raw_dir(cfg: Config) -> Path:
    return cfg.root / cfg.store.raw


def manifest_dir(cfg: Config) -> Path:
    return cfg.root / cfg.store.manifest_dir


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------


def _base_tokens(
    date: _dt.date,
    title: str,
    ext: str,
    topic: str | None,
    source_id: str | None,
) -> dict[str, str]:
    return {
        "year": f"{date:%Y}",
        "month": f"{date:%m}",
        "date": f"{date:%Y-%m-%d}",
        "kebab_title": slugify(title),
        "ext": ext,
        "topic": topic or "",
        "source_id": source_id or "",
    }


def _render(template: str, tokens: dict[str, str], what: str) -> str:
    try:
        return template.format(**tokens)
    except KeyError as e:
        bad = e.args[0]
        raise ConfigError(
            f"{what}: unknown token {{{bad}}} (valid: {', '.join(sorted(tokens))})"
        ) from e
    except (IndexError, ValueError) as e:
        raise ConfigError(f"{what}: malformed template {template!r} — {e}") from e


def make_slug(
    cfg: Config,
    *,
    title: str,
    date: _dt.date,
    ext: str | None = None,
    topic: str | None = None,
    source_id: str | None = None,
) -> str:
    """Render the configured ``[ingest] slug`` template.

    The ``{slug}`` token is intentionally absent from the slug's own token set —
    a slug template that references ``{slug}`` is a config error, not a recursion.
    """
    ext = ext or cfg.ingest.default_ext
    tokens = _base_tokens(date, title, ext, topic, source_id)
    return _render(cfg.ingest.slug, tokens, "[ingest] slug")


def make_raw_path(
    cfg: Config,
    *,
    title: str,
    date: _dt.date,
    slug: str,
    ext: str | None = None,
    topic: str | None = None,
    source_id: str | None = None,
) -> Path:
    """Absolute path for a raw file, per ``[store] raw_layout`` (relative to raw/)."""
    ext = ext or cfg.ingest.default_ext
    tokens = _base_tokens(date, title, ext, topic, source_id)
    tokens["slug"] = slug
    rel = _render(cfg.store.raw_layout, tokens, "[store] raw_layout")
    return raw_dir(cfg) / rel


def raw_relpath(cfg: Config, raw_abs: Path) -> str:
    """The raw path relative to the store root (as stored in the manifest)."""
    return raw_abs.relative_to(cfg.root).as_posix()
