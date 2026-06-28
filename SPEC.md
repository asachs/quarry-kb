# Quarry — Design Spec

> **Status:** spec / pre-build. This document defines Quarry well enough that a fresh
> session (or another engineer) can build it from scratch. The current implementation
> lives as a single file in the private `asachs/knowledge` repo (`bin/kb`, stashed here
> as `EXTRACTION-SOURCE-kb.py`) — Quarry generalises it into a standalone, public,
> config-driven, extensively-tested package.

## 1. What Quarry is

Quarry is a **knowledge-ingestion harness**: a CLI that owns the *deterministic* half of
turning a source (a YouTube video, a web page, a PDF, a repo…) into a linked article in a
markdown knowledge wiki. It resolves a source adapter, fetches, writes immutable raw
material, hands a machine-readable compile-spec to an LLM (or human) for the one
irreducibly-generative step — writing the article — then verifies provenance, lints, and
commits. It also surfaces semantic links (dedup at ingest, related-article discovery,
whole-wiki densification) via an optional embedding backend.

> *You extract raw material from the world and refine it into something structured.* That
> is the pipeline and the name.

**It is NOT** an LLM wrapper (it never calls a model — runnable/testable without API keys),
a note-taking app, or opinionated about *your* wiki's shape. Every convention is configuration.

## 2. Principles (carried from the harness, non-negotiable)

- **Code before prompts.** Deterministic mechanics are tested code; the LLM does only the article.
- **Two-call seam.** `ingest` (fetch → raw → manifest) and `finish` (verify → lint → commit) are separate; the agent/human writes the article between them. Quarry NEVER shells out to an LLM.
- **The manifest is the product.** The compile-spec is a persisted, machine-readable file; `finish` *verifies* the article against it (provenance), never trusts it.
- **Portable by construction.** No hardcoded paths; store root discovered at runtime; everything resolves from config.
- **Generic core.** No baked-in conventions. A `quarry.toml` is required; `quarry init` scaffolds a documented default. Quarry errors helpfully if config is absent.
- **Fail loud, fail tested.** Every mechanical step has a test that catches its break before a user does. Optional deps degrade gracefully, never crash.
- **Adapters are the extension unit.** New source = one small tested adapter, discoverable via entry points — no fork.

## 3. Package layout

```
quarry/                         # public repo (MIT or Apache-2.0)
  pyproject.toml                # pip-installable; console_script `quarry`; extras: [youtube] [web] [discovery] [all] [dev]
  src/quarry/
    __init__.py  __main__.py    # `python -m quarry`
    cli.py                      # argparse dispatch -> command funcs
    config.py                   # quarry.toml load, schema, validation, defaults, `init`
    store.py                    # root discovery (marker/git/explicit), path resolution from config
    manifest.py                # compile-manifest read/write, content hashing
    ingest.py                  # resolve adapter -> fetch -> raw write -> manifest -> dedup pre-check
    finish.py                  # provenance verify -> lint -> commit (no push unless --push)
    lint.py                    # structural-health lint (config-driven rules) + report
    discovery.py               # embedding backend (qmd): related, densify, dedup query — optional
    git.py                     # thin git helpers (rev-parse, add, commit, push) with non-git fallback
    adapters/
      __init__.py base.py registry.py
      youtube.py web.py        # shipped adapters (extras-gated imports)
  tests/                        # see §10
  docs/  examples/quarry.toml
  README.md  LICENSE  CHANGELOG.md  CONTRIBUTING.md
  .github/workflows/ci.yml
```

## 4. Configuration — `quarry.toml` (the heart of generic-core)

Discovered by walking up from CWD for `quarry.toml` (then a `[tool.quarry]` table in
`pyproject.toml` as a fallback). **Required** — absent config → `quarry: no quarry.toml
found (run 'quarry init')`. `quarry init` writes this fully-commented default:

```toml
[store]
# root is the dir containing quarry.toml unless set explicitly
wiki = "wiki"                 # compiled articles (relative to root)
raw  = "raw"                  # immutable source material
raw_layout = "{year}/{month}/{date}_{slug}.{ext}"   # raw path template (tokens below)
manifest_dir = ".quarry"      # compile-manifests (gitignored)

[frontmatter]
required = ["title", "updated", "sources", "related"]
sources_field = "sources"     # field whose entries cite raw/
related_field = "related"     # field listing related wiki articles

[ingest]
default_ext = "md"
slug = "{date}_{kebab_title}" # slug template
on_duplicate = "refuse"       # refuse | warn | allow  (governs the dedup pre-check)

[adapters]
enabled = ["youtube", "web"]  # allowlist; entry-point adapters gated by this

[discovery]
backend = "qmd"               # qmd | none
mode = "auto"                 # auto (use if available) | on (required) | off
collection = "wiki"
dedup_threshold = 85          # % match at ingest that triggers on_duplicate
densify_topk = 6              # mutual top-K for the densify sweep

[lint]
broken_links = true
require_sources_on_disk = true
orphan_check = true           # inbound-from-body only (frontmatter related: does NOT count — documented)
index_file = "index.md"       # "" disables the not-in-index check
fail_on = ["broken_links", "missing_sources"]   # which checks make `finish`/`lint` exit non-zero

[finish]
run_lint = true
auto_push = false
commit_template = "wiki: {slug}"
```

**Path tokens:** `{year} {month} {date} {slug} {kebab_title} {ext} {topic} {source_id}`.
Config is validated on load (unknown keys warn, type errors fail). A `Config` dataclass is
threaded through every command — **no module reads conventions directly.**

## 5. Commands (`quarry <cmd>`)

| Command | Purpose |
|---------|---------|
| `init` | scaffold `quarry.toml` (+ `.quarry/` gitignore entry) in CWD |
| `ingest <url> [--topic T] [--force]` | resolve adapter → fetch → write raw (per `raw_layout`) → write manifest → print compile-spec; dedup pre-check per `[discovery]`/`on_duplicate` |
| `finish <slug> [--article PATH] [--push]` | verify article provenance vs manifest → lint (if `run_lint`) → commit (push only on `--push`/config) |
| `lint` | run the structural-health report; exit non-zero per `[lint] fail_on` |
| `related <article>` | ranked semantic link candidates (excludes self + already-linked) |
| `densify [--apply] [--topk N]` | whole-wiki sweep for mutual top-K unlinked pairs; `--apply` adds bidirectional See-also links |
| `adapters` | list registered + enabled adapters |
| `doctor` | report config validity, optional deps/tools (git, qmd, adapter deps) |

Exit codes: 0 success; 1 user/operational error (clean one-line message, never a traceback); 2 config error.

## 6. Adapter contract + plugin system

```python
class Adapter(Protocol):
    name: str
    def matches(self, url: str) -> bool: ...
    def fetch(self, url: str) -> FetchResult:   # {content: str, metadata: {title, author, date, url, source_id, ext?}}
```

- **Registry**: built-in adapters + third-party via entry points
  `[project.entry-points."quarry.adapters"]`. The `[adapters] enabled` allowlist gates which run.
- **Self-contained**: each adapter carries its own fetch logic + a hermetic fixture test.
- **Errors isolate**: an adapter exception surfaces as a clean non-zero quarry error, never an uncaught traceback.
- **Shipped v1**: `youtube` (transcript via youtube-transcript-api current API + oEmbed metadata, extras `[youtube]`), `web` (readability/trafilatura extract, extras `[web]`). `pdf`, `github`, `instagram` are roadmap.

## 7. The compile-manifest seam

`ingest` writes `{manifest_dir}/{slug}.json`: `slug, source_url, adapter, raw_path,
content_sha256, target_wiki_path, required_frontmatter, must_cite_source, metadata`. It
then prints a human/agent-readable compile-spec. `finish` loads it and **verifies**: the
target article exists; its `sources_field` includes `must_cite_source`. Mismatch → abort.
Re-ingest of the same source is governed by `on_duplicate` + the dedup pre-check.

## 8. Lint (config-driven)

Port the current `run_lint` logic (broken links, missing sources, orphans, density,
top-connected, category health, not-in-index) but drive every check + the `fail_on` set
from `[lint]` config. Output: a structured `LintResult` (counts + per-issue lists) and a
formatted report. `finish` consumes the result object directly (no text-scraping). Keep a
**golden-output test** so the report format is locked.

## 9. Discovery (optional, pluggable backend)

`discovery.py` wraps an embedding/search backend (v1: `qmd`) behind a small interface
(`available()`, `query(text) -> [(score, path)]`). Powers: ingest **dedup** (`query(title)`,
≥`dedup_threshold` → `on_duplicate`), `related` (top candidates minus already-linked), and
`densify` (mutual top-K unlinked pairs → bidirectional See-also). `backend = "none"` or a
missing tool → these degrade gracefully (clean message / skip), never crash core flows.

## 10. Testing strategy ("extensive testing" — a first-class requirement)

- **Unit, per module**: config load/validate/default + `init`; store root discovery (git, marker, explicit); manifest write/read/hash; lint each check; adapter resolution; each adapter's parse logic (mocked, no network); discovery output parsing; git helpers (tmp repos).
- **Hermetic adapters**: recorded fixtures (cassettes) for youtube/web; **one** live `@pytest.mark.integration` test per network adapter, excluded from default runs.
- **Config matrix**: parametrised tests running the pipeline under *several* `quarry.toml` variants (different `raw_layout`, frontmatter schema, disabled discovery) — proves generic-core flexibility, not just the author's defaults.
- **Seam/provenance**: manifest round-trip; `finish` aborts on missing article, provenance mismatch, red lint; commit≠push; happy path.
- **Lint golden**: fixture wiki → expected report (byte-locked).
- **CLI integration**: invoke through the entry point (CliRunner/subprocess) for each command incl. error/exit-code paths and `--help`.
- **Edge/graceful**: empty store, malformed frontmatter, missing optional deps, non-git dir.
- **Gates**: coverage ≥ 90%; `ruff` clean; (optional) `mypy`. CI matrix py3.9–3.13.

## 11. Packaging

`pyproject.toml` (PEP 621, `hatchling` or `setuptools`): `console_scripts: quarry =
quarry.cli:main`; core deps **stdlib-only** (+ `tomli` for <3.11); extras
`[youtube]=youtube-transcript-api`, `[web]=trafilatura`, `[discovery]` (docs: qmd is an
external Node tool, not a pip dep — `doctor` checks it), `[all]`, `[dev]=pytest,ruff,coverage`.
SemVer; `CHANGELOG.md` (Keep-a-Changelog). Publish to PyPI on tagged release via CI.

## 12. CI/CD (`.github/workflows/ci.yml`)

On push/PR: matrix py3.9–3.13 → install `[dev,all]` → `ruff check` → `pytest --cov` (fail
< 90%) → upload coverage. Separate tagged-release job → build + `twine upload` to PyPI
(trusted publishing). Integration tests run only on a manual/nightly workflow (network).

## 13. Public hygiene (clean-room — zero personal data)

Quarry ships **no** personal content, paths, or config — only generic defaults + examples.
André's knowledge lives in the private `asachs/knowledge` repo, which becomes a *consumer*
(its own `quarry.toml`). README: what/why, 60-second quickstart, config reference, adapter-
authoring guide. LICENSE (MIT or Apache-2.0 — decide at bootstrap). CONTRIBUTING: adapter
contract + test requirement. CODE_OF_CONDUCT optional.

## 14. Extraction plan (single-file `bin/kb` → `src/quarry/`)

`EXTRACTION-SOURCE-kb.py` (the current 600-line harness) maps to modules:

| Current `bin/kb` | → Quarry module | Generalisation |
|------------------|-----------------|----------------|
| `find_repo_root`, `find_qmd` | `store.py`, `discovery.py` | root via config/marker; qmd behind backend iface |
| `read_frontmatter`, `slugify`, `raw_relpath` | `store.py` / utils | `raw_relpath` driven by `raw_layout` template |
| `Adapter`, `YouTubeAdapter`, `registry` | `adapters/` | entry-point discovery + `enabled` allowlist |
| `manifest_*`, seam | `manifest.py` | unchanged shape, config-driven paths |
| `run_lint` + `_lint_*` | `lint.py` | checks + `fail_on` from `[lint]` |
| `find_qmd`/`parse_qmd_hits`/`cmd_related`/`cmd_densify`/dedup | `discovery.py` | backend interface; thresholds from config |
| `cmd_*` | `cli.py` | argparse → command funcs taking `Config` |

Every hardcoded convention (`"wiki"`, `"raw"`, `raw/YYYY/MM`, `["title","updated","sources","related"]`, `85`, `6`) becomes a config field with the current value as the *example default*.

## 15. Migrating the private knowledge repo to consume Quarry

1. `pip install quarry[youtube,web]` (or pin a git ref pre-PyPI).
2. Add `quarry.toml` capturing the repo's current conventions (its existing wiki/raw/frontmatter shape).
3. Replace `bin/kb` + `scripts/qmd-*`/`wiki-lint.py` with Quarry (keep a `wiki-lint.py` shim → `quarry lint` for the cron during transition).
4. Verify: `quarry lint` matches the prior golden; re-run the ingest + densify flows.

## 16. v1 scope vs later

- **v1**: core pipeline (ingest/finish/manifest/lint), `youtube` + `web` adapters, qmd discovery (related/densify/dedup), config + `init`, full test suite + CI, PyPI publish, docs.
- **Later**: `pdf`/`github`/`instagram` adapters; pluggable discovery backends beyond qmd; `finish` auto-index; ingest-date vs source-upload-date; richer config validation; a `quarry serve`/watch mode.

## Open decisions for bootstrap

- License: MIT vs Apache-2.0.
- Build backend: hatchling (recommended) vs setuptools.
- Whether `web` adapter ships in v1 or only `youtube` (web extraction has heavier deps).
- Min Python: 3.9 (broad) vs 3.10/3.11 (cleaner typing, native tomllib at 3.11).
