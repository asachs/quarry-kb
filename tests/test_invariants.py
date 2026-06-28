"""Anti-criteria — the load-bearing invariants. ISC-96, 97, 98, 99, 100."""

import sys
from pathlib import Path

from quarry import config, lint

SRC = Path(__file__).resolve().parent.parent / "src" / "quarry"
SRC_FILES = sorted(SRC.rglob("*.py"))


def test_no_llm_sdk_imports():
    """ISC-96: Quarry never references an LLM SDK."""
    banned = ("anthropic", "openai", "cohere", "google.generativeai", "litellm", "langchain")
    for f in SRC_FILES:
        text = f.read_text()
        for b in banned:
            assert b not in text, f"{f.name} references {b}"


def test_no_api_key_or_env_access():
    """ISC-96/100: nothing reads API keys or the environment."""
    for f in SRC_FILES:
        text = f.read_text()
        assert "API_KEY" not in text, f"{f.name} mentions API_KEY"
        assert "os.environ" not in text, f"{f.name} reads os.environ"
        assert "getenv" not in text, f"{f.name} reads getenv"


def test_no_personal_data():
    """ISC-97: shipped code carries no private paths or the private repo name."""
    forbidden = ("/Users/", "/home/", "asachs/knowledge")
    for f in SRC_FILES:
        text = f.read_text()
        for b in forbidden:
            assert b not in text, f"{f.name} contains '{b}'"


def test_core_modules_have_no_hardcoded_conventions():
    """ISC-98: path/convention modules carry no bare 'wiki'/'raw' literals."""
    for mod in ("store.py", "ingest.py", "finish.py", "lint.py", "manifest.py"):
        text = (SRC / mod).read_text()
        assert '"wiki"' not in text, f"{mod} hardcodes \"wiki\""
        assert '"raw"' not in text and '"raw/"' not in text, f"{mod} hardcodes \"raw\""


def test_core_flows_work_without_optional_extras(monkeypatch, tmp_path: Path):
    """ISC-99: hiding the adapter extras must not break core flows."""
    monkeypatch.setitem(sys.modules, "trafilatura", None)
    monkeypatch.setitem(sys.modules, "youtube_transcript_api", None)
    monkeypatch.chdir(tmp_path)
    config.init()
    cfg = config.load(tmp_path)
    (cfg.root / "wiki").mkdir()
    (cfg.root / "wiki" / "a.md").write_text("---\ntitle: A\n---\n\nbody\n", encoding="utf-8")
    assert lint.run(cfg).total_articles == 1  # core flow unaffected


def test_runs_with_no_api_keys(monkeypatch, tmp_path: Path):
    """ISC-100: a core flow runs with common API-key env vars unset."""
    for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "QUARRY_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.chdir(tmp_path)
    config.init()
    assert config.load(tmp_path).store.wiki == "wiki"


def test_suite_is_hermetic_qmd_neutralized():
    """ISC-88/100: the autouse fixture neutralises any real qmd on the machine."""
    from quarry import discovery

    assert discovery.find_qmd() is None
