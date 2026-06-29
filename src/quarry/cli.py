"""Command-line entry point — argparse dispatch to command functions.

Each command function takes the parsed args and returns a process exit code.
Errors raised as ``ConfigError`` (exit 2) or ``QuarryError`` (exit 1) are caught
here and printed as clean one-liners — never a traceback.
"""

from __future__ import annotations

import argparse
import sys

from quarry import __version__, config, discovery, finish, git, ingest, lint
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
    tail = "" if res["target_wiki_path"] else " --article <path>"
    print(f"\nthen: quarry finish {res['slug']}{tail}")
    return 0


def cmd_finish(args: argparse.Namespace) -> int:
    cfg = config.load()
    res = finish.run(cfg, args.slug, article=args.article, push=args.push)
    state = "committed" + (" + pushed" if res["pushed"] else "")
    if not res["committed"]:
        state = "verified (not a git repo — skipped commit)"
    print(f"✓ provenance verified, lint clean, {state}: {res['article']}")
    return 0


def cmd_lint(args: argparse.Namespace) -> int:
    cfg = config.load()
    result = lint.run(cfg)
    print(result.report)
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
    if "reddit" in enabled:
        from quarry.adapters.reddit import oauth_configured

        check(
            "reddit adapter dep (curl_cffi)",
            _module_present("curl_cffi"),
            "pip install 'quarry-kb[reddit]'",
            hard=False,
        )
        check(
            "reddit OAuth (reliable; else best-effort no-key)",
            oauth_configured(),
            "set QUARRY_REDDIT_CLIENT_ID/SECRET — see reddit adapter docs",
            hard=False,
        )
    _, status = discovery.check(cfg)
    check(
        f"discovery backend ({cfg.discovery.backend})",
        status != discovery.MISSING,
        "qmd not found: npm i -g @tobilu/qmd && qmd embed",
        hard=False,
    )
    return 0 if ok else 1


def _discovery_backend_or_exit(cfg) -> object | None:
    """Resolve the discovery backend; print/raise per status. None => caller returns 0."""
    backend, status = discovery.check(cfg)
    if status == discovery.DISABLED:
        print("discovery is disabled ([discovery] backend = none)")
        return None
    if status == discovery.MISSING:
        raise QuarryError(
            "qmd not found (optional) — install: npm i -g @tobilu/qmd && qmd embed"
        )
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
