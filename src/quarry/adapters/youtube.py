"""YouTube adapter — transcript via youtube-transcript-api + oEmbed metadata.

Network calls live in ``_fetch_transcript`` / ``_fetch_oembed`` so tests can
override them and stay hermetic. Requires the ``[youtube]`` extra at fetch time.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
import urllib.parse
import urllib.request

from quarry.adapters.base import Adapter, FetchResult
from quarry.errors import QuarryError

_ID_PATTERNS = (
    r"(?:v=)([\w-]{11})",
    r"youtu\.be/([\w-]{11})",
    r"youtube\.com/shorts/([\w-]{11})",
    r"youtube\.com/embed/([\w-]{11})",
)


def _today_iso() -> str:
    return _dt.date.today().isoformat()


class YouTubeAdapter(Adapter):
    name = "youtube"

    def matches(self, url: str) -> bool:
        return "youtube.com" in url or "youtu.be" in url

    def video_id(self, url: str) -> str:
        for pat in _ID_PATTERNS:
            m = re.search(pat, url)
            if m:
                return m.group(1)
        raise QuarryError(f"could not parse a YouTube video id from: {url}")

    # --- overridable network methods -------------------------------------
    def _fetch_transcript(self, vid: str) -> str:
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
        except ImportError as e:
            raise QuarryError(
                "youtube adapter needs the [youtube] extra "
                "(pip install 'quarry[youtube]')"
            ) from e
        fetched = YouTubeTranscriptApi().fetch(vid)
        snippets = getattr(fetched, "snippets", fetched)
        return " ".join((getattr(s, "text", None) or s["text"]) for s in snippets).strip()

    def _fetch_oembed(self, url: str) -> dict:
        q = urllib.parse.urlencode({"url": url, "format": "json"})
        with urllib.request.urlopen(  # noqa: S310 - https oEmbed endpoint
            f"https://www.youtube.com/oembed?{q}", timeout=15
        ) as resp:
            return json.loads(resp.read().decode())

    # --- contract --------------------------------------------------------
    def fetch(self, url: str) -> FetchResult:
        vid = self.video_id(url)
        try:
            meta = self._fetch_oembed(url)
        except Exception:  # noqa: BLE001 - metadata is best-effort
            meta = {}
        content = self._fetch_transcript(vid)
        return FetchResult(
            content=content,
            metadata={
                "title": meta.get("title") or f"youtube-{vid}",
                "author": meta.get("author_name") or "unknown",
                "date": _today_iso(),
                "url": url,
                "source_id": vid,
            },
        )
