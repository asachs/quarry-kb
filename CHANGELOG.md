# Changelog

All notable changes to Quarry are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and Quarry adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Initial implementation, generalised from the private `bin/kb` harness.
- Configuration layer (`quarry.toml`) with `quarry init` scaffolding a fully-commented
  default; walk-up discovery, `[tool.quarry]` fallback, validation (unknown-key warnings,
  type and enum errors), and a `Config` dataclass threaded through every command.
- Store path templating: `raw_layout` and `slug` from config across the full token set.
- Compile-manifest seam (`manifest.py`) — write/load/hash round-trip.
- Adapters: contract + registry with entry-point plugin discovery and an `enabled`
  allowlist; built-in `youtube` and `web` adapters (extras-gated, hermetically tested).
- `ingest` (resolve → fetch → raw → manifest with an `on_duplicate` dedup pre-check) and
  `finish` (provenance verify → lint → commit, push only when opted in).
- Config-driven structural-health `lint` returning a structured `LintResult`, with a
  golden-output test.
- Optional `discovery` backend (`qmd`) powering dedup, `related`, and `densify`; degrades
  gracefully when the backend is `none` or the tool is absent.
- `doctor` command; commands `init`, `adapters`, `ingest`, `finish`, `lint`, `related`,
  `densify`.
- Extensive hermetic test suite (no network, no API keys) with a ≥90% coverage gate,
  `ruff`, and a Python 3.11–3.13 CI matrix.

[Unreleased]: https://github.com/asachs/quarry/commits/master
