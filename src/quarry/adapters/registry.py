"""Adapter registry — built-ins + third-party entry points, gated by config.

Adapter *classes* are cheap to import (heavy per-source dependencies are imported
lazily inside ``fetch``), so discovery never requires an optional extra. The
``[adapters] enabled`` allowlist decides which adapters actually run, and in what
order they are tried.
"""

from __future__ import annotations

import importlib
from importlib.metadata import entry_points

from quarry.adapters.base import Adapter, FetchResult
from quarry.config import Config
from quarry.errors import QuarryError

ENTRY_POINT_GROUP = "quarry.adapters"

# Built-in adapters as "module:Class" specs (imported lazily on demand).
# Order matters for resolution: specific adapters before the catch-all web.
_BUILTIN: dict[str, str] = {
    "youtube": "quarry.adapters.youtube:YouTubeAdapter",
    "github": "quarry.adapters.github:GitHubAdapter",
    "instagram": "quarry.adapters.instagram:InstagramAdapter",
    "pdf": "quarry.adapters.pdf:PdfAdapter",
    "web": "quarry.adapters.web:WebAdapter",
}


def _load_spec(spec: str) -> type[Adapter]:
    module_name, _, class_name = spec.partition(":")
    return getattr(importlib.import_module(module_name), class_name)


def discovered_adapters() -> dict[str, type[Adapter]]:
    """All registered adapter classes by name: built-ins plus entry points.

    A broken third-party plugin is skipped rather than crashing discovery.
    """
    out: dict[str, type[Adapter]] = {
        name: _load_spec(spec) for name, spec in _BUILTIN.items()
    }
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        try:
            out[ep.name] = ep.load()
        except Exception:  # noqa: BLE001 - a bad plugin must not kill discovery
            continue
    return out


def list_adapters(cfg: Config) -> list[tuple[str, bool]]:
    """Every discovered adapter as ``(name, enabled)``, enabled ones first."""
    discovered = discovered_adapters()
    enabled = cfg.adapters.enabled
    rows = [(name, name in enabled) for name in discovered]
    return sorted(rows, key=lambda r: (not r[1], r[0]))


def resolve_adapter(cfg: Config, url: str) -> Adapter:
    """First *enabled* adapter (in configured order) whose ``matches`` is true."""
    discovered = discovered_adapters()
    for name in cfg.adapters.enabled:
        cls = discovered.get(name)
        if cls is None:
            continue  # enabled in config but not installed/registered
        adapter = cls()
        if adapter.matches(url):
            adapter.cfg = cfg  # let the adapter read its own settings (e.g. youtube comments)
            return adapter
    raise QuarryError(f"no adapter matches URL (try 'quarry adapters'): {url}")


def fetch(adapter: Adapter, url: str) -> FetchResult:
    """Run an adapter's fetch, converting any fault into a clean QuarryError."""
    try:
        return adapter.fetch(url)
    except QuarryError:
        raise
    except Exception as e:  # noqa: BLE001 - surface as a clean one-liner, no traceback
        raise QuarryError(f"{adapter.name} adapter failed: {e}") from e
