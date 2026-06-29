"""Configuration — the heart of Quarry's generic core.

Every convention (paths, layouts, frontmatter schema, thresholds, commit message)
is a field here, not a hardcoded literal elsewhere. A ``Config`` is loaded once and
threaded through every command, so no other module reads conventions directly.

NOTE: this module deliberately does *not* ``from __future__ import annotations``.
Real (non-stringized) field types are needed at runtime so ``load`` can type-check
the user's ``quarry.toml`` against the dataclass definitions.
"""

import sys
import tomllib
import types
import typing
from dataclasses import dataclass, field, fields
from pathlib import Path

from quarry.errors import ConfigError, QuarryError

CONFIG_FILENAME = "quarry.toml"
MANIFEST_GITIGNORE_LINE = ".quarry/"

ON_DUPLICATE_CHOICES = ("refuse", "warn", "allow")
DISCOVERY_BACKEND_CHOICES = ("qmd", "none")
DISCOVERY_MODE_CHOICES = ("auto", "on", "off")


# ---------------------------------------------------------------------------
# Sub-configs — one dataclass per quarry.toml table. Defaults are the example
# conventions carried from bin/kb; every value is overridable.
# ---------------------------------------------------------------------------


@dataclass
class StoreConfig:
    wiki: str = "wiki"
    raw: str = "raw"
    raw_layout: str = "{year}/{month}/{slug}.{ext}"
    manifest_dir: str = ".quarry"
    root: str | None = None  # explicit store root; None => dir containing quarry.toml


@dataclass
class FrontmatterConfig:
    required: list[str] = field(
        default_factory=lambda: ["title", "updated", "sources", "related"]
    )
    sources_field: str = "sources"
    related_field: str = "related"


@dataclass
class IngestConfig:
    default_ext: str = "md"
    slug: str = "{date}_{kebab_title}"
    on_duplicate: str = "refuse"  # refuse | warn | allow


@dataclass
class AdaptersConfig:
    enabled: list[str] = field(
        default_factory=lambda: ["youtube", "reddit", "github", "instagram", "pdf", "web"]
    )


@dataclass
class DiscoveryConfig:
    backend: str = "qmd"  # qmd | none
    mode: str = "auto"  # auto | on | off
    collection: str = "wiki"
    dedup_threshold: int = 85
    densify_topk: int = 6


@dataclass
class LintConfig:
    broken_links: bool = True
    require_sources_on_disk: bool = True
    orphan_check: bool = True
    groundedness: bool = False  # flag bolded named terms not traceable to cited text sources
    index_file: str = "index.md"  # "" disables the not-in-index check
    fail_on: list[str] = field(
        default_factory=lambda: ["broken_links", "missing_sources"]
    )


@dataclass
class FinishConfig:
    run_lint: bool = True
    auto_push: bool = False
    commit_template: str = "wiki: {slug}"


@dataclass
class Config:
    """The fully-resolved configuration threaded through every command."""

    root: Path
    config_path: Path
    store: StoreConfig
    frontmatter: FrontmatterConfig
    ingest: IngestConfig
    adapters: AdaptersConfig
    discovery: DiscoveryConfig
    lint: LintConfig
    finish: FinishConfig


# Maps a quarry.toml table name to its dataclass + the Config attribute it fills.
_TABLES: dict[str, tuple[type, str]] = {
    "store": (StoreConfig, "store"),
    "frontmatter": (FrontmatterConfig, "frontmatter"),
    "ingest": (IngestConfig, "ingest"),
    "adapters": (AdaptersConfig, "adapters"),
    "discovery": (DiscoveryConfig, "discovery"),
    "lint": (LintConfig, "lint"),
    "finish": (FinishConfig, "finish"),
}


# ---------------------------------------------------------------------------
# Type checking — validate the parsed TOML against the dataclass field types.
# ---------------------------------------------------------------------------


def _matches(value: object, expected: object) -> bool:
    """Recursive isinstance that understands ``X | Y`` unions and ``list[T]``."""
    origin = typing.get_origin(expected)
    if origin in (typing.Union, types.UnionType):
        return any(_matches(value, arg) for arg in typing.get_args(expected))
    if origin is list:
        args = typing.get_args(expected) or (object,)
        return isinstance(value, list) and all(_matches(item, args[0]) for item in value)
    if expected is type(None):
        return value is None
    # bool is a subclass of int, but TOML distinguishes them — don't let a bool
    # silently satisfy an int field (or vice versa).
    if expected is int and isinstance(value, bool):
        return False
    if expected is bool and not isinstance(value, bool):
        return False
    return isinstance(value, expected)


def _type_name(expected: object) -> str:
    origin = typing.get_origin(expected)
    if origin in (typing.Union, types.UnionType):
        return " | ".join(_type_name(a) for a in typing.get_args(expected))
    if origin is list:
        args = typing.get_args(expected) or (object,)
        return f"list[{_type_name(args[0])}]"
    if expected is type(None):
        return "none"
    return getattr(expected, "__name__", str(expected))


def _build(cls: type, data: dict, table: str, warnings: list[str]):
    """Instantiate a sub-config dataclass from a TOML table dict.

    Unknown keys are collected as warnings (non-fatal). Type mismatches raise
    ConfigError. Missing keys fall back to the dataclass default.
    """
    spec = {f.name: f for f in fields(cls)}
    kwargs: dict[str, object] = {}
    for key, value in data.items():
        if key not in spec:
            warnings.append(f"[{table}] {key}")
            continue
        expected = spec[key].type
        if not _matches(value, expected):
            raise ConfigError(
                f"[{table}] {key}: expected {_type_name(expected)}, "
                f"got {type(value).__name__}"
            )
        kwargs[key] = value
    return cls(**kwargs)


# ---------------------------------------------------------------------------
# Discovery of the config file
# ---------------------------------------------------------------------------


def find_config(start: Path | None = None) -> tuple[Path, dict]:
    """Walk up from ``start`` (default CWD) for ``quarry.toml``.

    Falls back to a ``[tool.quarry]`` table in a ``pyproject.toml`` found on the
    way up. Raises ConfigError if neither is found.
    """
    start = (start or Path.cwd()).resolve()
    pyproject_fallback: tuple[Path, dict] | None = None
    for d in (start, *start.parents):
        cfg = d / CONFIG_FILENAME
        if cfg.is_file():
            return cfg, _parse_toml(cfg)
        if pyproject_fallback is None:
            pp = d / "pyproject.toml"
            if pp.is_file():
                table = _parse_toml(pp).get("tool", {}).get("quarry")
                if isinstance(table, dict):
                    pyproject_fallback = (pp, table)
    if pyproject_fallback is not None:
        return pyproject_fallback
    raise ConfigError("no quarry.toml found (run 'quarry init')")


def _parse_toml(path: Path) -> dict:
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path.name}: invalid TOML — {e}") from e


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------


def load(start: Path | None = None) -> Config:
    """Discover, parse, validate, and resolve a Config from quarry.toml."""
    config_path, raw = find_config(start)

    warnings: list[str] = []
    built: dict[str, object] = {}
    for table, (cls, attr) in _TABLES.items():
        section = raw.get(table, {})
        if not isinstance(section, dict):
            raise ConfigError(f"[{table}]: expected a table, got {type(section).__name__}")
        built[attr] = _build(cls, section, table, warnings)

    # Unknown top-level tables also warn (but a bare pyproject [tool.quarry]
    # fallback legitimately carries only known tables).
    for key in raw:
        if key not in _TABLES and key != "tool":
            warnings.append(f"[{key}] (unknown table)")

    if warnings:
        joined = ", ".join(warnings)
        print(f"quarry: warning: unknown config keys ignored: {joined}", file=sys.stderr)

    _validate_enums(built)

    store: StoreConfig = built["store"]  # type: ignore[assignment]
    root = Path(store.root).expanduser() if store.root else config_path.parent
    return Config(root=root.resolve(), config_path=config_path, **built)  # type: ignore[arg-type]


def _validate_enums(built: dict[str, object]) -> None:
    ingest: IngestConfig = built["ingest"]  # type: ignore[assignment]
    if ingest.on_duplicate not in ON_DUPLICATE_CHOICES:
        raise ConfigError(
            f"[ingest] on_duplicate: must be one of {ON_DUPLICATE_CHOICES}, "
            f"got '{ingest.on_duplicate}'"
        )
    disc: DiscoveryConfig = built["discovery"]  # type: ignore[assignment]
    if disc.backend not in DISCOVERY_BACKEND_CHOICES:
        raise ConfigError(
            f"[discovery] backend: must be one of {DISCOVERY_BACKEND_CHOICES}, "
            f"got '{disc.backend}'"
        )
    if disc.mode not in DISCOVERY_MODE_CHOICES:
        raise ConfigError(
            f"[discovery] mode: must be one of {DISCOVERY_MODE_CHOICES}, "
            f"got '{disc.mode}'"
        )


# ---------------------------------------------------------------------------
# init — scaffold a documented default quarry.toml
# ---------------------------------------------------------------------------

DEFAULT_TOML = """\
# quarry.toml — knowledge-ingestion harness configuration.
# Every convention Quarry uses lives here; nothing is hardcoded. Run `quarry doctor`
# to validate this file and check optional dependencies.

[store]
# root is the directory containing this quarry.toml unless set explicitly.
# root = "/abs/path/to/store"
wiki = "wiki"                 # compiled articles (relative to root)
raw  = "raw"                  # immutable source material (relative to root)
# raw_layout tokens: {year} {month} {date} {slug} {kebab_title} {ext} {topic} {source_id}
raw_layout = "{year}/{month}/{slug}.{ext}"   # raw path template (relative to raw/)
manifest_dir = ".quarry"      # compile-manifests (gitignored)

[frontmatter]
required = ["title", "updated", "sources", "related"]   # fields an article must carry
sources_field = "sources"     # frontmatter field whose entries cite raw/ material
related_field = "related"     # frontmatter field listing related wiki articles

[ingest]
default_ext = "md"
slug = "{date}_{kebab_title}" # slug template
on_duplicate = "refuse"       # refuse | warn | allow  (governs the dedup pre-check)

[adapters]
# allowlist; order = resolution priority (specific adapters before the catch-all web)
enabled = ["youtube", "reddit", "github", "instagram", "pdf", "web"]

[discovery]
backend = "qmd"               # qmd | none
mode = "auto"                 # auto (use if available) | on (required) | off
collection = "wiki"
dedup_threshold = 85          # % match at ingest that triggers on_duplicate
densify_topk = 6              # mutual top-K for the densify sweep

[lint]
broken_links = true
require_sources_on_disk = true
orphan_check = true           # inbound-from-body only (frontmatter related: does NOT count)
groundedness = false          # flag bolded names absent from cited sources (anti-fabrication)
index_file = "index.md"       # "" disables the not-in-index check
fail_on = ["broken_links", "missing_sources"]   # which checks make finish/lint exit non-zero
# add "groundedness" to fail_on to make finish ABORT on ungrounded terms (else advisory-only)

[finish]
# what `quarry finish` does after provenance + lint pass
run_lint = true               # run the lint report as part of finish
auto_push = false             # push after commit (otherwise push only with --push)
commit_template = "wiki: {slug}"
"""


def init(directory: Path | None = None, *, force: bool = False) -> Path:
    """Scaffold a documented ``quarry.toml`` and gitignore the manifest dir.

    Returns the path written. Refuses to overwrite an existing config unless
    ``force`` is set (raises QuarryError -> exit 1).
    """
    directory = (directory or Path.cwd()).resolve()
    config_path = directory / CONFIG_FILENAME
    if config_path.exists() and not force:
        raise QuarryError(
            f"{CONFIG_FILENAME} already exists at {config_path} (use --force to overwrite)"
        )
    config_path.write_text(DEFAULT_TOML, encoding="utf-8")
    _ensure_gitignore(directory)
    return config_path


def _ensure_gitignore(directory: Path) -> bool:
    """Add the manifest-dir line to .gitignore (creating it if absent).

    Returns True if the file was modified.
    """
    gitignore = directory / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    lines = {ln.strip() for ln in existing.splitlines()}
    if MANIFEST_GITIGNORE_LINE in lines:
        return False
    prefix = "" if existing == "" or existing.endswith("\n") else "\n"
    gitignore.write_text(
        existing + prefix + MANIFEST_GITIGNORE_LINE + "\n", encoding="utf-8"
    )
    return True
