"""Summarize results/scores.jsonl into tables, figures and the hypothesis checks.

    python grade.py      # results/raw/*.jsonl -> results/scores.jsonl
    python analyze.py    # -> results/summary.json, results/tables.md, figures/*.png

The pilot (rep 0) lives in results/pilot/ and never reaches scores.jsonl.
"""
from __future__ import annotations

import json
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

CATEGORIES = ["classify", "extract", "code-qa", "log-triage", "code-nav",
              "abstain", "diff-summary", "traceback", "code-review", "code-edit"]
MECHANICAL = ["classify", "extract", "code-qa", "log-triage"]       # DESIGN.md H1
JUDGMENT = ["code-review", "traceback", "abstain", "diff-summary"]  # DESIGN.md H2
AGENTIC = {"scout", "worker"}

SUBJECTS = [  # (model, arm, label); the capped arm is exploratory
    ("claude-haiku-5-5", "default", "Haiku 5.5"),
    ("claude-sonnet-5-5", "default", "Sonnet 5.5"),
    ("claude-opus-5-5", "default", "Opus 5.5"),
    ("claude-haiku-5-5", "cap1024", "Haiku 5.5 capped"),
]
HAIKU, SONNET, OPUS, CAPPED = (s[:2] for s in SUBJECTS)
COLORS = {HAIKU: "#2a9d8f", SONNET: "#e76f51", OPUS: "#264653", CAPPED: "#8ecae6"}

# Routing rule, fixed before the main runs were graded (METHODS.md): Haiku when it
# keeps 95% of Sonnet's score and invents no more often; Haiku with a check
# between 85% and 95% (or at 95%+ with more inventions); Sonnet below 85%.
ROUTE_HAIKU, ROUTE_CHECK = 0.95, 0.85
BOOT_N, BOOT_SEED = 10_000, 20261017


def mean(xs) -> float | None:
    xs = list(xs)
    return sum(xs) / len(xs) if xs else None


def label(subj) -> str:
    return next(s[2] for s in SUBJECTS if s[:2] == subj)


# --- per-subject statistics ----------------------------------------------------

def opportunities(items: dict[str, dict]) -> tuple[set, set]:
    """Item ids where a model can invent, and where it can over-abstain."""
    invent, abstain = set(), set()
    for i, it in items.items():
        if it["category"] == "extract" and any(v is None for v in it["gold"].values()):
            invent.add(i)
        if it["category"] in ("abstain", "code-nav"):
            (abstain if it["answerable"] else invent).add(i)
    return invent, abstain


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
            "inventions": sum(r["invention"] for r in cr),
            "over_abstains": sum(r["over_abstain"] for r in cr),
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
    for r in rows:
        by_item[r["id"]].append(r["score"])
    agree = (mean(len(set(v)) == 1 for v in by_item.values()) if len(reps) > 1 else None)
    inv_rows = [r for r in rows if r["id"] in inv_ids]
    abs_rows = [r for r in rows if r["id"] in abs_ids]
    return {
        "reps": reps, "n_rows": len(rows), "categories": cats, "per_rep": per_rep,
        "macro": mean(p["macro"] for p in per_rep),
        "macro_min": min(p["macro"] for p in per_rep),
        "macro_max": max(p["macro"] for p in per_rep),
        "micro": mean(p["micro"] for p in per_rep),
        "cost_per_run": mean(p["cost_usd"] for p in per_rep),
        "cost_per_call": mean(r["cost_usd"] or 0 for r in rows),
        "input_tokens": mean(r["input_tokens"] or 0 for r in rows),
        "output_tokens": mean(r["output_tokens"] or 0 for r in rows),
        "thinking_tokens": mean(r["thinking_tokens"] or 0 for r in rows),
        "wall_s": mean(r["wall_s"] or 0 for r in rows),
        "format_failures": sum(r["format_failure"] for r in rows),
        "call_errors": sorted({f"{r['id']} r{r['rep']}: {r['call_error'][:60]}"
                               for r in rows if r["call_error"]}),
        "invention_rate": mean(r["invention"] for r in inv_rows),
        "inventions": sum(r["invention"] for r in inv_rows), "invention_chances": len(inv_rows),
        "over_abstain_rate": mean(r["over_abstain"] for r in abs_rows),
        "over_abstains": sum(r["over_abstain"] for r in abs_rows), "abstain_chances": len(abs_rows),
        "rep_agreement": agree,
        "agentic_turns": mean(r["num_turns"] or 0 for r in rows if r["mode"] in AGENTIC),
        "model_mismatches": sorted({f"{r['id']} r{r['rep']}: {r['model_answered']}" for r in rows
                                    if r["model_answered"] and r["model_answered"] != r["model"]}),
        "item_means": {i: mean(v) for i, v in by_item.items()},
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
    return {"categories": rows, "macro_gap": overall}


def hypotheses(stats: dict, cmp: dict, rows: list[dict]) -> dict:
    h, s = stats[HAIKU], stats[SONNET]
    cr = cmp["categories"]
    mech = {c: cr[c]["ratio"] for c in MECHANICAL if c in cr}
    mech_gap = mean(cr[c]["sonnet"] - cr[c]["haiku"] for c in MECHANICAL if c in cr)
    judg_gap = mean(cr[c]["sonnet"] - cr[c]["haiku"] for c in JUDGMENT if c in cr)

    def mode_cost(subj, agentic: bool):
        return mean(r["cost_usd"] or 0 for r in rows
                    if (r["model"], r["arm"]) == subj and (r["mode"] in AGENTIC) == agentic)

    single_ratio = mode_cost(SONNET, False) / mode_cost(HAIKU, False)
    agentic_ratio = mode_cost(SONNET, True) / mode_cost(HAIKU, True)
    return {
        "H1": {"supported": all(v >= 0.95 for v in mech.values()),
               "evidence": {c: round(v, 3) for c, v in mech.items()}},
        "H2": {"supported": judg_gap > mech_gap,
               "evidence": {"judgment_gap": round(judg_gap, 3), "mechanical_gap": round(mech_gap, 3)}},
        "H3": {"supported": h["invention_rate"] > s["invention_rate"],
               "evidence": {"haiku": f"{h['inventions']}/{h['invention_chances']}",
                            "sonnet": f"{s['inventions']}/{s['invention_chances']}"}},
        "H4": {"supported": h["agentic_turns"] > s["agentic_turns"] and agentic_ratio < single_ratio,
               "evidence": {"haiku_turns": round(h["agentic_turns"], 2),
                            "sonnet_turns": round(s["agentic_turns"], 2),
                            "sonnet_over_haiku_cost_single": round(single_ratio, 1),
                            "sonnet_over_haiku_cost_agentic": round(agentic_ratio, 1)}},
        "H5": {"supported": None, "evidence": "see anchor/RESULTS.md"},
    }


# --- output --------------------------------------------------------------------

def f2(x) -> str:
    return "–" if x is None else f"{x:.2f}"


def rng_cell(st: dict) -> str:
    if st["min"] == st["max"]:
        return f2(st["mean"])
    return f"{f2(st['mean'])} ({f2(st['min'])}–{f2(st['max'])})"


def tables(stats: dict, cmp: dict, hyp: dict) -> str:
    present = [s for s in SUBJECTS if s[:2] in stats]
    out = ["# Tables (generated by analyze.py; do not edit by hand)", ""]

    out += ["## Overall", "",
            "| Subject | Reps | Macro score (rep range) | Micro | Cost per 74-item run | "
            "Cost per call | Thinking tok/call | Wall s/call | Format fails | Call errors | "
            "Inventions | Over-abstains | Rep agreement |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for m, a, lab in present:
        st = stats[(m, a)]
        rng = (f2(st["macro"]) if st["macro_min"] == st["macro_max"]
               else f"{f2(st['macro'])} ({f2(st['macro_min'])}–{f2(st['macro_max'])})")
        agree = "–" if st["rep_agreement"] is None else f"{st['rep_agreement']:.0%}"
        out.append(f"| {lab} | {len(st['reps'])} | {rng} | {f2(st['micro'])} | "
                   f"${st['cost_per_run']:.3f} | ${st['cost_per_call']:.4f} | "
                   f"{st['thinking_tokens']:.0f} | {st['wall_s']:.1f} | {st['format_failures']} | "
                   f"{len(st['call_errors'])} | {st['inventions']}/{st['invention_chances']} | "
                   f"{st['over_abstains']}/{st['abstain_chances']} | {agree} |")

    out += ["", "## Score by category (mean across reps; rep range in brackets)", "",
            "| Category | n | " + " | ".join(lab for _, _, lab in present) + " |",
            "|---|---|" + "---|" * len(present)]
    for c in CATEGORIES:
        if c not in stats[HAIKU]["categories"]:
            continue
        cells = [rng_cell(stats[s[:2]]["categories"][c]) if c in stats[s[:2]]["categories"] else "–"
                 for s in present]
        out.append(f"| {c} | {stats[HAIKU]['categories'][c]['n_items']} | " + " | ".join(cells) + " |")

    mg = cmp["macro_gap"]
    out += ["", "## Routing: Haiku vs Sonnet", "",
            f"Macro gap (Haiku − Sonnet): {mg[0]:+.3f}, 95% CI {mg[1]:+.3f} to {mg[2]:+.3f} "
            "(bootstrap over items within category).", "",
            "| Category | Haiku | Sonnet | Opus | Haiku/Sonnet | Gap (95% CI) | Inventions H/S | "
            "Sonnet cost × Haiku | Route |",
            "|---|---|---|---|---|---|---|---|---|"]
    for c, r in cmp["categories"].items():
        ratio = "∞" if r["ratio"] == float("inf") else f"{r['ratio']:.0%}"
        cost = "–" if r["cost_ratio"] is None else f"{r['cost_ratio']:.1f}×"
        out.append(f"| {c} | {f2(r['haiku'])} | {f2(r['sonnet'])} | {f2(r['opus'])} | {ratio} | "
                   f"{r['gap']:+.2f} ({r['gap_lo']:+.2f} to {r['gap_hi']:+.2f}) | "
                   f"{r['haiku_inventions']}/{r['sonnet_inventions']} | {cost} | {r['route']} |")

    out += ["", "## Cost, turns and time by category", "",
            "| Category | Mode | " + " | ".join(f"{lab} $/call" for _, _, lab in present)
            + " | " + " | ".join(f"{lab} turns" for _, _, lab in present) + " |",
            "|---|---|" + "---|" * (2 * len(present))]
    modes = {}
    for st in stats.values():
        for c in st["categories"]:
            modes.setdefault(c, None)
    for c in CATEGORIES:
        if c not in stats[HAIKU]["categories"]:
            continue
        cost = [f"{stats[s[:2]]['categories'][c]['cost_per_call']:.4f}"
                if c in stats[s[:2]]["categories"] else "–" for s in present]
        turns = [f"{stats[s[:2]]['categories'][c]['turns']:.1f}"
                 if c in stats[s[:2]]["categories"] else "–" for s in present]
        out.append(f"| {c} | {MODE_OF.get(c, '')} | " + " | ".join(cost) + " | " + " | ".join(turns) + " |")

    out += ["", "## Hypotheses", ""]
    for k, v in hyp.items():
        verdict = {True: "supported", False: "not supported", None: "separate"}[v["supported"]]
        out.append(f"- **{k}** {verdict}: `{json.dumps(v['evidence'], ensure_ascii=False)}`")

    out += ["", "## Errors and model checks", ""]
    for m, a, lab in present:
        st = stats[(m, a)]
        out.append(f"- {lab}: {len(st['call_errors'])} call errors"
                   + (f" ({'; '.join(st['call_errors'])})" if st["call_errors"] else "")
                   + f"; {len(st['model_mismatches'])} replies from a model other than the one requested"
                   + (f" ({'; '.join(st['model_mismatches'])})" if st["model_mismatches"] else ""))
    return "\n".join(out) + "\n"


MODE_OF: dict[str, str] = {}


def figures(stats: dict, cmp: dict, items: dict[str, dict]) -> list[str]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    FIGS.mkdir(exist_ok=True)
    present = [s for s in SUBJECTS if s[:2] in stats]
    cats = [c for c in CATEGORIES if c in stats[HAIKU]["categories"]]
    written = []

    # 1. Score by category, error bars = range across reps.
    fig, ax = plt.subplots(figsize=(11, 4.6))
    w = 0.8 / len(present)
    for k, (m, a, lab) in enumerate(present):
        cs = stats[(m, a)]["categories"]
        xs = [i + (k - (len(present) - 1) / 2) * w for i in range(len(cats))]
        ys = [cs[c]["mean"] if c in cs else 0 for c in cats]
        lo = [cs[c]["mean"] - cs[c]["min"] if c in cs else 0 for c in cats]
        hi = [cs[c]["max"] - cs[c]["mean"] if c in cs else 0 for c in cats]
        ax.bar(xs, ys, w, label=lab, color=COLORS[(m, a)],
               hatch="//" if a == "cap1024" else None, edgecolor="white", linewidth=0.5)
        if len(stats[(m, a)]["reps"]) > 1:
            ax.errorbar(xs, ys, yerr=[lo, hi], fmt="none", ecolor="#333", capsize=2, linewidth=0.8)
    ax.set_xticks(range(len(cats)), cats, rotation=20, ha="right")
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
    fig, ax = plt.subplots(figsize=(7.5, 4.6))
    for y, c in enumerate(order):
        r = rows[c]
        color = route_colors[r["route"]]
        ax.plot([r["gap_lo"], r["gap_hi"]], [y, y], color=color, linewidth=2.5)
        ax.plot(r["gap"], y, "o", color=color, markersize=7)
    ax.axvline(0, color="#333", linewidth=0.8)
    ax.legend(handles=[plt.Line2D([], [], color=col, marker="o", linewidth=2.5, label=f"route: {name}")
                       for name, col in route_colors.items()],
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
    for m, a, lab in present:
        st = stats[(m, a)]
        for p in st["per_rep"]:
            ax.plot(p["cost_usd"], p["macro"], "o", color=COLORS[(m, a)], alpha=0.35, markersize=5)
        ax.plot(st["cost_per_run"], st["macro"], "D", color=COLORS[(m, a)], markersize=9, label=lab)
    ax.set_xscale("log")
    ax.set_xlabel("list-price cost of one 74-item run, USD (log scale)")
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
    turns = {s[:2]: defaultdict(list) for s in present}
    for subj in turns:
        for r in ROWS:
            if (r["model"], r["arm"]) == subj and r["id"] in ag:
                turns[subj][r["id"]].append(r["num_turns"] or 0)
    fig, ax = plt.subplots(figsize=(11, 4.2))
    prim = [s for s in present if s[1] == "default"]
    w = 0.8 / len(prim)
    for k, (m, a, lab) in enumerate(prim):
        xs = [i + (k - (len(prim) - 1) / 2) * w for i in range(len(ag))]
        ax.bar(xs, [mean(turns[(m, a)][i]) or 0 for i in ag], w, label=lab, color=COLORS[(m, a)])
    ax.set_xticks(range(len(ag)), [f"{i}\n{items[i]['mode']}" for i in ag], fontsize=8)
    ax.set_ylabel("turns (mean across reps)")
    ax.set_title("Agentic items: turns taken per call")
    ax.legend(fontsize=8, frameon=False)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIGS / "agentic_turns.png", dpi=150)
    plt.close(fig)
    written.append("agentic_turns.png")
    return written


ROWS: list[dict] = []


def main() -> int:
    if not SCORES.exists():
        sys.exit("no results/scores.jsonl; run grade.py first")
    items = {it["id"]: it for it in map(json.loads, ITEMS.read_text(encoding="utf-8").splitlines())}
    MODE_OF.update({it["category"]: it["mode"] for it in items.values()})
    ROWS.extend(json.loads(line) for line in SCORES.read_text(encoding="utf-8").splitlines())
    assert all(r["rep"] > 0 for r in ROWS), "pilot rows (rep 0) must not be analysed"

    groups = defaultdict(list)
    for r in ROWS:
        groups[(r["model"], r["arm"])].append(r)
    stats = {subj: subject_stats(groups[subj], items) for subj in (s[:2] for s in SUBJECTS)
             if groups.get(subj)}
    if HAIKU not in stats or SONNET not in stats:
        sys.exit("need both Haiku and Sonnet default-arm scores")
    cmp = compare(stats, items)
    hyp = hypotheses(stats, cmp, ROWS)

    SUMMARY.write_text(json.dumps({
        "subjects": {label(s): {k: v for k, v in st.items() if k != "item_means"}
                     for s, st in stats.items()},
        "item_means": {label(s): st["item_means"] for s, st in stats.items()},
        "haiku_vs_sonnet": cmp, "hypotheses": hyp,
        "routing_rule": {"haiku_at_or_above": ROUTE_HAIKU, "check_at_or_above": ROUTE_CHECK},
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    TABLES.write_text(tables(stats, cmp, hyp), encoding="utf-8")
    figs = figures(stats, cmp, items)
    print(f"{len(ROWS)} rows, {len(stats)} subjects -> {SUMMARY.relative_to(HERE)}, "
          f"{TABLES.relative_to(HERE)}, figures/{{{','.join(figs)}}}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
