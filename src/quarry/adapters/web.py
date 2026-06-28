"""Web adapter — readable-content extraction via trafilatura.

The HTTP download lives in ``_download`` so tests can override it and run the
extraction hermetically against fixture HTML. Requires the ``[web]`` extra at
fetch time.
"""

from __future__ import annotations

import datetime as _dt
import urllib.parse
import urllib.request

from quarry.adapters.base import Adapter, FetchResult
from quarry.errors import QuarryError


class WebAdapter(Adapter):
    name = "web"

    def matches(self, url: str) -> bool:
        return url.startswith(("http://", "https://"))

    # --- overridable network method --------------------------------------
    def _download(self, url: str) -> str:
        with urllib.request.urlopen(url, timeout=20) as resp:  # noqa: S310
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.read().decode(charset, errors="replace")

    # --- extraction (pure; needs the [web] extra) ------------------------
    def _extract(self, html: str, url: str) -> tuple[str, dict]:
        try:
            import trafilatura
        except ImportError as e:
            raise QuarryError(
                "web adapter needs the [web] extra (pip install 'quarry-kb[web]')"
            ) from e

        content = trafilatura.extract(html, url=url, include_comments=False) or ""
        if not content.strip():
            raise QuarryError(f"web adapter could not extract readable content from: {url}")

        title = author = date = None
        try:
            md = trafilatura.extract_metadata(html)
            if md is not None:
                title = getattr(md, "title", None)
                author = getattr(md, "author", None)
                date = getattr(md, "date", None)
        except Exception:  # noqa: BLE001 - metadata is best-effort
            pass

        host = urllib.parse.urlparse(url).netloc
        meta = {
            "title": title or host or url,
            "author": author or "unknown",
            "date": date or _dt.date.today().isoformat(),
            "url": url,
            "source_id": host or url,
        }
        return content, meta

    # --- contract --------------------------------------------------------
    def fetch(self, url: str) -> FetchResult:
        html = self._download(url)
        content, meta = self._extract(html, url)
        return FetchResult(content=content, metadata=meta)
