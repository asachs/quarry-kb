"""The GitHub capture chooses what to keep instead of cutting the digest off."""

from quarry.adapters import github as gh
from quarry.adapters.github import GitHubAdapter
from quarry.config import GithubConfig

BAR = "=" * 48


def _digest(files: dict[str, str]) -> str:
    return "".join(f"{BAR}\nFILE: {p}\n{BAR}\n{t}\n\n" for p, t in files.items())


def _adapter(monkeypatch, files, tree="TREE", **settings):
    a = GitHubAdapter()
    monkeypatch.setattr(a, "_settings", lambda: GithubConfig(**settings))
    monkeypatch.setattr(a, "_ingest", lambda url: ("SUMMARY", tree, _digest(files)))
    return a


def test_split_files_roundtrip():
    files = {"README.md": "hello\nworld", "src/a.py": "x = 1"}
    assert gh.split_files(_digest(files)) == list(files.items())
    assert gh.split_files("no markers here") == []


def test_rank_puts_docs_and_manifests_before_source_and_tests_last():
    paths = [
        "apps/web/lib/i18n/locales/de/translation.json",
        "packages/db/schema.ts",
        "tests/test_x.py",
        "src/a.test.ts",
        "docs/guide.md",
        "package.json",
        "apps/web/Dockerfile",
        "README.md",
        "AGENTS.md",
        "main.py",
    ]
    order = sorted(paths, key=gh.rank)
    assert order[:2] == ["AGENTS.md", "README.md"]
    assert order.index("package.json") < order.index("docs/guide.md") < order.index("main.py")
    assert order.index("apps/web/Dockerfile") < order.index("main.py")
    assert order.index("main.py") < order.index("packages/db/schema.ts")
    assert order.index("packages/db/schema.ts") < order.index("tests/test_x.py")
    assert order[-1].endswith("translation.json")


def test_excluded_names_and_directories():
    pats = [*gh.DEFAULT_EXCLUDE, "docs/generated/"]
    for p in (
        "pnpm-lock.yaml",
        "a/package-lock.json",
        "Cargo.lock",
        "LICENSE",
        "LICENSE.md",
        "web/app.min.js",
        "x/node_modules/y/index.js",
        "docs/generated/api.md",
        "go.sum",
    ):
        assert gh.excluded(p, pats), p
    for p in ("README.md", "src/lock.py", "docs/guide.md", "build.gradle", "src/license_check.py"):
        assert not gh.excluded(p, pats), p


def test_lockfile_and_licence_no_longer_eat_the_budget(monkeypatch):
    # the shape that broke: licence and lockfile sort before the source in the digest
    files = {
        "README.md": "what it is",
        "LICENSE": "L" * 50_000,
        "pnpm-lock.yaml": "K" * 500_000,
        "packages/db/schema.ts": "export const bookmarks = sqliteTable()",
    }
    r = _adapter(monkeypatch, files, max_chars=10_000).fetch("https://github.com/o/r")
    assert "sqliteTable" in r.content and "what it is" in r.content
    assert "LLLL" not in r.content and "KKKK" not in r.content
    assert "2 of 2 text files are included" in r.content
    assert "Never fetched: lockfiles" in r.content


def test_one_large_file_is_shortened_not_allowed_to_crowd_out_others(monkeypatch):
    files = {"README.md": "R" * 5_000, "src/big.py": "B" * 9_000, "src/small.py": "small"}
    r = _adapter(monkeypatch, files, max_chars=8_000, max_file_chars=2_000).fetch(
        "https://github.com/o/r"
    )
    assert "small" in r.content and "file shortened by quarry" in r.content
    assert "2 file(s) were shortened to 2,000 characters: README.md, src/big.py" in r.content
    assert r.content.count("B") < 2_100


def test_files_that_do_not_fit_are_counted_and_flagged(monkeypatch):
    files = {"README.md": "R" * 900, "src/a.py": "A" * 900, "src/b.py": "C" * 900}
    r = _adapter(monkeypatch, files, max_chars=2_000).fetch("https://github.com/o/r")
    assert "2 of 3 text files are included" in r.content
    assert "1 file(s) did not fit and are NOT in this capture" in r.content
    assert r.content.index("## Capture notes") < r.content.index("## Tree")


def test_extra_exclude_patterns_from_config(monkeypatch):
    files = {"README.md": "r", "docs/generated/api.md": "GENERATED"}
    a = _adapter(monkeypatch, files, exclude=["docs/generated/"])
    assert "GENERATED" not in a.fetch("https://github.com/o/r").content
    assert "docs/generated/" in a._patterns() and "*.lock" in a._patterns()


def test_unrecognised_digest_is_cut_and_says_so(monkeypatch):
    a = GitHubAdapter()
    monkeypatch.setattr(a, "_settings", lambda: GithubConfig(max_chars=100))
    monkeypatch.setattr(a, "_ingest", lambda url: ("S", "T", "x" * 500))
    r = a.fetch("https://github.com/o/r")
    assert "[... truncated ...]" in r.content and "cut off at 100 characters" in r.content
    monkeypatch.setattr(a, "_ingest", lambda url: ("S", "T", "short"))
    assert "## Capture notes" not in a.fetch("https://github.com/o/r").content


def test_tree_is_cut_to_a_depth_that_fits(monkeypatch):
    tree = "\n".join(
        ["Directory structure:", "└── repo/", "    ├── README.md", "    ├── apps/"]
        + [f"    │   ├── web{i}/" for i in range(3)]
        + [f"    │   │   ├── f{i}.ts" for i in range(30)]
        + ["    └── packages/", "        └── db/", "            └── schema.ts"]
    )
    out, depth = gh.trim_tree(tree, 12)
    assert depth == 3 and "f0.ts" not in out and "web0/" in out and "db/" in out
    assert gh.trim_tree(tree, 1000) == (tree, None)
    out, depth = gh.trim_tree(tree, 2)
    assert depth == 1 and out.splitlines() == ["Directory structure:", "└── repo/"]
    r = _adapter(monkeypatch, {"README.md": "r"}, tree=tree, max_tree_lines=12).fetch(
        "https://github.com/o/r"
    )
    assert "The tree is shown to depth 3" in r.content


def test_default_settings_without_a_config():
    assert GitHubAdapter()._settings() == GithubConfig()


def test_prose_cannot_leave_source_out_and_the_reverse():
    docs = [(f"docs/page{i}.md", "D" * 1_000) for i in range(50)]
    src = [(f"src/mod{i}.py", "S" * 1_000) for i in range(50)]
    kept, stats = gh.select(docs + src, max_chars=10_000, max_file_chars=5_000)
    names = [p for p, _ in kept]
    assert sum(n.startswith("docs/") for n in names) >= 1
    assert sum(n.startswith("src/") for n in names) >= 3
    assert stats["chars"] <= 10_000 and len(stats["left_out"]) == 100 - len(kept)
    # with no source at all, the documentation may use the whole budget
    kept, _ = gh.select(docs, max_chars=10_000, max_file_chars=5_000)
    assert len(kept) == 10


def test_history_and_tests_only_get_what_is_left():
    files = [
        ("release-notes/v1.md", "N" * 400),
        ("tests/test_a.py", "T" * 400),
        ("src/a.py", "A" * 400),
        ("README.md", "R" * 400),
    ]
    kept, stats = gh.select(files, max_chars=900, max_file_chars=1_000)
    assert [p for p, _ in kept] == ["README.md", "src/a.py"]
    assert stats["left_out"] == ["tests/test_a.py", "release-notes/v1.md"] or set(
        stats["left_out"]
    ) == {"tests/test_a.py", "release-notes/v1.md"}


def test_core_code_ranks_ahead_of_other_code_and_of_config_noise():
    paths = [
        ".oxlintrc.json",
        "patches/react.patch",
        "kubernetes/web.yaml",
        ".github/ci.yml",
        "apps/web/components/Button.tsx",
        "packages/db/schema.ts",
        "packages/trpc/routers/bookmarks.ts",
        "apps/workers/index.ts",
        "scripts/dev.sh",
        "CLAUDE.md -> AGENTS.md",
    ]
    cls = {p: gh.rank(p)[0] for p in paths}
    assert cls["packages/db/schema.ts"] == gh.CORE_CODE == cls["apps/workers/index.ts"]
    assert cls["apps/web/components/Button.tsx"] == gh.CODE
    assert cls["packages/trpc/routers/bookmarks.ts"] == gh.CODE
    for p in (
        ".oxlintrc.json",
        "patches/react.patch",
        "kubernetes/web.yaml",
        ".github/ci.yml",
        "scripts/dev.sh",
    ):
        assert cls[p] == gh.OTHER, p
    assert cls["CLAUDE.md -> AGENTS.md"] == gh.DOCS
    assert gh.rank("apps/web/tailwind.config.ts")[0] == gh.OTHER
    assert gh.rank("apps/web/css.d.ts")[0] == gh.OTHER
