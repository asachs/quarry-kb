# Quarry

A config-driven **knowledge-ingestion harness** — a CLI that owns the *deterministic*
half of turning a source (a YouTube video, a web page, …) into a linked article in a
markdown knowledge wiki.

Quarry resolves a source adapter, fetches, writes immutable raw material, hands a
machine-readable compile-spec to an LLM (or human) for the one irreducibly-generative
step — writing the article — then verifies provenance, lints, and commits. **It never
calls a model**, so it is runnable and testable without API keys.

> You extract raw material from the world and refine it into something structured.
> That is the pipeline, and the name.

## Why

The deterministic mechanics of disciplined knowledge ingestion — fetch, immutable raw,
a verifiable manifest, provenance checking, structural lint, semantic link discovery —
are worth doing the same way every time. Quarry packages exactly that machinery and
nothing else: it is **not** an LLM wrapper, not a note-taking app, and not opinionated
about your wiki's shape. Every convention is configuration.

## Install

```bash
pip install quarry[youtube,web]     # core + both shipped adapters
pip install quarry                  # core only (PyYAML); add adapters as extras
```

Requires Python 3.11+.

## 60-second quickstart

```bash
cd your-wiki-repo
quarry init                  # scaffold a documented quarry.toml + gitignore .quarry/
# edit quarry.toml to match your wiki's conventions

quarry ingest <url>          # fetch -> raw/ + compile-manifest, then STOP
# ...now write the wiki article using the printed compile-spec...
quarry finish <slug>         # verify provenance -> lint -> commit (no push unless --push)
```

Other commands: `quarry lint`, `quarry adapters`, `quarry related <article>`,
`quarry densify [--apply]`, `quarry doctor`.

The two-call seam is deliberate: `ingest` and `finish` are separate processes, and the
generative step (writing the article) happens *between* them — done by you or your agent,
never by Quarry.

## Configuration reference

Quarry is configured by a `quarry.toml` discovered by walking up from the current
directory (a `[tool.quarry]` table in `pyproject.toml` is a fallback). `quarry init`
writes a fully-commented default. Tables:

| Table | Key | Purpose |
|-------|-----|---------|
| `[store]` | `wiki`, `raw`, `manifest_dir` | directories (relative to the store root) |
| | `raw_layout` | raw path template; tokens: `{year} {month} {date} {slug} {kebab_title} {ext} {topic} {source_id}` |
| | `root` | explicit store root (defaults to the dir containing `quarry.toml`) |
| `[frontmatter]` | `required`, `sources_field`, `related_field` | article frontmatter schema |
| `[ingest]` | `default_ext`, `slug`, `on_duplicate` | slug template; `on_duplicate` = `refuse \| warn \| allow` |
| `[adapters]` | `enabled` | allowlist of adapters to run |
| `[discovery]` | `backend`, `mode`, `collection`, `dedup_threshold`, `densify_topk` | semantic-link backend (`qmd` or `none`) |
| `[lint]` | `broken_links`, `require_sources_on_disk`, `orphan_check`, `index_file`, `fail_on` | which checks run and which fail the build |
| `[finish]` | `run_lint`, `auto_push`, `commit_template` | finish behaviour |

See [`examples/quarry.toml`](examples/quarry.toml) for the annotated default.

## Authoring an adapter

A new source type is one small adapter discoverable via the `quarry.adapters`
entry-point group — no fork. See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the contract,
the hermetic-test requirement, and a worked `pdf` example.

## Status

Pre-1.0, but feature-complete for v1 and fully tested. See [`SPEC.md`](SPEC.md) for the
design and [`ISA.md`](ISA.md) for the ideal-state criteria and build provenance.

## License

MIT — see [`LICENSE`](LICENSE).
