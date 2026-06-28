# Quarry

A config-driven **knowledge-ingestion harness** — a CLI that owns the *deterministic*
half of turning a source (a YouTube video, a web page, …) into a linked article in a
markdown knowledge wiki.

Quarry resolves a source adapter, fetches, writes immutable raw material, hands a
machine-readable compile-spec to an LLM (or human) for the one irreducibly-generative
step — writing the article — then verifies provenance, lints, and commits. **It never
calls a model**, so it is runnable and testable without API keys.

> You extract raw material from the world and refine it into something structured.
> That is the pipeline, and the name.

## Quickstart

```bash
pip install quarry[youtube,web]
cd your-wiki-repo
quarry init           # scaffold a documented quarry.toml
# edit quarry.toml to match your wiki's conventions
quarry ingest <url>   # fetch -> raw/ + compile-manifest, then STOP
# (write the wiki article using the printed compile-spec)
quarry finish <slug>  # verify provenance -> lint -> commit
```

## Status

Pre-1.0, under active construction. See [`SPEC.md`](SPEC.md) for the full design and
[`ISA.md`](ISA.md) for the build's ideal-state criteria and progress.

## License

MIT — see [`LICENSE`](LICENSE).
