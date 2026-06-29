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
    "groundedness": "ungrounded",
}


@dataclass
class LintResult:
    broken: list[tuple[str, str]] = field(default_factory=list)
    missing: list[tuple[str, str]] = field(default_factory=list)
    orphans: list[str] = field(default_factory=list)
    no_outgoing: list[str] = field(default_factory=list)
    not_indexed: list[str] = field(default_factory=list)
    ungrounded: list[tuple[str, str]] = field(default_factory=list)
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


# Groundedness: a bolded named term whose content words are ALL absent from the
# article's cited text sources is almost certainly fabricated or bled in from
# another source. Word-level (not phrase-level) matching keeps faithful paraphrase
# and synthesis from being flagged — only wholly-foreign named things surface.
_GND_STOP = frozenset(
    "the a an and or to of in with for on new best top build builds guide".split()
)


def _gwords(text: str) -> list[str]:
    """Lowercased content words (>2 chars, non-stopword) from arbitrary text."""
    return [
        w
        for w in re.sub(r"[^a-z0-9]+", " ", text.lower()).split()
        if len(w) > 2 and w not in _GND_STOP
    ]


def _bold_named_terms(content: str) -> list[str]:
    """`**...**` spans that contain an uppercase letter (named things, not emphasis)."""
    seen: set[str] = set()
    out: list[str] = []
    for m in re.finditer(r"\*\*(.+?)\*\*", content, flags=re.DOTALL):
        term = m.group(1).strip()
        if not any(c.isupper() for c in term) or not _gwords(term):
            continue
        key = term.lower()
        if key not in seen:
            seen.add(key)
            out.append(term)
    return out


def _source_words(path: Path, cfg: Config) -> set[str]:
    """Content words from every readable, local, text (.md/.txt) cited source."""
    hay: set[str] = set()
    for s in _sources(path, cfg.frontmatter.sources_field):
        if not _is_local_source(s):
            continue
        p = cfg.root / s
        if p.suffix.lower() in {".md", ".txt"} and p.is_file():
            try:
                hay.update(_gwords(p.read_text(encoding="utf-8")))
            except (OSError, UnicodeDecodeError):
                continue
    return hay


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

    ungrounded: list[tuple[str, str]] = []
    if cfg.lint.groundedness:
        for a in articles:
            hay = _source_words(wiki / a, cfg)
            if not hay:  # no checkable text source — can't verify, don't flag
                continue
            content = (wiki / a).read_text(encoding="utf-8")
            for term in _bold_named_terms(content):
                if not any(w in hay for w in _gwords(term)):
                    ungrounded.append((a, term))

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
        sorted(ungrounded) if cfg.lint.groundedness else None,
    )
    return LintResult(
        broken=sorted(broken),
        missing=sorted(missing),
        orphans=sorted(orphans),
        no_outgoing=sorted(no_outgoing),
        not_indexed=sorted(not_indexed),
        ungrounded=sorted(ungrounded),
        total_articles=len(articles),
        total_links=total_links,
        report=report,
    )


def _format(
    wiki, articles, incoming, outgoing, broken, missing,
    orphans, no_outgoing, not_indexed, total_links, ungrounded=None,
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
    if ungrounded is not None:
        e(f"Ungrounded terms:      {len(ungrounded)}")
    e("")
    if ungrounded:
        e("--- UNGROUNDED TERMS (bolded names not traceable to cited sources) ---")
        for a, term in ungrounded:
            e(f"  {a} -> {term}")
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
