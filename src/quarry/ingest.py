"""Ingest — the first half of the two-call seam.

Resolve an adapter, fetch the source, write immutable raw material, write the
compile-manifest, and STOP. The article is written by a human/agent between this
and ``finish``. A dedup pre-check (via discovery) guards against silent re-ingest.
"""

from __future__ import annotations

import datetime as _dt
import os
import shutil
import sys
from pathlib import Path

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


def _copy_assets(cfg: Config, assets: dict[str, str], dest: Path) -> list[str]:
    """Copy adapter assets into the store; return their root-relative paths (sorted)."""
    if not assets:
        return []
    dest.mkdir(parents=True, exist_ok=True)
    out = []
    for name, src in sorted(assets.items()):
        target = dest / Path(name).name
        shutil.copyfile(src, target)
        out.append(target.relative_to(cfg.root).as_posix())
    return out


def _media_section(raw_abs: Path, cfg: Config, asset_paths: list[str]) -> str:
    """A '## Media' list with links relative to the raw file, so it renders in place."""
    lines = ["## Media", ""]
    for rel in asset_paths:
        link = os.path.relpath(cfg.root / rel, start=raw_abs.parent)
        lines.append(f"- [{Path(rel).name}]({Path(link).as_posix()})")
    return "\n".join(lines) + "\n"


def run(cfg: Config, url: str, *, topic: str | None = None, force: bool = False) -> dict:
    """Fetch a source into raw/ + a compile-manifest. Returns the manifest + paths."""
    adapter = registry.resolve_adapter(cfg, url)
    result = registry.fetch(adapter, url)
    try:
        return _store_result(cfg, adapter.name, result, topic=topic, force=force)
    finally:
        if result.tmpdir:
            shutil.rmtree(result.tmpdir, ignore_errors=True)


def _store_result(
    cfg: Config, adapter_name: str, result, *, topic: str | None, force: bool
) -> dict:
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
    assets_dir = store.make_assets_dir(
        cfg, title=meta["title"], date=date, slug=slug, topic=topic, source_id=source_id
    )
    asset_paths = _copy_assets(cfg, result.assets, assets_dir)
    body = content
    if asset_paths:
        body = content.rstrip("\n") + "\n\n" + _media_section(raw_abs, cfg, asset_paths)
    raw_abs.write_text(_raw_frontmatter(meta) + body + "\n", encoding="utf-8")
    candidates = discovery.ingest_candidates(cfg, meta["title"], content)

    target_wiki = (
        f"{cfg.store.wiki}/{topic}/{store.slugify(meta['title'])}.md" if topic else None
    )
    m = manifest.build(
        slug=slug,
        source_url=meta["url"],
        adapter=adapter_name,
        raw_path=raw_rel,
        content=content,
        target_wiki_path=target_wiki,
        required_frontmatter=cfg.frontmatter.required,
        metadata=meta,
        assets=asset_paths,
        related_candidates=candidates,
    )
    manifest.write(cfg, slug, m)
    return {"slug": slug, "raw_path": raw_rel, "target_wiki_path": target_wiki, "manifest": m}
