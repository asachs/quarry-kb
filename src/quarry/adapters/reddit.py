"""Reddit adapter — post + comments via the public ``.json`` endpoint.

Reddit TLS/JA3-fingerprint-blocks pure-Python HTTP (urllib/requests/httpx get 403
where curl gets 200), so the fetch uses **curl_cffi** with ``impersonate="chrome"`` to
present a real browser handshake. No API key; rate-limited (~best-effort) — for reliable
high-volume use, the OAuth/PRAW path is the documented upgrade. Requires the ``[reddit]``
extra (curl_cffi). The fetch lives in an overridable method so tests stay hermetic.
"""

from __future__ import annotations

import datetime as _dt
import re

from quarry.adapters.base import Adapter, FetchResult
from quarry.errors import QuarryError

_TOP_COMMENTS = 20


def _ua() -> str:
    from quarry import __version__

    # Reddit's required descriptive format: <platform>:<app id>:<version> (by /u/<user>)
    return f"python:quarry-kb:{__version__} (by /u/quarry-kb)"


class RedditAdapter(Adapter):
    name = "reddit"

    def matches(self, url: str) -> bool:
        return "reddit.com/" in url or "redd.it/" in url

    @staticmethod
    def _json_url(base: str) -> str:
        return base.split("?")[0].rstrip("/") + ".json"

    # --- overridable network method (curl_cffi defeats Reddit's TLS/JA3 block) ----
    def _fetch_json(self, url: str) -> list:  # pragma: no cover - network/extra
        try:
            from curl_cffi import requests as cffi
        except ImportError as e:
            raise QuarryError(
                "reddit adapter needs the [reddit] extra (pip install 'quarry-kb[reddit]')"
            ) from e
        headers = {"User-Agent": _ua()}
        base = url.split("?")[0]
        if "/s/" in base:  # share link -> resolve to the canonical permalink first
            r = cffi.get(base, impersonate="chrome", headers=headers, timeout=20)
            base = str(r.url).split("?")[0]
        resp = cffi.get(self._json_url(base), impersonate="chrome", headers=headers, timeout=20)
        if resp.status_code == 403:
            raise QuarryError(
                "reddit: HTTP 403 (rate-limited or IP-throttled). Space requests out, or "
                "configure OAuth for reliable access."
            )
        if resp.status_code != 200:
            raise QuarryError(f"reddit: HTTP {resp.status_code} for {url}")
        return resp.json()

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
