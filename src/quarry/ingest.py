"""Ingest — the first half of the two-call seam.

Resolve an adapter, fetch the source, write immutable raw material, write the
compile-manifest, and STOP. The article is written by a human/agent between this
and ``finish``. A dedup pre-check (via discovery) guards against silent re-ingest.
"""

from __future__ import annotations

import datetime as _dt
import sys

from quarry import discovery, manifest, store
from quarry.adapters import registry
from quarry.config import Config
from quarry.errors import QuarryError


def _raw_frontmatter(meta: dict) -> str:
    return (
        "---\n"
        f"source: {meta['url']}\n"
        f"date: {meta['date']}\n"
        f"author: {meta.get('author', 'unknown')}\n"
        f"title: {meta['title']}\n"
        "---\n\n"
    )


def _dedup_precheck(cfg: Config, title: str) -> None:
    """Apply [ingest] on_duplicate against discovery dedup hits."""
    if cfg.ingest.on_duplicate == "allow":
        return
    hits = discovery.dedup_hits(cfg, title)
    if not hits:
        return
    detail = "; ".join(f"{s}% {p}" for s, p in hits[:3])
    if cfg.ingest.on_duplicate == "warn":
        print(f"quarry: warning: '{title}' may already be covered: {detail}", file=sys.stderr)
        return
    raise QuarryError(
        f"possible duplicate of '{title}': {detail} (re-run with --force to ingest anyway)"
    )


def run(cfg: Config, url: str, *, topic: str | None = None, force: bool = False) -> dict:
    """Fetch a source into raw/ + a compile-manifest. Returns the manifest + paths."""
    adapter = registry.resolve_adapter(cfg, url)
    result = registry.fetch(adapter, url)
    meta = result.metadata
    content = result.content

    if not force:
        _dedup_precheck(cfg, meta["title"])

    date = _dt.date.fromisoformat(meta["date"])
    source_id = meta.get("source_id")
    slug = store.make_slug(cfg, title=meta["title"], date=date, source_id=source_id, topic=topic)
    raw_abs = store.make_raw_path(
        cfg, title=meta["title"], date=date, slug=slug, source_id=source_id, topic=topic
    )
    raw_rel = store.raw_relpath(cfg, raw_abs)

    if raw_abs.exists() and not force:
        raise QuarryError(f"raw already exists: {raw_rel} (use --force to overwrite)")

    raw_abs.parent.mkdir(parents=True, exist_ok=True)
    raw_abs.write_text(_raw_frontmatter(meta) + content + "\n", encoding="utf-8")

    target_wiki = (
        f"{cfg.store.wiki}/{topic}/{store.slugify(meta['title'])}.md" if topic else None
    )
    m = manifest.build(
        slug=slug,
        source_url=meta["url"],
        adapter=adapter.name,
        raw_path=raw_rel,
        content=content,
        target_wiki_path=target_wiki,
        required_frontmatter=cfg.frontmatter.required,
        metadata=meta,
    )
    manifest.write(cfg, slug, m)
    return {"slug": slug, "raw_path": raw_rel, "target_wiki_path": target_wiki, "manifest": m}
