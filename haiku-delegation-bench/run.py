"""Run the 74 fixture items against one model, one rep at a time.

    python run.py --model claude-haiku-5-5 --reps 1 2 3
    python run.py --model claude-haiku-5-5 --reps 1 --arm cap1024
    python run.py --model claude-haiku-5-5 --reps 0 --only c01 N1 e1   # pilot -> results/pilot/

Each rep writes results/raw/<model>-<arm>-r<k>.jsonl, one line per item, and a
.meta.json beside it (CLI version, flags, start and end time). Reruns skip
items already on file, so an interrupted rep resumes where it stopped.
`--retry-errors` reruns items whose call failed for a reason other than a
timeout (a CLI crash or an unparseable reply); a timeout is the model's own
result under C3's limits and is kept.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "_lib"))
sys.path.insert(0, str(HERE / "gen"))

import claude_runner  # noqa: E402
from common import NAV_REPO_DIR, NAV_REPO_SHA  # noqa: E402

ITEMS = HERE / "fixtures" / "items.jsonl"
RAW = HERE / "results" / "raw"
PILOT = HERE / "results" / "pilot"   # rep 0: harness checks, never analysed

# C3 v2.157.2 defaults: claude_timeout, claude_scout_timeout, claude_write_timeout.
TIMEOUT_S = {"single": 120, "scout": 240, "worker": 600}
ARMS = {"default": None, "cap1024": 1024}   # arm -> MAX_THINKING_TOKENS
SKIP_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".claude"}


def short(model: str) -> str:
    return model.removeprefix("claude-")


def load_items() -> list[dict]:
    return [json.loads(line) for line in ITEMS.read_text(encoding="utf-8").splitlines()]


def snapshot(root: Path) -> dict[str, str]:
    """Every text file under root, keyed by its posix path relative to root."""
    out = {}
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if p.is_dir() or any(part in SKIP_DIRS for part in rel.parts) or p.suffix == ".pyc":
            continue
        out[rel.as_posix()] = p.read_text(encoding="utf-8", errors="replace")
    return out


def run_item(it: dict, model: str, arm: str, single_cwd: Path) -> dict:
    mode = it["mode"]
    kw = dict(model=model, mode=mode, system_prompt=it["system"],
              timeout_s=TIMEOUT_S[mode], thinking_cap=ARMS[arm])
    rec: dict = {}
    if mode == "worker":
        tmp = Path(tempfile.mkdtemp(prefix="hdb-ws-"))
        try:
            for rel, src in it["workspace"].items():
                f = tmp / rel
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(src, encoding="utf-8", newline="\n")
            call = claude_runner.run(it["prompt"], cwd=str(tmp),
                                     write_paths=list(it["write_paths"]), **kw)
            rec["after"] = snapshot(tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    elif mode == "scout":
        call = claude_runner.run(it["prompt"], cwd=str(NAV_REPO_DIR), **kw)
    else:
        call = claude_runner.run(it["prompt"], cwd=str(single_cwd), **kw)
    return {"id": it["id"], "model": model, "arm": arm, **rec, "call": call.to_dict(),
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def check_nav_repo() -> None:
    head = subprocess.run(["git", "-C", str(NAV_REPO_DIR), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(NAV_REPO_DIR), "status", "--porcelain"],
                           capture_output=True, text=True).stdout.strip()
    if head != NAV_REPO_SHA or dirty:
        sys.exit(f"fixture repo is at {head} (dirty={bool(dirty)}); expected clean {NAV_REPO_SHA}")


def run_rep(items: list[dict], model: str, arm: str, rep: int, workers: int,
            retry_errors: bool) -> None:
    out = (RAW if rep > 0 else PILOT) / f"{short(model)}-{arm}-r{rep}.jsonl"
    meta_path = out.with_suffix(".meta.json")
    done: dict[str, dict] = {}
    if out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            done[r["id"]] = r
    if retry_errors:
        retry = {i for i, r in done.items()
                 if not r["call"]["ok"] and not r["call"]["error"].startswith("timeout")}
        for i in retry:
            del done[i]
        if retry:
            print(f"  retrying {len(retry)} errored items: {sorted(retry)}")
    todo = [it for it in items if it["id"] not in done]
    print(f"{out.name}: {len(done)} on file, {len(todo)} to run")
    if not todo:
        return

    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    meta.setdefault("started", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    meta.update(model=model, arm=arm, rep=rep, thinking_cap=ARMS[arm], timeouts_s=TIMEOUT_S,
                claude_version=subprocess.run(["claude", "--version"], capture_output=True,
                                              text=True).stdout.strip(),
                nav_repo_sha=NAV_REPO_SHA, concurrency=workers)
    out.parent.mkdir(parents=True, exist_ok=True)

    lock = threading.Lock()
    single_cwd = Path(tempfile.mkdtemp(prefix="hdb-single-"))
    t0 = time.monotonic()
    n = 0
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {pool.submit(run_item, it, model, arm, single_cwd): it for it in todo}
            for fut in as_completed(futs):
                it = futs[fut]
                try:
                    rec = fut.result()
                except Exception as exc:  # harness bug, not a model result: don't record it
                    print(f"  !! {it['id']}: {type(exc).__name__}: {exc}")
                    continue
                rec["rep"] = rep
                done[rec["id"]] = rec
                n += 1
                c = rec["call"]
                with lock:
                    # Rewrite the whole file so a retried item replaces its old line.
                    tmp = out.with_suffix(".tmp")
                    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n"
                                           for r in done.values()), encoding="utf-8")
                    tmp.replace(out)
                flag = "ok" if c["ok"] else f"ERR {c['error'][:60]}"
                print(f"  [{n}/{len(todo)}] {it['id']:<4} {flag:<6} {c['wall_s']:6.1f}s "
                      f"turns={c['num_turns']} ${c['cost_usd']:.4f} {c['model_answered']}",
                      flush=True)
    finally:
        shutil.rmtree(single_cwd, ignore_errors=True)
    meta["finished"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    meta["last_session_wall_s"] = round(time.monotonic() - t0, 1)
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--reps", type=int, nargs="+", required=True)
    ap.add_argument("--arm", choices=sorted(ARMS), default="default")
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--only", nargs="*", help="item ids or categories")
    ap.add_argument("--retry-errors", action="store_true")
    args = ap.parse_args()

    check_nav_repo()
    items = load_items()
    if args.only:
        items = [it for it in items if it["id"] in args.only or it["category"] in args.only]
    for rep in args.reps:
        run_rep(items, args.model, args.arm, rep, args.workers, args.retry_errors)
    return 0


if __name__ == "__main__":
    sys.exit(main())
