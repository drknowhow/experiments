"""Build fixtures/items.jsonl from the generators in gen/.

Every generator checks its own gold while it builds (traceback projects are run,
nav answers are asserted against the pinned checkout, edit solutions are tested),
so a successful build means every gold value was verified at build time.

    python build.py
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "gen"))

import g_codeqa, g_diff, g_edit, g_logs, g_nav, g_review, g_text, g_traceback  # noqa: E402
from common import dump  # noqa: E402

GENERATORS = [g_text, g_diff, g_codeqa, g_traceback, g_logs, g_review, g_nav, g_edit]
EXPECTED = 74  # DESIGN.md section 3
OUT = HERE / "fixtures" / "items.jsonl"


def build() -> list[dict]:
    items: list[dict] = []
    for gen in GENERATORS:
        items += gen.items()
    ids = [it["id"] for it in items]
    dupes = [i for i, n in Counter(ids).items() if n > 1]
    assert not dupes, f"duplicate ids: {dupes}"
    assert len(items) == EXPECTED, f"built {len(items)} items, DESIGN.md says {EXPECTED}"
    return items


def main() -> None:
    items = build()
    OUT.parent.mkdir(exist_ok=True)
    dump(items, OUT)
    by_cat = Counter(it["category"] for it in items)
    for cat, n in by_cat.items():
        modes = sorted({it["mode"] for it in items if it["category"] == cat})
        print(f"{cat:<14} {n:>3}  {','.join(modes)}")
    print(f"{'total':<14} {len(items):>3}  -> {OUT.relative_to(HERE)}")


if __name__ == "__main__":
    main()
