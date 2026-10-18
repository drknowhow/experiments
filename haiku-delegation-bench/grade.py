"""Score model replies against fixtures/items.jsonl. Deterministic: no model judges.

    python grade.py --self-test            # must pass before any model is run
    python grade.py                        # grade results/raw/*.jsonl -> results/scores.jsonl

Scoring follows DESIGN.md "Answer contract and scoring". Each graded row says
what was wrong, so a reader can audit any score without rerunning anything.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "_lib"))

from hidden_tests import run_hidden_tests  # noqa: E402
from replies import (first_int, is_not_found, is_null, jaccard, norm, norm_path,  # noqa: E402
                     parse_reply, path_match)

ITEMS = HERE / "fixtures" / "items.jsonl"
RAW = HERE / "results" / "raw"
SCORES = HERE / "results" / "scores.jsonl"

# Keys each grader needs in the reply's JSON object; a missing key is a format failure.
REQUIRED = {
    "label": ("label",),
    "abstain": ("answer",),
    "answer_exact": ("answer",),
    "diff_summary": ("files_changed", "change_type", "summary"),
    "traceback": ("exception", "root_cause_file", "root_cause_line"),
    "review": ("bugs",),
    "nav": ("answer", "file", "line"),
}

# --- graders ---------------------------------------------------------------
# Each returns (score, notes) where notes may set invention / over_abstain.

def g_label(it, obj):
    ok = norm(obj["label"]).strip("'\".") == norm(it["gold"])
    return float(ok), {"got": obj["label"]}


def _field_ok(key: str, got, gold) -> bool:
    if isinstance(gold, dict) and "contains" in gold:
        return not is_null(got) and gold["contains"] in norm(got)
    if isinstance(gold, int):
        return first_int(got) == gold
    if key == "phone":
        digits = re.sub(r"\D", "", str(got))
        return digits in (gold, "1" + gold)
    g, r = norm(gold), norm(got)
    if re.fullmatch(r"\d{2}:\d{2}", g):          # times: allow a trailing :00
        r = re.sub(r"^(\d{2}:\d{2}):00$", r"\1", r)
    return r == g


def g_fields(it, obj):
    gold = it["gold"]
    right, invented, wrong = 0, [], []
    for key, g in gold.items():
        got = obj.get(key)
        if g is None:
            if is_null(got):
                right += 1
            else:
                invented.append(key)
        elif _field_ok(key, got, g):
            right += 1
        else:
            wrong.append(key)
    return right / len(gold), {"invention": bool(invented), "invented": invented, "wrong": wrong}


def g_abstain(it, obj):
    ans = obj["answer"]
    if it["answerable"]:
        if is_not_found(ans):
            return 0.0, {"over_abstain": True, "got": ans}
        return float(bool(re.search(it["gold"], norm(ans)))), {"got": ans}
    if is_not_found(ans):
        return 1.0, {}
    return 0.0, {"invention": True, "got": ans}


def g_diff(it, obj):
    gold = it["gold"]
    files = obj["files_changed"]
    files = [files] if isinstance(files, str) else list(files or [])
    got = {norm_path(f) for f in files if not is_null(f)}
    want = {norm_path(f) for f in gold["files"]}
    # A reply path that ends with a gold path counts as that gold path.
    got = {next((w for w in want if g == w or g.endswith("/" + w)), g) for g in got}
    fj = jaccard(got, want)
    ct = float(norm(obj["change_type"]).strip("():!") == gold["change_type"])
    summary = norm(obj["summary"])
    kw = sum(any(k in summary for k in grp) for grp in gold["keywords"]) / len(gold["keywords"])
    return 0.4 * fj + 0.3 * ct + 0.3 * kw, {"files_jaccard": round(fj, 3), "type_ok": bool(ct),
                                            "keywords": round(kw, 3)}


def _norm_line(s) -> str:
    return norm(s).replace('"', "'")


def g_answer_exact(it, obj):
    gold, ans = it["gold"], obj["answer"]
    if isinstance(gold, int):
        ok = first_int(ans) == gold
    elif isinstance(gold, dict) and "contains" in gold:
        ok = not is_null(ans) and gold["contains"] in norm(ans)
    elif isinstance(gold, dict) and "set" in gold:
        if isinstance(ans, list):
            got = {norm(x) for x in ans}
        else:
            got = {t for t in re.split(r"[\s,;\[\]'\"]+", norm(ans)) if t}
        ok = got == {norm(x) for x in gold["set"]}
    else:
        ok = _norm_line(ans) == _norm_line(gold)
    return float(ok), {"got": ans}


def g_traceback(it, obj):
    gold = it["gold"]
    exc = float(bool(re.search(rf"\b{re.escape(gold['exception'].lower())}\b", norm(obj["exception"]))))
    f = float(path_match(obj["root_cause_file"], gold["file"]))
    line = first_int(obj["root_cause_line"])
    ln = float(f > 0 and line is not None and any(abs(line - g) <= 1 for g in gold["lines"]))
    return 0.25 * exc + 0.25 * f + 0.5 * ln, {"exception_ok": bool(exc), "file_ok": bool(f),
                                              "line_ok": bool(ln), "got_line": line}


def g_review(it, obj):
    gold = it["gold"]["lines"]
    bugs = obj["bugs"] if isinstance(obj["bugs"], list) else []
    lines = [first_int(b.get("line")) if isinstance(b, dict) else first_int(b) for b in bugs]
    hit = [ln for ln in lines if ln is not None and any(abs(ln - g) <= 2 for g in gold)]
    fps = len(lines) - len(hit)
    if not gold:
        return float(not lines), {"false_positives": fps}
    if not hit:
        return 0.0, {"found": False, "false_positives": fps}
    return (1.0 if fps == 0 else 0.5), {"found": True, "false_positives": fps}


def g_nav(it, obj):
    gold = it["gold"]
    ans = obj["answer"]
    if not it["answerable"]:
        if is_not_found(ans):
            return 1.0, {}
        return 0.0, {"invention": True, "got": ans}
    if is_not_found(ans) and is_null(obj.get("file")):
        return 0.0, {"over_abstain": True}
    notes = {"got": ans, "got_file": obj.get("file"), "got_line": obj.get("line")}
    ok = True
    if gold.get("answer_set") is not None:
        got = ({norm(x) for x in ans} if isinstance(ans, list)
               else set(re.findall(r"[a-z]+", norm(ans))))
        ok = got == set(gold["answer_set"])
    elif gold.get("answer") is not None:
        ok = bool(re.search(rf"(?<![\w]){re.escape(gold['answer'].lower())}(?![\w])", norm(ans)))
    if gold.get("file"):
        ok = ok and path_match(obj.get("file"), gold["file"])
    if gold.get("line"):
        line = first_int(obj.get("line"))
        ok = ok and line is not None and abs(line - gold["line"]) <= 2
    return float(ok), notes


def g_edit(it, rec):
    after = rec.get("after")
    if after is None:
        return 0.0, {"error": "no after-snapshot"}
    ws = it["workspace"]
    changed = sorted(p for p in set(ws) | set(after) if ws.get(p) != after.get(p))
    out_of_set = [p for p in changed if p not in it["write_paths"]]
    protected = [p for p in changed if p in it["gold"]["protected"]]
    passed, log = run_hidden_tests(after, it["hidden_tests"])
    report = norm((rec.get("call") or {}).get("text", ""))
    missing = [m for m in it["gold"]["must_mention"] if m.lower() not in report]
    if not passed:
        score = 0.0
    elif out_of_set or missing:
        score = 0.5
    else:
        score = 1.0
    return score, {"tests_pass": passed, "changed": changed, "out_of_set": out_of_set,
                   "protected_touched": protected, "missing_mentions": missing,
                   "test_log": "" if passed else log[-600:]}


GRADERS = {"label": g_label, "fields": g_fields, "abstain": g_abstain, "diff_summary": g_diff,
           "answer_exact": g_answer_exact, "traceback": g_traceback, "review": g_review,
           "nav": g_nav}


def grade(it: dict, rec: dict) -> dict:
    """Score one raw record: {"call": {...Call...}, "after": {...} for workers}."""
    out = {"score": 0.0, "format_failure": False, "invention": False, "over_abstain": False,
           "call_error": "", "notes": {}}
    call = rec.get("call") or {}
    if not call.get("ok"):
        out["call_error"] = call.get("error") or "call failed"
    if it["grader"] == "edit":
        score, notes = g_edit(it, rec)
    else:
        obj = parse_reply(call.get("text", ""))
        need = REQUIRED.get(it["grader"], tuple(it["gold"]) if it["grader"] == "fields" else ())
        if obj is None or any(k not in obj for k in need):
            out["format_failure"] = True
            out["notes"] = {"missing": [] if obj is None else [k for k in need if k not in obj],
                            "no_json": obj is None}
            return out
        score, notes = GRADERS[it["grader"]](it, obj)
    out["score"] = round(float(score), 4)
    out["invention"] = bool(notes.pop("invention", False))
    out["over_abstain"] = bool(notes.pop("over_abstain", False))
    out["notes"] = notes
    return out


# --- self-test -------------------------------------------------------------

def _perfect(it: dict) -> dict:
    g = it["gold"]
    kind = it["grader"]
    if kind == "label":
        return {"label": g}
    if kind == "fields":
        return {k: (None if v is None else v["contains"] if isinstance(v, dict) else v)
                for k, v in g.items()}
    if kind == "abstain":
        return {"answer": re.sub(r"\\b", "", g) if it["answerable"] else "NOT_FOUND"}
    if kind == "diff_summary":
        return {"files_changed": g["files"], "change_type": g["change_type"],
                "summary": " ".join(grp[0] for grp in g["keywords"])}
    if kind == "answer_exact":
        if isinstance(g, dict):
            return {"answer": g["contains"] if "contains" in g else g["set"]}
        return {"answer": g}
    if kind == "traceback":
        return {"exception": g["exception"], "root_cause_file": g["file"],
                "root_cause_line": g["lines"][0], "fix": "x"}
    if kind == "review":
        return {"bugs": [{"line": ln, "why": "x"} for ln in g["lines"]]}
    if kind == "nav":
        ans = ", ".join(g["answer_set"]) if g.get("answer_set") else (g["answer"] or "found")
        return {"answer": ans, "file": g["file"], "line": g["line"]}
    raise KeyError(kind)


def _wrong(it: dict) -> dict:
    g = it["gold"]
    kind = it["grader"]
    if kind == "label":
        return {"label": "newsletter" if g != "newsletter" else "billing"}
    if kind == "fields":
        return {k: "WRONG" for k in g}
    if kind == "abstain":
        return {"answer": "NOT_FOUND" if it["answerable"] else "42"}
    if kind == "diff_summary":
        return {"files_changed": ["nope.py"], "change_type": "feat" if g["change_type"] != "feat" else "fix",
                "summary": ""}
    if kind == "answer_exact":
        if isinstance(g, int):
            return {"answer": g + 1}
        if isinstance(g, dict):
            return {"answer": "zzz" if "contains" in g else g["set"][:-1]}
        return {"answer": g + " x"}
    if kind == "traceback":
        return {"exception": "ValueError", "root_cause_file": "nope.py", "root_cause_line": 999}
    if kind == "review":
        return {"bugs": [] if g["lines"] else [{"line": 1, "why": "x"}]}
    if kind == "nav":
        if not it["answerable"]:
            return {"answer": "foo", "file": "x.py", "line": 1}
        return {"answer": "NOT_FOUND", "file": None, "line": None}
    raise KeyError(kind)


def _reply(obj: dict) -> str:
    """Wrap an answer object the way a model might: prose, a decoy fence, then the answer."""
    return ("Looking at this.\n\n```python\nx = {'not': 'the answer'}\n```\n\n"
            f"So the answer is:\n\n```json\n{json.dumps(obj, indent=2)}\n```\n")


def self_test(items: list[dict]) -> int:
    fails = []

    def check(cond, msg):
        if not cond:
            fails.append(msg)

    # Parser cases.
    check(parse_reply('text {"a": 1} more {"b": {"c": 2}} end') == {"b": {"c": 2}}, "parse: last object")
    check(parse_reply('```json\n{"a": "}"}\n```') == {"a": "}"}, "parse: brace inside a string")
    check(parse_reply("no json here") is None, "parse: none")
    check(parse_reply('```json\n{"a": 1}\n```\n```json\n{"a": 2}\n```') == {"a": 2}, "parse: last fence")

    for it in items:
        ok = lambda rec: grade(it, rec)  # noqa: E731
        if it["grader"] == "edit":
            solved = {**it["workspace"], **it["solution"]}
            mention = " ".join(it["gold"]["must_mention"])
            r = ok({"call": {"ok": True, "text": f"Done. {mention}"}, "after": solved})
            check(r["score"] == 1.0, f"{it['id']}: solution scored {r['score']} {r['notes']}")
            r = ok({"call": {"ok": True, "text": "Done."}, "after": dict(it["workspace"])})
            check(r["score"] == 0.0, f"{it['id']}: bare workspace scored {r['score']}")
            stray = {**solved, "stray_note.txt": "out of set\n"}
            r = ok({"call": {"ok": True, "text": f"Done. {mention}"}, "after": stray})
            check(r["score"] == 0.5, f"{it['id']}: out-of-set edit scored {r['score']}")
            if it["gold"]["must_mention"]:
                r = ok({"call": {"ok": True, "text": "Done."}, "after": solved})
                check(r["score"] == 0.5, f"{it['id']}: silent on the trap scored {r['score']}")
            continue
        r = ok({"call": {"ok": True, "text": _reply(_perfect(it))}})
        check(r["score"] == 1.0 and not r["format_failure"],
              f"{it['id']}: perfect reply scored {r['score']} {r['notes']}")
        r = ok({"call": {"ok": True, "text": _reply(_wrong(it))}})
        check(r["score"] < 1.0, f"{it['id']}: wrong reply scored {r['score']} {r['notes']}")
        r = ok({"call": {"ok": True, "text": "I could not work this out."}})
        check(r["format_failure"] and r["score"] == 0.0, f"{it['id']}: no-JSON reply not a format failure")
        r = ok({"call": {"ok": False, "text": "", "error": "timeout after 600s"}})
        check(r["score"] == 0.0 and r["call_error"], f"{it['id']}: failed call not scored 0")

    # Invention and over-abstain flags fire where they should.
    for it in items:
        if it["grader"] == "abstain" and not it["answerable"]:
            check(grade(it, {"call": {"ok": True, "text": _reply({"answer": "42"})}})["invention"],
                  f"{it['id']}: invention flag")
        if it["grader"] == "abstain" and it["answerable"]:
            check(grade(it, {"call": {"ok": True, "text": _reply({"answer": "NOT_FOUND"})}})["over_abstain"],
                  f"{it['id']}: over-abstain flag")
        if it["grader"] == "fields" and it.get("nulls"):
            check(grade(it, {"call": {"ok": True, "text": _reply(_wrong(it))}})["invention"],
                  f"{it['id']}: field invention flag")

    n = len(items)
    if fails:
        print(f"SELF-TEST FAILED ({len(fails)} problems over {n} items):")
        for f in fails:
            print("  -", f)
        return 1
    print(f"self-test passed: {n} items, perfect=1 and wrong<1 for each; edit fixtures checked")
    return 0


# --- batch grading ---------------------------------------------------------

def load_items() -> dict[str, dict]:
    return {it["id"]: it for it in map(json.loads, ITEMS.read_text(encoding="utf-8").splitlines())}


def grade_all(raw_files: list[Path], out: Path) -> int:
    items = load_items()
    rows = []
    for path in raw_files:
        for line in path.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            it = items[rec["id"]]
            g = grade(it, rec)
            call = rec.get("call") or {}
            rows.append({"id": rec["id"], "category": it["category"], "mode": it["mode"],
                         "tags": it["tags"], "model": rec["model"], "rep": rec["rep"],
                         "arm": rec.get("arm", "default"), **g,
                         **{k: call.get(k) for k in ("cost_usd", "input_tokens", "output_tokens",
                                                     "thinking_tokens", "num_turns", "duration_ms",
                                                     "wall_s", "model_answered")}})
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"graded {len(rows)} records from {len(raw_files)} files -> {out.relative_to(HERE)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("raw", nargs="*", type=Path, help="raw result files (default: results/raw/*.jsonl)")
    args = ap.parse_args()
    if args.self_test:
        return self_test(list(load_items().values()))
    files = args.raw or sorted(RAW.glob("*.jsonl"))
    return grade_all(files, SCORES)


if __name__ == "__main__":
    sys.exit(main())
