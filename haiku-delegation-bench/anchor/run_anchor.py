"""Private anchor: production email triage, one email per call, aggregates only.

The emails and the per-row replies never enter this repository. Both input
files and the raw output directory are paths outside it, given on the command
line; this script commits nothing and `anchor/summary.json` holds counts only.

    python anchor/run_anchor.py run   --gold <gold.jsonl> --contract <prompt.txt> \
        --private-dir <dir outside the repo> --model claude-haiku-5-5
    python anchor/run_anchor.py score --gold <gold.jsonl> --private-dir <dir> \
        --models claude-haiku-5-5 claude-sonnet-5-5

Gold rows carry message_id, subject, sender, body_snippet and `gold` (one of
seven labels, assigned by Opus). The contract is the production evaluator's
classification section with the allowlist facts as they stood at labelling
time, used verbatim as the system prompt. Each call sees subject, sender and
the first 1500 characters of the body, the same fields and cap the earlier
batched contests used. A reply with no valid label scores wrong.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import tempfile
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "_lib"))

import claude_runner  # noqa: E402

LABELS = ["receipt", "agent_actionable", "action_required", "calendar",
          "alert", "newsletter", "spam"]
SNIPPET_CAP = 1500
THIN = 15            # classes with fewer gold rows are reported, not interpreted
TIMEOUT_S = 120      # C3's single-call limit, as in the main runs

PROMPT = """Classify this email under the contract in your instructions.

```json
{email}
```

Reply with one JSON object in a fenced block: {{"label": "<category>"}}, where
category is one of: {labels}."""


def read_jsonl(path: Path) -> list[dict]:
    # split("\n"), not splitlines(): email bodies carry U+2028 and friends inside strings.
    return [json.loads(l) for l in path.read_text(encoding="utf-8").split("\n") if l.strip()]


def guard_private(path: Path) -> None:
    """Refuse a raw-output directory inside this repository."""
    try:
        path.resolve().relative_to(REPO.resolve())
    except ValueError:
        return
    sys.exit(f"--private-dir {path} is inside the repository; raw replies must stay outside it")


def parse_label(text: str) -> str | None:
    blocks = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    cands = blocks or re.findall(r"\{[^{}]*\}", text, re.S)
    for raw in reversed(cands):
        try:
            lab = str(json.loads(raw).get("label", "")).strip().lower()
        except (json.JSONDecodeError, AttributeError):
            continue
        return lab if lab in LABELS else None
    return None


def cmd_run(args) -> int:
    priv = Path(args.private_dir)
    guard_private(priv)
    priv.mkdir(parents=True, exist_ok=True)
    gold = read_jsonl(Path(args.gold))
    system = Path(args.contract).read_text(encoding="utf-8")
    out = priv / f"{args.model.removeprefix('claude-')}.jsonl"
    done = {r["message_id"]: r for r in read_jsonl(out)} if out.exists() else {}
    if args.retry_errors:
        for mid in [m for m, r in done.items()
                    if not r["ok"] and not r["error"].startswith("timeout")]:
            del done[mid]
    todo = [g for g in gold if g["message_id"] not in done][:args.limit]
    print(f"{out.name}: {len(done)} on file, {len(todo)} to run", flush=True)
    cwd = Path(tempfile.mkdtemp(prefix="hdb-anchor-"))
    lock = threading.Lock()

    def one(g: dict) -> dict:
        email = {"subject": g.get("subject") or "", "sender": g.get("sender") or "",
                 "body_snippet": (g.get("body_snippet") or "")[:SNIPPET_CAP]}
        prompt = PROMPT.format(email=json.dumps(email, ensure_ascii=False, indent=1),
                               labels=", ".join(LABELS))
        c = claude_runner.run(prompt, model=args.model, mode="single", system_prompt=system,
                              cwd=str(cwd), timeout_s=TIMEOUT_S)
        return {"message_id": g["message_id"], "model": args.model, "ok": c.ok,
                "error": c.error or "", "pred": parse_label(c.text) if c.ok else None,
                "text": c.text, "model_answered": c.model_answered, "cost_usd": c.cost_usd,
                "wall_s": c.wall_s, "output_tokens": c.output_tokens,
                "thinking_tokens": c.thinking_tokens}

    n = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(one, g): g for g in todo}
        for fut in as_completed(futs):
            try:
                rec = fut.result()
            except Exception as exc:  # harness bug: don't record it
                print(f"  !! {type(exc).__name__}: {exc}", flush=True)
                continue
            n += 1
            with lock:
                done[rec["message_id"]] = rec
                tmp = out.with_suffix(".tmp")
                tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n"
                                       for r in done.values()), encoding="utf-8")
                tmp.replace(out)
            if n % 25 == 0 or not rec["ok"]:
                flag = "ok" if rec["ok"] else f"ERR {rec['error'][:50]}"
                print(f"  [{n}/{len(todo)}] {flag}", flush=True)
    return 0


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - h) / d, (c + h) / d)


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact binomial p for b vs c discordant pairs."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def model_stats(gold: list[dict], rows: dict[str, dict]) -> dict:
    support = Counter(g["gold"] for g in gold)
    correct = [rows.get(g["message_id"], {}).get("pred") == g["gold"] for g in gold]
    k = sum(correct)
    preds = Counter(rows[g["message_id"]]["pred"] for g in gold
                    if g["message_id"] in rows and rows[g["message_id"]]["pred"])
    per = {}
    for lab in LABELS:
        tp = sum(1 for g in gold if g["gold"] == lab
                 and rows.get(g["message_id"], {}).get("pred") == lab)
        prec = tp / preds[lab] if preds[lab] else None
        rec = tp / support[lab] if support[lab] else None
        f1 = (2 * prec * rec / (prec + rec)) if prec and rec else 0.0
        per[lab] = {"support": support[lab], "predicted": preds[lab], "tp": tp,
                    "precision": prec, "recall": rec, "f1": round(f1, 4),
                    "interpreted": support[lab] >= THIN}
    interp = [p["f1"] for p in per.values() if p["interpreted"]]
    got = [rows[g["message_id"]] for g in gold if g["message_id"] in rows]
    return {
        "n": len(gold), "answered": len(got), "correct": k,
        "accuracy": round(k / len(gold), 4),
        "accuracy_ci95": [round(x, 4) for x in wilson(k, len(gold))],
        "macro_f1_interpreted_classes": round(sum(interp) / len(interp), 4),
        "no_valid_label": sum(1 for r in got if r["pred"] is None),
        "call_errors": sum(1 for r in got if not r["ok"]),
        "model_mismatches": sum(1 for r in got if r["ok"] and r["model_answered"]
                                and r["model_answered"] != r["model"]),
        "cost_per_call_usd": round(sum(r["cost_usd"] or 0 for r in got) / max(len(got), 1), 5),
        "wall_s_per_call": round(sum(r["wall_s"] or 0 for r in got) / max(len(got), 1), 2),
        "per_class": per,
        "_correct": correct,
    }


def cmd_score(args) -> int:
    priv = Path(args.private_dir)
    gold = read_jsonl(Path(args.gold))
    stats = {}
    for m in args.models:
        rows = {r["message_id"]: r
                for r in read_jsonl(priv / f"{m.removeprefix('claude-')}.jsonl")}
        stats[m] = model_stats(gold, rows)
    summary = {
        "set": "300 production emails, labels from Opus (private; aggregates only)",
        "fields_seen": "subject, sender, first 1500 body characters",
        "calls": "one email per call, claude -p, contract as system prompt",
        "thin_class_threshold": THIN,
        "models": {m: {k: v for k, v in s.items() if not k.startswith("_")}
                   for m, s in stats.items()},
    }
    if len(args.models) == 2:
        a, b = args.models
        ca, cb = stats[a]["_correct"], stats[b]["_correct"]
        only_a = sum(1 for x, y in zip(ca, cb) if x and not y)
        only_b = sum(1 for x, y in zip(ca, cb) if y and not x)
        summary["paired"] = {"a": a, "b": b, "only_a_right": only_a, "only_b_right": only_b,
                             "mcnemar_exact_p": round(mcnemar_exact(only_a, only_b), 4)}
    out = HERE / "summary.json"
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    for m, s in summary["models"].items():
        lo, hi = s["accuracy_ci95"]
        print(f"{m}: {s['correct']}/{s['n']} = {s['accuracy']:.1%} [{lo:.1%}, {hi:.1%}]  "
              f"macroF1={s['macro_f1_interpreted_classes']:.3f}  invalid={s['no_valid_label']} "
              f"errors={s['call_errors']}  ${s['cost_per_call_usd']}/call")
    if "paired" in summary:
        print("paired:", summary["paired"])
    print(f"-> {out}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--gold", required=True)
    r.add_argument("--contract", required=True)
    r.add_argument("--private-dir", required=True)
    r.add_argument("--model", required=True)
    r.add_argument("--workers", type=int, default=5)
    r.add_argument("--retry-errors", action="store_true")
    r.add_argument("--limit", type=int, default=None, help="run at most N rows (smoke test)")
    s = sub.add_parser("score")
    s.add_argument("--gold", required=True)
    s.add_argument("--private-dir", required=True)
    s.add_argument("--models", nargs="+", required=True)
    args = ap.parse_args()
    return cmd_run(args) if args.cmd == "run" else cmd_score(args)


if __name__ == "__main__":
    sys.exit(main())
