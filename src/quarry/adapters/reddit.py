"""Reddit adapter — best-effort, fighting a losing battle against Reddit's lockdown.

⚠️ **Reality check (2026): Reddit is actively hostile to programmatic access.** Both
paths below are degraded by design on Reddit's side, and this only gets worse over time:

- **No-key path is throttled.** The public ``.json`` endpoint is TLS/JA3-fingerprint
  -blocked for pure-Python clients (urllib/requests/httpx → 403; a real browser handshake
  → 200), so we fetch via **curl_cffi** (``impersonate="chrome"``) to look like Chrome.
  Even then it's IP-reputation rate-limited: a burst trips an opaque block that serves an
  HTML page with **no Retry-After / no X-Ratelimit headers** — you can't pace around it or
  know when it clears. Fine for the *occasional* link; unreliable at any volume.
- **OAuth path is gated.** Reddit's *Responsible Builder Policy* (Nov 2025) now requires
  **pre-approval for ALL apps, including personal/hobby scripts** — you can no longer
  self-serve a script app at reddit.com/prefs/apps; you must apply and be approved. The
  policy also restricts using Reddit data for AI/ML. So OAuth is not a 2-minute setup.

**Bottom line: treat Reddit as best-effort.** It works for the odd link when the IP isn't
throttled. For a thread that won't fetch, use the ``web`` adapter on the
``old.reddit.com`` permalink, or just paste the text. Don't build anything that *depends*
on reliable Reddit ingestion.

## Fetch paths (chosen automatically)

1. **OAuth** — used iff ``QUARRY_REDDIT_CLIENT_ID`` + ``QUARRY_REDDIT_CLIENT_SECRET`` are
   set (PRAW, read-only client-credentials grant — no username/password; ``[reddit-oauth]``
   extra). ~100 QPM, sidesteps the IP throttle — *if* you've been granted API access.
2. **No-key** — curl_cffi against ``.json`` (``[reddit]`` extra). The default fallback.

### If you do get API access (Responsible Builder approval)
Create a **script** app, then set ``QUARRY_REDDIT_CLIENT_ID`` / ``QUARRY_REDDIT_CLIENT_SECRET``
in the environment where Quarry runs and ``pip install 'quarry-kb[reddit-oauth]'``. Quarry
switches to OAuth automatically; ``quarry doctor`` shows which path is active.

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
