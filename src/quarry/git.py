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


def changed_paths(root: Path) -> list[str]:
    """Modified, added and untracked files (root-relative), from ``git status``."""
    r = subprocess.run(
        ["git", "status", "--porcelain", "-z", "--untracked-files=all"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    out: list[str] = []
    entries = r.stdout.split("\0")
    i = 0
    while i < len(entries):
        e = entries[i]
        i += 1
        if len(e) < 4:
            continue
        status, path = e[:2], e[3:]
        if "R" in status or "C" in status:
            i += 1  # a rename/copy is followed by its source path
        if "D" in status:
            continue
        out.append(path)
    return out


def commit_paths(root: Path, paths: list[str], message: str) -> bool:
    """Stage and commit ONLY ``paths`` (others' staged work is left alone).

    Returns False when none of the paths has changes (nothing to commit).
    """
    if not paths:
        return False
    _run(["add", "--", *paths], root, "add")
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--", *paths],
        cwd=root,
        capture_output=True,
        text=True,
    ).stdout.split()
    if not staged:
        return False
    _run(["commit", "-m", message, "--", *paths], root, "commit")
    return True


def push(root: Path) -> None:
    _run(["push"], root, "push")
