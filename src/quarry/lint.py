"""Structural-health lint — config-driven, returns a structured result.

Every check and the ``fail_on`` set come from ``[lint]`` config; nothing is
hardcoded. ``run`` returns a ``LintResult`` (counts + per-issue lists + a formatted
report) that ``finish`` consumes directly — no text-scraping. The report format is
locked by a golden-output test.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from quarry import frontmatter
from quarry.config import Config
from quarry.errors import QuarryError

# fail_on token -> LintResult attribute holding that issue list.
_CHECK_ATTR = {
    "broken_links": "broken",
    "missing_sources": "missing",
    "orphans": "orphans",
    "not_indexed": "not_indexed",
}


@dataclass
class LintResult:
    broken: list[tuple[str, str]] = field(default_factory=list)
    missing: list[tuple[str, str]] = field(default_factory=list)
    orphans: list[str] = field(default_factory=list)
    no_outgoing: list[str] = field(default_factory=list)
    not_indexed: list[str] = field(default_factory=list)
    total_articles: int = 0
    total_links: int = 0
    report: str = ""

    def count(self, check: str) -> int:
        return len(getattr(self, _CHECK_ATTR[check]))

    def fails(self, fail_on: list[str]) -> bool:
        return any(self.count(c) > 0 for c in fail_on if c in _CHECK_ATTR)

    def summary(self, fail_on: list[str]) -> str:
        return ", ".join(f"{self.count(c)} {c}" for c in fail_on if c in _CHECK_ATTR)


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------


def _body_links(content: str, rel: str) -> set[str]:
    """`[text](target.md)` links in the body, resolved relative to the store root.

    Frontmatter ``related:`` entries are ``- name.md`` list items, not ``[](...)``
    links, so they are intentionally excluded — they don't count toward inbound.
    """
    links: set[str] = set()
    for m in re.finditer(r"\[([^\]]*)\]\(([^)]+)\)", content):
        target = m.group(2)
        if target.startswith(("http", "#", "mailto:")):
            continue
        target = target.split("#")[0]
        if not target.endswith(".md"):
            continue
        parts: list[str] = []
        for part in (Path(rel).parent / target).parts:
            if part == "..":
                if parts:
                    parts.pop()
            elif part != ".":
                parts.append(part)
        if parts:
            links.add("/".join(parts))
    return links


def _sources(path: Path, sources_field: str) -> list[str]:
    fm = frontmatter.parse(path.read_text(encoding="utf-8"))
    s = fm.get(sources_field) or []
    if isinstance(s, str):
        s = [s]
    return [x for x in s if isinstance(x, str)]


def _is_local_source(source: str) -> bool:
    if source.startswith(("http://", "https://")):
        return False
    seg = source.split("/")[0]
    return not ("." in seg and not seg.startswith("."))


def _title(path: Path) -> str:
    fm = frontmatter.parse(path.read_text(encoding="utf-8"))
    t = fm.get("title")
    return t.strip('"') if isinstance(t, str) else path.stem


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


def run(cfg: Config) -> LintResult:
    wiki = cfg.root / cfg.store.wiki
    if not wiki.is_dir():
        raise QuarryError(f"no wiki directory at {wiki} — not a knowledge store")
    index = cfg.lint.index_file
    articles = sorted(
        str(p.relative_to(wiki))
        for p in wiki.rglob("*.md")
        if not (index and p.name == index)
    )
    aset = set(articles)

    outgoing: dict[str, set[str]] = {}
    incoming: dict[str, set[str]] = defaultdict(set)
    broken: list[tuple[str, str]] = []
    need_links = cfg.lint.broken_links or cfg.lint.orphan_check
    raw_prefixes = (f"{cfg.store.raw}/", f"../{cfg.store.raw}/")  # links into raw/ aren't broken
    for a in articles:
        content = (wiki / a).read_text(encoding="utf-8")
        links = _body_links(content, a) if need_links else set()
        outgoing[a] = links
        for t in links:
            if t in aset:
                incoming[t].add(a)
            elif cfg.lint.broken_links and not t.startswith(raw_prefixes):
                broken.append((a, t))

    missing: list[tuple[str, str]] = []
    if cfg.lint.require_sources_on_disk:
        for a in articles:
            for s in _sources(wiki / a, cfg.frontmatter.sources_field):
                if _is_local_source(s) and not (cfg.root / s).exists():
                    missing.append((a, s))

    orphans: list[str] = []
    if cfg.lint.orphan_check:
        orphans = [a for a in articles if not (incoming[a] - {index})]

    no_outgoing = [a for a in articles if not outgoing.get(a)]

    not_indexed: list[str] = []
    if index:
        indexed: set[str] = set()
        idx = wiki / index
        if idx.exists():
            for m in re.finditer(r"\[([^\]]*)\]\(([^)]+\.md)\)", idx.read_text(encoding="utf-8")):
                indexed.add(m.group(2))
        not_indexed = [a for a in articles if a not in indexed]

    total_links = sum(len(v) for v in outgoing.values())
    report = _format(
        wiki, articles, incoming, outgoing, broken, missing,
        sorted(orphans), no_outgoing, not_indexed, total_links,
    )
    return LintResult(
        broken=sorted(broken),
        missing=sorted(missing),
        orphans=sorted(orphans),
        no_outgoing=sorted(no_outgoing),
        not_indexed=sorted(not_indexed),
        total_articles=len(articles),
        total_links=total_links,
        report=report,
    )


def _format(
    wiki, articles, incoming, outgoing, broken, missing,
    orphans, no_outgoing, not_indexed, total_links,
) -> str:
    n = len(articles)
    avg = total_links / n if n else 0
    conn = {a: len(incoming[a]) + len(outgoing.get(a, set())) for a in articles}
    top = sorted(conn.items(), key=lambda x: (-x[1], x[0]))[:10]

    cats: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "orphans": 0})
    orphan_set = set(orphans)
    for a in articles:
        c = cats[Path(a).parent.as_posix()]
        c["total"] += 1
        if a in orphan_set:
            c["orphans"] += 1

    L: list[str] = []
    e = L.append
    e("=" * 60)
    e("WIKI STRUCTURAL HEALTH REPORT")
    e("=" * 60)
    e("")
    e(f"Total articles:        {n}")
    e(f"Total cross-references: {total_links}")
    e(f"Avg outgoing links:    {avg:.1f}")
    e(f"Orphaned articles:     {len(orphans)}")
    e(f"Zero outgoing links:   {len(no_outgoing)}")
    e(f"Broken links:          {len(broken)}")
    e(f"Missing source files:  {len(missing)}")
    e("")
    if broken:
        e("--- BROKEN LINKS ---")
        for a, t in sorted(broken):
            e(f"  {a} -> {t}")
        e("")
    if missing:
        e("--- MISSING SOURCE FILES ---")
        for a, s in sorted(missing):
            e(f"  {a} -> {s}")
        e("")
    e("--- TOP CONNECTED ---")
    for a, c in top:
        e(f"  {c:3d}  {a}")
    e("")
    if orphans:
        e("--- ORPHANED ARTICLES (no inbound from body) ---")
        for a in orphans:
            e(f"  {a}")
        e("")
    e("--- CATEGORY HEALTH ---")
    for cat in sorted(cats):
        c = cats[cat]
        health = 100 * (1 - c["orphans"] / c["total"]) if c["total"] else 0
        e(f"  {cat or '.':<20} {c['total']:>3} articles  {health:>5.0f}% linked")
    e("")
    if not_indexed:
        e("--- NOT IN INDEX ---")
        for a in not_indexed:
            e(f"  {a}")
        e("")
    return "\n".join(L)
