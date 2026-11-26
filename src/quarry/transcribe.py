"""Local speech-to-text via faster-whisper — the no-LLM, no-key audio extractor.

A deterministic *local* model (not an LLM, no API key), shipped behind the
``[whisper]`` extra. Used by the youtube (no-captions) and instagram adapters.
"""

from __future__ import annotations

from quarry.errors import QuarryError

_DEFAULT_MODEL = "base"


def available() -> bool:
    import importlib.util

    return importlib.util.find_spec("faster_whisper") is not None


def transcribe(audio_path: str, model: str = _DEFAULT_MODEL) -> str:  # pragma: no cover - model
    """Transcribe an audio file to plain text. Raises if the [whisper] extra is absent."""
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise QuarryError(
            "audio transcription needs the [whisper] extra "
            "(pip install 'quarry-kb[whisper]')"
        ) from e
    wm = WhisperModel(model, device="cpu", compute_type="int8")
    segments, _info = wm.transcribe(audio_path)
    return " ".join(seg.text.strip() for seg in segments).strip()


def decode_check() -> str | None:
    """Why audio decoding would fail right now, or ``None`` if it works.

    Decodes a fraction of a second of generated silence through the same path a real
    transcription takes, without loading a speech model. It exists because this step
    broke silently once: faster-whisper passed PyAV an argument that PyAV 19 had
    removed, every transcription raised, and the adapters (which treat audio as
    best-effort) wrote captures with no transcript for weeks.
    """
    if not available():
        return "the [whisper] extra is not installed"
    import os
    import tempfile
    import wave

    fd, path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(b"\x00\x00" * 3200)
        from faster_whisper.audio import decode_audio

        decode_audio(path, sampling_rate=16000)
    except Exception as e:  # noqa: BLE001 - report whatever broke
        return f"{type(e).__name__}: {e}"
    finally:
        os.unlink(path)
    return None
