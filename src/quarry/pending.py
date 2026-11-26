"""What has been captured but not compiled, and where a given URL stands.

`ingest` needs no model; writing the article does. When the model is unavailable (a rate
limit, an exhausted quota) the capture can still be taken, and something has to remember
that an article is owed. The compile-manifest already is that record: a manifest whose raw
source no article cites is a pending compile. ``pending`` lists them; ``status`` answers
"has this URL been captured or compiled?" so a queue of submitted URLs can be drained
without asking a model.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from quarry import frontmatter
from quarry.config import Config
from quarry.store import manifest_dir, raw_dir, wiki_dir

ABSENT, CAPTURED, COMPILED = "absent", "captured", "compiled"

# Query parameters that identify the share, not the thing shared.
_TRACKING = re.compile(
    r"^(utm_.*|igsh|igshid|img_index|si|fbclid|gclid|feature|ref|ref_src)$", re.I
)
_SOURCE_LINE = re.compile(r"^source:\s*(.+?)\s*$", re.M)


def normalize_url(url: str) -> str:
    """A URL reduced to what identifies the page: lower-case scheme and host, no ``www.``,
    no fragment, no tracking parameters, no trailing slash. Other query parameters stay
    (``watch?v=`` is the identity of a YouTube video)."""
    parts = urlsplit(url.strip().strip("\"'<>"))
    host = parts.netloc.lower().removeprefix("www.")
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if not _TRACKING.match(k)])
    scheme = "https" if parts.scheme.lower() in ("http", "https") else parts.scheme.lower()
    return urlunsplit((scheme, host, parts.path.rstrip("/"), query, ""))


def _cited(cfg: Config) -> dict[str, list[str]]:
    """Map of raw path (root-relative) to the wiki articles whose sources field cites it."""
    out: dict[str, list[str]] = {}
    for p in sorted(wiki_dir(cfg).rglob("*.md")):
        try:
            fm = frontmatter.parse(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - an unparseable article cites nothing
            continue
        sources = fm.get(cfg.frontmatter.sources_field) or []
        for s in [sources] if isinstance(sources, str) else sources:
            if isinstance(s, str):
                out.setdefault(s, []).append(p.relative_to(cfg.root).as_posix())
    return out


def _manifests(cfg: Config) -> list[dict]:
    out = []
    d = manifest_dir(cfg)
    for p in sorted(d.glob("*.json")) if d.is_dir() else []:
        try:
            m = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(m, dict) and m.get("slug") and m.get("raw_path"):
            m["_mtime"] = p.stat().st_mtime
            out.append(m)
    return out


def pending(cfg: Config) -> list[dict]:
    """Manifests whose raw source exists and is cited by no article, oldest first."""
    cited = _cited(cfg)
    out = []
    for m in _manifests(cfg):
        if m["raw_path"] in cited or not (cfg.root / m["raw_path"]).exists():
            continue
        out.append(
            {
                "slug": m["slug"],
                "source_url": m.get("source_url", ""),
                "raw_path": m["raw_path"],
                "target_wiki_path": m.get("target_wiki_path"),
                "captured_at": m["_mtime"],
            }
        )
    return sorted(out, key=lambda r: r["captured_at"])


def _raw_source(path: Path) -> str | None:
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            head = fh.read(2000)
    except OSError:
        return None
    if not head.startswith("---"):
        return None
    m = _SOURCE_LINE.search(head.split("\n---", 1)[0])
    return m.group(1) if m else None


def status(cfg: Config, url: str) -> dict:
    """Where ``url`` stands: ``absent``, ``captured`` (a raw exists, no article cites it) or
    ``compiled``. Looks at manifests and at every raw file's ``source:`` line, so a capture
    made on another machine (manifests are local) or by hand still counts."""
    want = normalize_url(url)
    raws: dict[str, str | None] = {}
    for m in _manifests(cfg):
        if normalize_url(m.get("source_url", "")) == want and (cfg.root / m["raw_path"]).exists():
            raws[m["raw_path"]] = m["slug"]
    root = raw_dir(cfg)
    for p in sorted(root.rglob("*.md")) if root.is_dir() else []:
        src = _raw_source(p)
        if src and normalize_url(src) == want:
            raws.setdefault(p.relative_to(cfg.root).as_posix(), None)
    if not raws:
        return {"url": url, "state": ABSENT, "raw_paths": [], "slugs": [], "articles": []}
    cited = _cited(cfg)
    articles = sorted({a for r in raws for a in cited.get(r, [])})
    return {
        "url": url,
        "state": COMPILED if articles else CAPTURED,
        "raw_paths": sorted(raws),
        "slugs": sorted(s for s in raws.values() if s),
        "articles": articles,
    }
