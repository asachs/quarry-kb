"""Finish — the second half of the two-call seam.

Verify the written article against the compile-manifest (provenance), lint the wiki,
then commit. Pushes only when explicitly opted in. The manifest is *verified*, never
trusted: a missing article or an article that doesn't cite its source aborts.
"""

from __future__ import annotations

from quarry import frontmatter, git, lint, manifest
from quarry.config import Config
from quarry.errors import QuarryError


def run(cfg: Config, slug: str, *, article: str | None = None, push: bool = False) -> dict:
    m = manifest.load(cfg, slug)

    article_rel = article or m.get("target_wiki_path")
    if not article_rel:
        raise QuarryError("no article path — pass --article <path>")
    article_abs = cfg.root / article_rel
    if not article_abs.exists():
        raise QuarryError(f"wiki article not found: {article_rel} — write it before finishing")

    fm = frontmatter.parse(article_abs.read_text(encoding="utf-8"))
    sources = fm.get(cfg.frontmatter.sources_field) or []
    if isinstance(sources, str):
        sources = [sources]
    if m["must_cite_source"] not in sources:
        raise QuarryError(
            f"provenance check failed: {article_rel} frontmatter "
            f"`{cfg.frontmatter.sources_field}:` must include '{m['must_cite_source']}' "
            f"(found: {sources})"
        )

    lint_result = None
    if cfg.finish.run_lint:
        lint_result = lint.run(cfg)
        if lint_result.fails(cfg.lint.fail_on):
            raise QuarryError(f"lint failed: {lint_result.summary(cfg.lint.fail_on)}")

    should_push = push or cfg.finish.auto_push
    committed = False
    if git.is_repo(cfg.root):
        git.add_all(cfg.root)
        git.commit(cfg.root, cfg.finish.commit_template.format(slug=m["slug"]))
        committed = True
        if should_push:
            git.push(cfg.root)

    return {
        "article": article_rel,
        "committed": committed,
        "pushed": committed and should_push,
        "lint": lint_result,
    }
