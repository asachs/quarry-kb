"""Source adapters — the extension unit.

A new source type is one small, self-contained adapter discoverable via the
``quarry.adapters`` entry-point group and gated by the ``[adapters] enabled``
allowlist. Built-in adapters: ``youtube``, ``web``.
"""

from quarry.adapters.base import Adapter, FetchResult

__all__ = ["Adapter", "FetchResult"]
