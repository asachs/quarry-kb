"""Instagram adapter — caption, audio transcript and (opt-in) media for public posts.

Deterministic only: yt-dlp metadata (caption, author, post date), an optional
faster-whisper audio transcript, and — with ``[instagram] media = true`` — the reel
video, frames sampled with ffmpeg, carousel slide images, and tesseract OCR of the
frames/slides. All of it lands in the raw (text) and next to it (assets). Describing
what the images *show* stays agent-side: Quarry never calls a model.

Carousels (``/p/`` posts made of images) have no video formats; yt-dlp still returns
each slide's image URL when ``ignore_no_formats_error`` is set, so they ingest like
any other post instead of failing with "No video formats found".

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
import glob
import os
import re
import shutil
import subprocess
import tempfile
import urllib.request

from quarry import transcribe
from quarry.adapters.base import Adapter, FetchResult
from quarry.config import InstagramConfig
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
_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126 Safari/537.36"
)


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


def post_date(info: dict) -> str:
    """The post's own date (ISO) from yt-dlp's ``upload_date`` / ``timestamp``; today if absent."""
    raw = info.get("upload_date")
    if isinstance(raw, str) and re.fullmatch(r"\d{8}", raw):
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    ts = info.get("timestamp")
    if isinstance(ts, (int, float)):
        return _dt.datetime.fromtimestamp(ts, tz=_dt.UTC).date().isoformat()
    return _dt.date.today().isoformat()


def best_image_url(entry: dict) -> str | None:
    """Largest thumbnail of a carousel entry (the slide image itself)."""
    thumbs = [t for t in entry.get("thumbnails") or [] if t.get("url")]
    if thumbs:
        def size(t: dict) -> tuple[int, int]:
            return ((t.get("width") or 0) * (t.get("height") or 0), t.get("preference") or 0)

        return max(thumbs, key=size)["url"]
    return entry.get("thumbnail")


def is_carousel(info: dict) -> bool:
    return info.get("_type") == "playlist" or bool(info.get("entries"))


def dedupe_ocr(items: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Drop empty OCR results and frames whose text repeats the previous frame's.

    Video frames sampled every few seconds mostly repeat the same caption; keeping only
    changes makes the OCR section read like a transcript of the on-screen text.
    """
    out: list[tuple[str, str]] = []
    prev = ""
    for label, text in items:
        norm = re.sub(r"\s+", " ", text).strip()
        if len(re.sub(r"\W", "", norm)) < 3 or norm.lower() == prev:
            continue
        out.append((label, norm))
        prev = norm.lower()
    return out


def _mmss(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 60}:{s % 60:02d}"


class InstagramAdapter(Adapter):
    name = "instagram"

    def matches(self, url: str) -> bool:
        return bool(re.search(r"instagram\.com/(reel|p|tv)/", url))

    def _shortcode(self, url: str) -> str:
        m = re.search(r"instagram\.com/(?:reel|p|tv)/([^/?#]+)", url)
        return m.group(1) if m else url

    def _settings(self) -> InstagramConfig:
        return getattr(self.cfg, "instagram", None) or InstagramConfig()

    # --- overridable network / tool methods --------------------------------
    def _info(self, url: str) -> dict:  # pragma: no cover - network
        ydl = _import_ytdlp()
        opts = {
            "quiet": True,
            "noprogress": True,
            "no_warnings": True,
            "skip_download": True,
            # carousels have no video formats; still return each slide's image URL
            "ignore_no_formats_error": True,
            **_cookie_opts(),
        }
        with ydl.YoutubeDL(opts) as y:
            return y.extract_info(url, download=False)

    def _audio(self, url: str, dest_dir: str) -> str | None:  # pragma: no cover - network/IO
        ydl = _import_ytdlp()
        opts = {
            "format": "bestaudio",
            "outtmpl": os.path.join(dest_dir, "audio.%(ext)s"),
            "quiet": True,
            "noprogress": True,
            "no_warnings": True,
            "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "wav"}],
            **_cookie_opts(),
        }
        with ydl.YoutubeDL(opts) as y:
            y.download([url])
        wavs = glob.glob(os.path.join(dest_dir, "*.wav"))
        return wavs[0] if wavs else None

    def _video(self, url: str, dest_dir: str) -> str | None:  # pragma: no cover - network/IO
        ydl = _import_ytdlp()
        opts = {
            "format": "b[ext=mp4]/b",
            "outtmpl": os.path.join(dest_dir, "video.%(ext)s"),
            "quiet": True,
            "noprogress": True,
            "no_warnings": True,
            **_cookie_opts(),
        }
        with ydl.YoutubeDL(opts) as y:
            y.download([url])
        vids = glob.glob(os.path.join(dest_dir, "video.*"))
        return vids[0] if vids else None

    def _download(self, url: str, dest: str) -> bool:  # pragma: no cover - network
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as fh:
            shutil.copyfileobj(r, fh)
        return os.path.getsize(dest) > 0

    def _frames(  # pragma: no cover - ffmpeg
        self, video: str, dest_dir: str, every: float
    ) -> list[tuple[float, str]]:
        pattern = os.path.join(dest_dir, "frame_%03d.jpg")
        vf = f"fps=1/{every},scale=720:-2"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", video, "-vf", vf, pattern],
            check=True,
            capture_output=True,
        )
        files = sorted(glob.glob(os.path.join(dest_dir, "frame_*.jpg")))
        return [(i * every, f) for i, f in enumerate(files)]

    def _duration(self, video: str) -> float:  # pragma: no cover - ffprobe
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", video],
            capture_output=True,
            text=True,
        )
        try:
            return float(r.stdout.strip())
        except ValueError:
            return 0.0

    def _ocr(self, image: str) -> str:  # pragma: no cover - tesseract
        r = subprocess.run(
            ["tesseract", image, "stdout", "-l", "eng"], capture_output=True, text=True
        )
        return r.stdout if r.returncode == 0 else ""

    def _tool(self, name: str) -> bool:
        return shutil.which(name) is not None

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

        settings = self._settings()
        caption = (info.get("description") or "").strip()
        uploader = info.get("uploader") or info.get("channel") or "unknown"
        carousel = is_carousel(info)
        if carousel and uploader == "unknown":
            first = (info.get("entries") or [{}])[0] or {}
            uploader = first.get("uploader") or first.get("channel") or "unknown"

        assets: dict[str, str] = {}
        ocr_items: list[tuple[str, str]] = []
        notes: list[str] = []
        transcript = ""
        tmp = tempfile.mkdtemp(prefix="quarry-ig-") if settings.media else None

        if carousel:
            entries = [e for e in info.get("entries") or [] if e]
            if tmp:
                for i, entry in enumerate(entries, 1):
                    img = best_image_url(entry)
                    if not img:
                        continue
                    name = f"slide_{i:02d}.jpg"
                    dest = os.path.join(tmp, name)
                    try:
                        if self._download(img, dest):
                            assets[name] = dest
                    except Exception:  # noqa: BLE001 - one bad slide must not sink the post
                        notes.append(f"slide {i}: download failed")
                if settings.ocr and self._tool("tesseract"):
                    for n, p in sorted(assets.items()):
                        text = re.sub(r"\s+", " ", self._ocr(p)).strip()
                        if text:
                            ocr_items.append((f"slide {n[6:8]}", text))
            body_kind = f"carousel of {len(entries)} slides"
        else:
            body_kind = "video"
            video = None
            if tmp:
                try:
                    video = self._video(url, tmp)
                except Exception:  # noqa: BLE001 - media is best-effort
                    notes.append("video download failed")
                if video:
                    if settings.keep_video:
                        assets["video" + os.path.splitext(video)[1]] = video
                    if settings.frame_interval > 0 and self._tool("ffmpeg"):
                        dur = self._duration(video)
                        every = float(settings.frame_interval)
                        if dur and settings.max_frames > 0:
                            every = max(every, dur / settings.max_frames)
                        frames = self._frames(video, tmp, every)[: max(settings.max_frames, 0)]
                        for t, f in frames:
                            name = f"frame_{_mmss(t).replace(':', 'm')}s.jpg"
                            assets[name] = f
                        if settings.ocr and self._tool("tesseract"):
                            ocr_items = dedupe_ocr([(_mmss(t), self._ocr(f)) for t, f in frames])
            if transcribe.available():
                try:
                    if video:
                        transcript = transcribe.transcribe(video)
                    else:
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
        if ocr_items:
            parts += ["## On-screen text (OCR)", ""]
            parts += [f"- **{label}**: {text}" for label, text in ocr_items]
            parts += [""]
        if notes:
            parts += ["## Capture notes", *[f"- {n}" for n in notes], ""]
        if not caption and not transcript and not ocr_items:
            parts += [
                "(no caption, audio or on-screen text extracted; "
                "visual content needs agent-side vision)"
            ]

        return FetchResult(
            content="\n".join(parts).strip() + "\n",
            metadata={
                "title": title,
                "author": uploader,
                "date": post_date(info),
                "url": url,
                "source_id": self._shortcode(url),
                "kind": body_kind,
            },
            assets=assets,
            tmpdir=tmp,
        )
