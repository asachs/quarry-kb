"""What each stage of a capture did, recorded so "empty" and "failed" never look alike.

A review of two months of captures found the capture stage failing silently in three
ways: audio transcription raised on every reel for weeks and the adapter wrote the capture
with no transcript and no note; 28 captures had no media at all with nothing to say why;
and no one could tell from a raw file which steps had run. Archivers solve this the same
way: every stage records its own outcome next to the artefact.

A stage is ``{"name", "status", "detail"}``. Statuses:

- ``ok``       the stage ran and produced something
- ``empty``    the stage ran and there was nothing to produce (a reel with no speech)
- ``skipped``  the stage did not run, by configuration or for want of a tool
- ``failed``   the stage ran and broke

Adapters append stages to ``FetchResult.stages``. ``ingest`` writes them into the manifest
(with the versions of the tools involved) and, as a ``## Capture quality`` block, at the
top of the raw file, where the agent compiling the article reads them first.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import shutil
import subprocess
import time
from pathlib import Path

OK, EMPTY, SKIPPED, FAILED = "ok", "empty", "skipped", "failed"
STATUSES = (OK, EMPTY, SKIPPED, FAILED)
_MARK = {OK: "ok", EMPTY: "EMPTY", SKIPPED: "skipped", FAILED: "FAILED"}

# Distribution names whose versions explain a capture (a pinned pair drifting apart is how
# impersonation and audio decoding broke).
_PACKAGES = (
    "quarry-kb", "yt-dlp", "curl_cffi", "faster-whisper", "av", "trafilatura", "gitingest",
    "youtube-transcript-api", "pymupdf", "pymupdf4llm",
)  # fmt: skip
_BINARIES = (("ffmpeg", "-version"), ("tesseract", "--version"))


def stage(name: str, status: str, detail: str = "", **data: object) -> dict:
    """A stage record. ``data`` adds measured values (speech seconds, frame counts) that a
    script can read without parsing ``detail``."""
    if status not in STATUSES:
        raise ValueError(f"unknown stage status: {status}")
    out = {"name": name, "status": status, "detail": " ".join(str(detail).split())[:240]}
    out.update({k: v for k, v in data.items() if k not in out})
    return out


def error_detail(e: BaseException) -> str:
    return f"{type(e).__name__}: {' '.join(str(e).split())[:180]}"


def problems(stages: list[dict]) -> list[dict]:
    """Stages a reader must know about: failed ones, and empty ones."""
    return [s for s in stages if s["status"] in (FAILED, EMPTY)]


def tool_versions() -> dict[str, str]:
    """Versions of the packages and binaries a capture may have used; absent ones omitted."""
    out: dict[str, str] = {}
    for name in _PACKAGES:
        try:
            out[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            continue
    for binary, flag in _BINARIES:
        path = shutil.which(binary)
        if not path:
            continue
        try:  # pragma: no cover - depends on installed binaries
            done = subprocess.run([path, flag], capture_output=True, text=True, timeout=10)
            first = (done.stdout or done.stderr).splitlines()[0]
            out[binary] = first.strip()[:60]
        except Exception:  # noqa: BLE001 - a version string is never worth failing a capture
            out[binary] = "present"
    return out


def quality_block(stages: list[dict], stored: list[dict] | None = None) -> str:
    """The ``## Capture quality`` section for the top of a raw file ("" if no stages)."""
    if not stages:
        return ""
    lines = ["## Capture quality", ""]
    bad = problems(stages)
    if any(s["status"] == FAILED for s in bad):
        lines.append(
            "**Some stages failed.** What they would have produced is missing from this "
            "capture; do not fill the gap from expectation."
        )
        lines.append("")
    for s in stages:
        detail = f" — {s['detail']}" if s["detail"] else ""
        lines.append(f"- {s['name']}: {_MARK[s['status']]}{detail}")
    for m in stored or []:
        lines.append(
            f"- kept outside the repository: {m['kind']} `{m['sha256'][:16]}…` "
            f"({m['bytes']:,} bytes)"
        )
    return "\n".join(lines) + "\n"


def insert_block(content: str, block: str) -> str:
    """Put ``block`` straight after the raw's first heading (or at the top if none)."""
    if not block:
        return content
    lines = content.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("# "):
            head = lines[: i + 1]
            rest = "\n".join(lines[i + 1 :]).lstrip("\n")
            return "\n".join(head) + "\n\n" + block + "\n" + rest
    return block + "\n" + content


# --- media kept outside the repository ------------------------------------------


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def store_media(
    store_dir: str | Path, src: str | Path, *, kind: str, source_url: str, source_id: str
) -> dict:
    """Copy ``src`` into a content-addressed store and log it. Returns its record.

    Layout: ``<store>/<first two hex>/<sha256><ext>`` plus ``<store>/index.jsonl``, one line
    per stored file, so a capture can be found again by URL or id. Storing the same bytes
    twice is a no-op apart from the index line.
    """
    src = Path(src)
    root = Path(store_dir).expanduser()
    digest = sha256_file(src)
    dest = root / digest[:2] / f"{digest}{src.suffix.lower()}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        tmp = dest.with_suffix(dest.suffix + ".part")
        shutil.copyfile(src, tmp)
        tmp.replace(dest)
    record = {
        "kind": kind,
        "sha256": digest,
        "bytes": dest.stat().st_size,
        "path": str(dest),
        "source_url": source_url,
        "source_id": source_id,
        "stored_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    with (root / "index.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record
