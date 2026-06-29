"""Instagram adapter — best-effort caption + audio transcript for public reels/posts.

Deterministic half only: yt-dlp metadata (caption) + optional faster-whisper audio
transcript. Frame/overlay vision-reading is agent-side, not here. Public content is
fragile (logged-out path); stories/private need cookies — surfaced as a clean error.
Requires the ``[instagram]`` extra (yt-dlp); audio transcript also needs ``[whisper]``.
"""

from __future__ import annotations

import datetime as _dt
import os
import re
import tempfile

from quarry import transcribe
from quarry.adapters.base import Adapter, FetchResult
from quarry.errors import QuarryError

_LOGIN_HINTS = ("login", "rate-limit", "not available", "restricted", "log in")


def _import_ytdlp():  # pragma: no cover - extra
    try:
        import yt_dlp

        return yt_dlp
    except ImportError as e:
        raise QuarryError(
            "instagram adapter needs the [instagram] extra (pip install 'quarry-kb[instagram]')"
        ) from e


class InstagramAdapter(Adapter):
    name = "instagram"

    def matches(self, url: str) -> bool:
        return bool(re.search(r"instagram\.com/(reel|p|tv)/", url))

    def _shortcode(self, url: str) -> str:
        m = re.search(r"instagram\.com/(?:reel|p|tv)/([^/?#]+)", url)
        return m.group(1) if m else url

    # --- overridable network methods --------------------------------------
    def _info(self, url: str) -> dict:  # pragma: no cover - network
        ydl = _import_ytdlp()
        with ydl.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True}) as y:
            return y.extract_info(url, download=False)

    def _audio(self, url: str, dest_dir: str) -> str | None:  # pragma: no cover - network/IO
        ydl = _import_ytdlp()
        opts = {
            "format": "bestaudio",
            "outtmpl": os.path.join(dest_dir, "audio.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "wav"}],
        }
        with ydl.YoutubeDL(opts) as y:
            y.download([url])
        import glob

        wavs = glob.glob(os.path.join(dest_dir, "*.wav"))
        return wavs[0] if wavs else None

    # --- contract ---------------------------------------------------------
    def fetch(self, url: str) -> FetchResult:
        try:
            info = self._info(url)
        except QuarryError:
            raise
        except Exception as e:  # noqa: BLE001 - classify into a clean message
            if any(h in str(e).lower() for h in _LOGIN_HINTS):
                raise QuarryError(
                    "instagram: login required or rate-limited — public reels/posts only "
                    "(stories/private need cookies)"
                ) from e
            raise QuarryError(f"instagram fetch failed: {e}") from e

        caption = (info.get("description") or "").strip()
        uploader = info.get("uploader") or info.get("channel") or "unknown"

        transcript = ""
        if transcribe.available():
            try:
                with tempfile.TemporaryDirectory() as d:
                    wav = self._audio(url, d)
                    if wav:
                        transcript = transcribe.transcribe(wav)
            except Exception:  # noqa: BLE001 - audio is best-effort
                transcript = ""

        title = caption.splitlines()[0][:80] if caption else f"instagram-{self._shortcode(url)}"
        parts = [f"# {title}", ""]
        if caption:
            parts += ["## Caption", caption, ""]
        if transcript:
            parts += ["## Audio transcript", transcript, ""]
        if not caption and not transcript:
            parts += ["(no caption or audio extracted; visual content needs agent-side vision)"]

        return FetchResult(
            content="\n".join(parts).strip() + "\n",
            metadata={
                "title": title,
                "author": uploader,
                "date": _dt.date.today().isoformat(),
                "url": url,
                "source_id": self._shortcode(url),
            },
        )
