"""code-qa: predict what a short Python program prints. Each snippet hides one
well-known trap. Gold is whatever the snippet prints when executed here, so a
wrong expectation in this file cannot become wrong gold."""
from __future__ import annotations

import subprocess
import sys

from common import item, json_contract, numbered

# id, trap, source
SNIPPETS = [
    ("q1", "mutable default argument", '''\
def add(x, bucket=[]):
    bucket.append(x)
    return bucket

add(1)
add(2)
print(add(3))
'''),
    ("q2", "late-binding closures in a comprehension", '''\
fs = [lambda: i * 10 for i in range(3)]
print([f() for f in fs])
'''),
    ("q3", "aliasing: += mutates, a = a + [...] rebinds", '''\
a = b = []
a.append(1)
b += [2]
a = a + [3]
print(a, b)
'''),
    ("q4", "a generator is exhausted after one pass", '''\
nums = (n * n for n in range(4))
total = sum(nums)
print(total, max(nums, default=-1), list(nums))
'''),
    ("q5", "return inside finally overrides; a finally assignment does not", '''\
def f():
    try:
        return "try"
    finally:
        return "finally"

def g():
    x = 1
    try:
        return x
    finally:
        x = 2

print(f(), g())
'''),
    ("q6", "banker's rounding, floor division and modulo of negatives", '''\
print(round(2.5), round(3.5), -7 // 2, -7 % 2, int(-3.7))
'''),
    ("q7", "class attribute shared until an instance assigns its own", '''\
class Team:
    members = []

    def join(self, name):
        self.members.append(name)

a, b = Team(), Team()
a.join("x")
b.join("y")
b.members = ["z"]
print(a.members, b.members, Team.members)
'''),
    ("q8", "removing from a list while iterating over it skips elements", '''\
xs = [1, 1, 2, 3, 3, 4]
for x in xs:
    if x % 2:
        xs.remove(x)
print(xs)
'''),
]


def _run(source: str) -> str:
    out = subprocess.run([sys.executable, "-I", "-c", source], capture_output=True,
                         text=True, encoding="utf-8", timeout=30, check=True).stdout
    lines = out.strip().split("\n")
    assert len(lines) == 1, f"snippet must print one line, got {lines!r}"
    return lines[0]


def items() -> list[dict]:
    out = []
    for qid, trap, source in SNIPPETS:
        gold = _run(source)
        task = ("What does this Python 3 program print? Give the exact output line, "
                "character for character." + json_contract('{"answer": "<the printed line>"}'))
        out.append(item(qid, "code-qa", task, gold, "answer_exact",
                        context=f"```python\n{numbered(source)}\n```",
                        task_type="explain", tags=("mechanical",), note=trap))
    return out
