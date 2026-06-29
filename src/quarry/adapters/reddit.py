"""Reddit adapter — post + comments, with an optional OAuth path.

Two fetch paths, chosen automatically:

1. **OAuth (reliable, recommended)** — if ``QUARRY_REDDIT_CLIENT_ID`` and
   ``QUARRY_REDDIT_CLIENT_SECRET`` are set, fetch via PRAW in read-only mode. This gets
   Reddit's authenticated budget (~100 queries/min per client id) and is not subject to
   the opaque IP-reputation throttling that hits the no-key path. Requires the
   ``[reddit-oauth]`` extra. **No Reddit username/password needed** — read-only uses the
   application-only (client-credentials) grant.

2. **No-key (best-effort, fallback)** — the public ``.json`` endpoint via **curl_cffi**
   (``impersonate="chrome"``). Reddit TLS/JA3-fingerprint-blocks pure-Python HTTP
   (urllib/requests/httpx get 403; a browser handshake gets 200), and curl_cffi swaps the
   TLS stack to match Chrome. Rate-limited and IP-reputation throttled — fine for the odd
   link, unreliable at volume. Requires the ``[reddit]`` extra.

## Setting up OAuth (one-time, ~2 minutes)

1. Go to https://www.reddit.com/prefs/apps  → "create another app…".
2. Choose type **"script"**, give it any name, set redirect uri to
   ``http://localhost:8080`` (unused for read-only). Create it.
3. The **client id** is the string just under the app name ("personal use script");
   the **client secret** is the ``secret`` field.
4. Export them where Quarry runs (shell profile, container env, etc.):
   ``export QUARRY_REDDIT_CLIENT_ID=...`` and ``export QUARRY_REDDIT_CLIENT_SECRET=...``.
5. ``pip install 'quarry-kb[reddit-oauth]'``. Quarry uses OAuth automatically when both
   vars are present, else falls back to the no-key path. ``quarry doctor`` shows which.

Network methods are overridable so the default test suite stays hermetic.
"""

from __future__ import annotations

import datetime as _dt
import os
import re

from quarry.adapters.base import Adapter, FetchResult
from quarry.errors import QuarryError

_TOP_COMMENTS = 20
_CID_ENV = "QUARRY_REDDIT_CLIENT_ID"
_SECRET_ENV = "QUARRY_REDDIT_CLIENT_SECRET"


def _ua() -> str:
    from quarry import __version__

    # Reddit's required descriptive format: <platform>:<app id>:<version> (by /u/<user>)
    return f"python:quarry-kb:{__version__} (by /u/quarry-kb)"


def oauth_configured() -> bool:
    return bool(os.getenv(_CID_ENV) and os.getenv(_SECRET_ENV))


class RedditAdapter(Adapter):
    name = "reddit"

    def matches(self, url: str) -> bool:
        return "reddit.com/" in url or "redd.it/" in url

    @staticmethod
    def _json_url(base: str) -> str:
        return base.split("?")[0].rstrip("/") + ".json"

    def _assemble(
        self,
        *,
        title: str,
        author: str,
        subreddit: str,
        selftext: str,
        link: str,
        created: float | None,
        comments_md: str,
        url: str,
        source_id: str,
    ) -> FetchResult:
        date = (
            _dt.datetime.fromtimestamp(created, tz=_dt.UTC).date().isoformat()
            if created
            else _dt.date.today().isoformat()
        )
        parts = [f"# {title}", f"r/{subreddit} — posted by u/{author}", ""]
        if selftext.strip():
            parts += [selftext.strip(), ""]
        elif link and link != url:
            parts += [f"Link post: {link}", ""]
        if comments_md:
            parts += ["## Top comments", "", comments_md]
        return FetchResult(
            content="\n".join(parts).strip() + "\n",
            metadata={
                "title": title or f"reddit-{source_id}",
                "author": f"u/{author}",
                "date": date,
                "url": url,
                "source_id": source_id or re.sub(r"\W+", "", url)[-12:],
            },
        )

    # --- OAuth path (PRAW, read-only) -------------------------------------
    def _fetch_via_praw(self, url: str) -> FetchResult:  # pragma: no cover - network/extra
        try:
            import praw
        except ImportError as e:
            raise QuarryError(
                "reddit OAuth needs the [reddit-oauth] extra "
                "(pip install 'quarry-kb[reddit-oauth]')"
            ) from e
        reddit = praw.Reddit(
            client_id=os.getenv(_CID_ENV),
            client_secret=os.getenv(_SECRET_ENV),
            user_agent=_ua(),
        )
        sub = reddit.submission(url=url)  # PRAW resolves /s/ share links too
        sub.comments.replace_more(limit=0)
        rendered: list[str] = []
        for c in sub.comments.list()[:_TOP_COMMENTS]:
            body = (getattr(c, "body", "") or "").strip()
            if body:
                rendered.append(f"**u/{c.author}** ({getattr(c, 'score', 0)} pts): {body}")
        return self._assemble(
            title=sub.title or "",
            author=str(sub.author),
            subreddit=str(sub.subreddit),
            selftext=sub.selftext or "",
            link=sub.url or url,
            created=getattr(sub, "created_utc", None),
            comments_md="\n\n".join(rendered),
            url=url,
            source_id=sub.id,
        )

    # --- no-key path (curl_cffi defeats Reddit's TLS/JA3 block) -----------
    def _fetch_json(self, url: str) -> list:  # pragma: no cover - network/extra
        try:
            from curl_cffi import requests as cffi
        except ImportError as e:
            raise QuarryError(
                "reddit adapter needs the [reddit] extra (pip install 'quarry-kb[reddit]')"
            ) from e
        headers = {"User-Agent": _ua()}
        base = url.split("?")[0]
        if "/s/" in base:  # share link -> resolve to the canonical permalink
            r = cffi.get(base, impersonate="chrome", headers=headers, timeout=20)
            base = str(r.url).split("?")[0]
        resp = cffi.get(self._json_url(base), impersonate="chrome", headers=headers, timeout=20)
        if resp.status_code == 403:
            raise QuarryError(
                "reddit: HTTP 403 (IP-reputation throttle; no Retry-After communicated). "
                "Configure OAuth (QUARRY_REDDIT_CLIENT_ID/SECRET) for reliable access."
            )
        if resp.status_code != 200:
            raise QuarryError(f"reddit: HTTP {resp.status_code} for {url}")
        return resp.json()

    def _fetch_via_json(self, url: str) -> FetchResult:
        data = self._fetch_json(url)
        try:
            post = data[0]["data"]["children"][0]["data"]
        except (KeyError, IndexError, TypeError) as e:
            raise QuarryError(f"reddit: unexpected response shape for {url}") from e
        rendered: list[str] = []
        listing = data[1] if len(data) > 1 else {}
        for child in listing.get("data", {}).get("children", []):
            if child.get("kind") != "t1":
                continue
            d = child.get("data", {})
            body = (d.get("body") or "").strip()
            if body:
                au = d.get("author") or "[deleted]"
                rendered.append(f"**u/{au}** ({d.get('score', 0)} pts): {body}")
            if len(rendered) >= _TOP_COMMENTS:
                break
        return self._assemble(
            title=post.get("title") or "",
            author=post.get("author") or "unknown",
            subreddit=post.get("subreddit") or "",
            selftext=post.get("selftext") or "",
            link=post.get("url") or url,
            created=post.get("created_utc"),
            comments_md="\n\n".join(rendered),
            url=url,
            source_id=post.get("id") or "",
        )

    # --- contract ---------------------------------------------------------
    def fetch(self, url: str) -> FetchResult:
        if oauth_configured():
            return self._fetch_via_praw(url)
        return self._fetch_via_json(url)
