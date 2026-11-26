"""Command-line entry point — argparse dispatch to command functions.

Each command function takes the parsed args and returns a process exit code.
Errors raised as ``ConfigError`` (exit 2) or ``QuarryError`` (exit 1) are caught
here and printed as clean one-liners — never a traceback.
"""

from __future__ import annotations

import argparse
import json
import sys

from quarry import (
    __version__,
    canary,
    capture,
    config,
    discovery,
    finish,
    git,
    ingest,
    lint,
    pending,
    relevance,
    transcribe,
)
from quarry.adapters import registry
from quarry.errors import ConfigError, QuarryError


def cmd_init(args: argparse.Namespace) -> int:
    path = config.init(force=args.force)
    print(f"✓ wrote {path.name}")
    print("✓ .quarry/ is gitignored")
    print("\nEdit quarry.toml to match your wiki, then: quarry ingest <url>")
    return 0


def cmd_adapters(args: argparse.Namespace) -> int:
    cfg = config.load()
    for name, enabled in registry.list_adapters(cfg):
        print(f"  {name:12} ({'enabled' if enabled else 'disabled'})")
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    cfg = config.load()
    res = ingest.run(cfg, args.url, topic=args.topic, force=args.force)
    m = res["manifest"]
    target = res["target_wiki_path"] or f"{cfg.store.wiki}/<topic>/{res['slug']}.md"
    print(f"✓ raw written: {res['raw_path']}")
    print(f"✓ manifest:    {cfg.store.manifest_dir}/{res['slug']}.json")
    print("\nCOMPILE-SPEC (write the wiki article, then run `quarry finish`):")
    print(f"  slug:             {res['slug']}")
    print(f"  source:           {m['source_url']}")
    print(f"  target (suggest): {target}")
    print(f"  MUST cite source: {cfg.frontmatter.sources_field}: [{m['must_cite_source']}]")
    print(f"  required frontmatter: {', '.join(m['required_frontmatter'])}")
    meta = m.get("metadata") or {}
    if meta.get("date"):
        kind = f"  ({meta['kind']})" if meta.get("kind") else ""
        print(f"  source date:      {meta['date']}{kind}")
    bad = capture.problems(m.get("stages") or [])
    if bad:
        print("  CAPTURE PROBLEMS (also at the top of the raw, under ## Capture quality):")
        for st in bad:
            detail = f" — {st['detail']}" if st["detail"] else ""
            print(f"    {st['name']}: {st['status'].upper()}{detail}")
        print("    say so in your reply, and do not fill these gaps from expectation")
    for rec in m.get("stored") or []:
        print(f"  kept outside git: {rec['kind']} sha256 {rec['sha256'][:16]}…  {rec['path']}")
    assets = m.get("assets") or []
    if assets:
        folder = assets[0].rsplit("/", 1)[0]
        print(f"  media ({len(assets)}):       {folder}/  — listed in the raw's ## Media section")
        print("                    images are saved; read them only where the raw's OCR")
        print("                    text doesn't already cover what matters")
    cands = m.get("related_candidates") or []
    if cands:
        print("  link candidates (keyword matches: candidates, not instructions; many are noise):")
        for c in cands:
            print(f"    {c['score']:4d}  {c['path']}  — {c['title']}")
    else:
        diag = m.get("discovery") or {}
        if diag.get("requested") and not diag.get("available"):
            print("  link candidates:  none — qmd was not found, so no lookup ran")
        elif diag.get("requested"):
            rc = diag.get("refresh_exit")
            stale = f", index refresh exited {rc}" if rc not in (None, 0) else ""
            print(
                f"  link candidates:  none — {diag.get('queries', 0)} qmd queries matched "
                f"{diag.get('paths_hit', 0)} articles{stale}; use `quarry related` after writing"
            )
    tail = "" if res["target_wiki_path"] else " --article <path>"
    print(f"\nthen: quarry finish {res['slug']}{tail}")
    print("  (finish finds the article by its source citation if you write it elsewhere)")
    return 0


def cmd_finish(args: argparse.Namespace) -> int:
    cfg = config.load()
    res = finish.run(cfg, args.slug, article=args.article, push=args.push)
    state = "committed" + (" + pushed" if res["pushed"] else "")
    if not res["committed"]:
        state = "verified (nothing committed — not a git repo or no changes)"
    print(f"✓ provenance verified, lint clean, {state}: {res['article']}")
    if res.get("indexed"):
        print(f"✓ added to {cfg.lint.index_file}")
    if res.get("marked_unverified"):
        name = cfg.frontmatter.verification_field
        print(
            f"✓ marked `{name}: unverified` — the source has images. After checking every "
            f"claim against them, set `{name}: verified` with `verified_on` and `verified_by`."
        )
    if res.get("staged"):
        print(f"  committed {len(res['staged'])} file(s): {', '.join(res['staged'])}")
    if cfg.lint.link_relevance:
        _print_link_report(cfg, res["article"])
    return 0


def _print_link_report(cfg, article: str, idx=None) -> int:
    """Weak links around one article, and closer articles it does not link. Returns the
    number of weak links."""
    idx = idx or relevance.build(cfg)
    rel = relevance.wiki_rel(cfg, article)
    rep = relevance.for_article(idx, rel, cfg.lint.weak_link_rank)
    wiki = cfg.store.wiki
    if rep["weak"]:
        print(
            f"! {len(rep['weak'])} cross-link(s) look weak: many articles are closer to "
            "this one than the one linked. Keep a link only if you can say what the two "
            "share; a wrong link is worse than one link fewer."
        )
        for rank, direction, other in rep["weak"]:
            arrow = {"out": "links to", "in": "is linked from", "both ways": "<->"}[direction]
            print(f"    {arrow} {wiki}/{other}  (rank {rank})")
    if rep["closest_unlinked"]:
        print("  closest articles not linked (candidates, not instructions):")
        for other in rep["closest_unlinked"]:
            print(f"    {wiki}/{other}")
    return len(rep["weak"])


def cmd_links(args: argparse.Namespace) -> int:
    cfg = config.load()
    if args.rank is not None:
        cfg.lint.weak_link_rank = args.rank
    idx = relevance.build(cfg)
    if args.article:
        rel = relevance.wiki_rel(cfg, args.article)
        if rel not in idx.vectors:
            raise QuarryError(f"not a wiki article: {args.article}")
        if not _print_link_report(cfg, args.article, idx):
            print("no weak links")
        return 0
    weak = relevance.weak_links(idx, cfg.lint.weak_link_rank)
    total = sum(len(t) for t in idx.links.values())
    print(
        f"{len(weak)} of {total} links rank beyond {cfg.lint.weak_link_rank} in both "
        "directions (weakest first). A prompt to look, not a verdict:"
    )
    for rank, a, b in weak[: args.limit]:
        print(f"  {rank:4d}  {a} -> {b}")
    if len(weak) > args.limit:
        print(f"  ... {len(weak) - args.limit} more (--limit)")
    return 0


def cmd_lint(args: argparse.Namespace) -> int:
    cfg = config.load()
    result = lint.run(cfg)
    print(result.report)
    if cfg.lint.link_relevance:
        weak = relevance.weak_links(relevance.build(cfg), cfg.lint.weak_link_rank)
        print(f"Weak links:            {len(weak)}  (report only; details: quarry links)")
    return 1 if result.fails(cfg.lint.fail_on) else 0


def _module_present(name: str) -> bool:
    import importlib.util

    return importlib.util.find_spec(name) is not None


def cmd_doctor(args: argparse.Namespace) -> int:
    """Report config validity + optional deps/tools. Exit non-zero on a hard problem."""
    ok = True

    def check(label: str, cond: bool, hint: str = "", hard: bool = True) -> None:
        nonlocal ok
        if hard and not cond:
            ok = False
        flag = "ok" if cond else ("XX" if hard else "--")
        print(f"  [{flag}] {label}" + ("" if cond or not hint else f"  -> {hint}"))

    try:
        cfg = config.load()
        check("quarry.toml found + valid", True)
    except (ConfigError, QuarryError) as e:
        check("quarry.toml", False, str(e))
        return 2

    check("inside a git repo", git.is_repo(cfg.root), "git init to enable commits", hard=False)
    enabled = set(cfg.adapters.enabled)
    if "youtube" in enabled:
        check(
            "youtube adapter dep (youtube-transcript-api)",
            _module_present("youtube_transcript_api"),
            "pip install 'quarry-kb[youtube]'",
            hard=False,
        )
    if "web" in enabled:
        check(
            "web adapter dep (trafilatura)",
            _module_present("trafilatura"),
            "pip install 'quarry-kb[web]'",
            hard=False,
        )
    if "instagram" in enabled:
        check(
            "instagram adapter dep (curl_cffi for yt-dlp impersonation)",
            _module_present("curl_cffi"),
            "pip install 'quarry-kb[instagram]'",
            hard=False,
        )
    if enabled & {"youtube", "instagram"} and transcribe.available():
        why = transcribe.decode_check()
        check(
            "audio transcription can decode audio (ffmpeg, or PyAV without it)",
            why is None,
            f"{why} — try: pip install 'av<19' in Quarry's environment",
            hard=False,
        )
    backend, status = discovery.check(cfg)
    check(
        f"discovery backend ({cfg.discovery.backend})",
        status != discovery.MISSING,
        "qmd not found: npm i -g @tobilu/qmd && qmd embed",
        hard=False,
    )
    indexed = backend.indexed_files(cwd=cfg.root) if hasattr(backend, "indexed_files") else None
    if indexed is not None:
        on_disk = sum(1 for _ in (cfg.root / cfg.store.wiki).rglob("*.md"))
        check(
            f"qmd index covers the wiki ({indexed} of {on_disk} files indexed)",
            indexed >= on_disk * 0.95,
            "the index is stale — run `qmd update` (and `qmd embed` for semantic search)",
            hard=False,
        )
    if cfg.canary.urls:
        healthy, why = canary.health(cfg)
        check(
            f"canary captures ({why})", healthy, "run `quarry canary` to see each stage", hard=False
        )
    looked, sym = canary.symptoms(cfg)
    if looked:
        check(
            f"recent captures ({looked} looked at): "
            + ("; ".join(sym) if sym else "no stage failing or empty unusually often"),
            not sym,
            "a stage that fails this often is broken, not unlucky",
            hard=False,
        )
    return 0 if ok else 1


def cmd_canary(args: argparse.Namespace) -> int:
    cfg = config.load()
    if not cfg.canary.urls:
        raise QuarryError("no canary sources — set [canary] urls in quarry.toml")
    rec = canary.run(cfg)
    if args.json:
        print(json.dumps(rec, indent=1, ensure_ascii=False))
    else:
        for r in rec["results"]:
            mark = "ok  " if r["ok"] else "FAIL"
            print(f"[{mark}] {r['adapter'] or '?':10} {r['url']}")
            for prob in r["problems"]:
                print(f"         {prob}")
        print(f"{rec['passed']} of {rec['total']} canary captures passed")
    return 0 if rec["passed"] == rec["total"] else 1


def _discovery_backend_or_exit(cfg) -> object | None:
    """Resolve the discovery backend; print/raise per status. None => caller returns 0."""
    backend, status = discovery.check(cfg)
    if status == discovery.DISABLED:
        print("discovery is disabled ([discovery] backend = none)")
        return None
    if status == discovery.MISSING:
        raise QuarryError("qmd not found (optional) — install: npm i -g @tobilu/qmd && qmd embed")
    return backend


def cmd_related(args: argparse.Namespace) -> int:
    cfg = config.load()
    backend = _discovery_backend_or_exit(cfg)
    if backend is None:
        return 0
    cands = discovery.related(cfg, args.article, backend)
    print(f"Related candidates for {args.article} (not yet linked):")
    for score, path in cands[: args.limit]:
        print(f"  {score:3d}%  {path}")
    if not cands:
        print("  (none new — already well-linked or no matches)")
    return 0


def cmd_densify(args: argparse.Namespace) -> int:
    cfg = config.load()
    backend = _discovery_backend_or_exit(cfg)
    if backend is None:
        return 0
    topk = args.topk if args.topk is not None else cfg.discovery.densify_topk
    pairs = discovery.densify_pairs(cfg, topk, backend)
    if not args.apply:
        print(f"{len(pairs)} mutual-unlinked pairs (use --apply to add bidirectional links):")
        for (a, b), s in pairs:
            print(f"  {s:3d}  {a}  <->  {b}")
        return 0
    added = discovery.apply_pairs(cfg, pairs)
    print(f"added {added} links across {len(pairs)} pairs")
    return 0


def cmd_pending(args: argparse.Namespace) -> int:
    cfg = config.load()
    rows = pending.pending(cfg)
    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return 0
    if not rows:
        print("nothing pending — every capture with a manifest has an article")
        return 0
    print(f"{len(rows)} capture(s) with no article yet (oldest first):")
    for r in rows:
        print(f"  {r['slug']}\n    source: {r['source_url']}\n    raw:    {r['raw_path']}")
    print("\nfor each: write the article citing the raw, then: quarry finish <slug>")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    cfg = config.load()
    res = pending.status(cfg, args.url)
    if args.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0
    print(f"{res['state']}: {args.url}")
    for r in res["raw_paths"]:
        print(f"  raw:     {r}")
    for a in res["articles"]:
        print(f"  article: {a}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="quarry", description="knowledge-ingestion harness")
    p.add_argument("--version", action="version", version=f"quarry {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("init", help="scaffold a documented quarry.toml in the current dir")
    pi.add_argument("--force", action="store_true", help="overwrite an existing quarry.toml")
    pi.set_defaults(func=cmd_init)

    pa = sub.add_parser("adapters", help="list registered adapters and which are enabled")
    pa.set_defaults(func=cmd_adapters)

    pg = sub.add_parser("ingest", help="fetch a source -> raw/ + compile-manifest")
    pg.add_argument("url")
    pg.add_argument("--topic", help="wiki topic dir for the suggested target path")
    pg.add_argument("--force", action="store_true", help="overwrite raw / bypass dedup")
    pg.set_defaults(func=cmd_ingest)

    pf = sub.add_parser("finish", help="verify provenance -> lint -> commit")
    pf.add_argument("slug")
    pf.add_argument("--article", help="wiki article path (if not in the manifest)")
    pf.add_argument("--push", action="store_true", help="push after commit (default: no)")
    pf.set_defaults(func=cmd_finish)

    pl = sub.add_parser("lint", help="run the structural-health report")
    pl.set_defaults(func=cmd_lint)

    pdr = sub.add_parser("doctor", help="check config validity + optional deps/tools")
    pdr.set_defaults(func=cmd_doctor)

    pr = sub.add_parser("related", help="semantic link candidates for an article")
    pr.add_argument("article", help="wiki article path or name fragment")
    pr.add_argument("--limit", type=int, default=6)
    pr.set_defaults(func=cmd_related)

    pd = sub.add_parser("densify", help="whole-wiki sweep for mutual-unlinked pairs")
    pd.add_argument("--apply", action="store_true", help="add the bidirectional links")
    pd.add_argument("--topk", type=int, default=None, help="override [discovery] densify_topk")
    pd.set_defaults(func=cmd_densify)

    pp = sub.add_parser("pending", help="captures that have no wiki article yet")
    pp.add_argument("--json", action="store_true", help="machine-readable output")
    pp.set_defaults(func=cmd_pending)

    pc = sub.add_parser("canary", help="capture the known-good sources and check every stage")
    pc.add_argument("--json", action="store_true", help="machine-readable output")
    pc.set_defaults(func=cmd_canary)

    pk = sub.add_parser("links", help="cross-links that look like padding (report only)")
    pk.add_argument("article", nargs="?", help="one article; omit for the whole wiki")
    pk.add_argument("--rank", type=int, default=None, help="override [lint] weak_link_rank")
    pk.add_argument("--limit", type=int, default=40, help="rows to print for the whole wiki")
    pk.set_defaults(func=cmd_links)

    ps = sub.add_parser("status", help="is this URL absent, captured or compiled?")
    ps.add_argument("url")
    ps.add_argument("--json", action="store_true", help="machine-readable output")
    ps.set_defaults(func=cmd_status)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as e:  # most specific first — distinct exit code
        print(f"quarry: {e}", file=sys.stderr)
        return 2
    except QuarryError as e:
        print(f"quarry: error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
