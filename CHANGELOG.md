# Changelog

All notable changes to Quarry are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and Quarry adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.6.0]

Driven by measuring an agent's ingests: across 143 Instagram/web ingest turns, 47% of
tool calls went on extracting media by hand (browser walks, yt-dlp/ffmpeg/tesseract,
image reads) and 25% on finding link targets and editing the index. Quarry now does the
deterministic parts of both, so the agent's work is mostly the article itself.

### Added
- **Instagram carousels ingest instead of failing.** Image-only `/p/` posts made yt-dlp
  stop with "No video formats found". The adapter now passes `ignore_no_formats_error`
  and reads each slide's image URL, so carousels ingest like reels.
- **Instagram media capture (`[instagram] media = true`, opt-in).** Carousel slides and
  reel frames (every `frame_interval` s, capped at `max_frames`) are saved next to the raw,
  OCR'd with tesseract (`ocr`), and listed in a `## Media` section; consecutive frames
  with the same text are collapsed so the OCR reads like a transcript of the on-screen
  text. The audio transcript is taken from the downloaded video (no second download).
  `keep_video` also keeps the video file (off by default: often 5–20 MB). Quarry still
  never calls a model — describing images stays with the agent, which now only needs to
  look where OCR falls short.
- **Adapter assets.** `FetchResult` gains `assets` (name → local file) and `tmpdir`;
  `ingest` copies assets per `[ingest] assets_layout` (default `{year}/{month}/{slug}`
  under `raw/`), records them in the manifest, and always removes the adapter's scratch
  directory (also when ingest refuses a duplicate or an existing raw).
- **Link candidates in the compile-spec (`[ingest] related_candidates = N`).** Existing
  articles worth linking are printed with their titles and stored in the manifest. With
  `[discovery] search = "search"` (BM25) a few distinctive keywords are queried one at a
  time and scores summed, requiring two shared keywords when three or more were used;
  the index file is never suggested.
- **`[discovery] search`** picks the qmd mode: `query` (hybrid + rerank, previous
  behaviour), `search` (BM25, instant) or `vsearch`. **`[discovery] refresh`** runs
  `qmd update` before ingest-time lookups so recent articles are found.
- **`[finish] auto_index`** adds a missing index entry, placed under the heading whose
  entries share the article's wiki folder (appended at the end otherwise); a `summary` or
  `description` frontmatter field becomes the entry's blurb.
- **`finish` finds the article by its source citation** when it isn't at the suggested
  path, so writing it under a shorter name no longer needs a manifest edit (several
  citing articles → an error asking for `--article`).
- **Instagram posts carry their own date** (`upload_date`/`timestamp`) instead of the
  ingest day, so raw paths and slugs date correctly.

### Changed
- **`finish` commits only this ingest's files by default (`[finish] stage = "scoped"`).**
  Previously it ran `git add -A`, sweeping any other uncommitted work (another ingest in
  progress, unrelated edits) into the commit. Scoped staging takes the raw, its assets,
  the article, sources it cites, the index, and changed wiki files that link to the
  article. `stage = "all"` restores the old behaviour. When nothing in scope changed,
  `finish` reports it instead of failing on an empty commit.

## [0.5.3]

### Added
- **`lint` now flags dated raw captures left loose in the raw root.** `[store] raw_layout`
  declares where raw material belongs, but nothing checked that it went there, so a store
  could drift to hundreds of misfiled captures with a clean lint. The check is narrow by
  design — only the root is inspected, since a store may legitimately keep dated files under
  a named category folder the template can't express — and it stays silent on a flat layout.
  Toggle with `[lint] raw_layout` (default on); add `"raw_layout"` to `fail_on` to gate on it.

## [0.5.2]

### Changed
- **Groundedness is no longer defeated by plurals or directory sources.** The check compared
  raw lowercased words, so `**Webhook Verification**` was flagged against a source that said
  "verifying webhooks", and a cited directory (a notes export, a scan bundle) contributed no
  words at all. Terms and source text are now lightly stemmed before comparison, and a cited
  directory's `.md`/`.txt` files are read (bounded at 500 files). Real fabrications are still
  caught; the false-positive rate drops.

## [0.5.1]

### Fixed
- **`lint` treated any link target starting with `http` as an external URL.** `_body_links`
  tested `target.startswith("http")`, so a relative link to a file whose name begins with
  `http` — `http-status-codes.md` being the obvious one — was discarded before resolution.
  The target could never accumulate inbound links and was reported as an orphan no matter how
  many articles linked to it, while the linking articles lost an outgoing edge. The test is
  now scheme-qualified (`http://`, `https://`), matching `_is_local_source` in the same module.

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
