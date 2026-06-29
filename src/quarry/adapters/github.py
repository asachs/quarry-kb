"""GitHub adapter — repo digest via gitingest (deterministic, no LLM, no key).

Wraps ``gitingest`` (summary + directory tree + concatenated file contents). The
ingest call lives in an overridable method so tests stay hermetic. Requires the
``[github]`` extra.
"""

from __future__ import annotations

import datetime as _dt
import re

from quarry.adapters.base import Adapter, FetchResult
from quarry.errors import QuarryError

_MAX_CONTENT = 200_000  # cap the concatenated digest; raw is material, not the article


class GitHubAdapter(Adapter):
    name = "github"

    def matches(self, url: str) -> bool:
        return bool(re.match(r"https?://github\.com/[^/]+/[^/]+", url))

    # --- overridable, needs the [github] extra ----------------------------
    def _ingest(self, url: str) -> tuple[str, str, str]:  # pragma: no cover - network/extra
        try:
            from gitingest import ingest
        except ImportError as e:
            raise QuarryError(
                "github adapter needs the [github] extra (pip install 'quarry-kb[github]')"
            ) from e
        summary, tree, content = ingest(url)
        return summary, tree, content

    # --- contract ---------------------------------------------------------
    def fetch(self, url: str) -> FetchResult:
        m = re.match(r"https?://github\.com/([^/]+)/([^/?#]+)", url)
        if not m:
            raise QuarryError(f"github: could not parse owner/repo from {url}")
        owner, repo = m.group(1), m.group(2).removesuffix(".git")

        summary, tree, content = self._ingest(url)
        if len(content) > _MAX_CONTENT:
            content = content[:_MAX_CONTENT] + "\n\n[... truncated ...]\n"
        body = (
            f"# {owner}/{repo}\n\n## Summary\n\n{summary}\n\n"
            f"## Tree\n\n{tree}\n\n## Contents\n\n{content}"
        )

        return FetchResult(
            content=body,
            metadata={
                "title": f"{owner}/{repo}",
                "author": owner,
                "date": _dt.date.today().isoformat(),
                "url": url,
                "source_id": f"{owner}/{repo}",
            },
        )
