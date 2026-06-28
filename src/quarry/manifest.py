"""The compile-manifest — the two-call seam's persisted, machine-readable product.

`ingest` writes a manifest describing exactly what was fetched and what the article
must cite; `finish` loads it and *verifies* the written article against it (never
trusts it). Paths are config-driven; the shape is stable.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from quarry.config import Config
from quarry.errors import QuarryError
from quarry.store import manifest_dir

# Keys every manifest carries. `finish` and tests assert against this set.
REQUIRED_KEYS = (
    "slug",
    "source_url",
    "adapter",
    "raw_path",
    "content_sha256",
    "target_wiki_path",
    "required_frontmatter",
    "must_cite_source",
    "metadata",
)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def manifest_path(cfg: Config, slug: str) -> Path:
    return manifest_dir(cfg) / f"{slug}.json"


def build(
    *,
    slug: str,
    source_url: str,
    adapter: str,
    raw_path: str,
    content: str,
    target_wiki_path: str | None,
    required_frontmatter: list[str],
    metadata: dict,
) -> dict:
    """Assemble a manifest. ``content_sha256`` is computed from ``content``; the
    raw file's own relpath is what the article ``must_cite_source``."""
    return {
        "slug": slug,
        "source_url": source_url,
        "adapter": adapter,
        "raw_path": raw_path,
        "content_sha256": sha256_text(content),
        "target_wiki_path": target_wiki_path,
        "required_frontmatter": list(required_frontmatter),
        "must_cite_source": raw_path,
        "metadata": metadata,
    }


def write(cfg: Config, slug: str, data: dict) -> Path:
    path = manifest_path(cfg, slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def load(cfg: Config, slug: str) -> dict:
    path = manifest_path(cfg, slug)
    if not path.exists():
        raise QuarryError(
            f"no compile-manifest for slug '{slug}' (did you run 'quarry ingest'?)"
        )
    return json.loads(path.read_text(encoding="utf-8"))
