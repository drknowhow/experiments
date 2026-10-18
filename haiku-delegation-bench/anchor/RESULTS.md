# Anchor: private email triage (aggregates only)

300 emails from our production triage pipeline, each with one of seven
labels assigned by Claude Opus. Every email went through `claude -p` on its
own (subject, sender and the first 1,500 body characters), with the
production triage prompt as the system prompt. The emails, the per-row
outputs and the prompt stay on the private machine. This file and
`summary.json` hold only aggregates, produced by `run_anchor.py score`.

The labels are Opus's, so accuracy here means agreement with Opus, not
agreement with a person.

## Result

| Model | Correct | Accuracy (Wilson 95%) | Macro F1, classes n ≥ 15 | Cost per call (list price) | Seconds per call |
|---|---|---|---|---|---|
| Haiku 5.5 | 254 / 300 | 84.7% [80.2, 88.3] | 0.826 | $0.00038 | 4.0 |
| Sonnet 5.5 | 275 / 300 | 91.7% [88.0, 94.3] | 0.904 | $0.00722 | 4.5 |

Paired on the same emails, Sonnet was right where Haiku was wrong 28 times
and the reverse happened 7 times (exact McNemar p = 0.0005). Every call
returned a valid label. One Sonnet call crashed in the CLI and was rerun
once, as METHODS.md allows.

Haiku reaches 92% of Sonnet's accuracy. Under the routing rule used for the
public categories, that puts email triage in the "Haiku, with a check on its
output" band. At list price Sonnet costs about 19 times as much per email.

## Per class

| Class | Support | Haiku P / R / F1 | Sonnet P / R / F1 |
|---|---|---|---|
| newsletter | 115 | 0.98 / 0.90 / 0.94 | 0.97 / 0.97 / 0.97 |
| alert | 79 | 0.82 / 0.85 / 0.83 | 0.99 / 0.90 / 0.94 |
| agent_actionable | 44 | 0.95 / 0.93 / 0.94 | 0.95 / 0.93 / 0.94 |
| action_required | 34 | 0.51 / 0.71 / 0.59 | 0.64 / 0.94 / 0.76 |
| receipt | 13 | 0.76 / 1.00 / 0.87 | 1.00 / 1.00 / 1.00 |
| calendar | 13 | 1.00 / 0.31 / 0.47 | 0.83 / 0.38 / 0.53 |
| spam | 2 | 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 |

Receipt, calendar and spam have fewer than 15 rows and are not interpreted.

Most of the gap is in two classes. Haiku labels 47 emails
`action_required` where Opus labels 34, and it finds only 24 of those 34,
so the "a person must act" class is the least reliable one. Haiku also
confuses `alert` with other classes more often than Sonnet does. On
`agent_actionable`, the class that triggers work by the agent, the two
models score the same.

## H5

**Supported.** Haiku 5.5's interval (80.2–88.3%) sits above Haiku 4.5's
68.3%, and Haiku 5.5 is below Sonnet 5.5 with p = 0.0005.

The 68.3% comes from an earlier run of our pipeline that sent 50 emails per
call, while this run sends one. The comparison is the one we pre-registered,
but it compares across two setups as well as two models.

## Earlier numbers on the same 300 emails, for context

| System | Setup | Accuracy |
|---|---|---|
| Haiku 4.5 | 50 emails per call | 68.3% |
| Sonnet 5 | 50 emails per call | 88.3% |
| Our fine-tuned ModernBERT classifier | one email at a time | 86.7% |
| Haiku 5.5 (this run) | one email per call | 84.7% |
| Sonnet 5.5 (this run) | one email per call | 91.7% |

Sonnet 5 and Sonnet 5.5 are different models. On a separate set of 600
emails, Haiku 5.5 at 50 emails per call scored 91.5% [89.2, 93.7]; that set
is not this one, so the two Haiku 5.5 numbers can't be compared directly.

## Known differences from production

- The production prompt was written for batches. It still contains a
  sentence telling the model to judge each email on its own even though it
  arrives in a batch, and it refers to a later pipeline step. We used it
  verbatim rather than edit it per model.
- Production sees the full body; this run cuts it at 1,500 characters for
  both models.

## Reproduce

The script needs the private gold file and prompt, so only we can rerun it:

```
python anchor/run_anchor.py run   --gold <gold.jsonl> --contract <prompt.txt> --private-dir <outside-repo> --model claude-haiku-5-5
python anchor/run_anchor.py run   --gold <gold.jsonl> --contract <prompt.txt> --private-dir <outside-repo> --model claude-sonnet-5-5
python anchor/run_anchor.py score --gold <gold.jsonl> --private-dir <outside-repo> --models claude-haiku-5-5 claude-sonnet-5-5
```

`run` refuses a `--private-dir` inside this repository.
