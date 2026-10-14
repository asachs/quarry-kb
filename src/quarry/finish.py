"""Finish — the second half of the two-call seam.

Verify the written article against the compile-manifest (provenance), lint the wiki,
then commit. Pushes only when explicitly opted in. The manifest is *verified*, never
trusted: a missing article or an article that doesn't cite its source aborts.

By default (``[finish] stage = "scoped"``) only this ingest's files are committed: the
raw, its assets, the article, the index, and changed wiki files that link to the
article (the cross-links written alongside it). Unrelated work in the tree is left
alone, so one in-progress ingest is never swept into another's commit.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from quarry import frontmatter, git, lint, manifest
from quarry.config import Config
from quarry.errors import QuarryError


def _sources_of(path: Path, field: str) -> list[str]:
    try:
        fm = frontmatter.parse(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - an unparseable article simply doesn't match
        return []
    sources = fm.get(field) or []
    return [sources] if isinstance(sources, str) else [s for s in sources if isinstance(s, str)]


def find_citing_articles(cfg: Config, raw_path: str) -> list[str]:
    """Wiki articles whose sources field cites ``raw_path`` (root-relative)."""
    wiki = cfg.root / cfg.store.wiki
    hits = []
    for p in sorted(wiki.rglob("*.md")):
        if raw_path in _sources_of(p, cfg.frontmatter.sources_field):
            hits.append(p.relative_to(cfg.root).as_posix())
    return hits


def _resolve_article(cfg: Config, m: dict, article: str | None) -> str:
    if article:
        if not (cfg.root / article).exists():
            raise QuarryError(f"wiki article not found: {article} — write it before finishing")
        return article
    target = m.get("target_wiki_path")
    if target and (cfg.root / target).exists():
        return target
    citing = find_citing_articles(cfg, m["must_cite_source"])
    if len(citing) == 1:
        return citing[0]
    if len(citing) > 1:
        raise QuarryError(
            f"several articles cite {m['must_cite_source']}: {', '.join(citing)} "
            "— pass --article <path>"
        )
    if target:
        raise QuarryError(f"wiki article not found: {target} — write it before finishing")
    raise QuarryError("no article path — pass --article <path>")


def _title(path: Path) -> str:
    fm = frontmatter.parse(path.read_text(encoding="utf-8"))
    t = fm.get("title")
    return t.strip().strip('"') if isinstance(t, str) and t.strip() else path.stem


def add_index_entry(cfg: Config, article_rel: str) -> bool:
    """Append ``article_rel`` to ``[lint] index_file`` if it isn't referenced there.

    The entry goes under the heading whose existing entries most often point into the
    article's top-level wiki folder; with no such heading it is appended at the end.
    Returns True if the index was changed.
    """
    if not cfg.lint.index_file:
        return False
    wiki = cfg.root / cfg.store.wiki
    index = wiki / cfg.lint.index_file
    if not index.exists():
        return False
    article_abs = cfg.root / article_rel
    link = os.path.relpath(article_abs, start=index.parent).replace(os.sep, "/")
    text = index.read_text(encoding="utf-8")
    if f"]({link})" in text or f"]({link}#" in text:
        return False
    folder = Path(link).parts[0] if len(Path(link).parts) > 1 else ""
    fm = frontmatter.parse(article_abs.read_text(encoding="utf-8"))
    summary = fm.get("summary") or fm.get("description")
    entry = f"- [{_title(article_abs)}]({link})"
    if isinstance(summary, str) and summary.strip():
        entry += f" — {summary.strip()}"

    lines = text.rstrip("\n").split("\n")
    best, best_n, heading = None, 0, None
    counts: dict[int, int] = {}
    last_item: dict[int, int] = {}
    for i, ln in enumerate(lines):
        if re.match(r"^#{1,6} ", ln):
            heading = i
            continue
        if heading is None:
            continue
        for target in re.findall(r"\]\(([^)#\s]+\.md)", ln):
            if folder and target.split("/")[0] == folder:
                counts[heading] = counts.get(heading, 0) + 1
        if ln.lstrip().startswith(("- ", "* ")):
            last_item[heading] = i
    for h, n in counts.items():
        if n > best_n:
            best, best_n = h, n
    if best is not None and best in last_item:
        lines.insert(last_item[best] + 1, entry)
    else:
        lines += ["", entry]
    index.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True


def _links_to(path: Path, article_abs: Path) -> bool:
    if path.suffix != ".md" or not path.exists():
        return False
    text = path.read_text(encoding="utf-8", errors="ignore")
    for target in re.findall(r"\]\(([^)#\s]+\.md)", text):
        if (path.parent / target).resolve() == article_abs.resolve():
            return True
    return False


def scoped_paths(cfg: Config, m: dict, article_rel: str) -> list[str]:
    """This ingest's files among the working tree's changes."""
    article_abs = cfg.root / article_rel
    own = {m["raw_path"], article_rel, *m.get("assets", [])}
    if cfg.lint.index_file:
        own.add(f"{cfg.store.wiki}/{cfg.lint.index_file}")
    asset_dirs = {str(Path(a).parent) for a in m.get("assets", [])}
    cited = set(_sources_of(article_abs, cfg.frontmatter.sources_field))
    wiki_prefix = cfg.store.wiki.rstrip("/") + "/"
    picked = []
    for rel in git.changed_paths(cfg.root):
        if (
            rel in own
            or rel in cited
            or str(Path(rel).parent) in asset_dirs
            or (rel.startswith(wiki_prefix) and _links_to(cfg.root / rel, article_abs))
        ):
            picked.append(rel)
    return sorted(picked)


def run(cfg: Config, slug: str, *, article: str | None = None, push: bool = False) -> dict:
    m = manifest.load(cfg, slug)
    article_rel = _resolve_article(cfg, m, article)
    article_abs = cfg.root / article_rel

    sources = _sources_of(article_abs, cfg.frontmatter.sources_field)
    if m["must_cite_source"] not in sources:
        raise QuarryError(
            f"provenance check failed: {article_rel} frontmatter "
            f"`{cfg.frontmatter.sources_field}:` must include '{m['must_cite_source']}' "
            f"(found: {sources})"
        )

    indexed = add_index_entry(cfg, article_rel) if cfg.finish.auto_index else False

    lint_result = None
    if cfg.finish.run_lint:
        lint_result = lint.run(cfg)
        if lint_result.fails(cfg.lint.fail_on):
            raise QuarryError(f"lint failed: {lint_result.summary(cfg.lint.fail_on)}")

    should_push = push or cfg.finish.auto_push
    committed = False
    staged: list[str] = []
    if git.is_repo(cfg.root):
        message = cfg.finish.commit_template.format(slug=m["slug"])
        if cfg.finish.stage == "all":
            git.add_all(cfg.root)
            git.commit(cfg.root, message)
            committed = True
        else:
            staged = scoped_paths(cfg, m, article_rel)
            committed = git.commit_paths(cfg.root, staged, message)
        if committed and should_push:
            git.push(cfg.root)

    return {
        "article": article_rel,
        "committed": committed,
        "pushed": committed and should_push,
        "lint": lint_result,
        "indexed": indexed,
        "staged": staged,
    }
