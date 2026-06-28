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
    """

    content: str
    metadata: dict = field(default_factory=dict)


class Adapter:
    """Base adapter. Subclasses set ``name`` and implement ``matches`` + ``fetch``."""

    name: str = "base"

    def matches(self, url: str) -> bool:  # pragma: no cover - interface
        raise NotImplementedError

    def fetch(self, url: str) -> FetchResult:  # pragma: no cover - interface
        raise NotImplementedError
