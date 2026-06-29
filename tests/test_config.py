"""Tests for config load / validate / defaults — ISC-13, 14, 15, 16, 17, 18, 19, 21."""

from pathlib import Path

import pytest

from quarry import config
from quarry.errors import ConfigError


def _write(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


def test_minimal_config_applies_all_defaults(chtmp: Path):
    """ISC-17: a near-empty quarry.toml loads with every field defaulted."""
    _write(chtmp / "quarry.toml", "[store]\n")
    cfg = config.load(chtmp)
    assert cfg.store.wiki == "wiki"
    assert cfg.store.manifest_dir == ".quarry"
    assert cfg.frontmatter.required == ["title", "updated", "sources", "related"]
    assert cfg.adapters.enabled == ["youtube", "github", "instagram", "pdf", "web"]
    assert cfg.lint.fail_on == ["broken_links", "missing_sources"]
    assert cfg.finish.commit_template == "wiki: {slug}"
    assert cfg.root == chtmp.resolve()


def test_overrides_take_effect(chtmp: Path):
    _write(
        chtmp / "quarry.toml",
        '[store]\nwiki = "notes"\n[discovery]\ndedup_threshold = 70\n',
    )
    cfg = config.load(chtmp)
    assert cfg.store.wiki == "notes"
    assert cfg.discovery.dedup_threshold == 70


def test_explicit_root_overrides_discovery(chtmp: Path):
    """ISC-21: [store] root overrides walk-up discovery."""
    target = chtmp / "elsewhere"
    target.mkdir()
    _write(chtmp / "quarry.toml", f'[store]\nroot = "{target}"\n')
    cfg = config.load(chtmp)
    assert cfg.root == target.resolve()


def test_config_discovered_by_walking_up(chtmp: Path):
    """find_config walks up from a nested CWD."""
    _write(chtmp / "quarry.toml", "[store]\n")
    nested = chtmp / "a" / "b"
    nested.mkdir(parents=True)
    cfg = config.load(nested)
    assert cfg.config_path == (chtmp / "quarry.toml")


def test_missing_config_raises_with_exact_message(chtmp: Path):
    """ISC-14: absent config raises ConfigError with the prescribed message."""
    with pytest.raises(ConfigError, match=r"no quarry\.toml found \(run 'quarry init'\)"):
        config.load(chtmp)


def test_unknown_key_warns_not_fails(chtmp: Path, capsys: pytest.CaptureFixture):
    """ISC-15: unknown keys warn to stderr but the load succeeds."""
    _write(chtmp / "quarry.toml", '[store]\nwiki = "w"\nbogus_key = "x"\n')
    cfg = config.load(chtmp)
    assert cfg.store.wiki == "w"
    err = capsys.readouterr().err
    assert "unknown config keys" in err
    assert "bogus_key" in err


def test_unknown_table_warns(chtmp: Path, capsys: pytest.CaptureFixture):
    _write(chtmp / "quarry.toml", "[store]\n[nonsense]\nx = 1\n")
    config.load(chtmp)
    assert "nonsense" in capsys.readouterr().err


def test_type_error_fails(chtmp: Path):
    """ISC-16: a wrong-typed value fails with a field-named ConfigError."""
    _write(chtmp / "quarry.toml", '[discovery]\ndedup_threshold = "lots"\n')
    with pytest.raises(ConfigError, match=r"dedup_threshold: expected int"):
        config.load(chtmp)


def test_bool_does_not_satisfy_int(chtmp: Path):
    """A TOML bool must not pass for an int field (bool subclasses int)."""
    _write(chtmp / "quarry.toml", "[discovery]\ndedup_threshold = true\n")
    with pytest.raises(ConfigError, match="dedup_threshold"):
        config.load(chtmp)


def test_list_element_type_checked(chtmp: Path):
    _write(chtmp / "quarry.toml", "[adapters]\nenabled = [1, 2]\n")
    with pytest.raises(ConfigError, match=r"enabled: expected list\[str\]"):
        config.load(chtmp)


def test_table_must_be_table(chtmp: Path):
    _write(chtmp / "quarry.toml", 'store = "notatable"\n')
    with pytest.raises(ConfigError, match=r"\[store\]: expected a table"):
        config.load(chtmp)


def test_invalid_toml_is_config_error(chtmp: Path):
    _write(chtmp / "quarry.toml", "[store\n")
    with pytest.raises(ConfigError, match="invalid TOML"):
        config.load(chtmp)


@pytest.mark.parametrize(
    "body,match",
    [
        ('[ingest]\non_duplicate = "nope"\n', "on_duplicate"),
        ('[discovery]\nbackend = "faiss"\n', "backend"),
        ('[discovery]\nmode = "sometimes"\n', "mode"),
    ],
)
def test_enum_validation(chtmp: Path, body: str, match: str):
    _write(chtmp / "quarry.toml", body)
    with pytest.raises(ConfigError, match=match):
        config.load(chtmp)


def test_pyproject_tool_quarry_fallback(chtmp: Path):
    """ISC-19: a [tool.quarry] table in pyproject.toml is the fallback source."""
    _write(
        chtmp / "pyproject.toml",
        '[tool.quarry.store]\nwiki = "kb"\n[tool.quarry.ingest]\non_duplicate = "allow"\n',
    )
    cfg = config.load(chtmp)
    assert cfg.store.wiki == "kb"
    assert cfg.ingest.on_duplicate == "allow"
    assert cfg.config_path == (chtmp / "pyproject.toml")


def test_standalone_config_beats_pyproject(chtmp: Path):
    """A nearer quarry.toml wins over a pyproject fallback higher up."""
    _write(chtmp / "pyproject.toml", '[tool.quarry.store]\nwiki = "from_pyproject"\n')
    _write(chtmp / "quarry.toml", '[store]\nwiki = "from_toml"\n')
    cfg = config.load(chtmp)
    assert cfg.store.wiki == "from_toml"


# --- Source-level invariants (ISC-13, ISC-18) -------------------------------

_SRC = Path(__file__).resolve().parent.parent / "src" / "quarry"


def test_no_tomli_backport_anywhere():
    """ISC-13: native tomllib only — no tomli import in the package."""
    for py in _SRC.rglob("*.py"):
        text = py.read_text()
        assert "import tomli\n" not in text and "import tomli " not in text
        assert "from tomli " not in text


def test_only_config_reads_tomllib():
    """ISC-18: conventions flow through Config — only config.py parses TOML."""
    readers = [
        py.name for py in _SRC.rglob("*.py") if "tomllib" in py.read_text()
    ]
    assert readers == ["config.py"], f"unexpected tomllib readers: {readers}"
