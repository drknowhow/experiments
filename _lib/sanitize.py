"""Scrub machine-specific strings from raw outputs, and scan files before staging.

    python _lib/sanitize.py fix   <experiment>/results/raw/*.jsonl
    python _lib/sanitize.py check            # every file git would add

`fix` rewrites each string inside the JSON records: the repository root
becomes `<repo>`, a temporary workspace becomes `<tmp>`, the home directory
becomes `<home>`. Path suffixes are kept, so a grader that matches on the end
of a path scores the same before and after.

`check` lists every file git would commit (tracked plus untracked, honouring
.gitignore) and reports lines that match a private pattern. It exits 1 on a
hard hit. Soft hits (words that are also ordinary English) are printed for a
person to look at and do not fail the check.

The generic patterns below catch local paths. Patterns that would themselves
be private (names, usernames, internal file names) live in the gitignored
`_lib/sanitize.private`, one per line as `hard <regex>` or `soft <regex>`.
Without that file the check still runs on the generic patterns and says so.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

_SEP = r"[\\/]+"
FIXES = [
    (re.compile(r"(?i)\b[A-Z]:" + _SEP + r"Users" + _SEP + r"[^\\/\s\"'`]+" + _SEP
                + r"AppData" + _SEP + r"Local" + _SEP + r"Temp" + _SEP + r"(?:claude" + _SEP
                + r"[^\\/\s\"'`]+" + _SEP + r")?[^\\/\s\"'`]+"), "<tmp>"),
    (re.compile(r"(?i)\b[A-Z]:" + _SEP + r"Users" + _SEP + r"[^\\/\s\"'`]+"), "<home>"),
    (re.compile(r"(?i)\b" + re.escape(REPO.drive) + _SEP
                + _SEP.join(re.escape(p) for p in REPO.parts[1:])), "<repo>"),
]

PRIVATE = Path(__file__).with_name("sanitize.private")


def load_patterns() -> tuple[list[re.Pattern], list[re.Pattern], bool]:
    hard = [r"(?i)appdata[\\/]", r"(?i)\b[A-Z]:[\\/]+users[\\/]", r"\b[A-Z]:[\\/]"]
    soft: list[str] = []
    found = PRIVATE.is_file()
    if found:
        for line in PRIVATE.read_text(encoding="utf-8").split("\n"):
            kind, _, pat = line.strip().partition(" ")
            if kind == "hard" and pat:
                hard.append(pat)
            elif kind == "soft" and pat:
                soft.append(pat)
    return [re.compile(p) for p in hard], [re.compile(p) for p in soft], found


def scrub(value):
    if isinstance(value, str):
        for pat, rep in FIXES:
            value = pat.sub(rep, value)
        return value
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, dict):
        return {scrub(k): scrub(v) for k, v in value.items()}
    return value


def cmd_fix(paths: list[str]) -> int:
    for p in map(Path, paths):
        text = p.read_text(encoding="utf-8")
        if p.suffix == ".jsonl":
            rows = [json.loads(l) for l in text.split("\n") if l.strip()]
            new = "".join(json.dumps(scrub(r), ensure_ascii=False) + "\n" for r in rows)
        else:
            new = json.dumps(scrub(json.loads(text)), indent=2, ensure_ascii=False) + "\n"
        if new != text:
            p.write_text(new, encoding="utf-8")
            print(f"scrubbed {p}")
    return 0


def files_to_commit() -> list[Path]:
    out = subprocess.run(["git", "-C", str(REPO), "ls-files", "--cached", "--others",
                          "--exclude-standard"], capture_output=True, text=True, check=True)
    return [REPO / l for l in out.stdout.splitlines() if l.strip()]


def cmd_check() -> int:
    hard_re, soft_re, found = load_patterns()
    if not found:
        print(f"note: {PRIVATE.name} not found; checked the generic path patterns only")
    hard = soft = 0
    me = Path(__file__).resolve()
    for f in files_to_commit():
        if f.resolve() == me or f.suffix in {".png", ".jpg", ".pyc"}:
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        for n, line in enumerate(text.split("\n"), 1):
            for pat, kind in [(p, "HARD") for p in hard_re] + [(p, "soft") for p in soft_re]:
                m = pat.search(line)
                if m:
                    lo = max(m.start() - 40, 0)
                    print(f"{kind} {f.relative_to(REPO)}:{n}: …{line[lo:m.end() + 40]}…")
                    hard += kind == "HARD"
                    soft += kind == "soft"
    print(f"{hard} hard, {soft} soft hits")
    return 1 if hard else 0


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "fix":
        sys.exit(cmd_fix(sys.argv[2:]))
    if len(sys.argv) == 2 and sys.argv[1] == "check":
        sys.exit(cmd_check())
    sys.exit(__doc__)
