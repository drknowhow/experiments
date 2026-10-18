"""code-review: find the seeded bug in a pull request that also makes benign
changes (type hints, a constant, a refactor). One pull request has no bug.

The diff shows the whole file with the new file's line numbers. Lines marked
`# BUG` in the new source are the gold; the marker is stripped before the diff
is rendered."""
from __future__ import annotations

import difflib

from common import item, json_contract

MARK = "  # BUG"

# id, file, PR description, old source, new source (bug lines marked)
PRS = [
    ("r1", "reviews.py", "Add type hints to the rating helpers; loop by index.", '''\
"""Helpers for product review pages."""


def star_bar(stars, width=5):
    """A text bar like '***--' for a rating out of `width`."""
    stars = max(0, min(width, stars))
    return "*" * stars + "-" * (width - stars)


def average_rating(reviews):
    """Mean star rating of a list of review dicts; 0.0 when there are none."""
    if not reviews:
        return 0.0
    total = 0
    for review in reviews:
        total += review["stars"]
    return total / len(reviews)
''', '''\
"""Helpers for product review pages."""


def star_bar(stars: int, width: int = 5) -> str:
    """A text bar like '***--' for a rating out of `width`."""
    stars = max(0, min(width, stars))
    return "*" * stars + "-" * (width - stars)


def average_rating(reviews: list[dict]) -> float:
    """Mean star rating of a list of review dicts; 0.0 when there are none."""
    if not reviews:
        return 0.0
    total = 0
    for i in range(1, len(reviews)):  # BUG
        total += reviews[i]["stars"]
    return total / len(reviews)
'''),
    ("r2", "money.py", "Cache exchange rates so a page of prices stops calling the "
     "rates API once per line.", '''\
"""Currency conversion for the storefront."""
from rates_api import fetch_rate


def convert(amount, currency):
    """Convert an amount in USD to `currency`."""
    rate = fetch_rate(currency)
    return round(amount * rate, 2)


def format_price(amount, currency):
    return f"{convert(amount, currency):,.2f} {currency}"
''', '''\
"""Currency conversion for the storefront."""
from rates_api import fetch_rate

_rates = {}


def convert(amount, currency):
    """Convert an amount in USD to `currency`."""
    if "rate" not in _rates:  # BUG
        _rates["rate"] = fetch_rate(currency)  # BUG
    rate = _rates["rate"]  # BUG
    return round(amount * rate, 2)


def format_price(amount, currency):
    return f"{convert(amount, currency):,.2f} {currency}"
'''),
    ("r3", "pricing.py", "Pull the default discount into a constant and add type hints.", '''\
"""Checkout pricing."""


def final_price(price, discount_pct=None):
    """Price after a percentage discount. None means the default 10%; 0 means
    no discount."""
    if discount_pct is None:
        discount_pct = 10
    return round(price * (100 - discount_pct) / 100, 2)


def with_shipping(price, shipping=4.99, free_over=50):
    return price if price >= free_over else round(price + shipping, 2)
''', '''\
"""Checkout pricing."""

DEFAULT_DISCOUNT_PCT = 10


def final_price(price: float, discount_pct: float | None = None) -> float:
    """Price after a percentage discount. None means the default 10%; 0 means
    no discount."""
    if not discount_pct:  # BUG
        discount_pct = DEFAULT_DISCOUNT_PCT
    return round(price * (100 - discount_pct) / 100, 2)


def with_shipping(price: float, shipping: float = 4.99, free_over: float = 50) -> float:
    return price if price >= free_over else round(price + shipping, 2)
'''),
    ("r4", "activity.py", "Use operator.itemgetter instead of lambdas.", '''\
"""Activity feed helpers."""


def timeline(events):
    """Events sorted oldest first."""
    return sorted(events, key=lambda e: e["ts"])


def by_author(events):
    out = {}
    for e in events:
        out.setdefault(e["author"], []).append(e)
    return out


def top_authors(events, n=3):
    counts = {a: len(es) for a, es in by_author(events).items()}
    return sorted(counts, key=lambda a: counts[a], reverse=True)[:n]
''', '''\
"""Activity feed helpers."""
from operator import itemgetter


def timeline(events):
    """Events sorted oldest first."""
    return sorted(events, key=itemgetter("ts"), reverse=True)  # BUG


def by_author(events):
    out = {}
    for e in events:
        out.setdefault(e["author"], []).append(e)
    return out


def top_authors(events, n=3):
    counts = {a: len(es) for a, es in by_author(events).items()}
    return sorted(counts, key=counts.__getitem__, reverse=True)[:n]
'''),
    ("r5", "tags.py", "Simplify tag parsing with a comprehension and Counter.", '''\
"""Post tags."""


def parse_tags(raw):
    tags = []
    for part in raw.split(","):
        part = part.strip().lower()
        if part:
            tags.append(part)
    return tags


def tag_counts(posts):
    counts = {}
    for post in posts:
        for tag in parse_tags(post["tags"]):
            counts[tag] = counts.get(tag, 0) + 1
    return counts
''', '''\
"""Post tags."""
from collections import Counter


def parse_tags(raw):
    return [part.strip().lower() for part in raw.split(",") if part.strip()]


def tag_counts(posts):
    return dict(Counter(tag for post in posts for tag in parse_tags(post["tags"])))
'''),
    ("r6", "orders.py", "Add an optional tax_rate to order_total.", '''\
"""Order maths."""


def order_total(items):
    """Sum of price * qty over the order's items."""
    total = 0
    for item in items:
        total += item["price"] * item["qty"]
    return round(total, 2)


def item_count(items):
    return sum(item["qty"] for item in items)
''', '''\
"""Order maths."""


def order_total(items, tax_rate=0.0):
    """Sum of price * qty over the order's items, plus tax at `tax_rate`
    (0.08 means 8%)."""
    subtotal = 0
    for item in items:
        subtotal += item["price"] * item["qty"]
    total = subtotal
    total = subtotal * tax_rate  # BUG
    return round(total, 2)


def item_count(items):
    return sum(item["qty"] for item in items)
'''),
]


def _strip(source: str) -> tuple[list[str], list[int]]:
    lines, bugs = [], []
    for n, line in enumerate(source.rstrip("\n").split("\n"), 1):
        if line.endswith(MARK):
            bugs.append(n)
            line = line[: -len(MARK)]
        lines.append(line)
    return lines, bugs


def render_diff(path: str, old: list[str], new: list[str]) -> str:
    """Whole-file unified diff; context and added lines carry the new file's
    line number, removed lines carry none."""
    out = [f"--- a/{path}", f"+++ b/{path}"]
    n = 0
    for line in list(difflib.unified_diff(old, new, lineterm="", n=10_000))[2:]:
        tag, body = line[:1], line[1:]
        if tag == "@":
            continue
        if tag == "-":
            out.append(f"{'':>4} - {body}")
        else:
            n += 1
            out.append(f"{n:>4} {'+' if tag == '+' else ' '} {body}")
    return "\n".join(out)


def items() -> list[dict]:
    out = []
    for rid, path, desc, old_src, new_src in PRS:
        old, _ = _strip(old_src)
        new, bugs = _strip(new_src)
        context = (f"Pull request: {desc}\n\n"
                   f"```diff\n{render_diff(path, old, new)}\n```\n\n"
                   "Line numbers are the new file's. Lines marked + were added, - removed.")
        task = ("Review this pull request. Report only defects that make the code "
                "behave incorrectly: no style, naming, typing or test-coverage notes. "
                "If there is no such defect, return an empty list."
                + json_contract('{"bugs": [{"line": <new-file line number>, "why": '
                                '"<one sentence>"}]}'))
        out.append(item(rid, "code-review", task, {"lines": bugs}, "review",
                        context=context, task_type="review", tags=("judgment",),
                        file=path))
    return out
