"""Instagram adapter — best-effort caption + audio transcript for public reels/posts.

Deterministic half only: yt-dlp metadata (caption) + optional faster-whisper audio
transcript. Frame/overlay vision-reading is agent-side, not here.

PUBLIC reels remain fetchable WITHOUT login/cookies in 2026, but Instagram's mid-2026
anonymous-access change means yt-dlp must use its Instagram impersonation rework (PR #17075,
in yt-dlp master / the first stable after 2026.06.09) backed by ``curl_cffi`` (TLS/JA3
target). The ``[instagram]`` extra pulls ``curl_cffi``; until a stable yt-dlp release carries
PR #17075, install yt-dlp from master. Without that, fetch fails with "empty media response"
and the adapter raises an actionable upgrade hint. Cookies (``QUARRY_INSTAGRAM_COOKIES`` /
``QUARRY_INSTAGRAM_COOKIES_FROM_BROWSER``) are only needed for PRIVATE posts/stories.
Audio transcript also needs the ``[whisper]`` extra.
"""

from __future__ import annotations

import datetime as _dt
import os
import re
import tempfile

from quarry import transcribe
from quarry.adapters.base import Adapter, FetchResult
from quarry.errors import QuarryError

# yt-dlp's logged-out Instagram path is blocked in 2026 ("empty media response");
# cookies are required even for public reels. These hints classify the failure.
_LOGIN_HINTS = (
    "login",
    "log in",
    "logged-in",
    "logged in",
    "cookies",
    "empty media response",
    "rate-limit",
    "not available",
    "restricted",
)

_COOKIES_ENV = "QUARRY_INSTAGRAM_COOKIES"  # path to a Netscape cookies.txt
_COOKIES_BROWSER_ENV = "QUARRY_INSTAGRAM_COOKIES_FROM_BROWSER"  # e.g. "firefox" or "chrome:Profile"


def cookies_configured() -> bool:
    """True if an Instagram cookie source is configured (file or browser)."""
    return bool(os.getenv(_COOKIES_ENV) or os.getenv(_COOKIES_BROWSER_ENV))


def _cookie_opts() -> dict:
    """yt-dlp options for the configured cookie source — empty if none set."""
    opts: dict = {}
    cookiefile = os.getenv(_COOKIES_ENV)
    if cookiefile:
        opts["cookiefile"] = cookiefile
    browser = os.getenv(_COOKIES_BROWSER_ENV)
    if browser:
        name, _, profile = browser.partition(":")
        opts["cookiesfrombrowser"] = (name, profile or None, None, None)
    return opts


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
        opts = {"quiet": True, "no_warnings": True, "skip_download": True, **_cookie_opts()}
        with ydl.YoutubeDL(opts) as y:
            return y.extract_info(url, download=False)

    def _audio(self, url: str, dest_dir: str) -> str | None:  # pragma: no cover - network/IO
        ydl = _import_ytdlp()
        opts = {
            "format": "bestaudio",
            "outtmpl": os.path.join(dest_dir, "audio.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "wav"}],
            **_cookie_opts(),
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
                    "instagram: extraction failed (empty media / login response). PUBLIC reels "
                    "are still fetchable without cookies, but need yt-dlp's Instagram "
                    "impersonation rework (PR #17075 — in yt-dlp master, or first stable "
                    "after 2026.06.09) "
                    "PLUS curl_cffi installed. Upgrade: pip install -U --pre 'yt-dlp' curl_cffi "
                    "(or install yt-dlp from git master until the fix ships in a release). Only "
                    "private posts/stories need cookies (QUARRY_INSTAGRAM_COOKIES)."
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
