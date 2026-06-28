"""Config-matrix test — ISC-87: the pipeline runs under several quarry.toml variants."""

from pathlib import Path

import pytest

from quarry import config, finish, ingest
from quarry.adapters import registry
from quarry.adapters.base import FetchResult


class FakeAdapter:
    name = "fake"

    def matches(self, url: str) -> bool:
        return True

    def fetch(self, url: str) -> FetchResult:
        return FetchResult(
            content="the body text",
            metadata={
                "title": "My Title",
                "author": "me",
                "date": "2026-06-28",
                "url": url,
                "source_id": "sid",
            },
        )


VARIANTS = [
    pytest.param(
        '[store]\nraw_layout = "{year}/{month}/{slug}.{ext}"\n',
        "sources",
        id="default-layout",
    ),
    pytest.param(
        '[store]\nraw_layout = "{slug}.{ext}"\n'
        '[frontmatter]\nsources_field = "cites"\n'
        '[discovery]\nbackend = "none"\n',
        "cites",
        id="flat-layout-alt-schema-no-discovery",
    ),
    pytest.param(
        '[store]\nraw_layout = "{topic}/{kebab_title}.{ext}"\n'
        '[finish]\ncommit_template = "add {slug}"\n',
        "sources",
        id="topic-layout-custom-commit",
    ),
]


@pytest.mark.parametrize("toml,sources_field", VARIANTS)
def test_pipeline_under_config_variants(chtmp: Path, monkeypatch, toml: str, sources_field: str):
    (chtmp / "quarry.toml").write_text(toml)
    cfg = config.load(chtmp)
    monkeypatch.setattr(registry, "resolve_adapter", lambda c, u: FakeAdapter())

    res = ingest.run(cfg, "https://example.com/x", topic="t")
    m = res["manifest"]
    assert (cfg.root / m["raw_path"]).is_file()  # raw written per the variant's layout

    art = cfg.root / res["target_wiki_path"]
    art.parent.mkdir(parents=True, exist_ok=True)
    art.write_text(
        f"---\ntitle: My Title\n{sources_field}:\n  - {m['must_cite_source']}\n---\n\nclean body\n",
        encoding="utf-8",
    )

    # finish in a non-git store: provenance + lint verified, commit skipped gracefully
    out = finish.run(cfg, res["slug"])
    assert out["article"] == res["target_wiki_path"]
    assert out["committed"] is False
