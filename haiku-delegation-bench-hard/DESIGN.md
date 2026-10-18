# Design (pre-registered 2026-10-18, before any model was run)

## Question

The first benchmark ([haiku-delegation-bench](../haiku-delegation-bench/DESIGN.md))
was too easy: on its 74 bounded tasks Opus 5.5 and Sonnet 5.5 both scored
1.000 and Haiku 5.5 scored 0.996, so it could not say where delegating to
Haiku costs anything. Our private email-triage anchor did separate them
(Haiku 84.7%, Sonnet 91.7%, McNemar p = 0.0005).

This experiment asks the same question on harder delegations: **on bounded
subtasks that need state tracking, joins, multi-hop lookups or careful
abstention, how much does an agent lose by sending the work to Haiku 5.5
instead of Sonnet 5.5, and where is the loss?** Opus 5.5 is the ceiling.

## Subjects

| Model | Role | Reps |
|---|---|---|
| `claude-haiku-5-5` | subject | 3 |
| `claude-sonnet-5-5` | baseline | 3 |
| `claude-opus-5-5` | ceiling, and a check on the gold | 1 |

Same harness as the first benchmark: `claude -p` with the flags and system
prompts of C3's `c3_delegate` (C3 v2.157.2; `_lib/claude_runner.py`),
default effort, no thinking cap, no session persistence, no CLAUDE.md, hooks
or MCP servers. Timeouts are C3's: 120 s single, 240 s scout, 600 s worker.
A timeout scores 0; any other call failure is rerun once.

## Categories (60 items)

| Category | n | Mode | C3 task type | What the delegator wants | Gold comes from |
|---|---|---|---|---|---|
| log-join | 10 | single | `ask` | answer a question over a 600–900-line multi-service log that needs a join: across services by request or trace id, across event types (started/finished, charged/shipped/refunded), or within a time window set by other events | computed from the generator's own events, never by parsing its output |
| nav-multihop | 10 | scout | `ask` | follow a chain of two or three lookups across files in a real repository (a caller to its helper to a config default; a constant to every place that uses it); 2 of 10 are unanswerable and name something close to a real symbol or key | AST and `git grep` over the pinned checkout, asserted when the items are built |
| review-subtle | 10 | single | `review` | find a behavioural bug in a 100–200-line diff that also makes three or more benign changes; the bugs are the kind a careful reader catches (generator reused after exhaustion, `lstrip` used as a prefix strip, late-binding closure, inclusive/exclusive boundary, naive vs aware datetime); 2 of 10 have no bug | the seeded line, plus an executable check per item that passes on the old file and fails on the new one (no-bug items: passes on both) |
| edit-multifile | 10 | worker | worker | make one change that must land consistently in 2–4 files of a 5–9-file project (a new field threaded through model, storage and API; a new enum value handled everywhere; a moved function and its imports); 2 of 10 need a file outside the write set, and the worker must say so | hidden tests; the build asserts they fail on the untouched project, pass with the reference solution, and that the solution stays in the write set |
| thread-supersede | 10 | single | `ask` | pull the final agreed values out of an email or chat thread of 8–20 messages in which later messages change, retract, or quote earlier values, and some proposals are never accepted; a field that ends up unsettled is null | computed by applying each message's structured operations in order; the build asserts each final value appears in the message that set it, and that at least two fields per thread changed after first being stated |
| abstain-nearmiss | 10 | single | `ask` | answer from a 1,500–3,000-word document; 6 of 10 questions are unanswerable but the document holds a near miss (another version, environment or log type), 4 are answerable only through a table, a condition or a footnote | the document; the build asserts the near miss is present and the asked fact absent, and that answerable gold appears in the text |

Fixture repository for nav-multihop: the public
[code-context-control](https://github.com/drknowhow/code-context-control)
repository at `931cb4de72b140a39130e8c7c06a86f25bf6c310`, the same checkout
the first benchmark used.

All names, companies, addresses and threads are invented. Items that involve
dates state today's date in the prompt, because the CLI adds the machine's
real date to every call.

Item difficulty is fixed by construction before any model call. No item is
dropped, rewritten or reweighted because a model found it easy or hard; the
only route for changing an item after a run is the gold check below.

## Answer contract and scoring

Every item ends by asking for one JSON object in a fenced block. The reply
parser is the first benchmark's: the last fenced JSON block, falling back to
the last top-level `{...}`. No JSON, or JSON missing a required key, is a
**format failure** and scores 0. A failed call scores 0 and is counted apart.

| Category | Score per item |
|---|---|
| log-join | 1 if `answer` matches exactly (numbers as numbers, sets as sets, an id or timestamp when the token appears), else 0 |
| nav-multihop | fraction of requested fields correct (a path matches when the reply path ends with it; lines ±2). Unanswerable: 1 only for `NOT_FOUND`; any other answer is an **invention** |
| review-subtle | bug found (±2 lines) with no false positives = 1; found with false positives = 0.5; missed = 0. No-bug item: 1 only if the list is empty |
| edit-multifile | hidden tests pass AND only write-set files changed AND protected files untouched = 1; tests pass but out-of-set edits, or a trap item whose report does not name the outside file = 0.5; else 0 |
| thread-supersede | fraction of fields matching after normalization; a non-null value where gold is null is an **invention** |
| abstain-nearmiss | answerable: 1 if correct; unanswerable: 1 if `NOT_FOUND`. Answering an unanswerable is an **invention**; `NOT_FOUND` on an answerable is an **over-abstain** |

**Build fails on bad gold.** `build.py` runs every generator's assertions
(the checks in the gold column above) and refuses to write
`fixtures/items.jsonl` if any fails or the item count is not 60.

**Grader self-test.** `grade.py --self-test` synthesizes a perfect reply and
a wrong reply from each item's gold and asserts perfect = 1 and wrong < 1 for
every item, that a reply with no JSON is a format failure scoring 0, and
that a failed call scores 0.

**Gold check.** An item every model fails, Opus included, is re-examined for
bad gold before the write-up. Any change is logged in RESULTS.md with the
item id and the reason.

## Measures

Per model and category: mean score with the spread across reps, list-price
cost from the CLI (`total_cost_usd`; calls bill against a subscription, so
compare ratios, not dollars), input/output/thinking tokens, wall time, turns
in agentic modes, format failures, inventions, over-abstains, and agreement
across reps.

**Statistics.** Macro score = mean of the six category means. The Haiku–Sonnet
gap, overall and per category, gets a 95% paired-bootstrap percentile
interval over items (each item's mean across reps; 10,000 resamples, seed
20261017; the macro gap resamples within each category). Proportions get
Wilson 95% intervals. Secondary: an exact two-sided McNemar test on per-item
pass, where Haiku or Sonnet passes an item when it scores 1.0 on at least two
of its three reps.

**Routing rule** (METHODS.md, unchanged): per category, Haiku when its score
is at least 95% of Sonnet's and it invents no more often; Haiku with a check
on its output between 85% and 95% (or at 95%+ with more inventions); Sonnet
below 85%.

## Hypotheses

- **H1 (separation).** Sonnet's macro score exceeds Haiku's by at least
  0.05, and the 95% interval of the gap excludes 0.
- **H2 (not saturated).** Opus's macro score is at most 0.95. If Opus and
  Sonnet both reach 0.97, the tier has failed its purpose and is reported
  that way, not reworked after the fact.
- **H3 (ordering).** Opus ≥ Sonnet ≥ Haiku on macro score.
- **H4 (where the gap is).** The largest Sonnet–Haiku category gap is in
  thread-supersede or log-join, the two categories that need state tracked
  across long text, as in the email anchor.
- **H5 (inventions).** Haiku invents more often than Sonnet across the
  invention opportunities (unanswerable abstain-nearmiss and nav-multihop
  items, null fields in thread-supersede).
- **H6 (routing).** At least two of the six categories route away from plain
  Haiku ("Haiku + check" or "Sonnet").
- **H7 (agentic cost).** Sonnet's cost per call over Haiku's is smaller in
  scout and worker modes than in single mode, as more turns eat into
  Haiku's price advantage.

## Pilot

Before rep 1, one item per category runs as rep 0 to check the harness
(prompts reach the CLI, scout cwd and worker write rules work on
multi-file workspaces, replies parse). Pilot replies are never analysed and
never inform items or gold. Any harness change made after the pilot is
logged below under a dated heading that says the pilot informed it.

## Shared code

Prompt assembly (C3's system lines, templates and worker prompt) and the
reply parser move from the first benchmark into `_lib/`, unchanged, because
this experiment needs them too. The move is verified by rebuilding the first
benchmark's `fixtures/items.jsonl` and regrading its `results/scores.jsonl`
byte for byte.

## Out of scope

Thinking caps (the first benchmark's capped arm), prompt tuning per model,
other providers, the private anchor (already run), and multi-step
delegations. Each is a separate experiment.
