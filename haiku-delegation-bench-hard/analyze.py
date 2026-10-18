"""Summarize results/scores.jsonl into tables, figures and the hypothesis checks.

    python grade.py      # results/raw/*.jsonl -> results/scores.jsonl
    python analyze.py    # -> results/summary.json, results/tables.md, figures/*.png

The pilot (rep 0) lives in results/pilot/ and never reaches scores.jsonl.
"""
from __future__ import annotations

import json
import math
import random
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCORES = HERE / "results" / "scores.jsonl"
ITEMS = HERE / "fixtures" / "items.jsonl"
SUMMARY = HERE / "results" / "summary.json"
TABLES = HERE / "results" / "tables.md"
FIGS = HERE / "figures"

CATEGORIES = ["log-join", "nav-multihop", "review-subtle", "edit-multifile",
              "thread-supersede", "abstain-nearmiss"]
STATEFUL = ["thread-supersede", "log-join"]   # DESIGN.md H4
AGENTIC = {"scout", "worker"}
MODES = ["single", "scout", "worker"]

SUBJECTS = [
    ("claude-haiku-5-5", "Haiku 5.5"),
    ("claude-sonnet-5-5", "Sonnet 5.5"),
    ("claude-opus-5-5", "Opus 5.5"),
]
HAIKU, SONNET, OPUS = (s[0] for s in SUBJECTS)
COLORS = {HAIKU: "#2a9d8f", SONNET: "#e76f51", OPUS: "#264653"}

# Routing rule (METHODS.md, unchanged from the first benchmark): Haiku when it
# keeps 95% of Sonnet's score and invents no more often; Haiku with a check
# between 85% and 95% (or at 95%+ with more inventions); Sonnet below 85%.
ROUTE_HAIKU, ROUTE_CHECK = 0.95, 0.85
BOOT_N, BOOT_SEED = 10_000, 20261017
Z95 = 1.959963984540054


def mean(xs) -> float | None:
    xs = list(xs)
    return sum(xs) / len(xs) if xs else None


def label(model: str) -> str:
    return next(s[1] for s in SUBJECTS if s[0] == model)


def wilson(k: int, n: int) -> tuple[float | None, float | None]:
    """Wilson 95% interval for k successes in n trials."""
    if n == 0:
        return None, None
    p = k / n
    denom = 1 + Z95 ** 2 / n
    centre = (p + Z95 ** 2 / (2 * n)) / denom
    half = Z95 * math.sqrt(p * (1 - p) / n + Z95 ** 2 / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def mcnemar_exact(b: int, c: int) -> float:
    """Exact two-sided McNemar p-value from the discordant counts b and c."""
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(min(b, c) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


# --- per-subject statistics ----------------------------------------------------

def opportunities(items: dict[str, dict]) -> tuple[set, set]:
    """Item ids where a model can invent, and where it can over-abstain (DESIGN.md H5)."""
    invent, abstain = set(), set()
    for i, it in items.items():
        if it["category"] == "thread-supersede":
            if any(f["value"] is None for f in it["gold"]["fields"].values()):
                invent.add(i)
        elif it["category"] in ("nav-multihop", "abstain-nearmiss"):
            (abstain if it["answerable"] else invent).add(i)
    return invent, abstain


def passes(scores: list[float]) -> bool:
    """DESIGN.md: a model passes an item when it scores 1.0 on two of three reps
    (one rep for Opus, which runs once)."""
    return sum(s == 1.0 for s in scores) >= (1 if len(scores) == 1 else 2)


def subject_stats(rows: list[dict], items: dict[str, dict]) -> dict:
    reps = sorted({r["rep"] for r in rows})
    inv_ids, abs_ids = opportunities(items)
    cat_rep = defaultdict(list)
    for r in rows:
        cat_rep[(r["category"], r["rep"])].append(r["score"])

    cats = {}
    for c in CATEGORIES:
        cr = [r for r in rows if r["category"] == c]
        if not cr:
            continue
        rep_means = [mean(cat_rep[(c, k)]) for k in reps if cat_rep[(c, k)]]
        cats[c] = {
            "n_items": len({r["id"] for r in cr}),
            "mean": mean(rep_means), "rep_means": rep_means,
            "min": min(rep_means), "max": max(rep_means),
            "cost_per_call": mean(r["cost_usd"] or 0 for r in cr),
            "wall_s": mean(r["wall_s"] or 0 for r in cr),
            "turns": mean(r["num_turns"] or 0 for r in cr),
            "thinking_tokens": mean(r["thinking_tokens"] or 0 for r in cr),
            "format_failures": sum(r["format_failure"] for r in cr),
            "call_errors": sum(bool(r["call_error"]) for r in cr),
            "inventions": sum(r["invention"] for r in cr if r["id"] in inv_ids),
            "invention_chances": sum(r["id"] in inv_ids for r in cr),
            "over_abstains": sum(r["over_abstain"] for r in cr if r["id"] in abs_ids),
        }

    per_rep = []
    for k in reps:
        rr = [r for r in rows if r["rep"] == k]
        per_rep.append({
            "rep": k, "n": len(rr),
            "macro": mean(mean(cat_rep[(c, k)]) for c in cats if cat_rep[(c, k)]),
            "micro": mean(r["score"] for r in rr),
            "cost_usd": sum(r["cost_usd"] or 0 for r in rr),
            "wall_s_sum": sum(r["wall_s"] or 0 for r in rr),
        })

    by_item = defaultdict(list)
    for r in sorted(rows, key=lambda r: r["rep"]):
        by_item[r["id"]].append(r["score"])
    agree = (mean(len(set(v)) == 1 for v in by_item.values()) if len(reps) > 1 else None)
    inv_rows = [r for r in rows if r["id"] in inv_ids]
    abs_rows = [r for r in rows if r["id"] in abs_ids]
    n_inv, n_abs = sum(r["invention"] for r in inv_rows), sum(r["over_abstain"] for r in abs_rows)
    item_pass = {i: passes(v) for i, v in by_item.items()}
    n_pass = sum(item_pass.values())
    mode_cost = {m: mean(r["cost_usd"] or 0 for r in rows if r["mode"] == m) for m in MODES}
    return {
        "reps": reps, "n_rows": len(rows), "categories": cats, "per_rep": per_rep,
        "macro": mean(p["macro"] for p in per_rep),
        "macro_min": min(p["macro"] for p in per_rep),
        "macro_max": max(p["macro"] for p in per_rep),
        "micro": mean(p["micro"] for p in per_rep),
        "cost_per_run": mean(p["cost_usd"] for p in per_rep),
        "cost_per_call": mean(r["cost_usd"] or 0 for r in rows),
        "cost_per_call_by_mode": mode_cost,
        "input_tokens": mean(r["input_tokens"] or 0 for r in rows),
        "output_tokens": mean(r["output_tokens"] or 0 for r in rows),
        "thinking_tokens": mean(r["thinking_tokens"] or 0 for r in rows),
        "wall_s": mean(r["wall_s"] or 0 for r in rows),
        "format_failures": sum(r["format_failure"] for r in rows),
        "call_errors": sorted({f"{r['id']} r{r['rep']}: {r['call_error'][:60]}"
                               for r in rows if r["call_error"]}),
        "invention_rate": n_inv / len(inv_rows) if inv_rows else None,
        "invention_ci": wilson(n_inv, len(inv_rows)),
        "inventions": n_inv, "invention_chances": len(inv_rows),
        "invented_items": sorted({r["id"] for r in inv_rows if r["invention"]}),
        "over_abstain_rate": n_abs / len(abs_rows) if abs_rows else None,
        "over_abstain_ci": wilson(n_abs, len(abs_rows)),
        "over_abstains": n_abs, "abstain_chances": len(abs_rows),
        "pass_rate": n_pass / len(item_pass), "pass_ci": wilson(n_pass, len(item_pass)),
        "passed": n_pass, "n_items": len(item_pass),
        "rep_agreement": agree,
        "agentic_turns": mean(r["num_turns"] or 0 for r in rows if r["mode"] in AGENTIC),
        "model_mismatches": sorted({f"{r['id']} r{r['rep']}: {r['model_answered']}" for r in rows
                                    if r["model_answered"] and r["model_answered"] != r["model"]}),
        "item_means": {i: mean(v) for i, v in by_item.items()},
        "item_pass": item_pass,
    }


# --- Haiku vs Sonnet -----------------------------------------------------------

def paired_gap(a: dict, b: dict, ids: list[str], rng: random.Random) -> tuple[float, float, float]:
    """Mean of a-b over items with a 95% bootstrap interval (items resampled)."""
    diffs = [a[i] - b[i] for i in ids]
    boots = sorted(mean(rng.choices(diffs, k=len(diffs))) for _ in range(BOOT_N))
    return mean(diffs), boots[int(0.025 * BOOT_N)], boots[int(0.975 * BOOT_N) - 1]


def macro_gap(a: dict, b: dict, by_cat: dict[str, list[str]], rng: random.Random):
    """Macro (category-weighted) gap, bootstrapped within each category."""
    diffs = {c: [a[i] - b[i] for i in ids] for c, ids in by_cat.items()}
    point = mean(mean(d) for d in diffs.values())
    boots = sorted(mean(mean(rng.choices(d, k=len(d))) for d in diffs.values())
                   for _ in range(BOOT_N))
    return point, boots[int(0.025 * BOOT_N)], boots[int(0.975 * BOOT_N) - 1]


def route(h: dict, s: dict) -> tuple[float, str]:
    ratio = 1.0 if s["mean"] == 0 and h["mean"] == 0 else (
        float("inf") if s["mean"] == 0 else h["mean"] / s["mean"])
    if ratio >= ROUTE_HAIKU and h["inventions"] <= s["inventions"]:
        return ratio, "Haiku"
    if ratio >= ROUTE_CHECK:
        return ratio, "Haiku + check"
    return ratio, "Sonnet"


def compare(stats: dict, items: dict[str, dict]) -> dict:
    h, s = stats[HAIKU], stats[SONNET]
    rng = random.Random(BOOT_SEED)
    shared = sorted(set(h["item_means"]) & set(s["item_means"]))
    by_cat = defaultdict(list)
    for i in shared:
        by_cat[items[i]["category"]].append(i)

    rows = {}
    for c in CATEGORIES:
        if c not in h["categories"] or c not in s["categories"]:
            continue
        hc, sc = h["categories"][c], s["categories"][c]
        gap = paired_gap(h["item_means"], s["item_means"], by_cat[c], rng)
        ratio, verdict = route(hc, sc)
        rows[c] = {"haiku": hc["mean"], "sonnet": sc["mean"],
                   "opus": stats.get(OPUS, {}).get("categories", {}).get(c, {}).get("mean"),
                   "ratio": ratio, "gap": gap[0], "gap_lo": gap[1], "gap_hi": gap[2],
                   "haiku_inventions": hc["inventions"], "sonnet_inventions": sc["inventions"],
                   "cost_ratio": (sc["cost_per_call"] / hc["cost_per_call"]
                                  if hc["cost_per_call"] else None),
                   "route": verdict}
    overall = macro_gap(h["item_means"], s["item_means"], dict(by_cat), rng)

    # Secondary: exact McNemar on per-item pass (DESIGN.md).
    b = sum(h["item_pass"][i] and not s["item_pass"][i] for i in shared)
    c = sum(s["item_pass"][i] and not h["item_pass"][i] for i in shared)
    mcn = {"haiku_only": b, "sonnet_only": c,
           "both": sum(h["item_pass"][i] and s["item_pass"][i] for i in shared),
           "neither": sum(not h["item_pass"][i] and not s["item_pass"][i] for i in shared),
           "p_exact": mcnemar_exact(b, c)}
    return {"categories": rows, "macro_gap": overall, "mcnemar": mcn}


def gold_check(stats: dict, items: dict[str, dict]) -> list[dict]:
    """Items no model passed, Opus included: re-examined for bad gold (DESIGN.md)."""
    out = []
    for i in items:
        if all(i in st["item_pass"] and not st["item_pass"][i] for st in stats.values()):
            out.append({"id": i, "category": items[i]["category"],
                        **{label(m): round(st["item_means"][i], 3) for m, st in stats.items()}})
    return out


# --- post-hoc sensitivity (NOT pre-registered) ---------------------------------
# Added after the runs, once the misses had been read. The pre-registered
# scoring above is the primary result and nothing here changes it or the gold;
# RESULTS.md reports both and says which is which.
POST_HOC_EXCLUDE = {
    "N04": "every call flagged as an invention rejects the premise (a canary never pages, "
           "because canaries are excluded from the alert queries); none names a canary threshold",
    "T05": "the gold reads \"Sure, no second shooter. That brings it to $3,100.\" as one "
           "counter-offer the client never accepted; reading \"Sure\" as accepting the "
           "removal, with only the new price left open, also fits the stated rule",
}
SENSITIVITY_VARIANTS = [("N04",), ("N04", "T05")]


def variant_summary(stats: dict, cmp: dict, hyp: dict, drop: tuple[str, ...]) -> dict:
    return {
        "excluded": list(drop),
        "macro": {label(m): st["macro"] for m, st in stats.items()},
        "macro_gap": list(cmp["macro_gap"]),
        "inventions": {label(m): f"{st['inventions']}/{st['invention_chances']}"
                       for m, st in stats.items()},
        "route_away_from_haiku": sorted(c for c, r in cmp["categories"].items()
                                        if r["route"] != "Haiku"),
        "hypotheses": {k: v["supported"] for k, v in hyp.items()},
    }


def sensitivity(groups: dict[str, list[dict]], items: dict[str, dict]) -> list[dict]:
    out = []
    for drop in SENSITIVITY_VARIANTS:
        keep = {i: it for i, it in items.items() if i not in drop}
        st = {m: subject_stats([r for r in groups[m] if r["id"] in keep], keep)
              for m, _ in SUBJECTS if groups.get(m)}
        cmp = compare(st, keep)
        out.append(variant_summary(st, cmp, hypotheses(st, cmp), drop))
    return out


def hypotheses(stats: dict, cmp: dict) -> dict:
    h, s, o = stats[HAIKU], stats[SONNET], stats.get(OPUS)
    cr = cmp["categories"]
    mg = cmp["macro_gap"]
    sonnet_lead = -mg[0]
    gaps = {c: r["sonnet"] - r["haiku"] for c, r in cr.items()}
    top = max(gaps.values())
    largest = sorted(c for c, g in gaps.items() if abs(g - top) < 1e-9)
    away = sorted(c for c, r in cr.items() if r["route"] != "Haiku")

    def ratio(mode):
        hc, sc = h["cost_per_call_by_mode"][mode], s["cost_per_call_by_mode"][mode]
        return sc / hc if hc else None

    single, scout, worker = ratio("single"), ratio("scout"), ratio("worker")
    hyp = {
        "H1": {"supported": sonnet_lead >= 0.05 and mg[2] < 0,
               "evidence": {"sonnet_minus_haiku_macro": round(sonnet_lead, 3),
                            "ci95": [round(-mg[2], 3), round(-mg[1], 3)]}},
        "H2": {"supported": None if o is None else o["macro"] <= 0.95,
               "evidence": {"opus_macro": None if o is None else round(o["macro"], 3),
                            "sonnet_macro": round(s["macro"], 3),
                            "tier_failed": (o is not None and o["macro"] >= 0.97
                                            and s["macro"] >= 0.97)}},
        "H3": {"supported": None if o is None else o["macro"] >= s["macro"] >= h["macro"],
               "evidence": {"opus": None if o is None else round(o["macro"], 3),
                            "sonnet": round(s["macro"], 3), "haiku": round(h["macro"], 3)}},
        "H4": {"supported": top > 0 and all(c in STATEFUL for c in largest),
               "evidence": {"largest": largest, "gap": round(top, 3),
                            "by_category": {c: round(g, 3) for c, g in gaps.items()}}},
        "H5": {"supported": h["invention_rate"] > s["invention_rate"],
               "evidence": {"haiku": f"{h['inventions']}/{h['invention_chances']}",
                            "sonnet": f"{s['inventions']}/{s['invention_chances']}",
                            "haiku_ci95": [round(x, 3) for x in h["invention_ci"]],
                            "sonnet_ci95": [round(x, 3) for x in s["invention_ci"]]}},
        "H6": {"supported": len(away) >= 2,
               "evidence": {"route_away_from_haiku": away}},
        "H7": {"supported": (None if None in (single, scout, worker)
                             else scout < single and worker < single),
               "evidence": {"sonnet_over_haiku_cost_single": None if single is None else round(single, 1),
                            "scout": None if scout is None else round(scout, 1),
                            "worker": None if worker is None else round(worker, 1)}},
    }
    return hyp


# --- output --------------------------------------------------------------------

def f2(x) -> str:
    return "–" if x is None else f"{x:.2f}"


def pct_ci(k: int, n: int, ci) -> str:
    if n == 0:
        return "–"
    return f"{k}/{n} = {k / n:.0%} ({ci[0]:.0%}–{ci[1]:.0%})"


def rng_cell(st: dict) -> str:
    if st["min"] == st["max"]:
        return f2(st["mean"])
    return f"{f2(st['mean'])} ({f2(st['min'])}–{f2(st['max'])})"


def tables(stats: dict, cmp: dict, hyp: dict, gold: list[dict], sens: list[dict]) -> str:
    present = [s for s in SUBJECTS if s[0] in stats]
    out = ["# Tables (generated by analyze.py; do not edit by hand)", ""]

    out += ["## Overall", "",
            "| Subject | Reps | Macro score (rep range) | Micro | Cost per 60-item run | "
            "Cost per call | Thinking tok/call | Wall s/call | Format fails | Call errors | "
            "Rep agreement |",
            "|---|---|---|---|---|---|---|---|---|---|---|"]
    for m, lab in present:
        st = stats[m]
        rng = (f2(st["macro"]) if st["macro_min"] == st["macro_max"]
               else f"{f2(st['macro'])} ({f2(st['macro_min'])}–{f2(st['macro_max'])})")
        agree = "–" if st["rep_agreement"] is None else f"{st['rep_agreement']:.0%}"
        out.append(f"| {lab} | {len(st['reps'])} | {rng} | {f2(st['micro'])} | "
                   f"${st['cost_per_run']:.3f} | ${st['cost_per_call']:.4f} | "
                   f"{st['thinking_tokens']:.0f} | {st['wall_s']:.1f} | {st['format_failures']} | "
                   f"{len(st['call_errors'])} | {agree} |")

    out += ["", "## Score by category (mean across reps; rep range in brackets)", "",
            "| Category | n | Mode | " + " | ".join(lab for _, lab in present) + " |",
            "|---|---|---|" + "---|" * len(present)]
    for c in CATEGORIES:
        if c not in stats[HAIKU]["categories"]:
            continue
        cells = [rng_cell(stats[m]["categories"][c]) if c in stats[m]["categories"] else "–"
                 for m, _ in present]
        out.append(f"| {c} | {stats[HAIKU]['categories'][c]['n_items']} | {MODE_OF.get(c, '')} | "
                   + " | ".join(cells) + " |")

    mg, mc = cmp["macro_gap"], cmp["mcnemar"]
    out += ["", "## Routing: Haiku vs Sonnet", "",
            f"Macro gap (Haiku − Sonnet): {mg[0]:+.3f}, 95% CI {mg[1]:+.3f} to {mg[2]:+.3f} "
            "(paired bootstrap over items within category).", "",
            "| Category | Haiku | Sonnet | Opus | Haiku/Sonnet | Gap (95% CI) | Inventions H/S | "
            "Sonnet cost × Haiku | Route |",
            "|---|---|---|---|---|---|---|---|---|"]
    for c, r in cmp["categories"].items():
        ratio = "∞" if r["ratio"] == float("inf") else f"{r['ratio']:.0%}"
        cost = "–" if r["cost_ratio"] is None else f"{r['cost_ratio']:.1f}×"
        out.append(f"| {c} | {f2(r['haiku'])} | {f2(r['sonnet'])} | {f2(r['opus'])} | {ratio} | "
                   f"{r['gap']:+.2f} ({r['gap_lo']:+.2f} to {r['gap_hi']:+.2f}) | "
                   f"{r['haiku_inventions']}/{r['sonnet_inventions']} | {cost} | {r['route']} |")

    out += ["", "## Item pass rates and McNemar", "",
            "An item is passed when it scores 1.0 on at least two of three reps (Opus: its one rep). "
            "Intervals are Wilson 95%.", "",
            "| Subject | Items passed |", "|---|---|"]
    for m, lab in present:
        st = stats[m]
        out.append(f"| {lab} | {pct_ci(st['passed'], st['n_items'], st['pass_ci'])} |")
    out += ["", f"Haiku vs Sonnet: both pass {mc['both']}, only Haiku {mc['haiku_only']}, "
                f"only Sonnet {mc['sonnet_only']}, neither {mc['neither']}; "
                f"exact two-sided McNemar p = {mc['p_exact']:.4f}."]

    out += ["", "## Inventions and over-abstains (per call; Wilson 95%)", "",
            "Invention chances: unanswerable abstain-nearmiss and nav-multihop items, and "
            "thread-supersede items with a null field. Over-abstain chances: answerable "
            "abstain-nearmiss and nav-multihop items.", "",
            "| Subject | Inventions | Items invented on | Over-abstains |", "|---|---|---|---|"]
    for m, lab in present:
        st = stats[m]
        out.append(f"| {lab} | {pct_ci(st['inventions'], st['invention_chances'], st['invention_ci'])} | "
                   f"{', '.join(st['invented_items']) or '–'} | "
                   f"{pct_ci(st['over_abstains'], st['abstain_chances'], st['over_abstain_ci'])} |")

    out += ["", "## Cost, turns and time by category", "",
            "| Category | Mode | " + " | ".join(f"{lab} $/call" for _, lab in present)
            + " | " + " | ".join(f"{lab} turns" for _, lab in present)
            + " | " + " | ".join(f"{lab} s/call" for _, lab in present) + " |",
            "|---|---|" + "---|" * (3 * len(present))]
    for c in CATEGORIES:
        if c not in stats[HAIKU]["categories"]:
            continue
        cs = [stats[m]["categories"].get(c) for m, _ in present]
        out.append(f"| {c} | {MODE_OF.get(c, '')} | "
                   + " | ".join("–" if x is None else f"{x['cost_per_call']:.4f}" for x in cs) + " | "
                   + " | ".join("–" if x is None else f"{x['turns']:.1f}" for x in cs) + " | "
                   + " | ".join("–" if x is None else f"{x['wall_s']:.1f}" for x in cs) + " |")

    out += ["", "## Cost per call by mode", "",
            "| Mode | " + " | ".join(f"{lab} $/call" for _, lab in present) + " | Sonnet × Haiku |",
            "|---|" + "---|" * (len(present) + 1)]
    for mode in MODES:
        vals = [stats[m]["cost_per_call_by_mode"][mode] for m, _ in present]
        hv, sv = stats[HAIKU]["cost_per_call_by_mode"][mode], stats[SONNET]["cost_per_call_by_mode"][mode]
        out.append(f"| {mode} | " + " | ".join("–" if v is None else f"{v:.4f}" for v in vals)
                   + f" | {'–' if not hv else f'{sv / hv:.1f}×'} |")

    out += ["", "## Hypotheses", ""]
    for k, v in hyp.items():
        verdict = {True: "supported", False: "not supported", None: "not tested"}[v["supported"]]
        out.append(f"- **{k}** {verdict}: `{json.dumps(v['evidence'], ensure_ascii=False)}`")

    out += ["", "## Gold check: items no model passed", ""]
    if gold:
        out += ["| Item | Category | " + " | ".join(lab for _, lab in present) + " |",
                "|---|---|" + "---|" * len(present)]
        for g in gold:
            out.append(f"| {g['id']} | {g['category']} | "
                       + " | ".join(f2(g.get(lab)) for _, lab in present) + " |")
    else:
        out.append("None.")

    out += ["", "## Post-hoc sensitivity (not pre-registered)", "",
            "Chosen after the runs, once the misses had been read. The first row is the "
            "pre-registered result; the others drop whole items. Gold is unchanged.", ""]
    out += [f"- {i}: {why}." for i, why in POST_HOC_EXCLUDE.items()]
    out += ["", "| Items dropped | " + " | ".join(lab for _, lab in present)
            + " | Gap Haiku − Sonnet (95% CI) | Inventions H/S | Routed away from Haiku | "
            "H1 | H2 | H5 | H6 |",
            "|---|" + "---|" * len(present) + "---|---|---|---|---|---|---|"]
    yn = {True: "yes", False: "no", None: "–"}
    for v in [variant_summary(stats, cmp, hyp, ())] + sens:
        g = v["macro_gap"]
        out.append(f"| {', '.join(v['excluded']) or 'none (pre-registered)'} | "
                   + " | ".join(f"{v['macro'][lab]:.3f}" for _, lab in present) + " | "
                   f"{g[0]:+.3f} ({g[1]:+.3f} to {g[2]:+.3f}) | "
                   f"{v['inventions'][label(HAIKU)]} / {v['inventions'][label(SONNET)]} | "
                   f"{', '.join(v['route_away_from_haiku']) or 'none'} | "
                   + " | ".join(yn[v["hypotheses"][h]] for h in ("H1", "H2", "H5", "H6")) + " |")

    out += ["", "## Errors and model checks", ""]
    for m, lab in present:
        st = stats[m]
        out.append(f"- {lab}: {len(st['call_errors'])} call errors"
                   + (f" ({'; '.join(st['call_errors'])})" if st["call_errors"] else "")
                   + f"; {len(st['model_mismatches'])} replies from a model other than the one requested"
                   + (f" ({'; '.join(st['model_mismatches'])})" if st["model_mismatches"] else ""))
    return "\n".join(out) + "\n"


MODE_OF: dict[str, str] = {}
ROWS: list[dict] = []


def figures(stats: dict, cmp: dict, items: dict[str, dict]) -> list[str]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    FIGS.mkdir(exist_ok=True)
    present = [s for s in SUBJECTS if s[0] in stats]
    cats = [c for c in CATEGORIES if c in stats[HAIKU]["categories"]]
    written = []

    # 1. Score by category, error bars = range across reps.
    fig, ax = plt.subplots(figsize=(10, 4.6))
    w = 0.8 / len(present)
    for k, (m, lab) in enumerate(present):
        cs = stats[m]["categories"]
        xs = [i + (k - (len(present) - 1) / 2) * w for i in range(len(cats))]
        ys = [cs[c]["mean"] if c in cs else 0 for c in cats]
        lo = [cs[c]["mean"] - cs[c]["min"] if c in cs else 0 for c in cats]
        hi = [cs[c]["max"] - cs[c]["mean"] if c in cs else 0 for c in cats]
        ax.bar(xs, ys, w, label=lab, color=COLORS[m], edgecolor="white", linewidth=0.5)
        if len(stats[m]["reps"]) > 1:
            ax.errorbar(xs, ys, yerr=[lo, hi], fmt="none", ecolor="#333", capsize=2, linewidth=0.8)
    ax.set_xticks(range(len(cats)), cats, rotation=15, ha="right")
    ax.set_ylim(0, 1.17)
    ax.set_yticks([0, 0.2, 0.4, 0.6, 0.8, 1.0])
    ax.set_ylabel("mean score")
    ax.set_title("Score by category (bars: mean across reps; whiskers: rep range)")
    ax.legend(ncol=len(present), loc="upper center", fontsize=8, frameon=False)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIGS / "scores_by_category.png", dpi=150)
    plt.close(fig)
    written.append("scores_by_category.png")

    # 2. Haiku - Sonnet gap per category with bootstrap intervals.
    rows = cmp["categories"]
    order = sorted(rows, key=lambda c: rows[c]["gap"])
    route_colors = {"Haiku": "#2a9d8f", "Haiku + check": "#e9c46a", "Sonnet": "#e76f51"}
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    for y, c in enumerate(order):
        r = rows[c]
        color = route_colors[r["route"]]
        ax.plot([r["gap_lo"], r["gap_hi"]], [y, y], color=color, linewidth=2.5)
        ax.plot(r["gap"], y, "o", color=color, markersize=7)
    mg = cmp["macro_gap"]
    ax.axvspan(mg[1], mg[2], color="#999", alpha=0.15, label="macro gap 95% CI")
    ax.axvline(0, color="#333", linewidth=0.8)
    ax.legend(handles=[plt.Line2D([], [], color=col, marker="o", linewidth=2.5, label=f"route: {name}")
                       for name, col in route_colors.items()]
              + [plt.Rectangle((0, 0), 1, 1, color="#999", alpha=0.3, label="macro gap 95% CI")],
              loc="upper left", fontsize=8, frameon=False)
    ax.set_yticks(range(len(order)), order)
    ax.set_xlabel("Haiku − Sonnet score (dot: mean over items; line: 95% bootstrap CI)")
    ax.set_title("Where Haiku loses to Sonnet (colour = routing verdict)")
    ax.grid(axis="x", alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIGS / "haiku_vs_sonnet_gap.png", dpi=150)
    plt.close(fig)
    written.append("haiku_vs_sonnet_gap.png")

    # 3. Cost per run vs macro score.
    fig, ax = plt.subplots(figsize=(6.5, 4.4))
    for m, lab in present:
        st = stats[m]
        for p in st["per_rep"]:
            ax.plot(p["cost_usd"], p["macro"], "o", color=COLORS[m], alpha=0.35, markersize=5)
        ax.plot(st["cost_per_run"], st["macro"], "D", color=COLORS[m], markersize=9, label=lab)
    ax.set_xscale("log")
    ax.set_xlabel("list-price cost of one 60-item run, USD (log scale)")
    ax.set_ylabel("macro score")
    ax.set_title("Cost against score (diamond: mean; dots: single reps)")
    ax.legend(fontsize=8, frameon=False, loc="lower right")
    ax.grid(alpha=0.3, which="both")
    fig.tight_layout()
    fig.savefig(FIGS / "cost_vs_score.png", dpi=150)
    plt.close(fig)
    written.append("cost_vs_score.png")

    # 4. Turns per agentic item.
    def natural(item_id: str) -> tuple[str, int]:  # N2 before N10
        stem = item_id.rstrip("0123456789")
        return stem, int(item_id[len(stem):] or 0)

    ag = [i for i in sorted(items, key=natural) if items[i]["mode"] in AGENTIC]
    turns = {m: defaultdict(list) for m, _ in present}
    for r in ROWS:
        if r["model"] in turns and r["id"] in ag:
            turns[r["model"]][r["id"]].append(r["num_turns"] or 0)
    fig, ax = plt.subplots(figsize=(11, 4.2))
    w = 0.8 / len(present)
    for k, (m, lab) in enumerate(present):
        xs = [i + (k - (len(present) - 1) / 2) * w for i in range(len(ag))]
        ax.bar(xs, [mean(turns[m][i]) or 0 for i in ag], w, label=lab, color=COLORS[m])
    ax.set_xticks(range(len(ag)), [f"{i}\n{items[i]['mode']}" for i in ag], fontsize=8)
    ax.set_ylabel("turns (mean across reps)")
    ax.set_title("Agentic items: turns taken per call")
    ax.legend(fontsize=8, frameon=False)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIGS / "agentic_turns.png", dpi=150)
    plt.close(fig)
    written.append("agentic_turns.png")

    # 5. Invention and over-abstain rates with Wilson intervals.
    fig, ax = plt.subplots(figsize=(7, 4))
    top = 0.0
    groups = [("invention", "inventions", "invention_chances", "invention_ci"),
              ("over-abstain", "over_abstains", "abstain_chances", "over_abstain_ci")]
    for k, (m, lab) in enumerate(present):
        st = stats[m]
        xs, ys, lo, hi = [], [], [], []
        for g, (_, num, den, ci) in enumerate(groups):
            if not st[den]:
                continue
            p = st[num] / st[den]
            xs.append(g + (k - (len(present) - 1) / 2) * w)
            ys.append(p)
            lo.append(max(0.0, p - st[ci][0]))   # float noise at p = 0 or 1
            hi.append(max(0.0, st[ci][1] - p))
            top = max(top, st[ci][1])
        ax.bar(xs, ys, w, label=lab, color=COLORS[m])
        ax.errorbar(xs, ys, yerr=[lo, hi], fmt="none", ecolor="#333", capsize=3, linewidth=0.8)
    ax.set_xticks(range(len(groups)), [f"{g[0]}\n(per chance)" for g in groups])
    ax.set_ylim(0, min(1.0, top * 1.25 + 0.02))   # rates near 0 vanish on a 0-1 axis
    ax.set_ylabel("rate (whiskers: Wilson 95%)")
    ax.set_title("Inventions and over-abstains")
    ax.legend(fontsize=8, frameon=False)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIGS / "inventions.png", dpi=150)
    plt.close(fig)
    written.append("inventions.png")
    return written


def main() -> int:
    if not SCORES.exists():
        sys.exit("no results/scores.jsonl; run grade.py first")
    items = {it["id"]: it for it in map(json.loads, ITEMS.read_text(encoding="utf-8").splitlines())}
    MODE_OF.update({it["category"]: it["mode"] for it in items.values()})
    ROWS.extend(json.loads(line) for line in SCORES.read_text(encoding="utf-8").splitlines())
    assert all(r["rep"] > 0 for r in ROWS), "pilot rows (rep 0) must not be analysed"

    groups = defaultdict(list)
    for r in ROWS:
        groups[r["model"]].append(r)
    stats = {m: subject_stats(groups[m], items) for m, _ in SUBJECTS if groups.get(m)}
    if HAIKU not in stats or SONNET not in stats:
        sys.exit("need both Haiku and Sonnet scores")
    cmp = compare(stats, items)
    hyp = hypotheses(stats, cmp)
    gold = gold_check(stats, items)
    sens = sensitivity(groups, items)

    SUMMARY.write_text(json.dumps({
        "subjects": {label(m): {k: v for k, v in st.items() if k not in ("item_means", "item_pass")}
                     for m, st in stats.items()},
        "item_means": {label(m): st["item_means"] for m, st in stats.items()},
        "item_pass": {label(m): st["item_pass"] for m, st in stats.items()},
        "haiku_vs_sonnet": cmp, "hypotheses": hyp, "gold_check": gold,
        "post_hoc_sensitivity": {"pre_registered": False, "reasons": POST_HOC_EXCLUDE,
                                 "variants": sens},
        "routing_rule": {"haiku_at_or_above": ROUTE_HAIKU, "check_at_or_above": ROUTE_CHECK},
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    TABLES.write_text(tables(stats, cmp, hyp, gold, sens), encoding="utf-8")
    figs = figures(stats, cmp, items)
    print(f"{len(ROWS)} rows, {len(stats)} subjects -> {SUMMARY.relative_to(HERE)}, "
          f"{TABLES.relative_to(HERE)}, figures/{{{','.join(figs)}}}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
