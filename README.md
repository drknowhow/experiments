# Experiments

Benchmarks and experiments from building [Yep](https://yepgent.com), a
personal agent that runs on Claude, and
[C3](https://github.com/drknowhow/code-context-control), its code-context
toolkit. Each one answers a question we needed answered for our own work,
such as which model a subtask should go to. We publish the design, the
code, the raw outputs and the results, including results that did not go
the way we expected.

The format follows [oaustegard/experiments](https://github.com/oaustegard/experiments).

## Index

| Date | Experiment | Question | Result |
|---|---|---|---|
| 2026-10-17 | [haiku-delegation-bench](haiku-delegation-bench/RESULTS.md) | How much does an agent lose by delegating bounded subtasks to Claude Haiku 5.5 instead of Sonnet 5.5? | On 74 bounded tasks Haiku scored 0.996 against Sonnet's 1.000 at about 1/17 of the list cost, and every category routes to Haiku. The set was too easy to separate the models; on private email triage Haiku trailed Sonnet, 84.7% against 91.7%. |
| 2026-10-18 | [haiku-delegation-bench-hard](haiku-delegation-bench-hard/RESULTS.md) | Do harder delegations (log joins, multi-hop navigation, subtle review bugs, multi-file edits, superseded thread values, near-miss abstention) separate Haiku 5.5 from Sonnet 5.5? | No. Opus scored 1.000, Sonnet 0.994 and Haiku 0.968 at about 1/16 of Sonnet's list cost, so the tier failed its pre-registered purpose. Five of six categories route to Haiku; abstention routes to Haiku with a check, mostly because of one item. |

## Layout

Each experiment has its own directory:

- `DESIGN.md`: the question, items, scoring and hypotheses, written
  before any model is called.
- `RESULTS.md`: what happened, including which hypotheses held.
- The code that builds the items, runs the models, grades the replies and
  draws the figures, and the raw outputs it graded.

Code shared by more than one experiment lives in [`_lib/`](_lib).
[METHODS.md](METHODS.md) describes the practices every experiment follows:
pre-registration, deterministic graders, reps, how cost is measured and how
private data is handled.

## License

MIT. See [LICENSE](LICENSE).
