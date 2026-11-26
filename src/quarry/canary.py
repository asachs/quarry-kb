"""A known-good capture, taken again on a schedule, to notice a broken stage within a day.

Three silent failures need three different checks. A job that did not run is caught by the
age of the last canary result. A capture that ran and produced nothing is caught here: the
canary sources are chosen because every stage should succeed on them (a reel with narration
and on-screen text, an article that extracts cleanly), so an ``empty`` or ``failed`` stage
on a canary is a broken stage, not a property of the source. A stage that is empty on most
real captures is caught by ``symptoms`` over recent manifests.

``run`` fetches each ``[canary] urls`` entry through its adapter and stores nothing in the
wiki; the result goes to ``<manifest dir>/canary.json`` for ``quarry doctor`` to read.
"""

from __future__ import annotations

import copy
import json
import shutil
import time
from pathlib import Path

from quarry import capture
from quarry.adapters import registry
from quarry.config import Config
from quarry.store import manifest_dir

# A canary whose content shrinks to under this share of its best run has lost something
# even if no stage says so (a consent page instead of an article, a caption with no body).
SHRINK = 0.5


def result_path(cfg: Config) -> Path:
    return manifest_dir(cfg) / "canary.json"


def load(cfg: Config) -> dict | None:
    try:
        data = json.loads(result_path(cfg).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _check_one(cfg: Config, url: str, best_chars: int) -> dict:
    out: dict = {"url": url, "adapter": None, "ok": False, "problems": [], "chars": 0}
    try:
        adapter = registry.resolve_adapter(cfg, url)
        out["adapter"] = adapter.name
        result = registry.fetch(adapter, url)
    except Exception as e:  # noqa: BLE001 - a canary reports, it never raises
        out["problems"].append(f"capture failed: {capture.error_detail(e)}")
        return out
    try:
        stages = list(result.stages) or [
            capture.stage("content", capture.OK if result.content.strip() else capture.EMPTY)
        ]
        out["stages"] = stages
        out["chars"] = len(result.content)
        for s in capture.problems(stages):
            detail = f" ({s['detail']})" if s["detail"] else ""
            out["problems"].append(f"{s['name']}: {s['status']}{detail}")
        if best_chars and out["chars"] < best_chars * SHRINK:
            out["problems"].append(
                f"content shrank to {out['chars']:,} characters from a best of {best_chars:,}"
            )
        out["ok"] = not out["problems"]
    finally:
        if result.tmpdir:
            shutil.rmtree(result.tmpdir, ignore_errors=True)
    return out


def run(cfg: Config) -> dict:
    """Capture every canary source once. Returns (and saves) the result record."""
    # A canary must not add to the media store every day, nor keep media in the repository.
    probe = copy.deepcopy(cfg)
    probe.instagram.video_store = ""
    probe.instagram.keep_video = False
    previous = load(cfg) or {}
    best = dict(previous.get("best_chars") or {})
    results = []
    for url in cfg.canary.urls:
        r = _check_one(probe, url, int(best.get(url, 0)))
        best[url] = max(int(best.get(url, 0)), r["chars"])
        results.append(r)
    record = {
        "ran_at": time.time(),
        "ran_at_iso": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "tools": capture.tool_versions(),
        "passed": sum(r["ok"] for r in results),
        "total": len(results),
        "results": results,
        "best_chars": best,
    }
    path = result_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return record


def health(cfg: Config, now: float | None = None) -> tuple[bool, str]:
    """``(healthy, one-line reason)`` from the saved result, for ``quarry doctor``."""
    data = load(cfg)
    if not data:
        return False, "never run — run `quarry canary` (and schedule it daily)"
    age_h = ((now or time.time()) - float(data.get("ran_at", 0))) / 3600
    passed, total = data.get("passed", 0), data.get("total", 0)
    if age_h > cfg.canary.max_age_hours:
        limit = cfg.canary.max_age_hours
        return False, f"last ran {age_h:.0f} h ago (limit {limit} h): the schedule has stopped"
    if passed < total:
        first = next(r for r in data.get("results", []) if not r.get("ok"))
        why = "; ".join(first.get("problems", []))[:160]
        who = first.get("adapter") or first["url"]
        return False, f"{total - passed} of {total} failing, e.g. {who}: {why}"
    return True, f"{passed} of {total} passed {age_h:.0f} h ago"


def symptoms(cfg: Config, last: int = 30, share: float = 1 / 3) -> tuple[int, list[str]]:
    """Stages that failed or came back empty unusually often across the most recent
    captures. Returns ``(captures looked at, [one line per symptom])``. A stage is reported
    when it failed in more than ``share`` of the captures that ran it, or was empty in more
    than twice that share."""
    d = manifest_dir(cfg)
    files = sorted(
        (p for p in d.glob("*.json") if p.name != "canary.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    ran: dict[str, int] = {}
    failed: dict[str, int] = {}
    empty: dict[str, int] = {}
    looked = 0
    for p in files:
        if looked >= last:
            break
        try:
            m = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        stages = m.get("stages") if isinstance(m, dict) else None
        if not stages:
            continue  # captured before stages were recorded
        looked += 1
        for s in stages:
            if s.get("status") == capture.SKIPPED:
                continue
            key = f"{m.get('adapter', '?')}: {s.get('name')}"
            ran[key] = ran.get(key, 0) + 1
            if s.get("status") == capture.FAILED:
                failed[key] = failed.get(key, 0) + 1
            elif s.get("status") == capture.EMPTY:
                empty[key] = empty.get(key, 0) + 1
    out = []
    for key, n in sorted(ran.items()):
        if n < 3:
            continue
        if failed.get(key, 0) / n > share:
            out.append(f"{key} failed in {failed[key]} of {n}")
        elif empty.get(key, 0) / n > min(2 * share, 0.9):
            out.append(f"{key} was empty in {empty[key]} of {n}")
    return looked, out
