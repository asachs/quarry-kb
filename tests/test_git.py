"""Tests for the thin git helpers — ISC-22, 45, 48."""

import subprocess
from pathlib import Path

import pytest

from quarry import git
from quarry.errors import QuarryError


@pytest.fixture
def gitrepo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    return tmp_path


def test_is_repo_true(gitrepo: Path):
    assert git.is_repo(gitrepo) is True


def test_is_repo_false(tmp_path: Path):
    """ISC-22/-48: a plain dir is not a repo (graceful, no crash)."""
    assert git.is_repo(tmp_path) is False


def test_add_and_commit(gitrepo: Path):
    (gitrepo / "f.txt").write_text("hi")
    git.add_all(gitrepo)
    git.commit(gitrepo, "first commit")
    msg = subprocess.run(
        ["git", "log", "-1", "--format=%s"], cwd=gitrepo, capture_output=True, text=True
    ).stdout.strip()
    assert msg == "first commit"


def test_commit_nothing_raises(gitrepo: Path):
    git.add_all(gitrepo)
    with pytest.raises(QuarryError, match="git commit failed"):
        git.commit(gitrepo, "empty")


def test_push_no_remote_raises(gitrepo: Path):
    (gitrepo / "f.txt").write_text("hi")
    git.add_all(gitrepo)
    git.commit(gitrepo, "c")
    with pytest.raises(QuarryError, match="git push failed"):
        git.push(gitrepo)
