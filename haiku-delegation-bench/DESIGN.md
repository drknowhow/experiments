# Design (pre-registered 2026-10-17, before any model was run)

## Question

When a coding agent hands a bounded subtask to a cheaper model, how much does
it lose by choosing Claude Haiku 5.5 instead of Sonnet 5.5? We want the answer
for each kind of subtask our agents actually delegate, not one overall score.

## Subjects

| Model | Role | Reps |
|---|---|---|
| `claude-haiku-5-5` | subject | 3 |
| `claude-sonnet-5-5` | baseline | 3 |
| `claude-opus-5-5` | ceiling, and a check on the gold | 1 |

All calls go through `claude -p` with the flags and system prompts that C3's
`c3_delegate` uses (see `_lib/claude_runner.py`). Default effort, no extended
thinking override. Each call starts fresh: no session persistence, no
CLAUDE.md, no hooks, no MCP servers.

## Categories (74 items)

| Category | n | Mode | What the delegator wants | Gold comes from |
|---|---|---|---|---|
| classify | 10 | single | apply a written triage policy to one notification | the policy, applied by hand; each item hits one precedence rule |
| extract | 8 | single | pull fields from a messy message into a schema; missing → null | hand-written messages with known fields |
| diff-summary | 6 | single | summarize a real commit diff with its message removed | the commit's files and conventional-commit prefix |
| code-qa | 8 | single | predict what a tricky Python snippet prints | executing the snippet |
| traceback | 6 | single | find the root cause of a traceback in a small multi-file project | executing the project; root cause seeded |
| log-triage | 6 | single | answer a counting/lookup question over a ~250-line log | computed from the generator's own events |
| abstain | 8 | single | answer from a document; half the questions are not answerable | the document; `NOT_FOUND` for unanswerable |
| code-review | 6 | single | find the one seeded bug in a diff with benign changes; one diff has no bug | the seeded line |
| code-nav | 10 | scout | look things up in a real repo with Read/Grep/Glob | grep/AST over the pinned checkout |
| code-edit | 6 | worker | make a specified change in a mini-project | hidden tests run after the edit |

Fixture repo for code-nav and diff-summary: the public
[code-context-control](https://github.com/drknowhow/code-context-control)
repository at `931cb4de72b140a39130e8c7c06a86f25bf6c310`.

## Answer contract and scoring

Every item ends by asking for one JSON object in a fenced block. `grade.py`
takes the last fenced JSON block (falling back to the last `{...}` in the
reply). No JSON, or JSON missing a required key, is a **format failure** and
scores 0.

| Category | Score per item |
|---|---|
| classify | 1 if `label` matches, else 0 |
| extract | fraction of fields matching after normalization; an **invention** is a non-null value where gold is null |
| diff-summary | 0.4 × file-set Jaccard + 0.3 × change-type match + 0.3 × fraction of gold keywords present in the summary |
| code-qa | 1 if `answer` matches after whitespace normalization |
| traceback | 0.25 exception type + 0.25 root-cause file + 0.5 root-cause line (±1) |
| log-triage | 1 if `answer` matches exactly (numbers compared as numbers) |
| abstain | answerable: 1 if correct; unanswerable: 1 if `NOT_FOUND`. Answering an unanswerable is an **invention**; `NOT_FOUND` on an answerable is an **over-abstain** |
| code-review | bug found (±2 lines) and no false positives = 1; found with false positives = 0.5; missed = 0. No-bug item: 1 only if the list is empty |
| code-nav | 1 if the answer matches (file path match + line ±2 where asked); unanswerable: 1 only for `NOT_FOUND` |
| code-edit | hidden tests pass AND only write-set files changed AND test files untouched = 1; tests pass but out-of-set edits = 0.5; else 0 |

**Grader self-test.** Before any grading, `grade.py --self-test`
synthesizes a perfect reply from each item's gold and a wrong reply, and
asserts perfect = 1 and wrong < 1 for every item. The code-edit fixtures are
checked the same way: the reference solution passes the hidden tests and the
untouched workspace fails them.

**Gold check.** An item every model fails, including Opus, is re-examined for
bad gold before the results are written up. Any change is logged in RESULTS.md.

## Measures

Per model and category: mean score (with the spread across reps), API-
equivalent cost as reported by the CLI (`total_cost_usd`), input/output/
thinking tokens, CLI duration and wall time, turns (agentic modes), format
failures, invention rate, and agreement across reps.

Cost is the CLI's list-price figure. Our calls bill against a subscription,
so the dollar column is a relative measure of load, not money spent.

## Hypotheses

- **H1.** On mechanical categories (classify, extract, code-qa, log-triage)
  Haiku scores at least 95% of Sonnet's score.
- **H2.** The gap widens on judgment categories (code-review, traceback,
  abstain, diff-summary).
- **H3.** Haiku invents more often than Sonnet (extract nulls, abstain,
  code-nav `NOT_FOUND`).
- **H4.** In agentic modes Haiku takes more turns than Sonnet, which shrinks
  its per-task cost advantage.
- **H5.** On our private email-triage anchor (300 rows, labels from Opus),
  Haiku 5.5 beats Haiku 4.5's 68.3% and stays below Sonnet.

## Anchor (private data, aggregates only)

The 300-email triage set from our production pipeline (seven labels, Opus
gold) is run per item through the same harness with the production prompt,
for Haiku 5.5 and Sonnet 5.5. Emails never leave the private machine and are
not committed. `anchor/` holds only aggregate accuracy and per-class support.
Thin classes (n < 15) are reported but not interpreted.

## Out of scope

Extended-thinking budgets, prompt tuning per model, other providers, and
tasks longer than one bounded delegation. Each of these is a separate
experiment.

## Pre-run additions (2026-10-17, still before any model call)

Settled while writing `grade.py` and `run.py`. None of them was informed by
a model's output.

**Prompt assembly.** Each item is the call C3 v2.157.2's `c3_delegate`
makes. For `single` and `scout` items the system prompt is the task type's
system line followed by the mode's rules, and the prompt is the task type's
template filled with the context and the task. `code-edit` items use C3's
worker system prompt and write-mode prompt, a 600 s timeout, and a
permission rule that allows edits only to the write set.

| Category | C3 task type |
|---|---|
| classify, extract, abstain, log-triage, code-nav | `ask` |
| diff-summary | `summarize` |
| code-qa | `explain` |
| traceback | `diagnose` |
| code-review | `review` |
| code-edit | worker (write mode) |

The scout runs inside the pinned checkout. Each worker call gets a fresh
temporary copy of its item's workspace, and the files left there afterwards
(caches excluded) are what `code-edit` is graded on.

**Grader details.**
- Text is compared lower-cased with whitespace collapsed; code-qa answers
  also treat `"` and `'` as the same character.
- extract: phone numbers are compared as digits (a leading country code 1
  is allowed), and a time written `HH:MM:00` matches `HH:MM`.
- log-triage: a lookup whose gold is an id or a timestamp scores when that
  token appears in the answer; the two-job question compares sets.
- traceback: the line credit needs the right file, because a line number
  in another file points at a different line.
- code-nav: a reply path matches when it ends with the gold path. The
  `--effort` question needs exactly the five levels.
- code-edit: e6 is a trap where half the task needs a file outside the write
  set. Passing the tests without saying in the report that `checkout.py`
  needs the rest of the change scores 0.5.
- A call that fails (timeout, CLI error) scores 0 and is counted apart from
  format failures.

**Timeouts and retries.** Each call gets C3's own limit for its mode:
120 s for `single`, 240 s for `scout`, 600 s for `worker`
(`claude_timeout`, `claude_scout_timeout`, `claude_write_timeout`). A
timeout is the model's result under those limits and scores 0. A call that
fails for any other reason (the CLI crashing, a reply the harness cannot
parse as CLI JSON) is rerun once with `run.py --retry-errors`; both rules
were in `run.py` before the 12-item pilot (rep 0, never analysed).

**Exploratory arm: Haiku with C3's thinking cap.** C3 caps the small tier at
`MAX_THINKING_TOKENS=1024` by default (`core/config.py:312` in the fixture
repo), so Haiku delegations in production run capped. One extra Haiku rep
runs with that cap. It is labelled exploratory and no hypothesis depends on
it. The primary comparison stays uncapped for all three models, as
registered above.
