"""Quarry's user-facing error taxonomy.

Errors are printed by the CLI as clean one-liners, never tracebacks. The error
class chooses the process exit code:

    QuarryError  -> exit 1  (user / operational error)
    ConfigError  -> exit 2  (configuration error)
"""

from __future__ import annotations


class QuarryError(Exception):
    """User-facing operational error — CLI prints a one-liner and exits 1."""


class ConfigError(QuarryError):
    """Configuration problem — CLI prints a one-liner and exits 2.

    Subclasses QuarryError so a broad ``except QuarryError`` still catches it, but
    the CLI checks for ``ConfigError`` first to assign the distinct exit code 2.
    """
