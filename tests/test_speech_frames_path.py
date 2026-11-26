"""Speech guard rails, settled-frame selection and the one-capture-path lint check."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from quarry import config, frames, lint, transcribe
from quarry.adapters.instagram import InstagramAdapter
from quarry.cli import main
from quarry.config import InstagramConfig, SpeechConfig

# --- speech -----------------------------------------------------------------


def _info(lang="en", prob=0.99, duration=60.0, speech=50.0):
    return SimpleNamespace(
        language=lang, language_probability=prob, duration=duration, duration_after_vad=speech
    )


def _speech(monkeypatch, replies):
    """replies: list of (text, info) returned by successive recognitions."""
    calls = []
    monkeypatch.setattr(transcribe, "available", lambda: True)
    monkeypatch.setattr(transcribe, "_samples", lambda path: "samples")

    def recognise(audio, speech, language):
        calls.append({"language": language, "vad": speech.vad_filter, "model": speech.model})
        return replies[min(len(calls) - 1, len(replies) - 1)]

    monkeypatch.setattr(transcribe, "_recognise", recognise)
    return calls


def test_transcript_is_text_that_remembers_how_it_was_made(monkeypatch):
    calls = _speech(monkeypatch, [("hello there world", _info())])
    t = transcribe.transcribe("a.mp4")
    assert t == "hello there world" and isinstance(t, str)
    assert (t.speech_seconds, t.duration, t.language, t.model) == (50.0, 60.0, "en", "small")
    assert calls == [{"language": None, "vad": True, "model": "small"}]
    d = t.describe()
    assert "3 words" in d and "50 s of speech in a 60 s clip" in d and "language en (0.99)" in d


def test_too_little_voice_is_withheld_with_the_reason(monkeypatch):
    _speech(monkeypatch, [("Thanks for watching!", _info(prob=0.6, speech=0.9, duration=6.3))])
    t = transcribe.transcribe("a.mp4")
    assert t == "" and "0.9 s of voice in the 6 s clip, too little to trust" in t.withheld
    assert t.describe() == t.withheld
    # with the filter off there is no speech measure to judge by, so the words stand
    _speech(monkeypatch, [("words", _info(speech=0.9))])
    assert transcribe.transcribe("a.mp4", SpeechConfig(vad_filter=False)) == "words"


def test_doubtful_language_is_retried_in_the_fallback(monkeypatch):
    calls = _speech(
        monkeypatch,
        [("Che cio che fa", _info(lang="it", prob=0.47)), ("What makes these pedals", _info())],
    )
    t = transcribe.transcribe("a.mp4", SpeechConfig(fallback_language="en"))
    assert t == "What makes these pedals" and t.forced_language == "en"
    assert [c["language"] for c in calls] == [None, "en"]
    assert "language forced to en" in t.describe()
    # a confident other language is left alone, and so is everything when no fallback is set
    calls = _speech(monkeypatch, [("Ikea und 3D-Druck", _info(lang="de", prob=0.997))])
    assert transcribe.transcribe("a.mp4", SpeechConfig(fallback_language="en")).language == "de"
    calls2 = _speech(monkeypatch, [("x y", _info(lang="it", prob=0.3))])
    transcribe.transcribe("a.mp4")
    assert len(calls) == 1 and len(calls2) == 1


def test_no_speech_and_model_override_and_missing_extra(monkeypatch):
    _speech(monkeypatch, [("", _info(speech=0.0, duration=43.0))])
    t = transcribe.transcribe("a.mp4")
    assert t == "" and t.describe() == "no speech in the 43 s clip (music or silence)"
    calls = _speech(monkeypatch, [("a b", _info())])
    assert (
        transcribe.transcribe("a.mp4", model="base").model == "base" and calls[0]["model"] == "base"
    )
    monkeypatch.setattr(transcribe, "available", lambda: False)
    with pytest.raises(Exception, match=r"\[whisper\] extra"):
        transcribe.transcribe("a.mp4")
    assert transcribe.Heard("").describe() == "no speech recognised (music or silence)"


# --- frames -----------------------------------------------------------------


def test_scores_use_the_largest_change_in_any_cell():
    size, grid = 12, 3
    blank = bytes(size * size)
    corner = bytearray(blank)
    for y in range(4):
        for x in range(4):
            corner[y * size + x] = 90  # one cell of nine changes completely
    s = frames.scores([blank, bytes(corner), bytes(corner)], size=size, grid=grid)
    assert s == [0.0, 90.0, 0.0]
    assert frames.scores([]) == [0.0] and frames.select([]).times == []


def test_select_takes_the_stillest_moment_of_each_window():
    # 2 thumbnails per second, 2-second windows of four; the tick (index 0, 4) is mid-change
    change = [0, 60, 50, 1, 70, 2, 40, 40]
    sel = frames.select(change, fps=2.0, interval=2.0)
    assert sel.times == [0.0, 2.5] and sel.windows == 2 and sel.settled == 2
    # on a tie the later frame wins: the animation has had longer to finish
    assert frames.select([5, 3, 3, 3], fps=2.0, interval=2.0).times == [1.5]


def test_select_drops_repeats_of_an_unchanged_picture_and_reports_them():
    held = [0] + [1] * 19  # ten seconds of one slide
    sel = frames.select(held, fps=2.0, interval=2.0)
    assert len(sel.times) == 1 and sel.unchanged == 4 and "4 repeats" in sel.describe()
    cut = [0] + [1] * 7 + [120] + [1] * 7  # one hard cut half-way
    sel = frames.select(cut, fps=2.0, interval=2.0)
    assert len(sel.times) == 2 and sel.unchanged == 2


def test_select_respects_the_cap_by_dropping_the_smallest_changes():
    change = [0] + [30, 30, 30, 30, 200, 30, 30, 30, 9, 9, 9, 9, 150, 30, 30, 30]
    sel = frames.select(change, fps=2.0, interval=2.0, max_frames=3)
    assert len(sel.times) == 3 and sel.over_cap >= 1 and sel.times[0] == min(sel.times)
    assert "frame cap reached" in sel.describe()
    assert frames.select(change, fps=2.0, interval=2.0, max_frames=0).over_cap == 0


def _reel(monkeypatch, tmp_path, settled):
    a = InstagramAdapter()
    files = []
    for i in range(3):
        f = tmp_path / f"f{i}.jpg"
        f.write_bytes(b"x")
        files.append((float(i * 2), str(f)))
    monkeypatch.setattr(a, "_settled", settled)
    monkeypatch.setattr(a, "_duration", lambda v: 100.0)
    monkeypatch.setattr(a, "_frames", lambda v, d, every: files)
    return a, files


def test_adapter_uses_settled_frames_and_falls_back_to_the_clock(monkeypatch, tmp_path):
    sel = frames.Selection(times=[0.0, 2.5], windows=4, unchanged=2, settled=2)
    a, files = _reel(monkeypatch, tmp_path, lambda v, d, s: (files[:2], sel))
    got, detail, data = a._choose_frames("v.mp4", str(tmp_path), InstagramConfig(media=True))
    assert got == files[:2] and "2 repeats of an unchanged picture left out" in detail
    assert data == {"frames": 2, "unchanged_dropped": 2, "over_cap_dropped": 0}

    def boom(v, d, s):
        raise RuntimeError("ffmpeg died")

    a, files = _reel(monkeypatch, tmp_path, boom)
    got, detail, data = a._choose_frames(
        "v.mp4", str(tmp_path), InstagramConfig(media=True, max_frames=40)
    )
    assert got == files and "fixed clock, one every 2.5 s" in detail
    assert (
        "spacing widened" in detail
        and "change analysis failed (RuntimeError: ffmpeg died)" in detail
    )
    a, files = _reel(monkeypatch, tmp_path, lambda v, d, s: ([], frames.Selection()))
    assert "found no frames" in a._choose_frames("v", str(tmp_path), InstagramConfig(media=True))[1]
    a, files = _reel(monkeypatch, tmp_path, boom)
    detail = a._choose_frames("v", str(tmp_path), InstagramConfig(frame_selection="clock"))[1]
    assert "fixed clock" in detail and "change analysis" not in detail


# --- one capture path -------------------------------------------------------


def _wiki(root: Path, extra=""):
    (root / "quarry.toml").write_text('[lint]\nmanaged_since = "2026-11-27"\n' + extra)
    (root / "wiki").mkdir()
    (root / "wiki" / "index.md").write_text("# i\n")
    return config.load(root)


def _raw(root: Path, rel: str, source: str | None, block=False, fm=True):
    p = root / "raw" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    head = f"---\nsource: {source}\ndate: 2026-11-27\n---\n\n" if fm and source else ""
    p.write_text(
        head + "# T\n\n" + ("## Capture quality\n\n- video: ok\n\n" if block else "") + "body\n"
    )


def test_lint_flags_url_captures_written_outside_quarry(chtmp: Path, capsys):
    cfg = _wiki(chtmp)
    _raw(chtmp, "2026/11/2026-11-27_by-hand.md", "https://www.instagram.com/reel/ABC/")
    _raw(chtmp, "2026/11/2026-11-28_quoted.md", '"https://example.com/a"')
    _raw(chtmp, "2026/11/2026-11-27_by-quarry.md", "https://example.com/x", block=True)
    _raw(chtmp, "2026/11/2026-11-26_before-cutoff.md", "https://example.com/old")
    _raw(chtmp, "2026/11/2026-11-27_pasted-text.md", "pasted by Andre")
    _raw(chtmp, "2026/11/2026-11-27_no-frontmatter.md", "https://example.com/n", fm=False)
    _raw(chtmp, "payroc/2026-11-27_study-note.md", "https://example.com/study")
    _raw(chtmp, "2026/11/undated-notes.md", "https://example.com/u")
    res = lint.run(cfg)
    assert res.unmanaged_raw == [
        "raw/2026/11/2026-11-27_by-hand.md",
        "raw/2026/11/2026-11-28_quoted.md",
    ]
    assert "Unmanaged captures:    2" in res.report and "quarry ingest <url> --force" in res.report
    assert not res.fails(cfg.lint.fail_on)
    assert res.fails(["unmanaged_raw"]) and res.count("unmanaged_raw") == 2
    assert main(["lint"]) == 0
    capsys.readouterr()


def test_lint_unmanaged_check_is_off_by_default_and_can_gate(chtmp: Path):
    (chtmp / "quarry.toml").write_text("[store]\n")
    (chtmp / "wiki").mkdir()
    _raw(chtmp, "2026/11/2026-11-27_by-hand.md", "https://example.com/a")
    assert lint.run(config.load(chtmp)).unmanaged_raw == []
    (chtmp / "quarry.toml").write_text(
        '[lint]\nmanaged_since = "2026-11-27"\nfail_on = ["unmanaged_raw"]\n'
    )
    assert main(["lint"]) == 1
