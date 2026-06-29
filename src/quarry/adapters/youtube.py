"""YouTube adapter — transcript with a deterministic fallback chain.

Transcript resolution order (each overridable for hermetic tests):
  1. youtube-transcript-api captions  ([youtube] extra)
  2. yt-dlp auto-subtitles             ([youtube] extra)
  3. yt-dlp audio + faster-whisper     ([youtube] + [whisper] extras)
Metadata comes from oEmbed (no key). Network methods are overridable so the default
test suite stays hermetic.
"""

from __future__ import annotations

import datetime as _dt
import glob
import json
import os
import re
import tempfile
import urllib.parse
import urllib.request

from quarry import transcribe
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


def _vtt_to_text(vtt: str) -> str:
    """Strip WebVTT timestamps/tags/dupes into plain text."""
    lines: list[str] = []
    for raw in vtt.splitlines():
        line = raw.strip()
        if not line or line == "WEBVTT" or "-->" in line or line.isdigit():
            continue
        line = re.sub(r"<[^>]+>", "", line)  # inline timing tags
        if line and (not lines or lines[-1] != line):
            lines.append(line)
    return " ".join(lines).strip()


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

    # --- transcript: captions -> yt-dlp subs -> whisper -------------------
    def _fetch_transcript(self, vid: str) -> str:
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
        except ImportError as e:
            raise QuarryError(
                "youtube adapter needs the [youtube] extra "
                "(pip install 'quarry-kb[youtube]')"
            ) from e
        fetched = YouTubeTranscriptApi().fetch(vid)
        snippets = getattr(fetched, "snippets", fetched)
        return " ".join((getattr(s, "text", None) or s["text"]) for s in snippets).strip()

    def _ytdlp_subs(self, url: str) -> str:  # pragma: no cover - network/extra
        ydl = _import_ytdlp()
        with tempfile.TemporaryDirectory() as d:
            opts = {
                "skip_download": True,
                "writeautomaticsub": True,
                "writesubtitles": True,
                "subtitleslangs": ["en"],
                "subtitlesformat": "vtt",
                "outtmpl": os.path.join(d, "%(id)s"),
                "quiet": True,
                "no_warnings": True,
            }
            with ydl.YoutubeDL(opts) as y:
                y.download([url])
            vtts = glob.glob(os.path.join(d, "*.vtt"))
            return _vtt_to_text(open(vtts[0], encoding="utf-8").read()) if vtts else ""

    def _whisper_fallback(self, url: str) -> str:  # pragma: no cover - network/model
        ydl = _import_ytdlp()
        with tempfile.TemporaryDirectory() as d:
            opts = {
                "format": "bestaudio",
                "outtmpl": os.path.join(d, "audio.%(ext)s"),
                "quiet": True,
                "no_warnings": True,
                "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "wav"}],
            }
            with ydl.YoutubeDL(opts) as y:
                y.download([url])
            wavs = glob.glob(os.path.join(d, "*.wav"))
            return transcribe.transcribe(wavs[0]) if wavs else ""

    def _transcript_with_fallback(self, url: str, vid: str) -> str:
        errors: list[str] = []
        for stage in (
            lambda: self._fetch_transcript(vid),
            lambda: self._ytdlp_subs(url),
            lambda: self._whisper_fallback(url),
        ):
            try:
                text = stage()
            except Exception as e:  # noqa: BLE001 - try the next fallback
                errors.append(str(e))
                continue
            if text and text.strip():
                return text
        raise QuarryError(
            f"youtube: no transcript via captions, subtitles, or whisper for {url}"
            + (f" ({'; '.join(errors[:2])})" if errors else "")
        )

    # --- metadata ---------------------------------------------------------
    def _fetch_oembed(self, url: str) -> dict:  # pragma: no cover - network
        q = urllib.parse.urlencode({"url": url, "format": "json"})
        with urllib.request.urlopen(  # noqa: S310
            f"https://www.youtube.com/oembed?{q}", timeout=15
        ) as resp:
            return json.loads(resp.read().decode())

    # --- contract ---------------------------------------------------------
    def fetch(self, url: str) -> FetchResult:
        vid = self.video_id(url)
        try:
            meta = self._fetch_oembed(url)
        except Exception:  # noqa: BLE001 - metadata is best-effort
            meta = {}
        content = self._transcript_with_fallback(url, vid)
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


def _import_ytdlp():  # pragma: no cover - extra
    try:
        import yt_dlp

        return yt_dlp
    except ImportError as e:
        raise QuarryError(
            "youtube fallback needs the [youtube] extra (pip install 'quarry-kb[youtube]')"
        ) from e
