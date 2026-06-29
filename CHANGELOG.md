# Changelog

All notable changes to Quarry are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and Quarry adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0]

### Added
- **Groundedness lint check** (`[lint] groundedness`, default off) — an anti-fabrication /
  anti-cross-source-bleed guardrail. For each article it extracts **bolded named terms**
  (`**...**` spans containing an uppercase letter — build names, products, proper nouns)
  and flags any whose content words are **all absent** from the article's cited *text*
  sources (`.md`/`.txt`; PDFs/binaries and source-less articles are skipped — unverifiable).
  Word-level (not phrase-level) matching means faithful paraphrase and synthesis are *not*
  flagged — only wholly-foreign named things surface. Advisory by default; add
  `"groundedness"` to `[lint] fail_on` to make `quarry finish` abort on ungrounded terms.
  Reports under `--- UNGROUNDED TERMS ---` with an `Ungrounded terms:` count.
  Motivation: an LLM compiling an article pulled build names from a *neighbouring* cited
  source during cross-linking and merged them into an article that credited only one
  source — code catches what trusting the model didn't.

## [0.2.3]

### Added
- `reddit` adapter optional **OAuth path** (PRAW, read-only client-credentials — only
  `QUARRY_REDDIT_CLIENT_ID` + `QUARRY_REDDIT_CLIENT_SECRET`, no username/password). Used
  automatically when both env vars are set; falls back to the no-key curl_cffi path
  otherwise. OAuth gets Reddit's ~100 QPM authenticated budget, immune to the IP-reputation
  throttle that hits the no-key path (which communicates no Retry-After). New
  `[reddit-oauth]` extra; setup process documented in the adapter. `quarry doctor` reports
  whether OAuth is configured.

### Note
- Principle refinement: the core never reads the environment and needs no keys, but
  **adapters may use optional credentials** (reddit OAuth, instagram cookies); the no-key
  path remains the default and the test suite still runs with zero keys.

## [0.2.2]

### Changed
- `reddit` adapter now fetches via **curl_cffi** (`impersonate="chrome"`) instead of
  stdlib urllib — Reddit TLS/JA3-fingerprint-blocks pure-Python clients (urllib 403,
  browser-handshake 200). Uses Reddit's required descriptive User-Agent format. `[reddit]`
  extra is now `curl_cffi` (was stdlib-only). No-key/best-effort (rate-limited); OAuth/PRAW
  remains the reliable upgrade. Resolves `/s/` share links via the redirect.

## [0.2.1]

### Fixed
- `reddit` adapter now resolves `/s/` share links to the canonical permalink before
  fetching `.json` (share links are redirects and don't accept a `.json` suffix directly).

## [0.2.0]

### Added
- New source adapters: **`reddit`** (public `.json`, stdlib-only), **`github`** (via
  `gitingest`), **`pdf`** (PyMuPDF4LLM + auto Tesseract OCR for scanned pages),
  **`instagram`** (best-effort caption + audio; public reels/posts only).
- YouTube adapter gains a deterministic transcript **fallback chain**: captions →
  yt-dlp auto-subs → local **faster-whisper** (audio via yt-dlp + ffmpeg).
- `transcribe` module: local speech-to-text via faster-whisper.
- New extras: `[reddit]` (none), `[github]`, `[pdf]`, `[instagram]`, `[whisper]`.
  Heavy local models ship as optional extras, never core (PEP 771).

### Principle
- Adapters extract RAW content deterministically (no LLM, no API key); generative
  steps (distillation, summarization, vision-reading) stay outside the harness.

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

[Unreleased]: https://github.com/asachs/quarry-kb/commits/master
