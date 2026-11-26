"""Is a cross-link one a reader would follow, or padding to reach a count?

Agents told to "link 2-3 related articles" pad: an article about a bookmarking app got a
link to an identity server because both are self-hosted. Nothing structural is wrong with
such a link, so the lint passes it.

The check here is deliberately modest. It builds a term-weighted vector for every article
(no model, no index to keep fresh) and asks, for a link from A to B: how many other
articles are closer to A than B is? A real link usually lands in the first handful; the
median existing link in the wiki this was tuned on ranked 7th of 546. A link that ranks
beyond ``weak_link_rank`` in both directions is reported as weak, with the closest
unlinked articles offered instead.

It is a prompt to look, never a gate: two articles can be rightly linked without sharing
a word (a rain-jacket test and a mountain itinerary), and a padded link can share enough
words to pass: on the case that prompted this, it caught one of the two padded links. The
raw similarity score was measured to be useless as a threshold, since padded and real links
overlap; only the rank separated them at all.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from quarry import frontmatter
from quarry.config import Config
from quarry.lint import _body_links, _related

_STOP = frozenset(
    "the a an and or of to in on for with is are was were be been it its this that as at by "
    "from not but if then than so such can will would should may might into over under about "
    "also more most other some any each which who whom whose what when where why how you your "
    "we our they their he she his her them me my do does did done has have had no yes one two "
    "new use used using via per etc see".split()
)
# An unlinked article is suggested only when it is in this one's top NEAR and this one is in
# its top NEAR_BACK: a one-sided match is how padding starts.
NEAR, NEAR_BACK = 10, 25
_TOKEN = re.compile(r"[a-z][a-z0-9\-]{2,}")
_LINK_LINE = re.compile(r"\]\([^)\s]+\.md(#[^)]*)?\)")


@dataclass
class Index:
    vectors: dict[str, dict[str, float]] = field(default_factory=dict)
    links: dict[str, set[str]] = field(default_factory=dict)  # article -> articles it links to
    _ranks: dict[str, dict[str, int]] = field(default_factory=dict)

    def similarity(self, a: str, b: str) -> float:
        va, vb = self.vectors[a], self.vectors[b]
        if len(va) > len(vb):
            va, vb = vb, va
        return sum(w * vb.get(t, 0.0) for t, w in va.items())

    def neighbours(self, a: str) -> list[str]:
        """Every other article, closest first."""
        return sorted(
            (b for b in self.vectors if b != a), key=lambda b: (-self.similarity(a, b), b)
        )

    def rank(self, a: str, b: str) -> int:
        """Position of ``b`` among ``a``'s neighbours (1 = closest)."""
        if a not in self._ranks:
            self._ranks[a] = {b2: i for i, b2 in enumerate(self.neighbours(a), 1)}
        return self._ranks[a][b]

    def pair_rank(self, a: str, b: str) -> int:
        """The better of the two directions: a link is weak only if neither article
        counts the other among its near neighbours."""
        return min(self.rank(a, b), self.rank(b, a))


def _tokens(title: str, body: str) -> list[str]:
    # A link's own line describes the target; counting it would make any pair look related.
    kept = "\n".join(line for line in body.split("\n") if not _LINK_LINE.search(line))
    text = f"{title} {title} {title} {kept}".lower()
    return [t for t in _TOKEN.findall(text) if t not in _STOP]


def _split(content: str) -> tuple[dict, str]:
    try:
        fm = frontmatter.parse(content)
    except Exception:  # noqa: BLE001 - an unparseable header is lint's finding, not ours
        fm = {}
    body = content
    if content.startswith("---"):
        end = content.find("\n---", 3)
        if end != -1:
            body = content[end + 4 :]
    return fm, body


def build(cfg: Config) -> Index:
    wiki = cfg.root / cfg.store.wiki
    index_name = cfg.lint.index_file
    paths = sorted(p for p in wiki.rglob("*.md") if not (index_name and p.name == index_name))
    counts: dict[str, Counter] = {}
    links: dict[str, set[str]] = {}
    for p in paths:
        rel = p.relative_to(wiki).as_posix()
        content = p.read_text(encoding="utf-8")
        fm, body = _split(content)
        title = fm.get("title")
        counts[rel] = Counter(_tokens(title if isinstance(title, str) else "", body))
        out = {e for e in _related(fm, cfg.frontmatter.related_field) if isinstance(e, str)}
        links[rel] = out | _body_links(body, rel)
    names = set(counts)
    n = len(counts) or 1
    df = Counter(t for c in counts.values() for t in c)
    idx = Index()
    for rel, c in counts.items():
        # terms in half the wiki say nothing about any one article
        vec = {t: (1 + math.log(k)) * math.log(n / df[t]) for t, k in c.items() if df[t] <= n / 2}
        norm = math.sqrt(sum(w * w for w in vec.values())) or 1.0
        idx.vectors[rel] = {t: w / norm for t, w in vec.items()}
        idx.links[rel] = {b for b in links[rel] if b in names and b != rel}
    return idx


def weak_links(idx: Index, threshold: int) -> list[tuple[int, str, str]]:
    """Every link in the wiki whose pair rank is beyond ``threshold``, weakest first."""
    out = []
    for a, targets in idx.links.items():
        for b in targets:
            r = idx.pair_rank(a, b)
            if r > threshold:
                out.append((r, a, b))
    return sorted(out, key=lambda x: (-x[0], x[1], x[2]))


def for_article(idx: Index, article: str, threshold: int, suggest: int = 5) -> dict:
    """The weak links into and out of one article, and the closest articles it does not
    link. ``article`` is relative to the wiki directory."""
    if article not in idx.vectors:
        return {"weak": [], "closest_unlinked": []}
    outgoing = idx.links[article]
    incoming = {a for a, targets in idx.links.items() if article in targets}
    weak = []
    for other in sorted(outgoing | incoming):
        r = idx.pair_rank(article, other)
        if r > threshold:
            direction = (
                "both ways"
                if other in outgoing and other in incoming
                else "out"
                if other in outgoing
                else "in"
            )
            weak.append((r, direction, other))
    linked = outgoing | incoming
    closest = [
        b
        for b in idx.neighbours(article)[:NEAR]
        if b not in linked and idx.rank(b, article) <= NEAR_BACK
    ][:suggest]
    return {"weak": sorted(weak, reverse=True), "closest_unlinked": closest}


def wiki_rel(cfg: Config, path: str) -> str:
    """A root-relative article path as the key this module uses (relative to the wiki)."""
    p = Path(path)
    prefix = Path(cfg.store.wiki)
    try:
        return p.relative_to(prefix).as_posix()
    except ValueError:
        return p.as_posix()
