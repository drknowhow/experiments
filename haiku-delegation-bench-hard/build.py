"""Build fixtures/items.jsonl from the generators in gen/.

Every generator checks its own gold while it builds (log answers are recomputed
from the parsed records, nav answers are asserted against the pinned checkout,
edit solutions and traps are run against their hidden tests, thread and
near-miss documents are checked for the facts they must and must not contain),
so a successful build means every gold value was verified at build time.

    python build.py
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "gen"))

import g_edit2, g_logjoin, g_navhop, g_nearmiss, g_review2, g_thread  # noqa: E402
from common import dump  # noqa: E402

GENERATORS = [g_logjoin, g_navhop, g_review2, g_edit2, g_thread, g_nearmiss]
EXPECTED = 60  # DESIGN.md section 3: six categories of ten
PER_CATEGORY = 10
OUT = HERE / "fixtures" / "items.jsonl"


def build() -> list[dict]:
    items: list[dict] = []
    for gen in GENERATORS:
        items += gen.items()
    ids = [it["id"] for it in items]
    dupes = [i for i, n in Counter(ids).items() if n > 1]
    assert not dupes, f"duplicate ids: {dupes}"
    assert len(items) == EXPECTED, f"built {len(items)} items, DESIGN.md says {EXPECTED}"
    per = Counter(it["category"] for it in items)
    assert set(per.values()) == {PER_CATEGORY}, f"category sizes: {dict(per)}"
    return items


def main() -> None:
    items = build()
    OUT.parent.mkdir(exist_ok=True)
    dump(items, OUT)
    by_cat = Counter(it["category"] for it in items)
    for cat, n in by_cat.items():
        modes = sorted({it["mode"] for it in items if it["category"] == cat})
        print(f"{cat:<17} {n:>3}  {','.join(modes)}")
    print(f"{'total':<17} {len(items):>3}  -> {OUT.relative_to(HERE)}")


if __name__ == "__main__":
    main()
