"""Quarry — a config-driven knowledge-ingestion harness.

Quarry owns the *deterministic* half of turning a source (a YouTube video, a web
page, …) into a linked article in a markdown knowledge wiki. It never calls an LLM:
the one irreducibly-generative step — writing the article — happens between the two
calls `quarry ingest` and `quarry finish`.
"""

__version__ = "0.1.0"

from quarry.errors import ConfigError, QuarryError

__all__ = ["ConfigError", "QuarryError", "__version__"]
