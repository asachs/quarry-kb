"""Stage status, the capture-quality block, the media store, canaries and symptoms."""

import json
import time
from pathlib import Path

import pytest

from quarry import canary, capture, config, ingest, manifest
from quarry.adapters import registry
from quarry.adapters.base import Adapter, FetchResult
from quarry.adapters.instagram import InstagramAdapter
from quarry.cli import main
from quarry.config import InstagramConfig


def _store(root: Path, extra: str = "") -> config.Config:
    (root / "quarry.toml").write_text("[store]\n" + extra)
    (root / "wiki").mkdir(exist_ok=True)
    return config.load(root)


class Fake(Adapter):
    name = "fake"
    result: FetchResult

    def matches(self, url):
        return True

    def fetch(self, url):
        return self.result


def _use(monkeypatch, result: FetchResult | Exception):
    a = Fake()

    def fetch(adapter, url):
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(registry, "resolve_adapter", lambda cfg, url: a)
    monkeypatch.setattr(registry, "fetch", fetch)


def _result(stages=None, content="# T\n\nbody text\n", stored=None):
    return FetchResult(
        content=content,
        metadata={"title": "T", "url": "https://x/y", "date": "2026-11-26", "source_id": "y"},
        stages=stages or [],
        stored=stored or [],
    )


# --- stages -----------------------------------------------------------------


def test_stage_rejects_unknown_status_and_trims_detail():
    with pytest.raises(ValueError):
        capture.stage("x", "great")
    s = capture.stage("x", capture.FAILED, "a\n  b " + "z" * 500)
    assert s["detail"].startswith("a b") and len(s["detail"]) == 240
    assert capture.error_detail(TypeError("bad\narg")) == "TypeError: bad arg"


def test_quality_block_marks_failures_and_lists_stored_media():
    stages = [
        capture.stage("video", capture.OK, "1,000 bytes"),
        capture.stage("audio transcript", capture.FAILED, "TypeError: boom"),
        capture.stage("caption", capture.EMPTY),
        capture.stage("frames", capture.SKIPPED, "ffmpeg is not installed"),
    ]
    block = capture.quality_block(stages, [{"kind": "video", "sha256": "ab" * 32, "bytes": 1000}])
    assert "**Some stages failed.**" in block
    assert "- audio transcript: FAILED — TypeError: boom" in block
    assert "- caption: EMPTY" in block and "- frames: skipped — ffmpeg" in block
    assert "kept outside the repository: video `abababababababab…` (1,000 bytes)" in block
    assert capture.quality_block([]) == ""
    assert "Some stages failed" not in capture.quality_block([capture.stage("a", capture.EMPTY)])
    assert [s["name"] for s in capture.problems(stages)] == ["audio transcript", "caption"]


def test_insert_block_goes_after_the_first_heading():
    out = capture.insert_block("# Title\n\n## Caption\ntext\n", "## Capture quality\n\n- a: ok\n")
    assert out.index("# Title") < out.index("## Capture quality") < out.index("## Caption")
    assert capture.insert_block("no heading", "B\n").startswith("B\n")
    assert capture.insert_block("x", "") == "x"


def test_tool_versions_reports_quarry_itself():
    assert "quarry-kb" in capture.tool_versions()


def test_ingest_writes_stages_to_manifest_and_raw(chtmp: Path, monkeypatch):
    cfg = _store(chtmp)
    stages = [
        capture.stage("video", capture.OK),
        capture.stage("audio transcript", capture.FAILED, "TypeError: boom"),
    ]
    _use(monkeypatch, _result(stages))
    res = ingest.run(cfg, "https://x/y")
    m = manifest.load(cfg, res["slug"])
    assert m["stages"] == stages and "quarry-kb" in m["tools"] and "stored" not in m
    raw = (chtmp / res["raw_path"]).read_text()
    assert raw.index("# T") < raw.index("## Capture quality") < raw.index("body text")
    assert "- audio transcript: FAILED — TypeError: boom" in raw


def test_ingest_records_a_content_stage_when_the_adapter_reports_none(chtmp: Path, monkeypatch):
    cfg = _store(chtmp)
    _use(monkeypatch, _result())
    res = ingest.run(cfg, "https://x/y")
    m = manifest.load(cfg, res["slug"])
    assert [(s["name"], s["status"]) for s in m["stages"]] == [("content", "ok")]


def test_ingest_cli_prints_capture_problems(chtmp: Path, monkeypatch, capsys):
    _store(chtmp)
    rec = {"kind": "video", "sha256": "cd" * 32, "bytes": 5, "path": "/store/cd/x.mp4"}
    _use(monkeypatch, _result([capture.stage("video", capture.FAILED, "blocked")], stored=[rec]))
    assert main(["ingest", "https://x/y"]) == 0
    out = capsys.readouterr().out
    assert "CAPTURE PROBLEMS" in out and "video: FAILED — blocked" in out
    assert "kept outside git: video sha256 cdcdcdcdcdcdcdcd…" in out


# --- media store ------------------------------------------------------------


def test_store_media_is_content_addressed_and_logged(tmp_path: Path):
    src = tmp_path / "video.MP4"
    src.write_bytes(b"reel bytes")
    store = tmp_path / "store"
    r1 = capture.store_media(store, src, kind="video", source_url="u", source_id="ABC")
    r2 = capture.store_media(store, src, kind="video", source_url="u", source_id="ABC")
    assert r1["sha256"] == capture.sha256_file(src) == r2["sha256"]
    dest = Path(r1["path"])
    assert (
        dest == store / r1["sha256"][:2] / f"{r1['sha256']}.mp4"
        and dest.read_bytes() == b"reel bytes"
    )
    lines = (store / "index.jsonl").read_text().strip().split("\n")
    assert len(lines) == 2 and json.loads(lines[0])["source_id"] == "ABC"
    assert len(list(store.rglob("*.mp4"))) == 1 and not list(store.rglob("*.part"))


# --- instagram stages -------------------------------------------------------


def _ig(monkeypatch, tmp_path, settings: InstagramConfig, *, video=True, transcript="hello there"):
    a = InstagramAdapter()
    vid = tmp_path / "video.mp4"
    vid.write_bytes(b"v" * 10)
    monkeypatch.setattr(a, "_settings", lambda: settings)
    monkeypatch.setattr(a, "_info", lambda url: {"description": "A caption", "uploader": "me"})

    def _video(url, dest):
        if isinstance(video, Exception):
            raise video
        return str(vid) if video else None

    monkeypatch.setattr(a, "_video", _video)
    monkeypatch.setattr(a, "_tool", lambda name: False)
    monkeypatch.setattr(a, "_audio", lambda url, d: None)
    from quarry import transcribe

    monkeypatch.setattr(transcribe, "available", lambda: transcript is not None)

    def _tr(path, model="base"):
        if isinstance(transcript, Exception):
            raise transcript
        return transcript

    monkeypatch.setattr(transcribe, "transcribe", _tr)
    return a


def _by_name(stages):
    return {s["name"]: s for s in stages}


def test_instagram_reports_each_stage_and_keeps_the_video(monkeypatch, tmp_path):
    store = tmp_path / "store"
    a = _ig(monkeypatch, tmp_path, InstagramConfig(media=True, video_store=str(store)))
    r = a.fetch("https://www.instagram.com/reel/ABC/")
    s = _by_name(r.stages)
    assert s["metadata"]["status"] == s["caption"]["status"] == s["video"]["status"] == "ok"
    assert s["video kept"]["status"] == "ok" and r.stored[0]["source_id"] == "ABC"
    assert Path(r.stored[0]["path"]).exists()
    assert s["frames"]["status"] == "skipped" and "ffmpeg" in s["frames"]["detail"]
    assert s["audio transcript"]["status"] == "ok" and "2 words" in s["audio transcript"]["detail"]


def test_instagram_failed_video_and_failed_transcript_are_recorded(monkeypatch, tmp_path):
    a = _ig(
        monkeypatch, tmp_path, InstagramConfig(media=True),
        video=RuntimeError("empty media response"), transcript=TypeError("metadata_errors"),
    )  # fmt: skip
    s = _by_name(a.fetch("https://www.instagram.com/reel/ABC/").stages)
    assert s["video"]["status"] == "failed" and "empty media response" in s["video"]["detail"]
    assert s["audio transcript"]["status"] == "failed"
    assert "no audio could be downloaded" in s["audio transcript"]["detail"]
    assert "video kept" not in s
    a = _ig(
        monkeypatch, tmp_path, InstagramConfig(media=True), transcript=TypeError("metadata_errors")
    )
    s = _by_name(a.fetch("https://www.instagram.com/reel/ABC/").stages)
    assert (
        s["audio transcript"]["status"] == "failed"
        and "TypeError" in s["audio transcript"]["detail"]
    )


def test_instagram_no_speech_is_empty_and_missing_whisper_is_skipped(monkeypatch, tmp_path):
    a = _ig(monkeypatch, tmp_path, InstagramConfig(media=True), transcript="")
    assert (
        _by_name(a.fetch("https://www.instagram.com/reel/A/").stages)["audio transcript"]["status"]
        == "empty"
    )
    a = _ig(monkeypatch, tmp_path, InstagramConfig(media=False), transcript=None)
    s = _by_name(a.fetch("https://www.instagram.com/reel/A/").stages)
    assert s["audio transcript"]["status"] == "skipped" and s["video"]["status"] == "skipped"
    a = _ig(monkeypatch, tmp_path, InstagramConfig(media=True), video=False)
    assert (
        _by_name(a.fetch("https://www.instagram.com/reel/A/").stages)["video"]["status"] == "failed"
    )


# --- canary and symptoms ----------------------------------------------------

CANARY = '[canary]\nurls = ["https://x/y"]\nmax_age_hours = 36\n'


def test_canary_passes_then_fails_on_an_empty_stage_and_on_shrinkage(chtmp, monkeypatch, capsys):
    cfg = _store(chtmp, CANARY)
    _use(monkeypatch, _result([capture.stage("transcript", capture.OK)], content="x" * 1000))
    rec = canary.run(cfg)
    assert rec["passed"] == rec["total"] == 1 and canary.health(cfg)[0]
    assert not list((chtmp / "raw").glob("**/*")) if (chtmp / "raw").exists() else True
    _use(
        monkeypatch,
        _result([capture.stage("transcript", capture.EMPTY, "no speech")], content="x" * 1000),
    )
    rec = canary.run(cfg)
    assert rec["passed"] == 0 and "transcript: empty (no speech)" in rec["results"][0]["problems"]
    healthy, why = canary.health(cfg)
    assert not healthy and "1 of 1 failing" in why
    _use(monkeypatch, _result([capture.stage("transcript", capture.OK)], content="x" * 100))
    assert "content shrank to 100" in canary.run(cfg)["results"][0]["problems"][0]
    assert main(["canary"]) == 1
    assert "[FAIL]" in capsys.readouterr().out


def test_canary_reports_a_capture_that_raises_and_never_touches_the_store(
    chtmp, monkeypatch, capsys
):
    cfg = _store(chtmp, CANARY + '[instagram]\nvideo_store = "/nonexistent/store"\n')
    seen = {}

    def resolve(c, url):
        seen["store"] = c.instagram.video_store
        raise RuntimeError("blocked")

    monkeypatch.setattr(registry, "resolve_adapter", resolve)
    rec = canary.run(cfg)
    assert seen["store"] == "" and cfg.instagram.video_store == "/nonexistent/store"
    assert "capture failed: RuntimeError: blocked" in rec["results"][0]["problems"][0]
    assert main(["canary", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["total"] == 1


def test_canary_health_never_run_and_stale(chtmp, monkeypatch):
    cfg = _store(chtmp, CANARY)
    assert canary.health(cfg) == (False, "never run — run `quarry canary` (and schedule it daily)")
    _use(monkeypatch, _result([capture.stage("a", capture.OK)]))
    canary.run(cfg)
    healthy, why = canary.health(cfg, now=time.time() + 40 * 3600)
    assert not healthy and "the schedule has stopped" in why
    canary.result_path(cfg).write_text("{broken")
    assert canary.load(cfg) is None


def test_canary_cli_needs_sources(chtmp, capsys):
    _store(chtmp)
    assert main(["canary"]) == 1
    assert "no canary sources" in capsys.readouterr().err


def _manifest(cfg, slug, stages, adapter="instagram"):
    m = manifest.build(
        slug=slug, source_url="u", adapter=adapter, raw_path=f"raw/{slug}.md", content="c",
        target_wiki_path=None, required_frontmatter=[], metadata={},
    )  # fmt: skip
    if stages is not None:
        m["stages"] = stages
    manifest.write(cfg, slug, m)


def test_symptoms_flags_a_stage_that_fails_or_is_empty_too_often(chtmp):
    cfg = _store(chtmp)
    for i in range(6):
        _manifest(cfg, f"f{i}", [
            capture.stage("audio transcript", capture.FAILED if i < 4 else capture.OK),
            capture.stage("caption", capture.EMPTY if i < 5 else capture.OK),
            capture.stage("frames", capture.SKIPPED),
            capture.stage("video", capture.OK),
        ])  # fmt: skip
    _manifest(cfg, "old", None)
    (manifest.manifest_path(cfg, "junk")).write_text("{nope")
    looked, sym = canary.symptoms(cfg)
    assert looked == 6
    assert sym == [
        "instagram: audio transcript failed in 4 of 6",
        "instagram: caption was empty in 5 of 6",
    ]
    assert canary.symptoms(cfg, last=2)[1] == []  # under three captures says nothing


def test_doctor_reports_canary_and_symptoms(chtmp, monkeypatch, capsys):
    cfg = _store(chtmp, CANARY)
    for i in range(3):
        _manifest(cfg, f"f{i}", [capture.stage("audio transcript", capture.FAILED)])
    main(["doctor"])
    out = capsys.readouterr().out
    assert "canary captures (never run" in out
    assert "instagram: audio transcript failed in 3 of 3" in out
