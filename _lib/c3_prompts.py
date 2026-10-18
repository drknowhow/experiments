"""C3 delegation prompts, assembled the way C3's `c3_delegate` assembles them
(cli/tools/delegate.py, C3 v2.157.2): system = the task type's system line +
the mode's rules, prompt = the task type's template; worker prompts use the
write-mode layout. So each benchmark item is the call a coding agent makes."""
from __future__ import annotations

import json
from pathlib import Path

DELEGATE_SYSTEM = (
    "You are a delegate answering one bounded request for another agent. You "
    "have no tools and cannot open files, run commands or browse: everything "
    "you know about the code is in the text below. If that text is not enough "
    "to answer, say exactly what is missing instead of guessing."
)

SCOUT_SYSTEM = (
    "You are a read-only scout answering one bounded request for another agent. "
    "You can use Read, Grep and Glob inside this repository and nothing else: no "
    "edits, no commands, no network. Look up only what the request needs, then "
    "answer concisely with file:line references. A file you are refused is off "
    "limits; do not try to reach it another way. If you cannot find the answer, "
    "say so instead of guessing."
)

WORKER_SYSTEM = (
    "You are a worker making one code change that a lead agent has already "
    "decided. You have Read, Grep, Glob, Edit and Write in this repository and "
    "nothing else: no commands, no tests, no network. Do exactly the change the "
    "task describes: no refactors, renames, reformatting or extras it did not "
    "ask for. Edit or create only paths in the write set; a refused path is off "
    "limits, do not reach it another way. Read a file before editing it and "
    "match its style. If the task is ambiguous, contradicts the code, or needs a "
    "file outside the write set, do the part you can do safely and report the "
    "rest instead of guessing. Make the edits first, then finish with a short "
    "report: each file changed and what changed, anything left undone and why, "
    "and any assumption the lead should check. The lead reviews your diff and "
    "runs the tests."
)

# C3 DELEGATE_TASKS entries the benchmark uses: (system line, prompt template).
C3_TASKS = {
    "summarize": ("You are a concise technical summarizer. Keep the answer compact and concrete.",
                  "Context:\n{context}\n\nTask:\n{task}\n\n"
                  "Return a compact summary with only the key points."),
    "explain": ("You explain code precisely and concisely. Prefer short bullet points and specific references.",
                "Context:\n{context}\n\nQuestion:\n{task}\n\n"
                "Explain only what is needed to answer the question."),
    "review": ("You are a pragmatic code reviewer. Prioritize bugs, regressions, and missing tests.",
               "Context:\n{context}\n\nReview task:\n{task}\n\n"
               "Return the most important findings first."),
    "ask": ("Answer narrowly and directly from the provided context.",
            "Context:\n{context}\n\nQuestion:\n{task}\n\nAnswer concisely."),
    "diagnose": ("You diagnose failures from logs and execution context. Focus on root cause and next step.",
                 "Context:\n{context}\n\nProblem:\n{task}\n\n"
                 "Identify the most likely cause and the next debugging step."),
}

WORKER_TIMEOUT_S = 600  # C3 claude_write_timeout default


def worker_prompt(task: str, write_paths, context: str = "") -> str:
    """C3's write-mode prompt layout."""
    return ("WRITE SET (the only paths you may edit or create, relative to the "
            "repository root):\n" + "\n".join(f"- {g}" for g in write_paths)
            + f"\n\nTIME: you are stopped after {WORKER_TIMEOUT_S}s."
            + f"\n\nTASK FROM THE LEAD AGENT:\n{task}"
            + f"\n\nCONTEXT:\n{context or '(none)'}")


def json_contract(shape: str) -> str:
    """The closing instruction every graded item ends with."""
    return ("\n\nEnd your reply with the answer as a single JSON object in a "
            f"```json fenced block, shaped exactly like: {shape}")


def numbered(source: str, start: int = 1) -> str:
    """Source with right-aligned line numbers, so line answers are unambiguous."""
    lines = source.rstrip("\n").split("\n")
    width = len(str(start + len(lines) - 1))
    return "\n".join(f"{i:>{width}} | {line}" for i, line in enumerate(lines, start))


def item(id: str, category: str, task: str, gold, grader: str, *, context: str = "",
         task_type: str = "ask", mode: str = "single", write_paths=(),
         tags: tuple[str, ...] = (), **extra) -> dict:
    """One benchmark item, with the exact system prompt and prompt to send."""
    if mode == "worker":
        system, prompt = WORKER_SYSTEM, worker_prompt(task, write_paths, context)
    else:
        line, template = C3_TASKS[task_type]
        rules = SCOUT_SYSTEM if mode == "scout" else DELEGATE_SYSTEM
        system = f"{line} {rules}"
        prompt = template.format(context=context or "(none)", task=task)
    d = {"id": id, "category": category, "mode": mode, "task_type": task_type,
         "system": system, "prompt": prompt, "gold": gold, "grader": grader,
         "tags": list(tags)}
    if write_paths:
        d["write_paths"] = list(write_paths)
    d.update(extra)
    return d


def dump(items: list[dict], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for it in items:
            fh.write(json.dumps(it, ensure_ascii=False) + "\n")
