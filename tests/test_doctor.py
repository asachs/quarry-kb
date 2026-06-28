"""Tests for `quarry doctor` — ISC-82."""

from pathlib import Path

from quarry.cli import main


def test_doctor_reports_and_exits_zero(cfg, capsys):
    """Valid config + (extras installed in the test env) -> exit 0, full report."""
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "quarry.toml found + valid" in out
    assert "youtube" in out and "web" in out
    assert "discovery backend" in out


def test_doctor_no_config_exits_two(chtmp: Path, capsys):
    assert main(["doctor"]) == 2
    out = capsys.readouterr().out
    assert "quarry.toml" in out
