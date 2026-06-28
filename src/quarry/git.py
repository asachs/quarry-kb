"""Thin git helpers with a non-git fallback.

`finish` uses these to commit a finished article. Each helper raises a clean
QuarryError on failure; ``is_repo`` lets callers degrade gracefully when the store
is not a git repository (or git is not installed).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from quarry.errors import QuarryError


def is_repo(root: Path) -> bool:
    """True iff ``root`` is inside a git work tree and git is available."""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=root,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return False
    return r.returncode == 0 and r.stdout.strip() == "true"


def _run(args: list[str], root: Path, what: str) -> None:
    try:
        subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True)
    except FileNotFoundError as e:
        raise QuarryError("git not found on PATH") from e
    except subprocess.CalledProcessError as e:
        raise QuarryError(f"git {what} failed: {e.stderr.strip() or e.stdout.strip()}") from e


def add_all(root: Path) -> None:
    _run(["add", "-A"], root, "add")


def commit(root: Path, message: str) -> None:
    _run(["commit", "-m", message], root, "commit")


def push(root: Path) -> None:
    _run(["push"], root, "push")
