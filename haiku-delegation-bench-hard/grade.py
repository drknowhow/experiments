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
from replies import first_int, is_not_found, is_null, norm, parse_reply, path_match  # noqa: E402

ITEMS = HERE / "fixtures" / "items.jsonl"
RAW = HERE / "results" / "raw"
SCORES = HERE / "results" / "scores.jsonl"

# Keys each grader needs in the reply's JSON object; a missing key is a format
# failure. navhop and thread need every field their gold names.
REQUIRED = {
    "join": ("answer",),
    "review": ("bugs",),
    "nearmiss": ("answer",),
}


def required(it: dict) -> tuple[str, ...]:
    if it["grader"] in ("navhop", "thread"):
        return tuple(it["gold"]["fields"])
    return REQUIRED.get(it["grader"], ())


# --- value normalizers -----------------------------------------------------

_SPLIT = re.compile(r"[\s,;\[\]'\"]+")
_TOKEN = re.compile(r"[a-z0-9]+(?:[.'][a-z0-9]+)*")


def as_set(v, dotted: bool = False) -> set[str]:
    """A list, or a string of items split on commas, spaces and brackets."""
    raw = [norm(x) for x in v if not is_null(x)] if isinstance(v, list) else _SPLIT.split(norm(v))
    out = {x.strip("'\"`") for x in raw}
    out.discard("")
    if dotted:  # file extensions: ".cs" and "cs" name the same thing
        out = {x if x.startswith(".") else "." + x for x in out}
    return out


def number(v) -> float | None:
    """The first number in a value: "$38,700" -> 38700.0, "99.8%" -> 99.8."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"-?\d[\d,]*(?:\.\d+)?|-?\.\d+", "" if v is None else str(v))
    return float(m.group().replace(",", "")) if m else None


def date(v) -> str | None:
    m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", "" if v is None else str(v))
    return f"{int(m[1]):04d}-{int(m[2]):02d}-{int(m[3]):02d}" if m else None


def clock(v) -> str | None:
    """24-hour HH:MM from "15:00", "15:00:00", "3pm" or "3:00 p.m."."""
    m = re.search(r"(?<!\d)(\d{1,2})(?::(\d{2}))?(?::\d{2})?\s*([ap])?\.?\s*(?:m\b\.?)?",
                  norm(v))
    if not m or (m[2] is None and m[3] is None):
        return None
    h, mins = int(m[1]), int(m[2] or 0)
    if m[3] == "p" and h < 12:
        h += 12
    if m[3] == "a" and h == 12:
        h = 0
    return f"{h:02d}:{mins:02d}" if h < 24 and mins < 60 else None


def boolean(v) -> bool | None:
    if isinstance(v, bool):
        return v
    s = norm(v).strip(".")
    return {"true": True, "yes": True, "false": False, "no": False}.get(s)


def tokens(v) -> set[str]:
    return set(_TOKEN.findall(norm(v)))


def text_ok(got, gold: str, others: list[str]) -> bool:
    """The reply holds the words that tell the gold value apart from the
    superseded ones, and none of the superseded values' own words: "D" and
    "Room D" both match "Room D" when the thread also proposed "Room B"."""
    if is_null(got):
        return False
    got_t, gold_t = tokens(got), tokens(gold)
    other_t = set().union(*(tokens(o) for o in others)) if others else set()
    key = (gold_t - other_t) or gold_t
    if not key <= got_t:
        return False
    return not any((tokens(o) - gold_t) and (tokens(o) - gold_t) <= got_t for o in others)


def contains_word(got, want: str) -> bool:
    return bool(re.search(rf"(?<![\w]){re.escape(want.lower())}(?![\w])", norm(got)))


# --- graders ---------------------------------------------------------------
# Each returns (score, notes) where notes may set invention / over_abstain.

def g_join(it, obj):
    gold, ans = it["gold"], obj["answer"]
    if isinstance(gold, int):
        ok = first_int(ans) == gold
    elif "set" in gold:
        ok = as_set(ans) == {norm(x) for x in gold["set"]}
    else:  # one id: the reply names it and no other id of the same shape
        ok = set(re.findall(gold["pattern"], norm(ans))) == {gold["id"]}
    return float(ok), {"got": ans}


def _nav_field(kind: str, got, want, file_ok: bool) -> bool:
    if kind == "int":
        return first_int(got) == want
    if kind == "str":
        return not is_null(got) and contains_word(got, want)
    if kind == "path":
        return path_match(got, want)
    if kind == "line":
        # A line number names a place only within its file.
        line = first_int(got)
        return file_ok and line is not None and abs(line - want) <= 2
    if kind == "set":
        return as_set(got, dotted=all(w.startswith(".") for w in want)) == set(want)
    if kind == "bool":
        return boolean(got) is want
    raise KeyError(kind)


def g_navhop(it, obj):
    fields = it["gold"]["fields"]
    main = next(iter(fields))
    if not it["answerable"]:
        if is_not_found(obj[main]):
            return 1.0, {}
        return 0.0, {"invention": True, "got": {k: obj.get(k) for k in fields}}
    path_keys = [k for k, f in fields.items() if f["kind"] == "path"]
    file_ok = all(path_match(obj.get(k), fields[k]["value"]) for k in path_keys)
    wrong = [k for k, f in fields.items() if not _nav_field(f["kind"], obj.get(k), f["value"], file_ok)]
    notes = {"wrong": wrong, "got": {k: obj.get(k) for k in wrong}}
    if is_not_found(obj[main]):
        notes["over_abstain"] = True
    return (len(fields) - len(wrong)) / len(fields), notes


def _thread_field(kind: str, got, want, others) -> bool:
    if kind == "date":
        return date(got) == want
    if kind == "time":
        return clock(got) == want
    if kind in ("int", "money", "number"):
        n = number(got)
        return n is not None and abs(n - want) < 1e-6
    if kind == "bool":
        return boolean(got) is want
    if kind == "text":
        return text_ok(got, want, others)
    raise KeyError(kind)


def g_thread(it, obj):
    right, invented, wrong = 0, [], []
    fields = it["gold"]["fields"]
    for key, f in fields.items():
        got = obj.get(key)
        if f["value"] is None:
            if is_null(got):
                right += 1
            else:
                invented.append(key)
        elif not is_null(got) and _thread_field(f["kind"], got, f["value"], f["others"]):
            right += 1
        else:
            wrong.append(key)
    got = {k: obj.get(k) for k in invented + wrong}
    return right / len(fields), {"invention": bool(invented), "invented": invented, "wrong": wrong,
                                 "got": got}


def g_nearmiss(it, obj):
    ans = obj["answer"]
    if it["answerable"]:
        if is_not_found(ans):
            return 0.0, {"over_abstain": True, "got": ans}
        return float(bool(re.search(it["gold"], norm(ans)))), {"got": ans}
    if is_not_found(ans):
        return 1.0, {}
    return 0.0, {"invention": True, "got": ans}


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


GRADERS = {"join": g_join, "navhop": g_navhop, "thread": g_thread, "nearmiss": g_nearmiss,
           "review": g_review}


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
        need = required(it)
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
    if kind == "join":
        if isinstance(g, int):
            return {"answer": g}
        return {"answer": g["set"] if "set" in g else g["id"]}
    if kind == "navhop":
        if not it["answerable"]:
            main = next(iter(g["fields"]))
            return {k: ("NOT_FOUND" if k == main else None) for k in g["fields"]}
        return {k: f["value"] for k, f in g["fields"].items()}
    if kind == "thread":
        return {k: f["value"] for k, f in g["fields"].items()}
    if kind == "nearmiss":
        return {"answer": it["surface"] if it["answerable"] else "NOT_FOUND"}
    if kind == "review":
        return {"bugs": [{"line": ln, "why": "x"} for ln in g["lines"]]}
    raise KeyError(kind)


def _restyled(it: dict) -> dict:
    """The perfect thread reply written the way a person might: "$38,700",
    "3:00 PM", "yes", lower case. Normalization must still score it 1."""
    out = {}
    for k, f in it["gold"]["fields"].items():
        v = f["value"]
        if v is None:
            out[k] = None
        elif f["kind"] == "money":
            out[k] = f"${v:,}"
        elif f["kind"] == "time":
            h, m = map(int, v.split(":"))
            out[k] = f"{(h - 1) % 12 + 1}:{m:02d} {'PM' if h >= 12 else 'AM'}"
        elif f["kind"] == "bool":
            out[k] = "yes" if v else "no"
        elif f["kind"] == "int":
            out[k] = f"{v:,}"
        elif f["kind"] == "number":
            out[k] = f"{v}%"
        else:
            out[k] = str(v).lower()
    return out


def _wrong(it: dict) -> dict:
    g = it["gold"]
    kind = it["grader"]
    if kind == "join":
        if isinstance(g, int):
            return {"answer": g + 1}
        if "set" in g:
            return {"answer": g["set"][:-1]}
        return {"answer": g["id"] + "x"}
    if kind == "navhop":
        if not it["answerable"]:
            return {k: 7 for k in g["fields"]}
        bad = {"int": lambda v: v + 1, "str": lambda v: "zzz_none", "path": lambda v: "nope.py",
               "line": lambda v: v + 50, "set": lambda v: v[:-1], "bool": lambda v: not v}
        return {k: bad[f["kind"]](f["value"]) for k, f in g["fields"].items()}
    if kind == "thread":
        out = {}
        for k, f in g["fields"].items():
            if f["others"]:
                out[k] = f["others"][0]
            elif f["kind"] == "date":
                out[k] = "1999-01-01"
            elif f["kind"] == "text":
                out[k] = "zzz"
            else:
                out[k] = 12345
        return out
    if kind == "nearmiss":
        return {"answer": it["distractors"][0] if it["answerable"] else it["near_miss"][0]}
    if kind == "review":
        return {"bugs": [] if g["lines"] else [{"line": 1, "why": "x"}]}
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

    # Parser and normalizer cases.
    check(parse_reply('text {"a": 1} more {"b": {"c": 2}} end') == {"b": {"c": 2}}, "parse: last object")
    check(parse_reply('```json\n{"a": "}"}\n```') == {"a": "}"}, "parse: brace inside a string")
    check(parse_reply("no json here") is None, "parse: none")
    check(parse_reply('```json\n{"a": 1}\n```\n```json\n{"a": 2}\n```') == {"a": 2}, "parse: last fence")
    for raw, want in [("15:00", "15:00"), ("3pm", "15:00"), ("3:00 p.m.", "15:00"), ("12:30 am", "00:30"),
                      ("09:30:00", "09:30"), ("10", None), ("noon", None)]:
        check(clock(raw) == want, f"clock({raw!r}) = {clock(raw)!r}, want {want!r}")
    for raw, want in [("$38,700", 38700.0), ("$0.14 per word", 0.14), ("99.8%", 99.8), (".5", 0.5),
                      (7, 7.0), (True, None), ("none", None)]:
        check(number(raw) == want, f"number({raw!r}) = {number(raw)!r}, want {want!r}")
    check(date("2026/11/7") == "2026-11-07" and date("Nov 7") is None, "date normalizer")
    check(as_set("cs, .rb htm", dotted=True) == {".cs", ".rb", ".htm"}, "as_set dotted")
    check(text_ok("D", "Room D", ["Room B"]) and text_ok("room d", "Room D", ["Room B"]),
          "text: distinguishing word matches")
    check(not text_ok("Room B", "Room D", ["Room B"]) and not text_ok("PDF, not DOCX", "PDF", ["DOCX"]),
          "text: superseded value rejected")
    check(text_ok("Saffron and Salt", "Saffron & Salt", []), "text: no others")

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
        r = ok({"call": {"ok": False, "text": "", "error": "timeout after 120s"}})
        check(r["score"] == 0.0 and r["call_error"], f"{it['id']}: failed call not scored 0")
        need = required(it)
        if len(need) > 1:
            partial = {k: v for k, v in _perfect(it).items() if k != need[-1]}
            r = ok({"call": {"ok": True, "text": _reply(partial)}})
            check(r["format_failure"], f"{it['id']}: reply missing {need[-1]!r} not a format failure")

        if it["grader"] == "thread":
            r = ok({"call": {"ok": True, "text": _reply(_restyled(it))}})
            check(r["score"] == 1.0, f"{it['id']}: restyled perfect reply scored {r['score']} {r['notes']}")
            for k, f in it["gold"]["fields"].items():
                for other in f["others"]:
                    obj = {**_perfect(it), k: other}
                    r = ok({"call": {"ok": True, "text": _reply(obj)}})
                    check(r["score"] < 1.0, f"{it['id']}: superseded {k}={other!r} scored {r['score']}")
            if it["null_fields"]:
                check(ok({"call": {"ok": True, "text": _reply(_wrong(it))}})["invention"],
                      f"{it['id']}: filled null field not an invention")
        if it["grader"] == "join" and isinstance(it["gold"], dict) and "id" in it["gold"]:
            other = "u_zed" if it["gold"]["id"].startswith("u_") else "t-zed"
            r = ok({"call": {"ok": True, "text": _reply({"answer": f"{it['gold']['id']} or {other}"})}})
            check(r["score"] == 0.0, f"{it['id']}: two candidate ids scored {r['score']}")
        if it["grader"] == "nearmiss" and it["answerable"]:
            for d in it["distractors"]:
                r = ok({"call": {"ok": True, "text": _reply({"answer": d})}})
                check(r["score"] == 0.0, f"{it['id']}: distractor {d!r} scored {r['score']}")
            check(ok({"call": {"ok": True, "text": _reply({"answer": "NOT_FOUND"})}})["over_abstain"],
                  f"{it['id']}: over-abstain flag")
        if it["grader"] in ("nearmiss", "navhop") and not it["answerable"]:
            r = ok({"call": {"ok": True, "text": _reply(_wrong(it))}})
            check(r["invention"] and r["score"] == 0.0, f"{it['id']}: invention flag")
        if it["grader"] == "navhop" and it["answerable"]:
            main = next(iter(it["gold"]["fields"]))
            obj = {k: (None if k != main else "NOT_FOUND") for k in it["gold"]["fields"]}
            check(ok({"call": {"ok": True, "text": _reply(obj)}})["over_abstain"],
                  f"{it['id']}: navhop over-abstain flag")
            obj = {**_perfect(it)}
            for k, f in it["gold"]["fields"].items():
                if f["kind"] == "path":
                    obj[k] = "nope.py"
            r = ok({"call": {"ok": True, "text": _reply(obj)}})
            check("line" not in [it["gold"]["fields"][k]["kind"] for k in it["gold"]["fields"]
                                 if k not in r["notes"]["wrong"]],
                  f"{it['id']}: a line in the wrong file counted")

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
