"""Tests for the CLI dispatch + exit codes — ISC-2, 3, 14, 79, 80, 81, 83."""

import subprocess
import sys
from pathlib import Path

import pytest

from quarry.cli import main


def test_module_entry_point():
    """ISC-3: `python -m quarry --help` runs via __main__ and exits 0."""
    result = subprocess.run(
        [sys.executable, "-m", "quarry", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "knowledge-ingestion harness" in result.stdout


def test_help_exits_zero(capsys: pytest.CaptureFixture):
    """ISC-81: --help works and exits 0."""
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "knowledge-ingestion harness" in capsys.readouterr().out


@pytest.mark.parametrize(
    "cmd",
    ["init", "adapters", "ingest", "finish", "lint", "doctor", "related", "densify"],
)
def test_every_command_has_help(cmd: str):
    """ISC-81: every subcommand responds to --help with exit 0."""
    with pytest.raises(SystemExit) as exc:
        main([cmd, "--help"])
    assert exc.value.code == 0


def test_version(capsys: pytest.CaptureFixture):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert "quarry" in capsys.readouterr().out


def test_no_command_errors():
    """ISC-79: invoking with no subcommand exits non-zero (argparse code 2)."""
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code != 0


def test_unknown_command_errors():
    """ISC-79: an unknown subcommand exits non-zero."""
    with pytest.raises(SystemExit) as exc:
        main(["frobnicate"])
    assert exc.value.code != 0


def test_init_via_cli(chtmp: Path, capsys: pytest.CaptureFixture):
    """ISC-2/-9: init through the dispatcher writes config and exits 0."""
    assert main(["init"]) == 0
    assert (chtmp / "quarry.toml").is_file()
    assert "wrote quarry.toml" in capsys.readouterr().out


def test_init_refuse_overwrite_exit_1(chtmp: Path, capsys: pytest.CaptureFixture):
    """ISC-80: an operational error (refuse overwrite) exits 1 with a one-liner."""
    main(["init"])
    assert main(["init"]) == 1
    err = capsys.readouterr().err
    assert err.startswith("quarry: error:")
    assert "Traceback" not in err


def test_missing_config_exit_2(chtmp: Path, capsys: pytest.CaptureFixture, monkeypatch):
    """ISC-14/-80: a config error maps to exit 2 with the prescribed message.

    Uses a throwaway 'probe' command that requires config, to exercise the
    ConfigError -> exit 2 path through main() without depending on a yet-unbuilt
    command.
    """
    import argparse

    from quarry import cli, config

    def cmd_probe(args: argparse.Namespace) -> int:
        config.load()
        return 0

    real_build = cli.build_parser

    def patched_build() -> argparse.ArgumentParser:
        parser = real_build()
        sub = parser._subparsers._group_actions[0]  # the subparsers action
        pp = sub.add_parser("probe")
        pp.set_defaults(func=cmd_probe)
        return parser

    monkeypatch.setattr(cli, "build_parser", patched_build)
    assert cli.main(["probe"]) == 2
    err = capsys.readouterr().err
    assert err == "quarry: no quarry.toml found (run 'quarry init')\n"
