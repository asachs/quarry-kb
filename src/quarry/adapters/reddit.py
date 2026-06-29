"""Reddit adapter — post + comments via the public ``.json`` endpoint.

Every public Reddit URL accepts a ``.json`` suffix and returns the post plus its
comment tree, with no API key (rate-limited ~10-60/min; needs a real User-Agent).
Stdlib-only — no extra. The network fetch lives in an overridable method so tests
stay hermetic.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
import urllib.request

from quarry.adapters.base import Adapter, FetchResult
from quarry.errors import QuarryError

_UA = "quarry-kb (+https://github.com/asachs/quarry-kb)"
_TOP_COMMENTS = 20


class RedditAdapter(Adapter):
    name = "reddit"

    def matches(self, url: str) -> bool:
        return "reddit.com/" in url or "redd.it/" in url

    # --- overridable network method ---------------------------------------
    def _resolve(self, url: str) -> str:  # pragma: no cover - network
        """Follow a /s/ share-link redirect to its canonical permalink."""
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310
            return resp.url

    @staticmethod
    def _json_url(base: str) -> str:
        return base.split("?")[0].rstrip("/") + ".json"

    def _fetch_json(self, url: str) -> list:  # pragma: no cover - network
        base = url.split("?")[0]
        if "/s/" in base:  # share link -> resolve to the real permalink first
            base = self._resolve(base)
        req = urllib.request.Request(
            self._json_url(base), headers={"User-Agent": _UA}
        )
        with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310
            return json.loads(resp.read().decode("utf-8", errors="replace"))

    # --- helpers ----------------------------------------------------------
    @staticmethod
    def _render_comments(listing: dict, limit: int = _TOP_COMMENTS) -> str:
        out: list[str] = []
        for child in listing.get("data", {}).get("children", []):
            if child.get("kind") != "t1":
                continue
            d = child.get("data", {})
            body = (d.get("body") or "").strip()
            if not body:
                continue
            author = d.get("author") or "[deleted]"
            score = d.get("score", 0)
            out.append(f"**u/{author}** ({score} pts): {body}")
            if len(out) >= limit:
                break
        return "\n\n".join(out)

    # --- contract ---------------------------------------------------------
    def fetch(self, url: str) -> FetchResult:
        data = self._fetch_json(url)
        try:
            post = data[0]["data"]["children"][0]["data"]
        except (KeyError, IndexError, TypeError) as e:
            raise QuarryError(f"reddit: unexpected response shape for {url}") from e

        title = post.get("title") or f"reddit-{post.get('id', '')}"
        author = post.get("author") or "unknown"
        subreddit = post.get("subreddit") or ""
        selftext = (post.get("selftext") or "").strip()
        link = post.get("url") or url
        created = post.get("created_utc")
        date = (
            _dt.datetime.fromtimestamp(created, tz=_dt.UTC).date().isoformat()
            if created
            else _dt.date.today().isoformat()
        )

        parts = [f"# {title}", f"r/{subreddit} — posted by u/{author}", ""]
        if selftext:
            parts += [selftext, ""]
        elif link and link != url:
            parts += [f"Link post: {link}", ""]
        comments = self._render_comments(data[1]) if len(data) > 1 else ""
        if comments:
            parts += ["## Top comments", "", comments]

        return FetchResult(
            content="\n".join(parts).strip() + "\n",
            metadata={
                "title": title,
                "author": f"u/{author}",
                "date": date,
                "url": url,
                "source_id": post.get("id") or re.sub(r"\W+", "", url)[-12:],
            },
        )
