"""Web adapter — readable-content extraction via trafilatura.

The HTTP download lives in ``_open`` / ``_download`` so tests can override them and run
the extraction hermetically against fixture HTML. Requires the ``[web]`` extra at fetch
time.

A URL is routed here when no more specific adapter claims it, and the PDF adapter claims
only URLs that end in ``.pdf``. Plenty of PDFs are served from URLs that do not
(``arxiv.org/pdf/1706.03762``, download endpoints, DOIs): the page arrives, it is not HTML,
and extraction fails with nothing to say why. So the response is checked: if it is a PDF,
by its first bytes or its content type, it is handed to the PDF adapter.
"""

from __future__ import annotations

import datetime as _dt
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

from quarry import capture
from quarry.adapters.base import Adapter, FetchResult
from quarry.errors import QuarryError


class _PdfResponse(Exception):
    """The URL served a PDF; carries its bytes to ``fetch``."""

    def __init__(self, data: bytes, content_type: str):
        super().__init__("the URL served a PDF")
        self.data = data
        self.content_type = content_type


class WebAdapter(Adapter):
    name = "web"

    def matches(self, url: str) -> bool:
        return url.startswith(("http://", "https://"))

    # --- overridable network method --------------------------------------
    def _open(self, url: str) -> tuple[bytes, str, str]:  # pragma: no cover - network
        """``(body, content type, charset)`` of the response."""
        with urllib.request.urlopen(url, timeout=20) as resp:  # noqa: S310
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.read(), resp.headers.get_content_type() or "", charset

    def _download(self, url: str) -> str:
        data, content_type, charset = self._open(url)
        if data[:1024].lstrip().startswith(b"%PDF-") or content_type == "application/pdf":
            raise _PdfResponse(data, content_type)
        return data.decode(charset, errors="replace")

    def _as_pdf(self, url: str, response: _PdfResponse) -> FetchResult:
        from quarry.adapters.pdf import PdfAdapter

        pdf = PdfAdapter()
        pdf.cfg = self.cfg
        with tempfile.NamedTemporaryFile(suffix=".pdf") as fh:
            fh.write(response.data)
            fh.flush()
            result = pdf.from_path(url, Path(fh.name))
        kind = response.content_type or "no content type"
        result.stages.insert(
            0,
            capture.stage(
                "page fetched",
                capture.OK,
                f"{len(response.data):,} bytes; the URL served a PDF ({kind}), "
                "so it was read as one",
            ),
        )
        return result

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
        try:
            html = self._download(url)
        except _PdfResponse as response:
            return self._as_pdf(url, response)
        content, meta = self._extract(html, url)
        stages = [
            capture.stage("page fetched", capture.OK, f"{len(html):,} characters of HTML"),
            capture.stage(
                "article text",
                capture.OK if len(content.strip()) >= 200 else capture.EMPTY,
                f"{len(content):,} characters extracted"
                + (
                    ""
                    if len(content.strip()) >= 200
                    else " (a block, consent or script-only page?)"
                ),
            ),
        ]
        return FetchResult(content=content, metadata=meta, stages=stages)
