"""code-nav: look something up in a real repository with Read, Grep and Glob.

The scout runs inside a clean checkout of a public repository pinned to one
commit. Every gold value is asserted against that checkout when the items are
built, and the two unanswerable questions are asserted absent."""
from __future__ import annotations

import subprocess

from common import NAV_REPO_DIR, NAV_REPO_SHA, item, json_contract

SHAPE = ('{"answer": "<value, or NOT_FOUND>", "file": "<repo-relative path or null>", '
         '"line": <line number or null>}')

# id, question, gold, check: (path, line, substring that line must contain) or
# ("absent", grep pattern)
NAV = [
    ("N1", "Where is the function parse_write_paths defined? Give its file and the "
     "line of its def.",
     {"answer": None, "file": "services/delegate_write.py", "line": 47},
     ("services/delegate_write.py", 47, "def parse_write_paths(")),
    ("N2", "Where is claude_thinking_cap_for defined? Give its file and the line of its def.",
     {"answer": None, "file": "cli/tools/delegate.py", "line": 510},
     ("cli/tools/delegate.py", 510, "def claude_thinking_cap_for(")),
    ("N3", "Where is the class ScheduleStore defined? Give its file and the line of "
     "its class statement.",
     {"answer": None, "file": "services/schedule_store.py", "line": 281},
     ("services/schedule_store.py", 281, "class ScheduleStore:")),
    ("N4", "What is the default thinking-token cap for the small delegation tier? "
     "Answer with the number.",
     {"answer": "1024", "file": None, "line": None},
     ("core/config.py", 312, '"claude_tier_thinking_tokens": {"small": 1024}')),
    ("N5", "What is the default value of MAX_WRITE_PATHS? Answer with the number.",
     {"answer": "50", "file": None, "line": None},
     ("services/delegate_write.py", 38, "MAX_WRITE_PATHS = 50")),
    ("N6", 'Which function raises the error "No project specified -- pass a registered '
     'name or a path."? Answer with the function name.',
     {"answer": "resolve_project", "file": "services/project_runtime.py", "line": None},
     ("services/project_runtime.py", 169, "No project specified -- pass a registered name or a path.")),
    ("N7", 'Which function or method raises the error "Unknown judge CLI"? Answer with '
     "its name.",
     {"answer": "_build_judge_command", "file": "services/e2e_evaluator.py", "line": None},
     ("services/e2e_evaluator.py", 398, "Unknown judge CLI")),
    ("N8", "Which --effort levels does the delegate accept for Claude? Answer with the "
     "levels, comma-separated.",
     {"answer_set": ["low", "medium", "high", "xhigh", "max"], "file": None, "line": None},
     ("cli/tools/delegate.py", 496, '_EFFORT_LEVELS = frozenset({"low", "medium", "high", "xhigh", "max"})')),
    ("N9", "Where is the function compute_embedding_drift defined? Give its file and "
     "the line of its def.",
     {"answer": "NOT_FOUND", "file": None, "line": None},
     ("absent", "compute_embedding_drift")),
    ("N10", "What is the default value of the config key delegate_max_retries?",
     {"answer": "NOT_FOUND", "file": None, "line": None},
     ("absent", "delegate_max_retries")),
]


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(NAV_REPO_DIR), *args], capture_output=True,
                          text=True, encoding="utf-8")


def _check(qid: str, check: tuple) -> None:
    head = _git("rev-parse", "HEAD").stdout.strip()
    assert head == NAV_REPO_SHA, f"fixture repo at {head}, expected {NAV_REPO_SHA}"
    if check[0] == "absent":
        hits = _git("grep", "-n", check[1]).stdout.strip()
        assert not hits, f"{qid}: {check[1]!r} is not absent:\n{hits}"
        return
    path, line, needle = check
    text = (NAV_REPO_DIR / path).read_text(encoding="utf-8").split("\n")
    assert needle in text[line - 1], f"{qid}: {path}:{line} is {text[line - 1]!r}"


def items() -> list[dict]:
    out = []
    for qid, question, gold, check in NAV:
        _check(qid, check)
        out.append(item(qid, "code-nav", question + json_contract(SHAPE), gold, "nav",
                        task_type="ask", mode="scout",
                        tags=("judgment",) if gold.get("answer") == "NOT_FOUND" else ("mechanical",),
                        answerable=gold.get("answer") != "NOT_FOUND"))
    return out
