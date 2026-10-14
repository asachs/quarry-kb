"""The adapter contract.

An adapter knows how to recognise a URL and fetch it into raw material plus
metadata. Network calls must live in small overridable methods so the default
test suite can stay hermetic (no network, no keys).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FetchResult:
    """What an adapter returns: the raw content plus source metadata.

    ``metadata`` carries at least ``title``, ``url``, ``date`` (ISO), and
    ``source_id``; adapters may add ``author``, ``ext``, etc.

    ``assets`` maps a file name to a local file the adapter produced (video, frames,
    slide images). ``ingest`` copies them into the store per ``[ingest] assets_layout``
    and lists them in the raw and the manifest. ``tmpdir`` (if set) is an adapter-owned
    scratch directory that ``ingest`` deletes once the assets are copied.
    """

    content: str
    metadata: dict = field(default_factory=dict)
    assets: dict[str, str] = field(default_factory=dict)
    tmpdir: str | None = None


class Adapter:
    """Base adapter. Subclasses set ``name`` and implement ``matches`` + ``fetch``."""

    name: str = "base"
    # The resolved Config, attached by registry.resolve_adapter so an adapter can read
    # its own settings (e.g. youtube comments). None when constructed standalone.
    cfg: object = None

    def matches(self, url: str) -> bool:  # pragma: no cover - interface
        raise NotImplementedError

    def fetch(self, url: str) -> FetchResult:  # pragma: no cover - interface
        raise NotImplementedError
