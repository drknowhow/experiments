"""traceback: find the root cause of a crash in a small multi-file project.

Each project is written to a temp dir and run, so the traceback is real. The
line that has to change is marked `# ROOT` in the source below; the marker is
stripped before the files are shown, and its line number becomes gold. Where
two lines are equally valid fixes, both are marked and either one scores."""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

from common import item, json_contract, numbered

MARK = "  # ROOT"

# id, exception type, entry file, {path: source}
PROJECTS = [
    ("t1", "TypeError", "main.py", {
        "settings.py": '''\
"""Runtime settings. Every value in DEFAULTS is an int (retries, timeout_s)."""

DEFAULTS = {
    "retries": "3",  # ROOT
    "timeout_s": 10,
}


def load(overrides=None):
    cfg = dict(DEFAULTS)
    cfg.update(overrides or {})
    return cfg
''',
        "retry.py": '''\
from settings import load


def with_retries(fn):
    cfg = load()
    last = None
    for attempt in range(cfg["retries"]):
        try:
            return fn()
        except ConnectionError as exc:
            last = exc
    raise last
''',
        "main.py": '''\
from retry import with_retries


def ping():
    return "pong"


print(with_retries(ping))
''',
    }),
    ("t2", "KeyError", "main.py", {
        "users.py": '''\
def make_user(name, email):
    return {"name": name, "email": email, "active": True}


def mailing_label(user):
    return f"{user['name']} <{user['emial']}>"  # ROOT
''',
        "main.py": '''\
from users import make_user, mailing_label

team = [make_user("Ada", "ada@example.com"), make_user("Alan", "alan@example.com")]
for member in team:
    print(mailing_label(member))
''',
    }),
    ("t3", "IndexError", "main.py", {
        "pager.py": '''\
def page_bounds(page, size):
    """Return (start, end) indexes for a 1-based page number."""
    start = page * size  # ROOT
    return start, start + size
''',
        "report.py": '''\
from pager import page_bounds


def first_row_of_page(rows, page, size):
    start, _ = page_bounds(page, size)
    return rows[start]
''',
        "main.py": '''\
from report import first_row_of_page

rows = [f"row{i}" for i in range(10)]
for page in range(1, 5):
    print(page, first_row_of_page(rows, page, size=3))
''',
    }),
    ("t4", "TypeError", "main.py", {
        "helpers.py": '''\
def normalize(handle):
    """Lowercase, trim, and make sure the handle starts with @."""
    handle = handle.strip().lower()
    if handle.startswith("@"):
        return handle
    handle = "@" + handle  # ROOT
''',
        "users.py": '''\
from helpers import normalize


def build_index(handles):
    return sorted(normalize(h) for h in handles)
''',
        "main.py": '''\
from users import build_index

print(build_index(["@Grace", "alan ", "@Ada"]))
''',
    }),
    ("t5", "RuntimeError", "main.py", {
        "inventory.py": '''\
def drop_empty(stock):
    """Remove items whose count is zero, in place."""
    for name in stock:  # ROOT
        if stock[name] == 0:
            del stock[name]  # ROOT
    return stock
''',
        "main.py": '''\
from inventory import drop_empty

stock = {"apples": 4, "pears": 0, "plums": 2, "figs": 0}
print(drop_empty(stock))
''',
    }),
    ("t6", "KeyError", "app.py", {
        "cache.py": '''\
import json


def save(path, mapping):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(mapping))  # ROOT


def load(path):
    """Return the mapping exactly as it was passed to save()."""
    with open(path, encoding="utf-8") as fh:
        return json.loads(fh.read())  # ROOT
''',
        "app.py": '''\
import os
import tempfile

from cache import load, save

scores = {1: "gold", 2: "silver", 3: "bronze"}
path = os.path.join(tempfile.mkdtemp(), "scores.json")
save(path, scores)
restored = load(path)
print("winner:", restored[1])
''',
    }),
]


def _strip(source: str) -> tuple[str, list[int]]:
    lines, roots = [], []
    for n, line in enumerate(source.rstrip("\n").split("\n"), 1):
        if line.endswith(MARK):
            roots.append(n)
            line = line[: -len(MARK)]
        lines.append(line)
    return "\n".join(lines) + "\n", roots


def _run(files: dict[str, str], entry: str) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        for path, src in files.items():
            Path(tmp, path).write_text(src, encoding="utf-8")
        proc = subprocess.run([sys.executable, "-E", "-s", "-X", "utf8", entry], cwd=tmp,
                              capture_output=True, text=True, encoding="utf-8", timeout=30)
        assert proc.returncode != 0, f"{entry} was expected to crash"
        trace = proc.stderr
        # Show paths relative to the project root, as a user would paste them.
        trace = re.sub(r'File "[^"]*?[\\/]([^"\\/]+\.py)"', r'File "\1"', trace)
        return proc.stdout + trace


def items() -> list[dict]:
    out = []
    for tid, exc, entry, project in PROJECTS:
        shown, gold_lines = {}, {}
        for path, src in project.items():
            clean, roots = _strip(src)
            shown[path] = clean
            if roots:
                gold_lines[path] = roots
        assert len(gold_lines) == 1, f"{tid}: root cause must sit in one file"
        trace = _run(shown, entry)
        assert exc in trace, f"{tid}: expected {exc}, got\n{trace}"
        root_file, lines = next(iter(gold_lines.items()))
        context = "\n\n".join(f"{path}\n```python\n{numbered(src)}\n```"
                              for path, src in shown.items())
        context += f"\n\nRunning `python {entry}` prints:\n```\n{trace.rstrip()}\n```"
        task = ("This project crashes. Find the root cause: the one line that has to "
                "change to fix the bug, which may not be the line the traceback ends on."
                + json_contract('{"exception": "<exception type>", "root_cause_file": '
                                '"<path>", "root_cause_line": <line number>, "fix": '
                                '"<the corrected line or a one-sentence fix>"}'))
        gold = {"exception": exc, "file": root_file, "lines": lines}
        out.append(item(tid, "traceback", task, gold, "traceback", context=context,
                        task_type="diagnose", tags=("judgment",)))
    return out
