"""PDF adapter — text via PyMuPDF4LLM (markdown), auto-OCR for scanned pages.

PyMuPDF4LLM emits structured markdown and auto-detects scanned-vs-text, routing
only image pages to OCR (Tesseract, if installed — a separate system binary).
Accepts an ``http(s)`` PDF URL or a local file path. Requires the ``[pdf]`` extra.
Extraction lives in an overridable method so tests stay hermetic.
"""

from __future__ import annotations

import datetime as _dt
import tempfile
import urllib.request
from pathlib import Path

from quarry import capture
from quarry.adapters.base import Adapter, FetchResult
from quarry.errors import QuarryError


class PdfAdapter(Adapter):
    name = "pdf"

    def matches(self, url: str) -> bool:
        head = url.split("?")[0].lower()
        if head.startswith(("http://", "https://")):
            return head.endswith(".pdf")
        return head.endswith(".pdf")  # local path

    # --- overridable IO ---------------------------------------------------
    def _local_path(self, url: str) -> tuple[Path, bool]:  # pragma: no cover - network/IO
        """Return (path, is_temp). Downloads http(s) URLs to a temp file."""
        if url.lower().startswith(("http://", "https://")):
            fd = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
            with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310
                fd.write(resp.read())
            fd.close()
            return Path(fd.name), True
        p = Path(url).expanduser()
        if not p.is_file():
            raise QuarryError(f"pdf: file not found: {url}")
        return p, False

    def _to_markdown(self, path: Path) -> tuple[str, dict]:  # pragma: no cover - extra/IO
        try:
            import pymupdf
            import pymupdf4llm
        except ImportError as e:
            raise QuarryError(
                "pdf adapter needs the [pdf] extra (pip install 'quarry-kb[pdf]')"
            ) from e
        md = pymupdf4llm.to_markdown(str(path))
        meta = {}
        try:
            with pymupdf.open(str(path)) as doc:
                meta = dict(doc.metadata or {})
        except Exception:  # noqa: BLE001 - metadata best-effort
            pass
        return md, meta

    # --- contract ---------------------------------------------------------
    def from_path(self, url: str, path: Path) -> FetchResult:
        """The capture of a PDF already on disk. ``url`` is where it came from."""
        md, meta = self._to_markdown(path)
        if not md.strip():
            raise QuarryError(f"pdf: no extractable text from {url} (scanned + no OCR engine?)")

        # the last path segment, minus a .pdf suffix only: Path.stem would turn the arXiv id
        # "1706.03762" into "1706"
        stem = url.split("?")[0].rstrip("/").replace("\\", "/").rsplit("/", 1)[-1]
        if stem.lower().endswith(".pdf"):
            stem = stem[:-4]
        title = (meta.get("title") or "").strip() or stem
        return FetchResult(
            stages=[capture.stage("text", capture.OK, f"{len(md):,} characters extracted")],
            content=md,
            metadata={
                "title": title,
                "author": (meta.get("author") or "unknown").strip() or "unknown",
                "date": _dt.date.today().isoformat(),
                "url": url,
                "source_id": stem,
            },
        )

    def fetch(self, url: str) -> FetchResult:
        path, is_temp = self._local_path(url)
        try:
            return self.from_path(url, path)
        finally:
            if is_temp:
                path.unlink(missing_ok=True)
