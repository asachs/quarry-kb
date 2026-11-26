"""Local speech-to-text via faster-whisper — the no-LLM, no-key audio extractor.

A deterministic *local* model (not an LLM, no API key), shipped behind the
``[whisper]`` extra. Used by the youtube (no-captions) and instagram adapters.
"""

from __future__ import annotations

from quarry.errors import QuarryError

_DEFAULT_MODEL = "small"
_RATE = 16_000


class Heard(str):
    """A transcript that remembers how it was made. It is a ``str`` (the text), so callers
    that only want words need not care; the attributes feed the capture's stage record.

    ``speech_seconds`` is how much voice the non-speech filter kept out of ``duration``.
    ``withheld`` is set, and the text is empty, when the recogniser returned words that
    should not be trusted (see ``transcribe``).
    """

    language: str = ""
    language_probability: float = 0.0
    duration: float = 0.0
    speech_seconds: float = 0.0
    model: str = ""
    forced_language: str = ""
    withheld: str = ""

    def describe(self) -> str:
        """One line for a stage record."""
        if self.withheld:
            return self.withheld
        if not self:
            return (
                f"no speech in the {self.duration:.0f} s clip (music or silence)"
                if self.duration
                else "no speech recognised (music or silence)"
            )
        how = (
            f"language forced to {self.forced_language} after a doubtful detection"
            if self.forced_language
            else f"language {self.language} ({self.language_probability:.2f})"
            if self.language
            else ""
        )
        heard = (
            f"{self.speech_seconds:.0f} s of speech in a {self.duration:.0f} s clip; "
            if self.duration
            else ""
        )
        tail = f"; {how}" if how else ""
        return (
            f"{len(self.split())} words; {heard}model {self.model or 'unknown'}{tail}; "
            "machine transcript, names and numbers may be misheard"
        )


def available() -> bool:
    import importlib.util

    return importlib.util.find_spec("faster_whisper") is not None


def _samples(audio_path: str):  # pragma: no cover - ffmpeg/numpy
    """The audio as 16 kHz mono float32 samples, decoded by ffmpeg when it is installed.

    faster-whisper decodes through PyAV by default, and that pairing broke once (PyAV 19
    removed an argument faster-whisper passes), silently, for weeks. ffmpeg is already
    required for frames, and handing the model samples takes PyAV out of the path. Returns
    the path unchanged when ffmpeg is missing, so the old route still works.
    """
    import shutil
    import subprocess

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return audio_path
    import numpy as np

    done = subprocess.run(
        [ffmpeg, "-v", "error", "-nostdin", "-i", audio_path, "-vn", "-ac", "1",
         "-ar", str(_RATE), "-f", "s16le", "-"],
        capture_output=True,
    )  # fmt: skip
    if done.returncode != 0:
        detail = done.stderr.decode("utf-8", "replace").strip()[-200:]
        raise QuarryError(f"ffmpeg could not decode the audio: {detail}")
    return np.frombuffer(done.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def _recognise(audio, speech, language):  # pragma: no cover - model
    from faster_whisper import WhisperModel

    wm = WhisperModel(speech.model, device="cpu", compute_type="int8")
    segments, info = wm.transcribe(audio, vad_filter=speech.vad_filter, language=language)
    return " ".join(seg.text.strip() for seg in segments).strip(), info


def transcribe(audio_path: str, speech=None, model: str | None = None) -> Heard:
    """Transcribe an audio or video file. Raises if the [whisper] extra is absent.

    ``speech`` is the ``[speech]`` config. Three things learned from transcribing 180 reels
    are built in:

    - **The non-speech filter is on.** Without it the model writes words over music.
    - **Too little voice is not a transcript.** Music-only clips still came back as "you"
      or "Thanks for watching!" from under a second of detected voice. Under
      ``min_speech_seconds`` the words are withheld and the reason recorded.
    - **A doubtful language is retried.** Two English reels were detected as Italian at
      about 0.5 and transcribed as nonsense. Below ``min_language_probability`` the clip is
      transcribed again in ``fallback_language``, if one is set.
    """
    if not available():
        raise QuarryError(
            "audio transcription needs the [whisper] extra (pip install 'quarry-kb[whisper]')"
        )
    from quarry.config import SpeechConfig

    speech = speech or SpeechConfig()
    if model:
        speech = SpeechConfig(**{**speech.__dict__, "model": model})
    audio = _samples(audio_path)
    text, info = _recognise(audio, speech, None)
    forced = ""
    prob = float(getattr(info, "language_probability", 0.0) or 0.0)
    lang = getattr(info, "language", "") or ""
    fallback = speech.fallback_language
    if text and fallback and lang != fallback and prob < speech.min_language_probability:
        text, info = _recognise(audio, speech, fallback)
        forced = fallback
    duration = float(getattr(info, "duration", 0.0) or 0.0)
    speech_s = float(getattr(info, "duration_after_vad", duration) or 0.0)
    withheld = ""
    if text and speech.vad_filter and speech_s < speech.min_speech_seconds:
        withheld = (
            f"{speech_s:.1f} s of voice in the {duration:.0f} s clip, too little to trust "
            "over music; nothing transcribed"
        )
        text = ""
    out = Heard(text)
    out.language = forced or lang
    out.language_probability = prob
    out.duration = duration
    out.speech_seconds = speech_s
    out.model = speech.model
    out.forced_language = forced
    out.withheld = withheld
    return out


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
