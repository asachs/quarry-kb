---
task: "Build Quarry — config-driven knowledge-ingestion harness from bin/kb"
slug: 20260628-141500_quarry-v1
project: Quarry
effort: deep
effort_source: explicit
phase: execute
progress: 77/100
mode: interactive
started: 2026-06-28T14:15:00Z
updated: 2026-06-28T17:55:00Z
---

## Problem

A working knowledge-ingestion harness already exists as a single 728-line file (`bin/kb`) inside the private `asachs/knowledge` repo. It does its job well — two-call ingest/finish seam, provenance verification, in-process lint, qmd discovery — but it is welded to one wiki's conventions. Every path (`wiki`, `raw`, `.kb`), every layout (`raw/YYYY/MM/...`), every frontmatter field (`title, updated, sources, related`), every threshold (dedup 85%, densify top-6), and the commit message are hardcoded. It ships with **zero automated tests**, so each mechanical break is discovered by a human in production. It cannot be installed, reused by anyone else, or extended without forking. The deterministic machinery that makes LLM-assisted knowledge work reliable is trapped in one private file.

## Vision

`pip install quarry[youtube,web]`, drop a `quarry.toml`, and any markdown knowledge wiki gets the same disciplined ingest pipeline: resolve an adapter, fetch a source, write immutable raw material, hand the agent a machine-readable compile-spec, then verify provenance, lint, and commit. Every convention is configuration; nothing is baked in. The core runs and tests **without a single API key**, because Quarry never calls a model — it owns only the deterministic half. Euphoric surprise: `bin/kb` becomes a *consumer* of Quarry via its own `quarry.toml`, a stranger ships a `pdf` adapter as a third-party plugin without touching Quarry's source, and the whole thing is green at ≥90% coverage across Python 3.11–3.13.

## Out of Scope

- **No LLM calls, ever.** Quarry owns the deterministic half only; writing the article is the agent's/human's job between `ingest` and `finish`. Runnable and testable without API keys is a hard line.
- **No opinion about *your* wiki's shape.** Quarry ships generic defaults and examples — never André's content, paths, or conventions. The private knowledge repo's data stays private.
- **No knowledge-repo migration in this effort.** Quarry is built standalone first; cutting `asachs/knowledge` over to consume it (its own `quarry.toml`, golden-lint match, `bin/kb` retirement) is a separate, later effort.
- **No PyPI publish or GitHub remote in this effort.** The CI workflow file is written and the release job is defined, but actual publishing (trusted-publishing setup, account/token steps) is deferred to André's review — local-first.
- **No roadmap adapters in v1.** `pdf`, `github`, `instagram` are explicitly later; v1 ships `youtube` + `web` only.
- **No discovery backends beyond qmd in v1.** The discovery interface is pluggable, but only the `qmd` backend is implemented now.
- **No `quarry serve`/watch mode, no auto-index on finish, no ingest-date-vs-upload-date split.** All deferred to later.
- **No note-taking-app features.** Quarry is a CLI harness, not an editor or UI.

## Principles

- **Code before prompts.** Every deterministic mechanic is tested code; the irreducibly-generative article step is the only thing left to the LLM/human, and Quarry never performs it.
- **The manifest is the product.** The compile-spec is a persisted, machine-readable file; `finish` *verifies* the article against it, never trusts it.
- **Generic core.** No baked-in conventions. A `Config` dataclass is threaded everywhere; no module reads conventions directly. Absent config fails helpfully, never silently defaults to the author's wiki.
- **Fail loud, fail tested.** Every mechanical step has a test that catches its break before a user does. User-facing errors are clean one-liners, never tracebacks.
- **Optional deps degrade gracefully.** A missing extra or external tool produces a clean message or a skipped feature — never a crash in a core flow.
- **Adapters are the extension unit.** A new source is one small, self-contained, hermetically-tested adapter discoverable via entry points — no fork required.
- **Portable by construction.** No hardcoded paths; store root discovered at runtime from config.

## Constraints

- **Min Python 3.11.** Native `tomllib` — no `tomli` backport anywhere. Modern `X | Y` typing permitted.
- **Build backend: hatchling.** `src/`-layout, `console_scripts: quarry = quarry.cli:main`.
- **License: MIT.**
- **Core runtime dependency is exactly one: `PyYAML`.** (Deliberate deviation from the source spec's "stdlib-only core" — frontmatter parsing on arbitrary user wikis is made robust with a real YAML parser rather than a regex reader. `tomllib` is stdlib at 3.11, so no toml dep.) All other deps are extras: `[youtube]=youtube-transcript-api`, `[web]=trafilatura`, `[discovery]` (docs-only; qmd is an external Node tool, not a pip dep), `[all]`, `[dev]=pytest,ruff,coverage`.
- **Two-call seam is immovable.** `ingest` (fetch → raw → manifest) and `finish` (verify → lint → commit) are separate processes; Quarry NEVER shells out to an LLM between them.
- **No push without explicit opt-in.** `finish` commits but only pushes on `--push` or `[finish] auto_push=true`.
- **Coverage gate ≥ 90%; `ruff` clean.** Both enforced in CI and treated as build-failing.
- **Adapter network calls live behind overridable methods** so the default test suite is fully hermetic (no network, no keys).

## Goal

Generalise `bin/kb` into **Quarry**: an installable, MIT-licensed, config-driven Python ≥3.11 package (`src/quarry/`, hatchling, console script `quarry`) that ships the full ingest/finish/manifest/lint pipeline, `youtube` + `web` adapters with entry-point plugin discovery, an optional pluggable `qmd` discovery backend (related/densify/dedup), and `init`/`doctor` commands — verified by an extensive, hermetic test suite at ≥90% coverage with `ruff` clean and a py3.11–3.13 CI matrix, carrying zero personal data and never calling an LLM.

## Criteria

### Packaging & Build

- [ ] ISC-1: `pip install .` in a clean venv exits 0.
- [x] ISC-2: The installed `quarry --help` console script runs and exits 0.
- [x] ISC-3: `python -m quarry --help` exits 0 (module entry point).
- [x] ISC-4: `pyproject.toml` declares `build-backend = "hatchling.build"`.
- [x] ISC-5: `pyproject.toml` declares `requires-python = ">=3.11"`.
- [ ] ISC-6: The core install pulls exactly one runtime dependency, `PyYAML` (probe: fresh-venv `pip list` minus pip/setuptools = `[quarry, PyYAML]`).
- [ ] ISC-7: Extras `[youtube]`, `[web]`, `[discovery]`, `[all]`, `[dev]` are declared and each installs without error.
- [x] ISC-8: A `LICENSE` file is present and is the MIT license text.

### Config & init

- [x] ISC-9: `quarry init` in an empty dir writes a `quarry.toml`.
- [x] ISC-10: The scaffolded `quarry.toml` is fully commented — every config table carries an explanatory comment.
- [x] ISC-11: `quarry init` ensures `.quarry/` is in `.gitignore` (creating `.gitignore` if absent).
- [x] ISC-12: `quarry init` refuses to overwrite an existing `quarry.toml` (exit ≠ 0, clean message) unless `--force`.
- [x] ISC-13: Config parsing uses native `tomllib`; no `tomli` import exists anywhere (probe: `rg "import tomli\b"` → 0 hits).
- [x] ISC-14: Any command run with no `quarry.toml` found exits **2** with `quarry: no quarry.toml found (run 'quarry init')`.
- [x] ISC-15: Unknown config keys produce a warning to stderr but do not fail the load.
- [x] ISC-16: A config type error (e.g. string where int expected) fails with exit **2** and a field-named message.
- [x] ISC-17: Loading a minimal `quarry.toml` (only `[store]`) succeeds with every other field defaulted.
- [x] ISC-18: The `Config` dataclass is the sole carrier of conventions — only `config.py` reads `tomllib`/raw config (probe: `rg "tomllib" src/quarry` → only `config.py`).
- [x] ISC-19: A `[tool.quarry]` table in `pyproject.toml` is honored as a fallback when no standalone `quarry.toml` exists.

### Store & root discovery

- [x] ISC-20: Store root is discovered by walking up from CWD to the directory containing `quarry.toml`.
- [x] ISC-21: An explicit `[store] root` in config overrides walk-up discovery.
- [x] ISC-22: Store path resolution works in a non-git directory (git is not required).
- [x] ISC-23: All `raw_layout` tokens — `{year} {month} {date} {slug} {kebab_title} {ext} {topic} {source_id}` — expand correctly.
- [x] ISC-24: Changing `raw_layout` in config changes the written raw path accordingly (config-matrix test).
- [x] ISC-25: The `slug` template from `[ingest]` drives the generated slug.

### Manifest seam

- [x] ISC-26: `ingest` writes `{manifest_dir}/{slug}.json`.
- [x] ISC-27: The manifest contains all required keys: `slug, source_url, adapter, raw_path, content_sha256, target_wiki_path, required_frontmatter, must_cite_source, metadata`.
- [x] ISC-28: `content_sha256` equals the SHA-256 of the fetched content (round-trip assertion).
- [x] ISC-29: A manifest write → load round-trips to an equal object.
- [x] ISC-30: `finish` aborts (exit ≠ 0, clean message) when no manifest exists for the slug.

### Ingest

- [x] ISC-31: `ingest <url>` resolves the first matching enabled adapter.
- [x] ISC-32: `ingest` writes immutable raw material at the configured raw path.
- [x] ISC-33: `ingest` refuses to clobber existing raw without `--force` (exit ≠ 0).
- [x] ISC-34: `ingest` prints a human/agent-readable compile-spec to stdout.
- [x] ISC-35: `--topic T` populates `target_wiki_path` in the manifest.
- [x] ISC-36: With discovery available and a hit ≥ `dedup_threshold`, `on_duplicate=refuse` aborts ingest (exit ≠ 0).
- [x] ISC-37: `on_duplicate=warn` prints a warning and proceeds with ingest.
- [x] ISC-38: `on_duplicate=allow` ingests with no dedup interruption.
- [x] ISC-39: `--force` bypasses the dedup pre-check.
- [x] ISC-40: An adapter exception during fetch surfaces as a clean non-zero quarry error (no traceback).

### Finish & provenance

- [x] ISC-41: `finish` aborts when the target article file does not exist.
- [x] ISC-42: `finish` aborts when the article's `sources_field` does not include `must_cite_source` (provenance verified, not trusted).
- [x] ISC-43: `finish` runs lint when `[finish] run_lint=true`.
- [x] ISC-44: `finish` aborts when a `[lint] fail_on` check fails.
- [x] ISC-45: `finish` commits (`git add` + `git commit`) on success.
- [x] ISC-46: `finish` does NOT push unless `--push` or `[finish] auto_push=true`.
- [x] ISC-47: The commit message matches `[finish] commit_template`.
- [x] ISC-48: `finish` in a non-git directory degrades gracefully (skips commit with a clear note, no crash).

### Lint

- [x] ISC-49: `lint` detects broken internal markdown links.
- [x] ISC-50: `lint` detects frontmatter sources not present on disk.
- [x] ISC-51: `lint` detects orphan articles using inbound-from-body only (frontmatter `related:` does NOT count — documented behaviour).
- [x] ISC-52: `lint` reports link density (total cross-refs, avg outgoing).
- [x] ISC-53: `lint` reports the top-connected articles.
- [x] ISC-54: `lint` reports per-category health.
- [x] ISC-55: `lint` reports not-in-index articles when `index_file` is set.
- [x] ISC-56: `index_file = ""` disables the not-in-index check.
- [x] ISC-57: `lint` exits non-zero iff a `[lint] fail_on` check fails.
- [x] ISC-58: `lint` returns a structured `LintResult` (counts + per-issue lists); `finish` consumes the object directly, no text-scraping.
- [x] ISC-59: Each lint check is individually toggleable from `[lint]` config.
- [x] ISC-60: Golden-output test — a fixture wiki produces a byte-locked report string.

### Discovery (optional, pluggable)

- [x] ISC-61: `discovery.available()` returns `False` cleanly when the backend tool is absent.
- [x] ISC-62: `backend="none"` disables discovery; `related`/`densify` print a clean message and core flows are unaffected.
- [x] ISC-63: `related <article>` prints ranked candidates excluding the article itself.
- [x] ISC-64: `related` excludes already-linked articles (frontmatter `related` + body links).
- [x] ISC-65: `densify` lists mutual top-K unlinked pairs.
- [x] ISC-66: `densify --apply` adds bidirectional `## See also` links.
- [x] ISC-67: `densify --topk N` overrides the configured `densify_topk`.
- [x] ISC-68: The qmd-output parser turns real `qmd query` stdout into `[(score, path)]` (fixture test).
- [x] ISC-69: Missing qmd during `related`/`densify` exits non-zero with a clean install hint, never a traceback.

### Adapters & plugins

- [x] ISC-70: `adapters` lists registered adapters and marks which are enabled.
- [x] ISC-71: The `[adapters] enabled` allowlist gates which adapters actually run.
- [x] ISC-72: Third-party adapters are discoverable via the `quarry.adapters` entry-point group.
- [x] ISC-73: The youtube adapter parses a video id from `watch?v=`, `youtu.be/`, `/shorts/`, and `/embed/` URLs.
- [x] ISC-74: The youtube adapter returns content + metadata from a recorded cassette (no network).
- [x] ISC-75: The web adapter extracts main content via trafilatura from a recorded fixture (no network).
- [x] ISC-76: The web adapter returns the required metadata (`title, url, date, source_id`).
- [x] ISC-77: Exactly one live `@pytest.mark.integration` test exists per network adapter, excluded from the default run.
- [x] ISC-78: A missing adapter extra (e.g. `youtube-transcript-api`) yields a clean install hint, not an `ImportError` traceback.

### CLI & errors

- [x] ISC-79: `quarry <unknown-command>` exits non-zero with usage text.
- [x] ISC-80: Exit codes are honored across paths: 0 success, 1 operational error, 2 config error.
- [ ] ISC-81: Every command responds to `--help`.
- [ ] ISC-82: `doctor` reports config validity plus optional deps/tools (git, qmd, adapter deps).
- [ ] ISC-83: Every user-facing error class prints a one-line message, never a traceback (probe: induce each).

### Testing & quality gates

- [ ] ISC-84: `pytest` exits 0 with `[dev,all]` installed.
- [ ] ISC-85: Coverage ≥ 90% (probe: `coverage report` total).
- [ ] ISC-86: `ruff check` reports no errors.
- [ ] ISC-87: A parametrised config-matrix test runs the pipeline under ≥ 3 distinct `quarry.toml` variants (different `raw_layout`, frontmatter schema, discovery off).
- [ ] ISC-88: The default test run is fully hermetic — passes with network blocked (probe: run under no-network sandbox).

### CI/CD

- [ ] ISC-89: `.github/workflows/ci.yml` exists with a py3.11/3.12/3.13 matrix.
- [ ] ISC-90: CI runs `ruff check` and `pytest --cov`, failing the build under 90% coverage.
- [ ] ISC-91: Integration (network) tests are gated to a manual/nightly workflow, not the default CI run.
- [ ] ISC-92: A tagged-release PyPI trusted-publishing job is defined in CI but not wired to fire (publish deferred).

### Docs & public hygiene

- [ ] ISC-93: `README.md` covers what/why, a 60-second quickstart, a config reference, and an adapter-authoring guide.
- [ ] ISC-94: `examples/quarry.toml` exists and matches the `quarry init` default output.
- [ ] ISC-95: `CHANGELOG.md` (Keep-a-Changelog) and `CONTRIBUTING.md` (adapter contract + test requirement) are present.

### Anti-criteria

- [ ] ISC-96: Anti — Quarry NEVER imports or calls an LLM SDK (probe: `rg -i "anthropic|openai|llm_call" src/quarry` → 0 hits; full suite runs with no API keys set).
- [ ] ISC-97: Anti — zero personal data: the repo contains no reference to André's wiki content, private absolute paths, or `asachs/knowledge` (probe: `rg -i "asachs|/Users/asachs|knowledge repo content"` → 0 hits in shipped files).
- [ ] ISC-98: Anti — no hardcoded conventions: core modules contain no bare `"wiki"`/`"raw"`/`85`/`6` convention literals outside `config.py` defaults and tests (probe: targeted `rg` of `src/quarry` excluding `config.py`).
- [ ] ISC-99: Anti — optional-dep absence never crashes a core flow: `ingest`/`finish`/`lint` on a local non-network source succeed with only the core install (no extras).
- [ ] ISC-100: Anti — the full default test suite passes with no API keys and no network present (testable-without-keys is provable, not just claimed).

## Test Strategy

```yaml
# Representative per-ISC entries; remaining ISCs follow the same per-module pattern
# (unit test in tests/test_<module>.py with the named tool/probe).

- isc: ISC-1
  type: packaging
  check: clean-venv install
  threshold: exit 0
  tool: python -m venv .v && .v/bin/pip install .

- isc: ISC-6
  type: dependency-audit
  check: core runtime deps
  threshold: exactly {PyYAML}
  tool: pip list --format=freeze in core-only venv

- isc: ISC-13
  type: source-grep
  check: no tomli backport
  threshold: 0 hits
  tool: rg "import tomli\b" src/

- isc: ISC-14
  type: cli-exit
  check: missing config message + code
  threshold: exit 2 + exact string
  tool: pytest CliRunner in a config-less tmp dir

- isc: ISC-24
  type: config-matrix
  check: raw path follows configured raw_layout
  threshold: path equals templated expectation
  tool: parametrised pytest over quarry.toml variants

- isc: ISC-28
  type: provenance
  check: manifest content_sha256 == sha256(content)
  threshold: equal
  tool: pytest manifest round-trip

- isc: ISC-42
  type: provenance
  check: finish aborts on missing source citation
  threshold: exit 1 + provenance message
  tool: pytest finish with non-citing article fixture

- isc: ISC-46
  type: seam-guard
  check: commit without push
  threshold: git log has commit, no push invoked
  tool: pytest with a tmp git repo + push spy

- isc: ISC-60
  type: golden
  check: lint report byte-match
  threshold: exact string equality
  tool: pytest against fixture wiki + recorded golden

- isc: ISC-74
  type: hermetic-adapter
  check: youtube fetch from cassette
  threshold: content+metadata match recorded fixture
  tool: pytest with monkeypatched _fetch_transcript/_fetch_oembed

- isc: ISC-75
  type: hermetic-adapter
  check: web extraction from fixture HTML
  threshold: extracted content matches expected
  tool: pytest with local HTML fixture (no network)

- isc: ISC-85
  type: coverage-gate
  check: total coverage
  threshold: >= 90%
  tool: coverage run -m pytest && coverage report --fail-under=90

- isc: ISC-86
  type: lint-gate
  check: ruff
  threshold: 0 errors
  tool: ruff check .

- isc: ISC-88
  type: hermetic-suite
  check: default run with no network
  threshold: all pass
  tool: pytest under network-blocked sandbox

- isc: ISC-96
  type: anti-probe
  check: no LLM SDK usage
  threshold: 0 hits + suite green with no keys
  tool: rg -i "anthropic|openai" src/quarry; pytest with env unset

- isc: ISC-100
  type: anti-probe
  check: no-keys/no-network full run
  threshold: exit 0
  tool: env -i pytest in network-blocked sandbox
```

## Features

```yaml
- name: ConfigAndInit
  description: quarry.toml schema, load/validate/defaults, Config dataclass, `init` scaffold
  satisfies: [ISC-9, ISC-10, ISC-11, ISC-12, ISC-13, ISC-14, ISC-15, ISC-16, ISC-17, ISC-18, ISC-19]
  depends_on: []
  parallelizable: false  # foundation everything threads through

- name: StoreAndPaths
  description: root discovery, path-token templating, raw_layout/slug resolution
  satisfies: [ISC-20, ISC-21, ISC-22, ISC-23, ISC-24, ISC-25]
  depends_on: [ConfigAndInit]
  parallelizable: false

- name: ManifestSeam
  description: compile-manifest read/write/hash, round-trip
  satisfies: [ISC-26, ISC-27, ISC-28, ISC-29, ISC-30]
  depends_on: [StoreAndPaths]
  parallelizable: true

- name: Adapters
  description: Adapter contract, registry, entry-point discovery, enabled allowlist, youtube + web with cassettes
  satisfies: [ISC-31, ISC-40, ISC-70, ISC-71, ISC-72, ISC-73, ISC-74, ISC-75, ISC-76, ISC-77, ISC-78]
  depends_on: [ConfigAndInit]
  parallelizable: true

- name: Ingest
  description: resolve adapter -> fetch -> raw write -> manifest -> dedup pre-check + on_duplicate
  satisfies: [ISC-32, ISC-33, ISC-34, ISC-35, ISC-36, ISC-37, ISC-38, ISC-39]
  depends_on: [ManifestSeam, Adapters, Discovery]
  parallelizable: false

- name: Lint
  description: config-driven structural-health checks, LintResult object, fail_on, golden test
  satisfies: [ISC-49, ISC-50, ISC-51, ISC-52, ISC-53, ISC-54, ISC-55, ISC-56, ISC-57, ISC-58, ISC-59, ISC-60]
  depends_on: [ConfigAndInit, StoreAndPaths]
  parallelizable: true

- name: Finish
  description: provenance verify -> lint -> commit (no push unless opted in), non-git fallback
  satisfies: [ISC-41, ISC-42, ISC-43, ISC-44, ISC-45, ISC-46, ISC-47, ISC-48]
  depends_on: [ManifestSeam, Lint, GitHelpers]
  parallelizable: false

- name: Discovery
  description: qmd backend behind available()/query() interface; related, densify, dedup; graceful degrade
  satisfies: [ISC-61, ISC-62, ISC-63, ISC-64, ISC-65, ISC-66, ISC-67, ISC-68, ISC-69]
  depends_on: [ConfigAndInit, StoreAndPaths]
  parallelizable: true

- name: GitHelpers
  description: thin rev-parse/add/commit/push wrappers with non-git fallback
  satisfies: [ISC-22, ISC-45, ISC-48]
  depends_on: []
  parallelizable: true

- name: CliAndDoctor
  description: argparse dispatch to Config-taking command funcs, exit codes, doctor, error one-liners
  satisfies: [ISC-1, ISC-2, ISC-3, ISC-79, ISC-80, ISC-81, ISC-82, ISC-83]
  depends_on: [ConfigAndInit, Ingest, Finish, Lint, Discovery]
  parallelizable: false

- name: Packaging
  description: pyproject (hatchling, requires-python, extras), LICENSE, console script
  satisfies: [ISC-4, ISC-5, ISC-6, ISC-7, ISC-8]
  depends_on: []
  parallelizable: true

- name: TestSuiteAndGates
  description: full hermetic suite, config matrix, coverage >=90%, ruff clean
  satisfies: [ISC-84, ISC-85, ISC-86, ISC-87, ISC-88]
  depends_on: [CliAndDoctor]
  parallelizable: false

- name: CI
  description: ci.yml matrix py3.11-3.13, ruff+pytest+cov gate, gated integration, deferred release job
  satisfies: [ISC-89, ISC-90, ISC-91, ISC-92]
  depends_on: [TestSuiteAndGates]
  parallelizable: true

- name: DocsAndHygiene
  description: README, examples/quarry.toml, CHANGELOG, CONTRIBUTING, anti-data/anti-LLM guards
  satisfies: [ISC-93, ISC-94, ISC-95, ISC-96, ISC-97, ISC-98, ISC-99, ISC-100]
  depends_on: [CliAndDoctor]
  parallelizable: true
```

## Decisions

- 2026-06-28 14:15: License **MIT**, build backend **hatchling**, min Python **3.11** (native `tomllib`, no `tomli` dep), v1 ships **both** `youtube` + `web` adapters. Settled in bootstrap interview; recorded as Constraints.
- 2026-06-28 14:15: **PyYAML added to the core runtime dependency**, overriding the source spec's "stdlib-only core" principle (SPEC.md §2/§11). Rationale: the source's regex frontmatter reader is fragile against arbitrary user wikis, and frontmatter is on the critical provenance path. Net core deps = `PyYAML` only (tomllib is stdlib at 3.11). SPEC.md §2/§11 to be reconciled so the principle matches reality. This is the one deliberate divergence from the spec.
- 2026-06-28 14:15: **Build ISA/plan-first, then incrementally** (config+store → manifest+seam → adapters → lint → discovery → finish → CLI → tests → CI), with review checkpoints. Chosen over one-pass for early drift-catch.
- 2026-06-28 14:15: **Quarry built standalone first**; knowledge-repo migration (§15) deferred to a separate effort. Keeps public hygiene clean and decouples the two repos' histories.
- 2026-06-28 14:15: **Local-first** — CI workflow written and a release job defined, but GitHub remote + PyPI trusted-publishing deferred to André's review (avoids spending effort on account/token setup prematurely).
- 2026-06-28 14:15: **ISC count is 100, under the E4 soft floor of 128** — show-your-math: the package's genuine verification surface is ~100 atomic probes across 11 modules + packaging + CI + docs. Decomposing to 128 would manufacture probes that don't map to real failure modes (the canonical showpiece makes the same call at 38 vs the E5 floor). If splitting later reveals real sub-probes (e.g. per-token `raw_layout` checks), IDs will extend as ISC-23.1/23.2 without renumbering.
- 2026-06-28 14:15: Root discovery changes signal from `bin/kb`'s "dir containing `wiki/`+`raw/`" to "dir containing `quarry.toml`" — the config file becomes the marker, consistent with generic-core.
- 2026-06-28 15:40: **`raw_layout` default corrected** from the spec's `{year}/{month}/{date}_{slug}.{ext}` to `{year}/{month}/{slug}.{ext}`. The spec's defaults were self-contradictory: `{slug}` already defaults to `{date}_{kebab_title}`, so `{date}_{slug}` double-prefixed the date (`.../2026-06-28_2026-06-28_hello.md`). Caught by `test_make_raw_path_default_layout`. `{slug}` is the named file; the layout organises by `{year}/{month}` and must not re-add `{date}`. SPEC.md §4 reconciled. (`{date}` token remains available for users who want a title-only slug.)

## Changelog

_No conjecture/refuted-by/learned/criterion-now entries yet — this section accrues at the LEARN phase as the build refutes assumptions. The PyYAML deviation (Decisions, 2026-06-28) is the first standing conjecture: that a real YAML parser is worth breaking the zero-dep-core principle; it will be confirmed or refuted once frontmatter edge cases are tested._

## Verification

### Checkpoint 1 — ConfigAndInit (2026-06-28, py3.11.15)

- Suite: `34 passed in 0.13s`; `ruff check .` → `All checks passed!`; `coverage report --fail-under=90` → TOTAL **96%** (config.py 96%, cli.py 100%).
- ISC-2: `quarry --version` (installed console script) → `quarry 0.1.0`, exit 0.
- ISC-3: `tests/test_cli.py::test_module_entry_point` — `python -m quarry --help` returns 0.
- ISC-4/-5: `pyproject.toml` → `build-backend = "hatchling.build"`, `requires-python = ">=3.11"`.
- ISC-8: `LICENSE` present, MIT text.
- ISC-9/-11/-12: smoke run — `quarry init` wrote `quarry.toml` + gitignored `.quarry/`; second `init` → `quarry: error: quarry.toml already exists ... (use --force ...)`, exit 1.
- ISC-10: `test_init_template_is_fully_commented` — every table commented (caught + fixed a missing `[finish]` comment).
- ISC-13/-18: `test_no_tomli_backport_anywhere`, `test_only_config_reads_tomllib` (only `config.py`).
- ISC-14: `test_missing_config_exit_2` — stderr exactly `quarry: no quarry.toml found (run 'quarry init')`, exit 2.
- ISC-15/-16/-17/-19/-21: covered by `tests/test_config.py` (unknown-key warn, type+enum errors, minimal defaults, `[tool.quarry]` fallback, explicit root).
- ISC-79/-80: `test_unknown_command_errors` (non-zero), exit-code paths 0/1/2 all exercised.

### Checkpoint 2 — StoreAndPaths + ManifestSeam (2026-06-28, py3.11.15)

- Suite: `58 passed`; `ruff check .` → All checks passed; coverage TOTAL **97%** (store.py 95%, manifest.py 100%).
- ISC-20/-22: `test_root_discovery_nested_non_git` — root found by walk-up from a nested dir with no `.git` anywhere.
- ISC-23: `test_all_tokens_expand` — every documented token (`year month date slug kebab_title ext topic source_id`) renders in `raw_layout`.
- ISC-24: `test_make_raw_path_matrix` (3 layouts) — a different `raw_layout` yields a different path.
- ISC-25: `test_make_slug_default_template` / `test_make_slug_custom_template` — `[ingest] slug` template drives the slug; `{slug}` in its own template is a clean ConfigError.
- ISC-26: `test_write_creates_json_at_manifest_path` — manifest at `{manifest_dir}/{slug}.json`.
- ISC-27: `test_build_has_all_required_keys` — all `REQUIRED_KEYS` present; `must_cite_source == raw_path`.
- ISC-28: `test_content_sha256_matches` — `content_sha256` equals `sha256(content)`.
- ISC-29: `test_roundtrip_equal` — write → load returns an equal object.
- ISC-30: `test_load_missing_raises` — missing manifest → clean QuarryError.

### Checkpoint 3 — Adapters (2026-06-28, py3.11.15, dev+all)

- Suite: `82 passed, 2 deselected` (the integration tests); `ruff` clean; coverage TOTAL **95%** (registry/base 100%; web 86%, youtube 87% — uncovered lines are the network-only methods, exercised by the gated `@integration` tests).
- ISC-31: `test_resolve_matches_first_enabled` — first enabled matching adapter wins.
- ISC-40: `test_fetch_wraps_adapter_exception` / `..._passes_quarry_error_through` — adapter fault → clean `QuarryError`, no traceback.
- ISC-70: `test_list_adapters_marks_enabled`, `test_adapters_command_lists` — `quarry adapters` lists + marks enabled.
- ISC-71: `test_resolve_respects_enabled_allowlist` — disabled adapter not used even when it would match.
- ISC-72: `test_entry_point_discovery` / `..._broken_plugin_skipped` — `quarry.adapters` entry points discovered; bad plugin skipped.
- ISC-73: `test_youtube_video_id` (watch/youtu.be/shorts/embed).
- ISC-74: `test_youtube_fetch_from_cassette` — content+metadata from monkeypatched network methods (hermetic).
- ISC-75/-76: `test_web_extracts_from_fixture` — trafilatura extraction + metadata from fixture HTML (no network).
- ISC-77: `test_youtube_live` / `test_web_live` marked `@integration`, excluded by default (confirmed: 2 deselected).
- ISC-78: `test_youtube_missing_extra` / `test_web_missing_extra` — missing extra → clean install hint, not `ImportError`.

### Checkpoint 4 — Discovery + Ingest (2026-06-28, py3.11.15, dev+all)

- Suite: `116 passed, 2 deselected`; `ruff` clean; coverage TOTAL **93%**. New: `frontmatter.py` 100%, `ingest.py` 100%, `discovery.py` 86% (uncovered = `find_qmd` OS-path fallbacks + real `_run_qmd` subprocess, external-only).
- **Hermeticity breach caught + fixed:** the basic ingest tests reached a *real* `qmd` installed on the machine (it returned `88% wiki/ai-ml/llm-security.md` from the actual knowledge base). Added an autouse `_hermetic_qmd` fixture neutralising `find_qmd` so no test can touch a real external tool — directly serves ISC-88.
- ISC-32: `test_ingest_writes_raw_and_manifest` — raw (with frontmatter) + manifest written; sha matches.
- ISC-33/-39: `test_ingest_refuses_existing_raw`, `test_force_bypasses_dedup`.
- ISC-34: `test_ingest_prints_compile_spec` (via CLI).
- ISC-35: `test_ingest_topic_sets_target`.
- ISC-36/-37/-38: dedup `refuse` aborts / `warn` proceeds / `allow` skips the query entirely.
- ISC-61/-62: `NoneBackend` unavailable; `check()` → DISABLED/MISSING/OK; CLI prints "disabled" (exit 0) vs "qmd not found" (exit 1).
- ISC-63/-64: `test_related_excludes_self_and_linked`.
- ISC-65/-66/-67: `test_densify_pairs_and_apply` (bidirectional, idempotent), `test_densify_topk_limits_neighbours`.
- ISC-68: `test_parse_qmd_hits`.
- ISC-69: `test_related_cli_missing_qmd_exits_one` / densify equivalent.

### Checkpoint 5 — GitHelpers + Lint + Finish (2026-06-28, py3.11.15, dev+all)

- Suite: `140 passed, 2 deselected`; `ruff` clean; coverage TOTAL **93%**. New: `git.py` 87%, `lint.py` 90%, `finish.py` 94%.
- ISC-41: `test_finish_missing_article` / `test_finish_no_article_path`.
- ISC-42: `test_finish_provenance_failure` — article not citing source is rejected.
- ISC-43/-44: `test_finish_aborts_on_lint_failure` — broken link fails lint, aborts finish.
- ISC-45/-46/-47: `test_finish_commits_without_push` (commit + no push + `commit_template` message), `test_finish_pushes_when_opted_in`.
- ISC-48: `test_finish_non_git_graceful` + `git.is_repo` False on a plain dir.
- ISC-49/-50/-51: `test_fixture_detects_issues` (broken / missing / orphan); `test_orphans_are_body_inbound_only` proves frontmatter `related` does NOT count.
- ISC-52/-53/-54: `test_report_has_density_top_and_category`.
- ISC-55/-56: not-in-index list; `test_empty_index_disables_check`.
- ISC-57: `test_fails_respects_fail_on` + CLI exit 0/1.
- ISC-58: structured `LintResult` (per-issue lists) consumed by `finish` directly.
- ISC-59: `test_broken_check_toggleable` / `test_sources_check_toggleable`.
- ISC-60: `test_golden_report` — byte-locked report vs `fixtures/lint_report.golden.txt`.

_Remaining ISCs verified at their feature checkpoints._

<!--
Quarry project ISA, E4, all twelve sections. Generalises the private bin/kb (728 lines) into a public, config-driven, tested package. 100 ISCs across packaging, config/init, store, manifest seam, ingest, finish/provenance, lint, discovery, adapters/plugins, CLI, testing gates, CI, docs/hygiene. Anti-criteria (ISC-96..100) cover the load-bearing invariants: no LLM, no personal data, no hardcoded conventions, graceful optional-dep degrade, no-keys/no-network testability. No antecedents — the goal is verifiable (build/test/install/lint), not experiential. ISC count under the E4 floor is justified in Decisions. Changelog + Verification intentionally empty at OBSERVE per the empty-section rule.
-->
