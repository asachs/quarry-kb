"""Discovery — optional semantic link surfacing via a pluggable backend.

Powers three things: the ingest **dedup** pre-check, `related` (link candidates for
one article), and `densify` (whole-wiki mutual top-K unlinked pairs). The v1 backend
shells out to the external `qmd` tool. When the backend is `none` or the tool is
absent, discovery degrades gracefully — core flows (ingest/finish/lint) never depend
on it.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from shutil import which

from quarry import frontmatter
from quarry.config import Config

# status values returned by check()
OK = "ok"
DISABLED = "disabled"  # intentionally off ([discovery] backend = none / mode = off)
MISSING = "missing"  # backend selected but its tool is unavailable


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------


def find_qmd() -> str | None:
    p = which("qmd")
    if p:
        return p
    for c in (
        Path.home() / ".npm-global/bin/qmd",
        Path("/usr/local/bin/qmd"),
        Path("/usr/bin/qmd"),
    ):
        if c.exists():
            return str(c)
    return None


def _run_qmd(qmd: str, subcmd: str, text: str, cwd: Path | None) -> str:
    return subprocess.run(
        [qmd, subcmd, text], cwd=cwd, capture_output=True, text=True
    ).stdout


def parse_qmd_hits(out: str) -> list[tuple[int, str]]:
    """Parse `qmd query`/`vsearch` stdout into [(score, 'wiki/<path>.md')], best-first."""
    hits: list[tuple[int, str]] = []
    cur: str | None = None
    for line in out.splitlines():
        m = re.match(r"qmd://wiki/(\S+\.md)", line)
        if m:
            cur = "wiki/" + m.group(1)
            continue
        s = re.search(r"Score:\s+(\d+)%", line)
        if s and cur:
            hits.append((int(s.group(1)), cur))
            cur = None
    return hits


class NoneBackend:
    """Discovery turned off — always unavailable, returns nothing."""

    def available(self) -> bool:
        return False

    def query(self, text: str, cwd: Path | None = None) -> list[tuple[int, str]]:
        return []


class QmdBackend:
    def __init__(self, qmd_path: str | None):
        self._qmd = qmd_path

    def available(self) -> bool:
        return self._qmd is not None

    def query(self, text: str, cwd: Path | None = None) -> list[tuple[int, str]]:
        if not self._qmd:
            return []
        return parse_qmd_hits(_run_qmd(self._qmd, "query", text, cwd))


def get_backend(cfg: Config):
    if cfg.discovery.backend == "none" or cfg.discovery.mode == "off":
        return NoneBackend()
    return QmdBackend(find_qmd())


def check(cfg: Config) -> tuple[object, str]:
    """Return (backend, status) where status is OK | DISABLED | MISSING."""
    backend = get_backend(cfg)
    if isinstance(backend, NoneBackend):
        return backend, DISABLED
    return backend, OK if backend.available() else MISSING


# ---------------------------------------------------------------------------
# Wiki helpers
# ---------------------------------------------------------------------------


def _wiki_articles(cfg: Config) -> list[Path]:
    wiki = cfg.root / cfg.store.wiki
    index = cfg.lint.index_file or "index.md"
    return sorted(p for p in wiki.rglob("*.md") if p.name != index)


def _title_of(cfg: Config, rel: str) -> str:
    fm = frontmatter.parse((cfg.root / rel).read_text(encoding="utf-8"))
    t = fm.get("title") or Path(rel).stem
    return t.strip('"') if isinstance(t, str) else Path(rel).stem


def _existing_link_stems(text: str, related: object) -> set[str]:
    stems = {Path(r).stem for r in (related or []) if isinstance(r, str)}
    for m in re.finditer(r"\]\(([^)]+?\.md)\)", text):  # body markdown links
        stems.add(Path(m.group(1)).stem)
    return stems


def _query_text(cfg: Config, text: str, limit: int) -> str:
    fm = frontmatter.parse(text)
    title = fm.get("title")
    title = title.strip('"') if isinstance(title, str) else ""
    body = re.sub(r"^---.*?---", "", text, flags=re.S).strip().replace("\n", " ")
    return f"{title} {body[:limit]}".strip()


# ---------------------------------------------------------------------------
# Dedup (used by ingest)
# ---------------------------------------------------------------------------


def dedup_hits(cfg: Config, title: str) -> list[tuple[int, str]]:
    """Articles matching ``title`` at or above the configured dedup threshold."""
    backend = get_backend(cfg)
    if not backend.available():
        return []
    return [
        (s, p) for s, p in backend.query(title, cwd=cfg.root) if s >= cfg.discovery.dedup_threshold
    ]


# ---------------------------------------------------------------------------
# related
# ---------------------------------------------------------------------------


def _resolve_article(cfg: Config, article: str) -> Path:
    direct = cfg.root / article
    if direct.exists():
        return direct
    matches = sorted((cfg.root / cfg.store.wiki).rglob(f"*{Path(article).stem}*.md"))
    if not matches:
        from quarry.errors import QuarryError

        raise QuarryError(f"article not found: {article}")
    return matches[0]


def related(cfg: Config, article: str, backend) -> list[tuple[int, str]]:
    """Ranked link candidates for an article, excluding itself and already-linked."""
    art = _resolve_article(cfg, article)
    text = art.read_text(encoding="utf-8")
    fm = frontmatter.parse(text)
    hits = backend.query(_query_text(cfg, text, 280), cwd=cfg.root)
    skip = _existing_link_stems(text, fm.get(cfg.frontmatter.related_field)) | {art.stem}
    fresh: list[tuple[int, str]] = []
    seen: set[str] = set()
    for score, path in hits:
        stem = Path(path).stem
        if stem not in skip and stem not in seen:
            seen.add(stem)
            fresh.append((score, path))
    return fresh


# ---------------------------------------------------------------------------
# densify
# ---------------------------------------------------------------------------


def mutual_unlinked_pairs(
    nbrs: dict[str, list[tuple[int, str]]], links: dict[str, set[str]]
) -> list[tuple[tuple[str, str], int]]:
    """Pairs where each article is in the other's top-K and neither links the other.

    Score-scale-independent (mutual top-K), so robust to the backend's absolute scale.
    """
    recs: dict[tuple[str, str], int] = {}
    for a, hits in nbrs.items():
        a_score = {pp: s for s, pp in hits}
        for b in a_score:
            b_hits = nbrs.get(b, [])
            if a not in {pp for _, pp in b_hits}:
                continue
            if Path(b).stem in links.get(a, set()) or Path(a).stem in links.get(b, set()):
                continue
            recs[tuple(sorted([a, b]))] = a_score.get(b, 0) + {pp: s for s, pp in b_hits}.get(a, 0)
    return sorted(recs.items(), key=lambda x: -x[1])


def densify_pairs(cfg: Config, topk: int, backend) -> list[tuple[tuple[str, str], int]]:
    nbrs: dict[str, list[tuple[int, str]]] = {}
    links: dict[str, set[str]] = {}
    for p in _wiki_articles(cfg):
        rel = str(p.relative_to(cfg.root))
        text = p.read_text(encoding="utf-8")
        fm = frontmatter.parse(text)
        links[rel] = _existing_link_stems(text, fm.get(cfg.frontmatter.related_field))
        hits = backend.query(_query_text(cfg, text, 240), cwd=cfg.root)
        nbrs[rel] = [(s, pp) for s, pp in hits if pp != rel][:topk]
    return mutual_unlinked_pairs(nbrs, links)


def _add_seealso(cfg: Config, src_rel: str, dst_rel: str) -> bool:
    src = cfg.root / src_rel
    text = src.read_text(encoding="utf-8")
    fm = frontmatter.parse(text)
    if Path(dst_rel).stem in _existing_link_stems(text, fm.get(cfg.frontmatter.related_field)):
        return False
    rel_link = os.path.relpath(cfg.root / dst_rel, start=src.parent)
    bullet = f"- [{_title_of(cfg, dst_rel)}]({rel_link})"
    lines = text.rstrip().splitlines()
    if "## See also" in text:
        idx = next(i for i, ln in enumerate(lines) if ln.strip() == "## See also")
        j = idx + 1
        while j < len(lines) and (lines[j].startswith("- ") or lines[j].strip() == ""):
            j += 1
        lines.insert(j, bullet)
        src.write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        src.write_text(text.rstrip() + "\n\n## See also\n\n" + bullet + "\n", encoding="utf-8")
    return True


def apply_pairs(cfg: Config, pairs: list[tuple[tuple[str, str], int]]) -> int:
    added = 0
    for (a, b), _ in pairs:
        added += _add_seealso(cfg, a, b)
        added += _add_seealso(cfg, b, a)
    return added
