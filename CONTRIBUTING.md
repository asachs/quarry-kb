# Contributing to Quarry

Thanks for your interest. Quarry is small, deterministic, and heavily tested by design —
contributions are expected to keep it that way.

## Development setup

Quarry uses [`uv`](https://docs.astral.sh/uv/) for environments and Python management.

```bash
uv run --extra dev --extra all python -m pytest      # run the suite
uv run --extra dev ruff check .                      # lint
uv run --extra dev --extra all python -m coverage run -m pytest \
  && uv run --extra dev python -m coverage report --fail-under=90
```

Quality gates (enforced in CI): **all tests pass**, **`ruff` clean**, **coverage ≥ 90%**,
across Python 3.11–3.13.

## The adapter contract

A new source type is a small, self-contained adapter — no fork required.

```python
from quarry.adapters.base import Adapter, FetchResult

class PdfAdapter(Adapter):
    name = "pdf"

    def matches(self, url: str) -> bool:
        return url.lower().endswith(".pdf")

    def fetch(self, url: str) -> FetchResult:
        # Put network/IO in small overridable methods so tests stay hermetic.
        return FetchResult(content="...", metadata={
            "title": "...", "url": url, "date": "2026-01-01", "source_id": "...",
        })
```

Register it via an entry point in your package's `pyproject.toml`:

```toml
[project.entry-points."quarry.adapters"]
pdf = "your_package.pdf:PdfAdapter"
```

Then enable it in the consuming wiki's `quarry.toml`:

```toml
[adapters]
enabled = ["youtube", "web", "pdf"]
```

### Requirements for an adapter PR

1. **Hermetic test.** Network calls live behind overridable methods; tests use a recorded
   fixture/cassette and must pass with no network and no API keys.
2. **One `@pytest.mark.integration` live test** is allowed (excluded from the default run).
3. **Clean errors.** A missing optional dependency raises a `QuarryError` with an install
   hint — never a bare `ImportError` traceback.

## Principles to respect

- **Quarry never calls an LLM.** The article-writing step happens between `ingest` and
  `finish`, performed by a human or agent — not by Quarry.
- **No hardcoded conventions.** Everything configurable flows through the `Config` dataclass.
- **Fail loud, fail tested.** Every mechanical step has a test that catches its break.
