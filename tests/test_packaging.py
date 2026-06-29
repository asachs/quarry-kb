"""Tests for packaging metadata — ISC-4, 5, 6, 7, 8, 94."""

import tomllib
from pathlib import Path

from quarry.config import DEFAULT_TOML

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text())
PROJECT = PYPROJECT["project"]


def test_build_backend_hatchling():
    assert PYPROJECT["build-system"]["build-backend"] == "hatchling.build"


def test_requires_python_3_11():
    assert PROJECT["requires-python"] == ">=3.11"


def test_core_dependency_is_pyyaml_only():
    """ISC-6: exactly one core runtime dependency, PyYAML."""
    assert PROJECT["dependencies"] == ["PyYAML>=6.0"]


def test_no_tomli_dependency():
    assert all("tomli" not in d for d in PROJECT["dependencies"])


def test_extras_declared():
    """ISC-7: all five extras are declared."""
    assert set(PROJECT["optional-dependencies"]) == {
        "youtube", "web", "reddit", "reddit-oauth", "github", "pdf",
        "instagram", "whisper", "discovery", "all", "dev",
    }


def test_console_script():
    assert PROJECT["scripts"]["quarry"] == "quarry.cli:main"


def test_adapter_entry_point_group_present():
    assert "quarry.adapters" in PROJECT["entry-points"]


def test_license_is_mit():
    """ISC-8."""
    assert (ROOT / "LICENSE").read_text().startswith("MIT License")


def test_examples_quarry_toml_matches_init_default():
    """ISC-94: examples/quarry.toml is byte-identical to what `quarry init` writes."""
    assert (ROOT / "examples" / "quarry.toml").read_text() == DEFAULT_TOML
