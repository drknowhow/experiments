"""diff-summary: summarize a real commit from the pinned fixture repo with its
message removed. Gold files and type come from the commit itself; keyword
groups are any-of substrings a correct summary would contain."""
from __future__ import annotations

import subprocess

from common import NAV_REPO_DIR, item, json_contract

TYPES = ["feat", "fix", "refactor", "perf", "docs", "test", "chore"]

# sha, gold type, keyword groups (each group: any one substring counts)
COMMITS = [
    ("1141056", "fix", [["totp", "2fa", "seed", "one-time"], ["digit"],
                        ["regex", "character class", "range", "re.sub", "pattern"]]),
    ("541d6cf", "test", [["sleep"], ["wait", "poll"], ["flaky", "flak", "race", "timing"]]),
    ("914ea05", "feat", [["version"], ["tab"], ["persist", "preference", "restore", "remember"]]),
    ("b457b80", "docs", [["lock"], ["readme", "front page", "documentation", "docs"],
                         ["access guard", "opt-out", "opt out", "built-in", "built in"]]),
    ("6435f74", "fix", [["numpy"], ["main thread", "import"], ["hang", "deadlock", "freeze", "hung", "block"]]),
    ("ebeae14", "chore", [["gitignore", "ignore"], [".claude", ".codex", "agent", "ide", "editor"],
                          ["pycache", "python", "cache", "build", "artifact", "ghost", "runtime"]]),
]


def _git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(NAV_REPO_DIR), *args], capture_output=True,
                          text=True, encoding="utf-8", check=True).stdout


def items() -> list[dict]:
    out = []
    for n, (sha, ctype, keywords) in enumerate(COMMITS, 1):
        diff = _git("show", "--format=", "--no-color", sha).strip()
        files = [f for f in _git("show", "--format=", "--name-only", sha).split("\n") if f.strip()]
        task = ("Summarize this commit for a changelog. The commit message has been "
                "removed; work from the diff alone. "
                f"change_type is one of: {', '.join(TYPES)} (conventional-commit "
                "meaning). summary is one or two sentences saying what changed and why."
                + json_contract('{"files_changed": ["path", ...], "change_type": "...", '
                                '"summary": "..."}'))
        gold = {"files": files, "change_type": ctype, "keywords": keywords}
        out.append(item(f"d{n:02d}", "diff-summary", task, gold, "diff_summary",
                        context=f"```diff\n{diff}\n```", task_type="summarize",
                        tags=("judgment",), sha=sha))
    return out
