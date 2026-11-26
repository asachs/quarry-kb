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
    "raw_layout": "misfiled_raw",
    "groundedness": "ungrounded",
    "related": "bad_related",
    "frontmatter": "bad_frontmatter",
    "wikilinks": "wikilinks",
    "verification": "bad_verification",
}


@dataclass
class LintResult:
    broken: list[tuple[str, str]] = field(default_factory=list)
    missing: list[tuple[str, str]] = field(default_factory=list)
    orphans: list[str] = field(default_factory=list)
    no_outgoing: list[str] = field(default_factory=list)
    not_indexed: list[str] = field(default_factory=list)
    misfiled_raw: list[str] = field(default_factory=list)
    ungrounded: list[tuple[str, str]] = field(default_factory=list)
    bad_related: list[tuple[str, str]] = field(default_factory=list)
    bad_frontmatter: list[tuple[str, str]] = field(default_factory=list)
    wikilinks: list[tuple[str, int]] = field(default_factory=list)
    # articles from visual sources whose verification status is missing or incomplete
    bad_verification: list[tuple[str, str]] = field(default_factory=list)
    # articles from visual sources still marked unverified (a backlog count, not a defect)
    unverified: list[str] = field(default_factory=list)
    # orphan -> how many other articles name it in frontmatter `related:` (not a body link)
    orphan_related: dict[str, int] = field(default_factory=dict)
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
        # Scheme-qualified, not a bare "http" prefix: a relative link to a file whose
        # name starts with "http" (e.g. `http-status-codes.md`) is a local target.
        if target.startswith(("http://", "https://", "#", "mailto:")):
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


def _related(fm: dict, related_field: str) -> list[object]:
    r = fm.get(related_field) or []
    return r if isinstance(r, list) else [r]


def _related_ok(entry: object, wiki: Path, aset: set[str]) -> bool:
    """A ``related:`` entry is a wiki-root-relative path to an existing article, or a
    trailing-slash path to an existing wiki folder. Anything else — a ``wiki/`` prefix,
    a ``../`` path, markdown-link syntax, a missing ``.md`` — resolves to nothing for
    the tools that read the field, and does so silently."""
    if not isinstance(entry, str):
        return False
    if entry in aset:
        return True
    if entry.endswith("/") and ".." not in Path(entry).parts and not entry.startswith("/"):
        return (wiki / entry).is_dir()
    return False


_FENCE = re.compile(r"^(```|~~~).*?^\1[^\n]*$", flags=re.DOTALL | re.MULTILINE)
_CODE_SPAN = re.compile(r"`[^`\n]*`")
_WIKILINK = re.compile(r"\[\[[^\[\]\n]+\]\]")


def _wikilink_count(content: str) -> int:
    """`[[wikilinks]]` in the body, ignoring code fences and code spans (an article
    may legitimately discuss the syntax)."""
    body = content
    if content.startswith("---"):
        end = content.find("\n---", 3)
        if end != -1:
            body = content[end + 4 :]
    body = _CODE_SPAN.sub("", _FENCE.sub("", body))
    return len(_WIKILINK.findall(body))


_IMAGE_EXT = frozenset({".jpg", ".jpeg", ".png", ".webp", ".gif"})
VERIFICATION_STATES = ("unverified", "verified")
_VERIFIED_RECORD = ("verified_on", "verified_by")


def visual_sources(path: Path, cfg: Config) -> list[str]:
    """Cited local sources that have images saved beside them (``raw/x.md`` + ``raw/x/``).

    That layout is what ``ingest`` writes for adapter media (reel frames, carousel
    slides). An article compiled from such a source states things nobody can check
    against the raw text alone, which is why its verification status is tracked.
    """
    out: list[str] = []
    for s in _sources(path, cfg.frontmatter.sources_field):
        if not _is_local_source(s):
            continue
        p = cfg.root / s
        d = p.with_suffix("")
        if (
            p.is_file()
            and d.is_dir()
            and any(f.suffix.lower() in _IMAGE_EXT for f in d.iterdir() if f.is_file())
        ):
            out.append(s)
    return out


def verification_problem(fm: dict, field_name: str) -> str | None:
    """Why an article from a visual source fails the status rule — ``None`` if it passes."""
    status = fm.get(field_name)
    if status is None:
        return f"no `{field_name}:` (its source has images; start at `unverified`)"
    if status not in VERIFICATION_STATES:
        return f"`{field_name}: {status}` is not one of {', '.join(VERIFICATION_STATES)}"
    if status == "verified":
        absent = [k for k in _VERIFIED_RECORD if not fm.get(k)]
        if absent:
            return "verified without a record (" + ", ".join(absent) + " missing)"
    return None


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


def _stem(w: str) -> str:
    """Crude suffix strip so `webhooks`/`verifying` match `webhook`/`verification`.

    Deliberately not a real stemmer: this check is advisory and over-matching costs
    a missed flag, while under-matching costs a false accusation of ungroundedness.
    """
    for suf, keep in (("ies", "y"), ("ing", ""), ("ed", ""), ("es", ""), ("s", "")):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[: -len(suf)] + keep
    return w


def _gwords(text: str) -> list[str]:
    """Lowercased, stemmed content words (>2 chars, non-stopword) from arbitrary text."""
    return [
        _stem(w)
        for w in re.sub(r"[^a-z0-9]+", " ", text.lower()).split()
        if len(w) > 2 and w not in _GND_STOP
    ]


def _bold_named_terms(content: str) -> list[str]:
    """Multi-word Title-Case names in `**...**` spans — the proper-noun / build-name
    signature, as opposed to bolded labels (``**Status:**``), emphasised sentences
    (``**Heat exposure.**``), or single emphasised words (``**Print**``).

    Filters, tuned for precision over recall (this is advisory): 2–4 words, no trailing
    punctuation, no markdown link/bracket chars, and every non-stopword word Capitalised.
    """
    seen: set[str] = set()
    out: list[str] = []
    for m in re.finditer(r"\*\*(.+?)\*\*", content, flags=re.DOTALL):
        term = m.group(1).strip()
        if any(ch in term for ch in "[]()\n") or term.endswith((":", ".", "!", "?", ",", ";")):
            continue
        words = term.split()
        if not 2 <= len(words) <= 4:
            continue
        content_words = [w for w in words if w.lower() not in _GND_STOP]
        if not content_words or not all(w[:1].isupper() for w in content_words):
            continue
        key = term.lower()
        if key not in seen:
            seen.add(key)
            out.append(term)
    return out


# A cited source may be a whole directory (a notes export, a scan bundle). Read its
# text files too, bounded so one huge directory can't dominate a lint run.
_GND_DIR_FILE_CAP = 500


def _source_text_files(p: Path) -> list[Path]:
    """The readable text files a cited source resolves to — itself, or its contents."""
    if p.is_file():
        return [p] if p.suffix.lower() in {".md", ".txt"} else []
    if p.is_dir():
        found = sorted(f for f in p.rglob("*") if f.suffix.lower() in {".md", ".txt"})
        return found[:_GND_DIR_FILE_CAP]
    return []


# A handle or hashtag glues a name into one token (`#bambulab`, `@chapterone_dublin`).
_GLUED = re.compile(r"[#@]([a-z0-9_.]+)")


@dataclass
class _SourceText:
    """What the cited text sources say, in the three forms a name can be matched in."""

    words: set[str] = field(default_factory=set)  # stemmed content words
    glued: set[str] = field(default_factory=set)  # hashtag / handle tokens, alnum only
    flat: str = ""  # all text, lowercased, non-alphanumerics collapsed to single spaces

    def __bool__(self) -> bool:
        return bool(self.words or self.flat.strip())

    def grounds(self, term: str) -> bool:
        tw = _gwords(term)
        if tw and any(w in self.words for w in tw):
            return True
        flat_term = re.sub(r"[^a-z0-9]+", " ", term.lower()).strip()
        if not tw:
            # A name made only of short tokens (`NW-L1 V2`) has no content words to
            # match on; fall back to the phrase itself rather than flag it unseen.
            return bool(flat_term) and f" {flat_term} " in f" {self.flat} "
        joined = flat_term.replace(" ", "")
        return len(joined) >= 6 and any(joined in g for g in self.glued)


def _source_text(path: Path, cfg: Config) -> _SourceText:
    """Text from every readable, local, text cited source (file or directory)."""
    st = _SourceText()
    chunks: list[str] = []
    for s in _sources(path, cfg.frontmatter.sources_field):
        if not _is_local_source(s):
            continue
        for f in _source_text_files(cfg.root / s):
            try:
                text = f.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            st.words.update(_gwords(text))
            low = text.lower()
            st.glued.update(re.sub(r"[^a-z0-9]", "", g) for g in _GLUED.findall(low))
            chunks.append(re.sub(r"[^a-z0-9]+", " ", low))
    st.flat = " ".join(chunks)
    return st


_DATED_RAW = re.compile(r"^\d{4}-\d{2}-\d{2}[_-]")


def _misfiled_raw(cfg: Config) -> list[str]:
    """Dated raw captures sitting loose in raw/ when ``raw_layout`` nests them.

    Narrow by design: only the root is checked, because a store may legitimately keep
    dated files under a named category folder that the layout template can't express.
    """
    if "/" not in cfg.store.raw_layout:  # a flat layout — loose files are correct
        return []
    root = cfg.root / cfg.store.raw
    if not root.is_dir():
        return []
    return sorted(
        f"{cfg.store.raw}/{p.name}"
        for p in root.iterdir()
        if p.is_file() and _DATED_RAW.match(p.name)
    )


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


def run(cfg: Config) -> LintResult:
    wiki = cfg.root / cfg.store.wiki
    if not wiki.is_dir():
        raise QuarryError(f"no wiki directory at {wiki} — not a knowledge store")
    index = cfg.lint.index_file
    articles = sorted(
        str(p.relative_to(wiki)) for p in wiki.rglob("*.md") if not (index and p.name == index)
    )
    aset = set(articles)

    outgoing: dict[str, set[str]] = {}
    incoming: dict[str, set[str]] = defaultdict(set)
    broken: list[tuple[str, str]] = []
    need_links = cfg.lint.broken_links or cfg.lint.orphan_check
    raw_prefixes = (f"{cfg.store.raw}/", f"../{cfg.store.raw}/")  # links into raw/ aren't broken
    bad_related: list[tuple[str, str]] = []
    bad_frontmatter: list[tuple[str, str]] = []
    wikilinks: list[tuple[str, int]] = []
    bad_verification: list[tuple[str, str]] = []
    unverified: list[str] = []
    related_in: dict[str, set[str]] = defaultdict(set)
    for a in articles:
        content = (wiki / a).read_text(encoding="utf-8")
        if cfg.lint.frontmatter_check:
            why = frontmatter.problem(content)
            if why:
                bad_frontmatter.append((a, why))
        for entry in _related(frontmatter.parse(content), cfg.frontmatter.related_field):
            if isinstance(entry, str) and entry in aset:
                related_in[entry].add(a)
            if cfg.lint.related_check and not _related_ok(entry, wiki, aset):
                bad_related.append((a, str(entry)))
        if cfg.lint.verification_check and visual_sources(wiki / a, cfg):
            fm = frontmatter.parse(content)
            why_v = verification_problem(fm, cfg.frontmatter.verification_field)
            if why_v:
                bad_verification.append((a, why_v))
            elif fm.get(cfg.frontmatter.verification_field) == "unverified":
                unverified.append(a)
        if cfg.lint.wikilinks:
            n_wl = _wikilink_count(content)
            if n_wl:
                wikilinks.append((a, n_wl))
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

    orphan_related = {a: len(related_in[a] - {a}) for a in orphans}

    no_outgoing = [a for a in articles if not outgoing.get(a)]

    ungrounded: list[tuple[str, str]] = []
    if cfg.lint.groundedness:
        for a in articles:
            src = _source_text(wiki / a, cfg)
            if not src:  # no checkable text source — can't verify, don't flag
                continue
            content = (wiki / a).read_text(encoding="utf-8")
            for term in _bold_named_terms(content):
                if not src.grounds(term):
                    ungrounded.append((a, term))

    misfiled_raw = _misfiled_raw(cfg) if cfg.lint.raw_layout else []

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
        wiki,
        articles,
        incoming,
        outgoing,
        broken,
        missing,
        sorted(orphans),
        no_outgoing,
        not_indexed,
        total_links,
        sorted(ungrounded) if cfg.lint.groundedness else None,
        misfiled_raw,
        sorted(bad_related),
        sorted(bad_frontmatter),
        sorted(wikilinks),
        orphan_related,
        sorted(bad_verification),
        len(unverified),
    )
    return LintResult(
        broken=sorted(broken),
        missing=sorted(missing),
        orphans=sorted(orphans),
        no_outgoing=sorted(no_outgoing),
        not_indexed=sorted(not_indexed),
        ungrounded=sorted(ungrounded),
        misfiled_raw=misfiled_raw,
        bad_related=sorted(bad_related),
        bad_frontmatter=sorted(bad_frontmatter),
        wikilinks=sorted(wikilinks),
        bad_verification=sorted(bad_verification),
        unverified=sorted(unverified),
        orphan_related=orphan_related,
        total_articles=len(articles),
        total_links=total_links,
        report=report,
    )


def _format(
    wiki,
    articles,
    incoming,
    outgoing,
    broken,
    missing,
    orphans,
    no_outgoing,
    not_indexed,
    total_links,
    ungrounded=None,
    misfiled_raw=(),
    bad_related=(),
    bad_frontmatter=(),
    wikilinks=(),
    orphan_related=None,
    bad_verification=(),
    n_unverified=0,
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
    if misfiled_raw:
        e(f"Misfiled raw files:    {len(misfiled_raw)}")
    # The three below print only when non-zero, so a clean store's report is unchanged.
    if bad_frontmatter:
        e(f"Bad frontmatter:       {len(bad_frontmatter)}")
    if bad_related:
        e(f"Unresolved related:    {len(bad_related)}")
    if wikilinks:
        e(f"Wikilinks:             {sum(n for _, n in wikilinks)}")
    if bad_verification:
        e(f"Verification status:   {len(bad_verification)}")
    if n_unverified:
        e(f"Unverified (visual):   {n_unverified}")
    e("")
    if bad_verification:
        e("--- VERIFICATION STATUS (article from a visual source, status missing/incomplete) ---")
        for a, why in bad_verification:
            e(f"  {a} -> {why}")
        e("")
    if bad_frontmatter:
        e("--- BAD FRONTMATTER (missing or not valid YAML — fields read as absent) ---")
        for a, why in bad_frontmatter:
            e(f"  {a} -> {why}")
        e("")
    if bad_related:
        e("--- UNRESOLVED RELATED (not a wiki-root-relative path to an article) ---")
        for a, entry in bad_related:
            e(f"  {a} -> {entry}")
        e("")
    if wikilinks:
        e("--- WIKILINKS ([[...]] does not render or count as a link) ---")
        for a, n_wl in wikilinks:
            e(f"  {n_wl:3d}  {a}")
        e("")
    if misfiled_raw:
        e("--- MISFILED RAW (dated captures loose in the raw root) ---")
        for r in misfiled_raw:
            e(f"  {r}")
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
            n_rel = (orphan_related or {}).get(a, 0)
            # Named in other articles' frontmatter only: the backlink exists but isn't
            # a body link, which is the one thing that fixes an orphan.
            e(
                f"  {a}  (in {n_rel} related: list{'s' if n_rel != 1 else ''}, no body link)"
                if n_rel
                else f"  {a}"
            )
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
