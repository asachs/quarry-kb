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
