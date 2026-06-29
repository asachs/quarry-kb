# Changelog

All notable changes to Quarry are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and Quarry adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.0]

### Added
- **YouTube: capture the video description (and, optionally, comments) into the raw.** The
  youtube adapter now always folds the **video description** (via yt-dlp) into the raw as a
  `## Description` section above the transcript — it carries source links, chapter
  timestamps, and the creator's own summary. Best-effort: omitted if the `[youtube]` extra is
  absent or extraction fails (transcript still written).
- **Optional comments** via new `[youtube]` config (`comments`, default `false`;
  `top_comments`, default `10`). When enabled, captures the **pinned comment** (creator
  errata/links — high signal) and the **top-by-likes** comments, each labelled
  `## Pinned comment` / `## Top comments (community — not the creator's claims)` so the
  article writer treats them as context, not source truth. Off by default because it needs
  yt-dlp's `getcomments` (slower); bounded via a `max_comments` cap (top-level only, no replies).
  Config now reaches adapters: `registry.resolve_adapter` attaches the resolved `Config` to
  the adapter (`adapter.cfg`).

## [0.4.0]

### Removed
- **Reddit adapter (and the `[reddit]` / `[reddit-oauth]` extras).** Reddit is no longer a
  viable deterministic, no-auth source: TLS/JA3 fingerprint-blocking of pure-Python clients,
  IP-reputation throttling with no `Retry-After`, and the Nov-2025 Responsible Builder Policy
  gating all API apps (incl. read-only OAuth) behind manual approval. It violated Quarry's
  "runnable without keys" principle and only ever half-worked. Removed the adapter, registry
  entry, the two extras, and the `reddit` default in `[adapters] enabled`. To ingest a Reddit
  thread, save the page/`.json` and use the `web`/`pdf` adapter, or supply your own adapter
  via the entry-point hook. `curl_cffi` remains (the `instagram` extra uses it). See README.

## [0.3.2]

### Fixed
- **Instagram: correct root cause — it's a yt-dlp version gap, not authentication.** Public
  reels remain fetchable WITHOUT cookies; the mid-2026 "empty media response" failure is fixed
  by yt-dlp's Instagram impersonation rework ([PR #17075](https://github.com/yt-dlp/yt-dlp/pull/17075),
  merged 2026-06-28; in yt-dlp master / the first stable after 2026.06.09) backed by `curl_cffi`.
  Verified end-to-end on a server from a non-residential IP. Changes: the `[instagram]` extra now
  pulls `curl_cffi`; the failure message now points at the yt-dlp upgrade (and clarifies cookies
  are only for private posts/stories), correcting 0.3.1's misleading "authentication required"
  wording. Cookie support from 0.3.1 (`QUARRY_INSTAGRAM_COOKIES` /
  `QUARRY_INSTAGRAM_COOKIES_FROM_BROWSER`) stays for private content.

## [0.3.1]

### Fixed
- **Instagram adapter — cookie support + correct error classification.** As of 2026
  Instagram blocks logged-out yt-dlp extraction even for public reels ("Instagram sent an
  empty media response"). The adapter now accepts optional cookies — `QUARRY_INSTAGRAM_COOKIES`
  (path to a Netscape cookies.txt from a logged-in browser) or
  `QUARRY_INSTAGRAM_COOKIES_FROM_BROWSER` (e.g. `firefox`, or `chrome:Profile`) — passed
  through to yt-dlp for both metadata and audio. Without cookies it now raises a clean,
  actionable error naming the env vars (previously the "empty media response" phrasing fell
  through the login-hint classifier and dumped the raw yt-dlp error). Mirrors the reddit-OAuth
  optional-credential pattern: the core stays key-free; adapters may use optional credentials.

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
