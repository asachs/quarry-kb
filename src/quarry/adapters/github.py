"""GitHub adapter — repo digest via gitingest (deterministic, no LLM, no key).

Wraps ``gitingest`` (summary + directory tree + concatenated file contents). The
ingest call lives in an overridable method so tests stay hermetic. Requires the
``[github]`` extra.

The digest of a real repository is far larger than a raw file should be, so the adapter
chooses what to keep instead of cutting the digest off wherever the budget runs out. A
capture of a 2,300-file monorepo once spent its whole budget on the licence text and the
first part of a lockfile and stopped before any source code, with nothing in the raw to
say so. Now: files that describe nothing (lockfiles, licence text, minified and generated
files) are never fetched; what remains is ranked (documentation, then manifests and
config, then source, shallow paths first); each file is capped so one cannot crowd out
the rest; and a ``## Capture notes`` section states how many files were kept, shortened
and left out.
"""

from __future__ import annotations

import datetime as _dt
import fnmatch
import re

from quarry.adapters.base import Adapter, FetchResult
from quarry.config import GithubConfig
from quarry.errors import QuarryError

# Files that say nothing about what a project is or how it works.
DEFAULT_EXCLUDE = (
    "*.lock",
    "*-lock.json",
    "*-lock.yaml",
    "*.lockb",
    "go.sum",
    "LICENSE*",
    "LICENCE*",
    "COPYING*",
    "NOTICE*",
    "*.min.js",
    "*.min.css",
    "*.map",
    "*.snap",
    "*.svg",
    "*.ipynb",
    "node_modules/",
    "vendor/",
    "dist/",
    "build/",
    "__snapshots__/",
)

_SEP = re.compile(r"^={20,}\n(?:FILE|SYMLINK): (.+?)\n={20,}\n", re.M)
_DOC_NAMES = ("readme", "agents", "claude", "contributing", "architecture", "design")
_MANIFESTS = (
    "package.json",
    "pyproject.toml",
    "cargo.toml",
    "go.mod",
    "setup.py",
    "setup.cfg",
    "requirements.txt",
    "gemfile",
    "pom.xml",
    "build.gradle",
    "dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
    "makefile",
    "turbo.json",
    "pnpm-workspace.yaml",
    ".env.sample",
    ".env.example",
)
_TEST = re.compile(
    r"(^|/)(tests?|__tests__|e2e|e2e_tests|fixtures|testdata|spec)(/|$)|\.(test|spec)\."
)
_HISTORY = re.compile(r"(^|/)(release[-_]?notes|changelogs?|migrations?)(/|$)")
_LOCALE = re.compile(r"(^|/)(locales?|i18n|translations?)(/|$)")


def split_files(content: str) -> list[tuple[str, str]]:
    """A gitingest digest as ``(path, text)`` pairs, in digest order."""
    marks = list(_SEP.finditer(content))
    out = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(content)
        out.append((m.group(1).strip(), content[m.end() : end].strip("\n")))
    return out


_CODE = (
    ".ts", ".tsx", ".js", ".jsx", ".mjs", ".py", ".go", ".rs", ".java", ".kt", ".swift", ".rb",
    ".php", ".c", ".h", ".cc", ".cpp", ".cs", ".scala", ".clj", ".cljs", ".ex", ".exs", ".sql",
    ".prisma", ".proto", ".graphql", ".lua", ".zig", ".nix",
)  # fmt: skip
# File names that usually hold a project's shape: its data model, entry points and wiring.
_CORE = re.compile(
    r"^(schema|models?|types?|index|main|app|server|cli|api|config|routes?|routers?|workers?"
    r"|queue|db|database|core|lib|mod|__init__|__main__)$"
)
_OPS = re.compile(r"(^|/)(\.[^/]+|patches|kubernetes|k8s|charts|helm|\.github)(/|$)")

DOCS, MANIFEST, PROSE, CORE_CODE, CODE, OTHER, TESTS, LOCALES = range(8)


def rank(path: str) -> tuple[int, int, str]:
    """Sort key. Classes in order: top-level documentation, manifests, other prose, code
    whose name suggests the project's shape, other code, everything else (config, patches,
    deployment files), tests and history, translations. Within a class, shallow paths
    first."""
    low = path.split(" -> ")[0].lower()
    name = low.rsplit("/", 1)[-1]
    depth = low.count("/")
    stem, dot, ext = name.rpartition(".")
    stem, ext = (stem, dot + ext) if dot and stem else (name, "")
    if _LOCALE.search(low):
        cls = LOCALES
    elif _TEST.search(low) or _HISTORY.search(low):
        cls = TESTS
    elif stem in _DOC_NAMES and depth <= 1:
        cls = DOCS
    elif name in _MANIFESTS or name.startswith("dockerfile"):
        cls = MANIFEST
    elif ext in (".md", ".mdx", ".rst", ".txt"):
        cls = PROSE
    elif _OPS.search(low) or " -> " in path or ".config." in name or name.endswith(".d.ts"):
        cls = OTHER
    elif ext in _CODE:
        cls = CORE_CODE if _CORE.match(stem) else CODE
    else:
        cls = OTHER
    return (cls, depth, low)


def excluded(path: str, patterns: tuple[str, ...] | list[str]) -> bool:
    name = path.rsplit("/", 1)[-1]
    for pat in patterns:
        if pat.endswith("/"):
            if f"/{pat}" in f"/{path}/":
                return True
        elif fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(path, pat):
            return True
    return False


# The share of the budget each class may take on the first pass, so that a repository with
# a lot of prose cannot leave its source out (and the reverse). What a class does not use
# is handed out again in rank order.
_SHARE = {
    DOCS: 0.30,
    MANIFEST: 0.10,
    PROSE: 0.15,
    CORE_CODE: 0.30,
    CODE: 0.15,
    OTHER: 0.0,
    TESTS: 0.0,
    LOCALES: 0.0,
}


def select(
    files: list[tuple[str, str]], *, max_chars: int, max_file_chars: int
) -> tuple[list[tuple[str, str]], dict]:
    """Choose which files fit the budget. Returns the kept files (ranked) and the counts
    the capture notes report."""
    ranked = sorted(files, key=lambda f: rank(f[0]))
    bodies: dict[str, str] = {}
    shortened: set[str] = set()
    for path, text in ranked:
        if len(text) > max_file_chars:
            text = text[:max_file_chars].rstrip() + "\n[... file shortened by quarry ...]"
            shortened.add(path)
        bodies[path] = text
    chosen: set[str] = set()
    used = 0
    spent = dict.fromkeys(_SHARE, 0)
    # Second pass: what the shares left unused goes to code first, since prose has had its
    # share and a long docs folder would otherwise take the remainder as well.
    code_first = sorted(ranked, key=lambda f: (rank(f[0])[0] not in (CORE_CODE, CODE), rank(f[0])))
    for share_limited, order in ((True, ranked), (False, code_first)):
        for path, _ in order:
            size = len(bodies[path])
            cls = rank(path)[0]
            if path in chosen or used + size > max_chars:
                continue
            if share_limited and spent[cls] + size > _SHARE[cls] * max_chars:
                continue
            chosen.add(path)
            used += size
            spent[cls] += size
    kept = [(p, bodies[p]) for p, _ in ranked if p in chosen]
    return kept, {
        "shortened": [p for p, _ in kept if p in shortened],
        "left_out": [p for p, _ in ranked if p not in chosen],
        "chars": used,
    }


def trim_tree(tree: str, max_lines: int) -> tuple[str, int | None]:
    """The directory tree cut to a depth at which it fits ``max_lines``. Returns the tree
    and the depth it was cut to (``None`` when nothing was cut)."""
    lines = tree.rstrip("\n").split("\n")
    if max_lines <= 0 or len(lines) <= max_lines:
        return tree, None

    def depth(line: str) -> int:
        m = re.match(r"^((?:│   |    )*)(?:├── |└── )", line)
        return len(m.group(1)) // 4 + 1 if m else 0

    depths = [depth(line) for line in lines]
    limit = max(depths)
    cut = lines
    while limit > 1 and len(cut) > max_lines:
        limit -= 1
        cut = [line for line, d in zip(lines, depths, strict=True) if d <= limit]
    return "\n".join(cut) + "\n", limit


class GitHubAdapter(Adapter):
    name = "github"

    def matches(self, url: str) -> bool:
        return bool(re.match(r"https?://github\.com/[^/]+/[^/]+", url))

    def _settings(self) -> GithubConfig:
        return getattr(self.cfg, "github", None) or GithubConfig()

    def _patterns(self) -> list[str]:
        return [*DEFAULT_EXCLUDE, *self._settings().exclude]

    # --- overridable, needs the [github] extra ----------------------------
    def _ingest(self, url: str) -> tuple[str, str, str]:  # pragma: no cover - network/extra
        try:
            from gitingest import ingest
        except ImportError as e:
            raise QuarryError(
                "github adapter needs the [github] extra (pip install 'quarry-kb[github]')"
            ) from e
        s = self._settings()
        summary, tree, content = ingest(
            url, max_file_size=s.max_file_bytes, exclude_patterns=set(self._patterns())
        )
        return summary, tree, content

    # --- contract ---------------------------------------------------------
    def fetch(self, url: str) -> FetchResult:
        m = re.match(r"https?://github\.com/([^/]+)/([^/?#]+)", url)
        if not m:
            raise QuarryError(f"github: could not parse owner/repo from {url}")
        owner, repo = m.group(1), m.group(2).removesuffix(".git")
        s = self._settings()

        summary, tree, content = self._ingest(url)
        patterns = self._patterns()
        files = split_files(content)
        notes: list[str] = []
        if files:
            wanted = [(p, t) for p, t in files if not excluded(p, patterns)]
            kept, stats = select(wanted, max_chars=s.max_chars, max_file_chars=s.max_file_chars)
            content = "\n\n".join(f"{'=' * 48}\nFILE: {p}\n{'=' * 48}\n{t}" for p, t in kept)
            notes.append(
                f"{len(kept)} of {len(wanted)} text files are included below "
                f"({stats['chars']:,} characters), documentation and manifests first, "
                "then code (data model, entry points and wiring before the rest)."
            )
            if stats["shortened"]:
                notes.append(
                    f"{len(stats['shortened'])} file(s) were shortened to "
                    f"{s.max_file_chars:,} characters: " + ", ".join(stats["shortened"][:20])
                )
            if stats["left_out"]:
                notes.append(
                    f"{len(stats['left_out'])} file(s) did not fit and are NOT in this capture; "
                    "the tree lists them. Anything about their contents is unverified."
                )
            notes.append("Never fetched: lockfiles, licence text, minified and generated files.")
        elif len(content) > s.max_chars:
            # an unrecognised digest shape: fall back to a plain cut, and say so
            content = content[: s.max_chars] + "\n\n[... truncated ...]\n"
            notes.append(f"The digest was cut off at {s.max_chars:,} characters.")
        tree, cut_depth = trim_tree(tree, s.max_tree_lines)
        if cut_depth is not None:
            notes.append(f"The tree is shown to depth {cut_depth}; deeper entries are omitted.")

        body = f"# {owner}/{repo}\n\n## Summary\n\n{summary}\n\n"
        if notes:
            body += "## Capture notes\n\n" + "\n".join(f"- {n}" for n in notes) + "\n\n"
        body += f"## Tree\n\n{tree}\n\n## Contents\n\n{content}"

        return FetchResult(
            content=body,
            metadata={
                "title": f"{owner}/{repo}",
                "author": owner,
                "date": _dt.date.today().isoformat(),
                "url": url,
                "source_id": f"{owner}/{repo}",
            },
        )
