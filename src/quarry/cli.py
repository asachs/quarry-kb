"""Command-line entry point — argparse dispatch to command functions.

Each command function takes the parsed args and returns a process exit code.
Errors raised as ``ConfigError`` (exit 2) or ``QuarryError`` (exit 1) are caught
here and printed as clean one-liners — never a traceback.
"""

from __future__ import annotations

import argparse
import sys

from quarry import __version__, config
from quarry.errors import ConfigError, QuarryError


def cmd_init(args: argparse.Namespace) -> int:
    path = config.init(force=args.force)
    print(f"✓ wrote {path.name}")
    print("✓ .quarry/ is gitignored")
    print("\nEdit quarry.toml to match your wiki, then: quarry ingest <url>")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="quarry", description="knowledge-ingestion harness")
    p.add_argument("--version", action="version", version=f"quarry {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("init", help="scaffold a documented quarry.toml in the current dir")
    pi.add_argument("--force", action="store_true", help="overwrite an existing quarry.toml")
    pi.set_defaults(func=cmd_init)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as e:  # most specific first — distinct exit code
        print(f"quarry: {e}", file=sys.stderr)
        return 2
    except QuarryError as e:
        print(f"quarry: error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
