# Working in this repository

This repository is public. Read METHODS.md before adding anything.

## Adding an experiment
- Create a kebab-case directory named for the question.
- Write DESIGN.md (question, items, scoring, hypotheses) and commit it
  before the first model call.
- Put shared code in _lib/ only when a second experiment needs it.
- Raw model outputs go in results/raw/. Never edit generated files
  (tables, summaries, figures) by hand; rerun the script.
- Write RESULTS.md last, then add a row to the README index.

## Never commit
- Private inputs. Pass them by path and commit aggregates only.
- Local paths, usernames or machine names. Run
  `python _lib/sanitize.py check` before every commit.
- Credentials, or production prompts that name private resources.

## Gold
Change gold only through the gold check in METHODS.md, and log every
change in RESULTS.md with the item id and the reason.

## Publishing
Nothing is pushed until the owner has reviewed it.
