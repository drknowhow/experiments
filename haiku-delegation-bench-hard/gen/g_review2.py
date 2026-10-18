"""review-subtle: find the behavioural bug in a pull request that also makes
three or more benign changes. Two of the ten pull requests have no bug: their
changes look suspicious but preserve behaviour.

A pull request is an old source plus (before, after) edits applied in order;
each `before` must occur exactly once in the text it is applied to. Lines of
the bug edit marked `# BUG` are the gold, and the marker is stripped before
the diff is rendered. The build runs every item's checks against both files,
each check on a freshly executed module: the old file must pass them all, and
the new file must fail exactly the checks tagged as the bug's and pass the
rest. No-bug items must pass every check on both files. Any exception counts
as a failed check."""
from __future__ import annotations

import difflib
import sys
import types
import warnings
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from common import item, json_contract

CAT = "review-subtle"
MARK = "  # BUG"
MIN_LINES, MAX_LINES = 100, 200


def _src(text: str) -> str:
    assert text.startswith("\n"), "sources open with a newline after the quotes"
    return text[1:]


# --- R01: a generator consumed twice ------------------------------------------

R01_OLD = _src(r'''
"""Weekly sales report: totals, units by product and the best sellers.

A sale is a dict with the keys order, sku, region, qty and unit_cents. A
refund is recorded as a sale with a negative quantity against the original
order.
"""
from collections import Counter, defaultdict


def parse_row(row):
    """One CSV row (a dict of strings) as a sale."""
    return {
        "order": row["order"].strip(),
        "sku": row["sku"].strip().upper(),
        "region": row["region"].strip().title(),
        "qty": int(row["qty"]),
        "unit_cents": int(round(float(row["unit_price"]) * 100)),
    }


def parse_rows(rows):
    """Sales from CSV rows, skipping rows with no SKU."""
    return [parse_row(r) for r in rows if r.get("sku", "").strip()]


def is_refund(sale):
    """True for a refund line."""
    return sale["qty"] < 0


def money(cents):
    """Format integer cents as dollars, like '$1,234.50'."""
    return "$%s.%02d" % (format(cents // 100, ","), cents % 100)


def line_cents(sale):
    """Value of one sale line in cents."""
    return sale["qty"] * sale["unit_cents"]


def summarize(sales):
    """Totals over the week's sales, ignoring refunds."""
    kept = [s for s in sales if not is_refund(s)]
    gross = sum(line_cents(s) for s in kept)
    units = Counter()
    for s in kept:
        units[s["sku"]] += s["qty"]
    orders = len({s["order"] for s in kept})
    return {
        "gross_cents": gross,
        "units": dict(units),
        "top": units.most_common(3),
        "orders": orders,
    }


def refunds_cents(sales):
    """Total refunded, as a positive number of cents."""
    return -sum(line_cents(s) for s in sales if is_refund(s))


def by_region(sales):
    """Net cents per region (refunds subtracted), regions sorted by name."""
    totals = defaultdict(int)
    for s in sales:
        totals[s["region"]] += line_cents(s)
    return dict(sorted(totals.items()))


def average_order_cents(sales):
    """Mean gross per order, rounded down to a whole cent; 0 with no orders."""
    summary = summarize(sales)
    if not summary["orders"]:
        return 0
    return summary["gross_cents"] // summary["orders"]


def week_over_week(this_week, last_week):
    """Percent change in gross from last week to this week, one decimal.

    None when last week had no sales, since the change is then undefined.
    """
    before = summarize(last_week)["gross_cents"]
    after = summarize(this_week)["gross_cents"]
    if before == 0:
        return None
    return round(100.0 * (after - before) / before, 1)


def render(sales, title="Weekly sales"):
    """The report as a list of plain-text lines."""
    summary = summarize(sales)
    out = [title, "=" * len(title)]
    out.append("Gross: %s" % money(summary["gross_cents"]))
    out.append("Refunds: %s" % money(refunds_cents(sales)))
    out.append("Orders: %d" % summary["orders"])
    out.append("Average order: %s" % money(average_order_cents(sales)))
    out.append("")
    out.append("Best sellers:")
    for rank, (sku, qty) in enumerate(summary["top"], 1):
        out.append("  %d. %s (%d units)" % (rank, sku, qty))
    out.append("")
    out.append("By region:")
    for region, cents in by_region(sales).items():
        out.append("  %-8s %s" % (region, money(cents)))
    return out
''')

R01_EDITS = [
    ("from collections import Counter, defaultdict\n",
     "from collections import Counter, defaultdict\n\nTOP_N = 3\n"),
    ("def is_refund(sale):", "def is_refund(sale: dict) -> bool:"),
    ("def money(cents):", "def money(cents: int) -> str:"),
    ('    return "$%s.%02d" % (format(cents // 100, ","), cents % 100)',
     '    return f"${cents // 100:,}.{cents % 100:02d}"'),
    ("def line_cents(sale):", "def line_cents(sale: dict) -> int:"),
    ('''\
    kept = [s for s in sales if not is_refund(s)]
    gross = sum(line_cents(s) for s in kept)
    units = Counter()
    for s in kept:
        units[s["sku"]] += s["qty"]
    orders = len({s["order"] for s in kept})''', '''\
    kept = (s for s in sales if not is_refund(s))  # BUG
    gross = sum(line_cents(s) for s in kept)
    units = Counter()
    for s in kept:  # BUG
        units[s["sku"]] += s["qty"]
    orders = len({s["order"] for s in kept})  # BUG'''),
    ('"top": units.most_common(3),', '"top": units.most_common(TOP_N),'),
    ('        out.append("  %d. %s (%d units)" % (rank, sku, qty))',
     '        out.append(f"  {rank}. {sku} ({qty} units)")'),
    ('        out.append("  %-8s %s" % (region, money(cents)))',
     '        out.append(f"  {region:<8} {money(cents)}")'),
]

_SALES = [
    {"order": "o1", "sku": "A", "region": "North", "qty": 2, "unit_cents": 500},
    {"order": "o1", "sku": "B", "region": "North", "qty": 1, "unit_cents": 1250},
    {"order": "o2", "sku": "A", "region": "South", "qty": 3, "unit_cents": 500},
    {"order": "o3", "sku": "C", "region": "South", "qty": 1, "unit_cents": 9999},
    {"order": "o2", "sku": "A", "region": "South", "qty": -1, "unit_cents": 500},
]

R01_CHECKS = {
    "units": lambda m: m.summarize(_SALES)["units"] == {"A": 5, "B": 1, "C": 1},
    "orders": lambda m: m.summarize(_SALES)["orders"] == 3,
    "top": lambda m: m.summarize(_SALES)["top"] == [("A", 5), ("B", 1), ("C", 1)],
    "average": lambda m: m.average_order_cents(_SALES) == 4583,
    "gross": lambda m: m.summarize(_SALES)["gross_cents"] == 13749,
    "money": lambda m: (m.money(123450), m.money(5), m.money(100000000))
    == ("$1,234.50", "$0.05", "$1,000,000.00"),
    "refunds": lambda m: m.refunds_cents(_SALES) == 500,
    "regions": lambda m: m.by_region(_SALES) == {"North": 2250, "South": 10999},
    "region_lines": lambda m: m.render(_SALES)[-2:]
    == ["  North    $22.50", "  South    $109.99"],
    "wow": lambda m: m.week_over_week(_SALES, _SALES[:1]) == 1274.9
    and m.week_over_week(_SALES, []) is None,
    "parse": lambda m: m.parse_rows([
        {"order": " o9 ", "sku": " ab-1 ", "region": "north ", "qty": "2", "unit_price": "4.10"},
        {"order": "o10", "sku": "  ", "region": "x", "qty": "1", "unit_price": "1"}])
    == [{"order": "o9", "sku": "AB-1", "region": "North", "qty": 2, "unit_cents": 410}],
}

# --- R02: lstrip used as a prefix strip ---------------------------------------

R02_OLD = _src(r'''
"""Names, paths and sizes for product images.

Every upload is kept as the original plus one rendition per size. A
rendition's file name is the original's with the size as a prefix, so the
thumbnail of 'hat.png' is 'thumb_hat.png'.
"""
import math
import os

THUMB_PREFIX = "thumb_"
SIZES = {"thumb": (128, 128), "card": (480, 360), "zoom": (1600, 1200)}
TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
         ".webp": "image/webp"}
MAX_NAME = 80


def is_allowed(name):
    """True when the file extension is one we serve."""
    return os.path.splitext(name)[1].lower() in TYPES


def content_type(name):
    """The Content-Type header for a stored file."""
    return TYPES.get(os.path.splitext(name)[1].lower(), "application/octet-stream")


def clean_name(name):
    """A safe file name: last path part only, lowercase, spaces to dashes."""
    base = name.rsplit("/", 1)[-1]
    base = base.strip().lower().replace(" ", "-")
    stem, ext = os.path.splitext(base)
    return stem[: MAX_NAME - len(ext)] + ext


def rendition_name(name, size):
    """File name of the given size's rendition of an original."""
    if size not in SIZES:
        raise ValueError("unknown size: %s" % size)
    return "%s_%s" % (size, name)


def original_name(name):
    """'thumb_hat.png' -> 'hat.png'; names without the prefix are unchanged."""
    if name.startswith(THUMB_PREFIX):
        return name[len(THUMB_PREFIX):]
    return name


def storage_path(product_id, name):
    """Where a file lives in the bucket, sharded by the id's last two digits."""
    shard = "%02d" % (product_id % 100)
    return "products/%s/%d/%s" % (shard, product_id, name)


def public_url(base, product_id, name):
    """The CDN URL for a stored file."""
    return base.rstrip("/") + "/" + storage_path(product_id, name)


def parse_size(text):
    """'480x360' -> (480, 360)."""
    w, sep, h = text.lower().partition("x")
    if not sep or not w.isdigit() or not h.isdigit():
        raise ValueError("expected WIDTHxHEIGHT, got %r" % text)
    return int(w), int(h)


def fit(width, height, box):
    """Scale (width, height) to fit inside box, keeping the aspect ratio.

    Images already inside the box are not enlarged. Sides round to whole
    pixels and never drop below one.
    """
    box_w, box_h = box
    scale = min(box_w / width, box_h / height, 1.0)
    return max(1, round(width * scale)), max(1, round(height * scale))


def aspect(width, height):
    """Aspect ratio in lowest terms, like '4:3'."""
    g = math.gcd(width, height)
    return "%d:%d" % (width // g, height // g)


def renditions(name, width, height):
    """Every rendition of an original as (file name, (width, height))."""
    out = []
    for size, box in SIZES.items():
        out.append((rendition_name(name, size), fit(width, height, box)))
    return out


def thumbnails(names):
    """The thumbnail files among names, mapped to their originals."""
    return {n: original_name(n) for n in names if n.startswith(THUMB_PREFIX)}


def orphans(names):
    """Thumbnails whose original is missing from names, sorted."""
    present = set(names)
    return sorted(t for t, o in thumbnails(names).items() if o not in present)


def describe(name, width, height):
    """One line for the asset admin page."""
    return "%s %dx%d (%s)" % (name, width, height, aspect(width, height))
''')

R02_EDITS = [
    ("def is_allowed(name):", "def is_allowed(name: str) -> bool:"),
    ("def rendition_name(name, size):", "def rendition_name(name: str, size: str) -> str:"),
    ('        raise ValueError("unknown size: %s" % size)\n    return "%s_%s" % (size, name)',
     '        raise ValueError(f"unknown size: {size}")\n    return f"{size}_{name}"'),
    ("def original_name(name):", "def original_name(name: str) -> str:"),
    ('''\
    if name.startswith(THUMB_PREFIX):
        return name[len(THUMB_PREFIX):]
    return name''', '''\
    return name.lstrip(THUMB_PREFIX)  # BUG'''),
    ('''\
    shard = "%02d" % (product_id % 100)
    return "products/%s/%d/%s" % (shard, product_id, name)''', '''\
    return f"products/{product_id % 100:02d}/{product_id}/{name}"'''),
    ('    return "%s %dx%d (%s)" % (name, width, height, aspect(width, height))',
     '    return f"{name} {width}x{height} ({aspect(width, height)})"'),
]

R02_CHECKS = {
    "original": lambda m: m.original_name("thumb_hat.png") == "hat.png"
    and m.original_name("hat.png") == "hat.png",
    "orphans": lambda m: m.orphans(["thumb_hat.png", "hat.png", "cap.png"]) == [],
    "original_other": lambda m: m.original_name("thumb_cap.png") == "cap.png",
    "rendition": lambda m: m.rendition_name("hat.png", "card") == "card_hat.png",
    "rendition_bad": lambda m: _raises(ValueError, m.rendition_name, "hat.png", "huge"),
    "storage": lambda m: m.storage_path(12345, "hat.png") == "products/45/12345/hat.png"
    and m.storage_path(7, "a.png") == "products/07/7/a.png",
    "url": lambda m: m.public_url("https://cdn.example.test/", 7, "a.png")
    == "https://cdn.example.test/products/07/7/a.png",
    "fit": lambda m: m.fit(3200, 1800, (480, 360)) == (480, 270)
    and m.fit(100, 50, (480, 360)) == (100, 50),
    "clean": lambda m: m.clean_name("uploads/Red Hat.PNG") == "red-hat.png",
    "allowed": lambda m: m.is_allowed("a.JPG") and not m.is_allowed("a.gif"),
    "describe": lambda m: m.describe("hat.png", 1600, 1200) == "hat.png 1600x1200 (4:3)",
    "size": lambda m: m.parse_size("480X360") == (480, 360),
}

# --- R03: late-binding closure in a loop --------------------------------------

R03_OLD = _src(r'''
"""Unit conversions for the trip planner.

Distances are stored in kilometres, fuel in litres, weights in kilograms and
temperatures in Celsius; the display layer converts on the way out.
"""

FACTORS = {
    "km_to_mi": 0.621371,
    "mi_to_km": 1.609344,
    "l_to_gal": 0.264172,
    "gal_to_l": 3.785412,
    "kg_to_lb": 2.204623,
    "lb_to_kg": 0.453592,
}
UNITS = {"km": "km_to_mi", "mi": "mi_to_km", "l": "l_to_gal", "gal": "gal_to_l",
         "kg": "kg_to_lb", "lb": "lb_to_kg"}


def _scale(factor):
    """A function that multiplies its argument by factor."""
    def convert(value):
        return value * factor
    return convert


def build_converters(factors):
    """Name -> conversion function, one per entry in factors."""
    converters = {}
    for name, factor in factors.items():
        converters[name] = _scale(factor)
    return converters


CONVERTERS = build_converters(FACTORS)


def convert(value, name, digits=2):
    """value converted by the named factor, rounded to digits places."""
    if name not in CONVERTERS:
        raise KeyError("no conversion named %r" % name)
    return round(CONVERTERS[name](value), digits)


def c_to_f(c):
    """Celsius to Fahrenheit."""
    return c * 9 / 5 + 32


def f_to_c(f):
    """Fahrenheit to Celsius."""
    return (f - 32) * 5 / 9


def parse_quantity(text):
    """'12.5 km' -> (12.5, 'km'). Raises ValueError on anything else."""
    parts = text.split()
    if len(parts) != 2:
        raise ValueError("expected '<number> <unit>', got %r" % text)
    number, unit = parts
    unit = unit.lower()
    if unit not in UNITS:
        raise ValueError("unknown unit %r" % unit)
    return float(number), unit


def to_other_system(text, digits=1):
    """'10 km' -> '6.2 mi'; the unit flips between metric and imperial."""
    value, unit = parse_quantity(text)
    name = UNITS[unit]
    target = name.split("_to_")[1]
    return "%s %s" % (convert(value, name, digits), target)


def fuel_economy(km, litres):
    """(litres per 100 km, miles per US gallon) for a trip."""
    if km <= 0 or litres <= 0:
        raise ValueError("distance and fuel must be positive")
    per_100 = litres / km * 100
    mpg = CONVERTERS["km_to_mi"](km) / CONVERTERS["l_to_gal"](litres)
    return round(per_100, 1), round(mpg, 1)


def format_distance(km, imperial=False, digits=1):
    """A distance for display, in miles when imperial is set."""
    if imperial:
        return "%.*f mi" % (digits, CONVERTERS["km_to_mi"](km))
    return "%.*f km" % (digits, km)


def format_temperature(c, imperial=False):
    """A temperature for display in whole degrees, like '22 C'."""
    if imperial:
        return "%d F" % round(c_to_f(c))
    return "%d C" % round(c)


def pace(km, minutes):
    """Minutes per kilometre as 'm:ss'."""
    if km <= 0:
        raise ValueError("distance must be positive")
    secs = round(minutes * 60 / km)
    return "%d:%02d" % divmod(secs, 60)


def speed_kmh(km, minutes):
    """Average speed in km/h, one decimal."""
    return round(km / (minutes / 60), 1)


def trip_summary(legs, imperial=False):
    """Leg count and total distance (legs in km) as display text."""
    return "%d legs, %s" % (len(legs), format_distance(sum(legs), imperial))
''')

R03_EDITS = [
    ('''\
def _scale(factor):
    """A function that multiplies its argument by factor."""
    def convert(value):
        return value * factor
    return convert


def build_converters(factors):
    """Name -> conversion function, one per entry in factors."""
    converters = {}
    for name, factor in factors.items():
        converters[name] = _scale(factor)''', '''\
def build_converters(factors):
    """Name -> conversion function, one per entry in factors."""
    converters = {}
    for name, factor in factors.items():
        converters[name] = lambda value: value * factor  # BUG'''),
    ('        raise KeyError("no conversion named %r" % name)',
     '        raise KeyError(f"no conversion named {name!r}")'),
    ("def c_to_f(c):", "def c_to_f(c: float) -> float:"),
    ("def f_to_c(f):", "def f_to_c(f: float) -> float:"),
    ('    return "%s %s" % (convert(value, name, digits), target)',
     '    return f"{convert(value, name, digits)} {target}"'),
    ('        return "%d F" % round(c_to_f(c))\n    return "%d C" % round(c)',
     '        return f"{round(c_to_f(c))} F"\n    return f"{round(c)} C"'),
    ("def speed_kmh(km, minutes):", "def speed_kmh(km: float, minutes: float) -> float:"),
]

R03_CHECKS = {
    "km_to_mi": lambda m: m.convert(10, "km_to_mi") == 6.21,
    "mi_to_km": lambda m: m.convert(5, "mi_to_km") == 8.05,
    "flip": lambda m: m.to_other_system("10 km") == "6.2 mi",
    "fuel": lambda m: m.fuel_economy(100, 8) == (8.0, 29.4),
    "imperial": lambda m: m.format_distance(10, imperial=True) == "6.2 mi",
    "lb_to_kg": lambda m: m.convert(10, "lb_to_kg") == 4.54,
    "unknown": lambda m: _raises(KeyError, m.convert, 1, "km_to_au"),
    "temps": lambda m: m.c_to_f(100) == 212 and m.f_to_c(212) == 100,
    "parse": lambda m: m.parse_quantity("12.5 KM") == (12.5, "km"),
    "metric": lambda m: m.format_distance(12) == "12.0 km"
    and m.trip_summary([12.5, 30.0]) == "2 legs, 42.5 km",
    "temperature": lambda m: m.format_temperature(21.6) == "22 C"
    and m.format_temperature(21.6, True) == "71 F",
    "pace": lambda m: m.pace(5, 27.5) == "5:30" and m.speed_kmh(10, 50) == 12.0,
}

# --- R04: inclusive/exclusive boundary in a bisect lookup ---------------------

R04_OLD = _src(r'''
"""Quantity pricing and quotes for wholesale orders.

Prices are integer cents. An order moves to a cheaper tier as soon as its
quantity reaches that tier's minimum.
"""

# (minimum quantity, unit price in cents), ascending by minimum
TIERS = [(1, 1000), (10, 900), (50, 800), (200, 700)]
SHIPPING_CENTS = 1500
FREE_SHIPPING_FROM = 50000
CODES = {"SPRING10": 10, "TRADE15": 15}
MAX_QTY = 10000


def unit_price(qty):
    """Unit price for an order of qty items."""
    if qty < 1:
        raise ValueError("quantity must be at least 1")
    price = TIERS[0][1]
    for min_qty, cents in TIERS:
        if qty >= min_qty:
            price = cents
    return price


def next_tier(qty):
    """(items still needed, unit price) for the next cheaper tier, or None."""
    for min_qty, cents in TIERS:
        if min_qty > qty:
            return min_qty - qty, cents
    return None


def savings(qty):
    """Cents saved against paying the first tier's price for every item."""
    return (TIERS[0][1] - unit_price(qty)) * qty


def tier_index(qty):
    """0-based index of qty's tier, for highlighting the pricing table."""
    for i in range(len(TIERS) - 1, -1, -1):
        if qty >= TIERS[i][0]:
            return i
    raise ValueError("quantity must be at least 1")


def cheaper_to_round_up(qty):
    """True when ordering up to the next tier costs less than qty items."""
    hint = next_tier(qty)
    if not hint:
        return False
    need, cents = hint
    return (qty + need) * cents < unit_price(qty) * qty


def shipping(subtotal):
    """Flat shipping, free once the subtotal reaches the threshold."""
    return 0 if subtotal >= FREE_SHIPPING_FROM else SHIPPING_CENTS


def discount(subtotal, code):
    """Cents off for a discount code; unknown or empty codes give 0."""
    pct = CODES.get((code or "").strip().upper(), 0)
    return subtotal * pct // 100


def quote(qty, code=None):
    """A full quote for qty items as a dict of cents."""
    if qty > MAX_QTY:
        raise ValueError("orders above %d items need a custom quote" % MAX_QTY)
    unit = unit_price(qty)
    subtotal = unit * qty
    off = discount(subtotal, code)
    ship = shipping(subtotal - off)
    return {
        "unit": unit,
        "subtotal": subtotal,
        "discount": off,
        "shipping": ship,
        "total": subtotal - off + ship,
    }


def money(cents):
    """'$1,234.50' for 123450."""
    return "$%s.%02d" % (format(cents // 100, ","), cents % 100)


def quote_lines(qty, code=None):
    """The quote as text lines for the order page."""
    q = quote(qty, code)
    lines = [
        "%d x %s" % (qty, money(q["unit"])),
        "Subtotal: %s" % money(q["subtotal"]),
    ]
    if q["discount"]:
        lines.append("Discount: -%s" % money(q["discount"]))
    lines.append("Shipping: %s" % ("free" if not q["shipping"] else money(q["shipping"])))
    lines.append("Total: %s" % money(q["total"]))
    hint = next_tier(qty)
    if hint:
        need, cents = hint
        lines.append("Add %d more for %s each" % (need, money(cents)))
    return lines


def price_table():
    """(range label, unit price text) per tier, for the pricing page."""
    rows = []
    for i, (min_qty, cents) in enumerate(TIERS):
        if i + 1 < len(TIERS):
            label = "%d-%d" % (min_qty, TIERS[i + 1][0] - 1)
        else:
            label = "%d+" % min_qty
        rows.append((label, money(cents)))
    return rows
''')

R04_EDITS = [
    ('"""\n\n# (minimum quantity', '"""\nimport bisect\n\n# (minimum quantity'),
    ("TIERS = [(1, 1000), (10, 900), (50, 800), (200, 700)]\n",
     "TIERS = [(1, 1000), (10, 900), (50, 800), (200, 700)]\n"
     "TIER_MINS = [min_qty for min_qty, _ in TIERS]\n"),
    ("def unit_price(qty):", "def unit_price(qty: int) -> int:"),
    ('''\
    price = TIERS[0][1]
    for min_qty, cents in TIERS:
        if qty >= min_qty:
            price = cents
    return price''', '''\
    return TIERS[bisect.bisect_left(TIER_MINS, qty) - 1][1]  # BUG'''),
    ("def shipping(subtotal):", "def shipping(subtotal: int) -> int:"),
    ("def discount(subtotal, code):", "def discount(subtotal: int, code: str | None) -> int:"),
    ('        raise ValueError("orders above %d items need a custom quote" % MAX_QTY)',
     '        raise ValueError(f"orders above {MAX_QTY} items need a custom quote")'),
    ('    return "$%s.%02d" % (format(cents // 100, ","), cents % 100)',
     '    return f"${cents // 100:,}.{cents % 100:02d}"'),
]

R04_CHECKS = {
    "edges": lambda m: [m.unit_price(q) for q in (1, 10, 50, 200)] == [1000, 900, 800, 700],
    "quote_edge": lambda m: m.quote(10)["total"] == 10500,
    "inside": lambda m: [m.unit_price(q) for q in (9, 25, 199, 5000)] == [1000, 900, 800, 700],
    "quote": lambda m: m.quote(25, "spring10") == {
        "unit": 900, "subtotal": 22500, "discount": 2250, "shipping": 1500, "total": 21750},
    "free_ship": lambda m: m.quote(80)["shipping"] == 0,
    "too_many": lambda m: _raises(ValueError, m.quote, 10001),
    "table": lambda m: m.price_table() == [
        ("1-9", "$10.00"), ("10-49", "$9.00"), ("50-199", "$8.00"), ("200+", "$7.00")],
    "lines": lambda m: m.quote_lines(25, "TRADE15") == [
        "25 x $9.00", "Subtotal: $225.00", "Discount: -$33.75", "Shipping: $15.00",
        "Total: $206.25", "Add 25 more for $8.00 each"],
    "savings": lambda m: m.savings(25) == 2500 and m.next_tier(500) is None,
    "tier_index": lambda m: [m.tier_index(q) for q in (1, 10, 49, 200)] == [0, 1, 1, 3],
    "round_up": lambda m: m.cheaper_to_round_up(48) and not m.cheaper_to_round_up(9),
}

# --- R05: an aware timestamp made naive without converting to UTC -------------

R05_OLD = _src(r'''
"""Booking slots for the clinic's appointment page.

The booking form sends ISO 8601 timestamps that carry the visitor's UTC
offset, e.g. '2026-03-02T08:00:00-05:00'. Everything here is naive UTC.
"""
from datetime import datetime, time, timedelta, timezone

SLOT = timedelta(minutes=30)
OPEN, CLOSE = time(9, 0), time(17, 0)  # UTC
CLOSED_WEEKDAYS = {5, 6}  # Saturday, Sunday


def parse_utc(ts):
    """An offset-carrying ISO timestamp as a naive UTC datetime."""
    return datetime.fromisoformat(ts).astimezone(timezone.utc).replace(tzinfo=None)


def to_iso(dt):
    """A naive UTC datetime as an ISO string with a Z suffix."""
    return dt.isoformat(timespec="minutes") + "Z"


def is_open_day(day):
    """True on days the clinic takes bookings."""
    return day.weekday() not in CLOSED_WEEKDAYS


def slots_for_day(day):
    """Start times of every bookable slot on day, in order."""
    if not is_open_day(day):
        return []
    start = datetime.combine(day, OPEN)
    end = datetime.combine(day, CLOSE)
    out = []
    while start + SLOT <= end:
        out.append(start)
        start += SLOT
    return out


def overlaps(a_start, a_end, b_start, b_end):
    """True when two half-open intervals share any time."""
    return a_start < b_end and b_start < a_end


def bookings_on(day, bookings):
    """The (start, end) bookings that start on day, earliest first."""
    return sorted((b, e) for b, e in bookings if b.date() == day)


def free_slots(day, bookings):
    """Slots on day not overlapping any (start, end) booking."""
    return [s for s in slots_for_day(day)
            if not any(overlaps(s, s + SLOT, b, e) for b, e in bookings)]


def next_free(after, bookings, horizon_days=14):
    """The first free slot starting at or after the given time, or None."""
    for offset in range(horizon_days + 1):
        day = after.date() + timedelta(days=offset)
        for s in free_slots(day, bookings):
            if s >= after:
                return s
    return None


def request_booking(ts, bookings):
    """Validate a start time sent by the booking form; return its slot.

    Raises ValueError when the time is not a slot start or is taken.
    """
    start = parse_utc(ts)
    if start not in slots_for_day(start.date()):
        raise ValueError("not a slot start: %s" % to_iso(start))
    if start not in free_slots(start.date(), bookings):
        raise ValueError("slot taken: %s" % to_iso(start))
    return start, start + SLOT


def label(dt):
    """'Mon 2 Mar 09:00' for the slot picker."""
    return "%s %d %s" % (dt.strftime("%a"), dt.day, dt.strftime("%b %H:%M"))


def week_grid(monday, bookings):
    """{date: [labels of free slots]} for the five weekdays from monday."""
    grid = {}
    for offset in range(5):
        day = monday + timedelta(days=offset)
        grid[day] = [label(s) for s in free_slots(day, bookings)]
    return grid


def utilization(day, bookings):
    """Share of the day's slots that are booked, 0.0 to 1.0."""
    slots = slots_for_day(day)
    if not slots:
        return 0.0
    return 1 - len(free_slots(day, bookings)) / len(slots)


def busiest(days, bookings):
    """The day with the highest utilization; the earliest wins a tie."""
    return max(days, key=lambda d: (utilization(d, bookings), -d.toordinal()))
''')

R05_EDITS = [
    ("def parse_utc(ts):", "def parse_utc(ts: str) -> datetime:"),
    ("    return datetime.fromisoformat(ts).astimezone(timezone.utc).replace(tzinfo=None)",
     "    return datetime.fromisoformat(ts).replace(tzinfo=None)  # BUG"),
    ("def to_iso(dt):", "def to_iso(dt: datetime) -> str:"),
    ('        raise ValueError("not a slot start: %s" % to_iso(start))',
     '        raise ValueError(f"not a slot start: {to_iso(start)}")'),
    ('        raise ValueError("slot taken: %s" % to_iso(start))',
     '        raise ValueError(f"slot taken: {to_iso(start)}")'),
    ("def label(dt):", "def label(dt: datetime) -> str:"),
    ('    return "%s %d %s" % (dt.strftime("%a"), dt.day, dt.strftime("%b %H:%M"))',
     '    return f"{dt:%a} {dt.day} {dt:%b %H:%M}"'),
]

_MON = date(2026, 3, 2)
R05_CHECKS = {
    "parse_offset": lambda m: m.parse_utc("2026-03-02T08:00:00-05:00") == datetime(2026, 3, 2, 13, 0),
    "request": lambda m: m.request_booking("2026-03-02T09:30:00-05:00", [])
    == (datetime(2026, 3, 2, 14, 30), datetime(2026, 3, 2, 15, 0)),
    "parse_utc_input": lambda m: m.parse_utc("2026-03-02T13:00:00+00:00") == datetime(2026, 3, 2, 13, 0),
    "slots": lambda m: len(m.slots_for_day(_MON)) == 16 and m.slots_for_day(date(2026, 3, 7)) == [],
    "free": lambda m: len(m.free_slots(_MON, [(datetime(2026, 3, 2, 9, 0),
                                              datetime(2026, 3, 2, 10, 15))])) == 13,
    "label": lambda m: m.label(datetime(2026, 3, 2, 9, 0)) == "Mon 2 Mar 09:00",
    "grid": lambda m: m.week_grid(_MON, [])[_MON][0] == "Mon 2 Mar 09:00",
    "next_free": lambda m: m.next_free(datetime(2026, 3, 6, 16, 45), []) == datetime(2026, 3, 9, 9, 0),
    "iso": lambda m: m.to_iso(datetime(2026, 3, 2, 13, 0)) == "2026-03-02T13:00Z",
    "on_day": lambda m: m.bookings_on(_MON, [
        (datetime(2026, 3, 3, 9, 0), datetime(2026, 3, 3, 9, 30)),
        (datetime(2026, 3, 2, 11, 0), datetime(2026, 3, 2, 11, 30)),
        (datetime(2026, 3, 2, 9, 0), datetime(2026, 3, 2, 9, 30))])
    == [(datetime(2026, 3, 2, 9, 0), datetime(2026, 3, 2, 9, 30)),
        (datetime(2026, 3, 2, 11, 0), datetime(2026, 3, 2, 11, 30))],
    "util": lambda m: m.utilization(_MON, [(datetime(2026, 3, 2, 9, 0),
                                           datetime(2026, 3, 2, 13, 0))]) == 0.5,
    "taken": lambda m: _raises(ValueError, m.request_booking, "2026-03-02T13:00:00+00:00",
                               [(datetime(2026, 3, 2, 13, 0), datetime(2026, 3, 2, 13, 30))]),
}

# --- R06: Decimal quantize falls back to banker's rounding --------------------

R06_OLD = _src(r'''
"""Invoice arithmetic for the shop. Money is Decimal throughout, never float.

Tax is charged per line and rounded per line, halves away from zero, which is
how the state's published tax tables round.
"""
from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal("0.01")
TENTH = Decimal("0.1")
TAX_RATE = Decimal("0.0725")
LATE_RATE = Decimal("0.015")  # per started 30 days


def to_cents(amount):
    """amount rounded to whole cents, halves away from zero."""
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def percent(part, whole):
    """part as a percentage of whole, one decimal place, halves up."""
    if not whole:
        return Decimal("0.0")
    return (Decimal(100) * part / whole).quantize(TENTH, rounding=ROUND_HALF_UP)


def line_amount(qty, unit_price):
    """qty times unit price, in cents."""
    return to_cents(Decimal(qty) * unit_price)


def line_tax(amount, taxable=True):
    """Tax on one line's amount."""
    if not taxable:
        return Decimal("0.00")
    return to_cents(amount * TAX_RATE)


def apply_discount(amount, pct):
    """amount less pct percent, in cents."""
    return to_cents(amount * (Decimal(100) - Decimal(pct)) / Decimal(100))


def build(lines, discount_pct=0):
    """Totals for an invoice.

    lines are dicts with sku, qty, unit_price (Decimal) and an optional
    taxable flag (default True). The discount applies before tax.
    """
    rows = []
    for ln in lines:
        amount = line_amount(ln["qty"], ln["unit_price"])
        if discount_pct:
            amount = apply_discount(amount, discount_pct)
        tax = line_tax(amount, ln.get("taxable", True))
        rows.append({"sku": ln["sku"], "amount": amount, "tax": tax})
    subtotal = sum((r["amount"] for r in rows), Decimal("0.00"))
    tax = sum((r["tax"] for r in rows), Decimal("0.00"))
    return {"rows": rows, "subtotal": subtotal, "tax": tax, "total": subtotal + tax}


def money(amount):
    """'$1,234.50' for Decimal('1234.5')."""
    return "${:,.2f}".format(to_cents(amount))


def render(invoice, number):
    """The invoice as plain-text lines."""
    out = ["Invoice %s" % number, ""]
    for r in invoice["rows"]:
        out.append("%-12s %10s  tax %8s" % (r["sku"], money(r["amount"]), money(r["tax"])))
    out.append("")
    out.append("%-12s %10s" % ("Subtotal", money(invoice["subtotal"])))
    out.append("%-12s %10s" % ("Tax", money(invoice["tax"])))
    out.append("%-12s %10s" % ("Total", money(invoice["total"])))
    return out


def split_evenly(total, parts):
    """total split into parts amounts that differ by at most a cent.

    The first amounts take the extra cents, so the parts always sum to total.
    """
    if parts < 1:
        raise ValueError("parts must be at least 1")
    cents = int(to_cents(total) / CENT)
    base, extra = divmod(cents, parts)
    return [(base + (1 if i < extra else 0)) * CENT for i in range(parts)]


def tax_share(invoice):
    """Tax as a percentage of the subtotal."""
    return percent(invoice["tax"], invoice["subtotal"])


def late_fee(total, days_late):
    """LATE_RATE of total per started 30 days late; nothing when on time."""
    if days_late <= 0:
        return Decimal("0.00")
    periods = (days_late + 29) // 30
    return to_cents(total * LATE_RATE * periods)


def amount_due(invoice, days_late=0):
    """What is owed now: the invoice total plus any late fee."""
    return invoice["total"] + late_fee(invoice["total"], days_late)
''')

R06_EDITS = [
    ("def to_cents(amount):", "def to_cents(amount: Decimal) -> Decimal:"),
    ("    return amount.quantize(CENT, rounding=ROUND_HALF_UP)",
     "    return amount.quantize(CENT)  # BUG"),
    ("def line_amount(qty, unit_price):",
     "def line_amount(qty: int, unit_price: Decimal) -> Decimal:"),
    ("def line_tax(amount, taxable=True):",
     "def line_tax(amount: Decimal, taxable: bool = True) -> Decimal:"),
    ('    return "${:,.2f}".format(to_cents(amount))',
     '    return f"${to_cents(amount):,.2f}"'),
    ('    out = ["Invoice %s" % number, ""]', '    out = [f"Invoice {number}", ""]'),
    ("def split_evenly(total, parts):",
     "def split_evenly(total: Decimal, parts: int) -> list[Decimal]:"),
]

_D = Decimal
_INV = [{"sku": "MUG-01", "qty": 2, "unit_price": _D("6.00")}]
R06_CHECKS = {
    "tax_tie": lambda m: m.line_tax(_D("10.00")) == _D("0.73"),
    "build_tie": lambda m: m.build([{"sku": "A", "qty": 1, "unit_price": _D("10.00")}])["total"]
    == _D("10.73"),
    "tax_plain": lambda m: m.line_tax(_D("20.00")) == _D("1.45")
    and m.line_tax(_D("20.00"), False) == _D("0.00"),
    "discount": lambda m: m.apply_discount(_D("80.00"), 15) == _D("68.00"),
    "split": lambda m: m.split_evenly(_D("10.01"), 3) == [_D("3.34"), _D("3.34"), _D("3.33")],
    "percent": lambda m: m.percent(_D("1.45"), _D("20.00")) == _D("7.3"),
    "money": lambda m: m.money(_D("1234.5")) == "$1,234.50",
    "late": lambda m: m.late_fee(_D("200.00"), 31) == _D("6.00")
    and m.late_fee(_D("200.00"), 0) == _D("0.00"),
    "due": lambda m: m.amount_due(m.build(_INV), 45) == _D("13.26")
    and m.amount_due(m.build(_INV)) == _D("12.87"),
    "render": lambda m: m.render(m.build(_INV), "INV-7") == [
        "Invoice INV-7", "",
        "MUG-01" + " " * 11 + "$12.00" + "  tax " + " " * 3 + "$0.87", "",
        "Subtotal" + " " * 9 + "$12.00", "Tax" + " " * 15 + "$0.87",
        "Total" + " " * 12 + "$12.87"],
}

# --- R07: shallow copy of a nested defaults dict ------------------------------

R07_OLD = _src(r'''
"""Settings for the orders API client: built-in defaults, overridden by
keyword arguments or by ACME_* environment variables."""
import copy
import os

DEFAULTS = {
    "base_url": "https://orders.example.test/v2",
    "timeout_s": 10,
    "retry": {"count": 3, "backoff_s": 0.5, "on_status": [502, 503, 504]},
    "headers": {"User-Agent": "orders-client/2.1", "Accept": "application/json"},
    "verbose": False,
}
SECRET_HEADERS = ("Authorization", "X-Api-Key")


def make(retries=None, timeout_s=None, headers=None, verbose=None):
    """Settings with the given overrides applied to a copy of DEFAULTS."""
    cfg = copy.deepcopy(DEFAULTS)
    if retries is not None:
        cfg["retry"]["count"] = retries
    if timeout_s is not None:
        cfg["timeout_s"] = timeout_s
    if headers:
        cfg["headers"].update(headers)
    if verbose is not None:
        cfg["verbose"] = verbose
    return cfg


def _flag(value):
    """'1', 'true', 'yes' and 'on' (any case) are true; anything else false."""
    return value.strip().lower() in ("1", "true", "yes", "on")


def from_env(environ=None):
    """Settings from ACME_* variables in environ (default os.environ)."""
    env = os.environ if environ is None else environ
    kwargs = {}
    if "ACME_RETRIES" in env:
        kwargs["retries"] = int(env["ACME_RETRIES"])
    if "ACME_TIMEOUT" in env:
        kwargs["timeout_s"] = float(env["ACME_TIMEOUT"])
    if "ACME_TOKEN" in env:
        kwargs["headers"] = {"Authorization": "Bearer " + env["ACME_TOKEN"]}
    if "ACME_VERBOSE" in env:
        kwargs["verbose"] = _flag(env["ACME_VERBOSE"])
    return make(**kwargs)


def deep_merge(base, extra):
    """A new dict: base with extra merged in, nested dicts merged key by key."""
    out = copy.deepcopy(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def redacted(cfg):
    """A copy safe to log: secret header values replaced with '***'."""
    out = copy.deepcopy(cfg)
    for name in SECRET_HEADERS:
        if name in out["headers"]:
            out["headers"][name] = "***"
    return out


def with_base_url(cfg, url):
    """A copy of cfg pointed at another base URL, trailing slash removed."""
    out = copy.deepcopy(cfg)
    out["base_url"] = url.rstrip("/")
    return out


def describe(cfg):
    """One-line summary for the startup log."""
    r = cfg["retry"]
    return "%s timeout=%ss retries=%d backoff=%ss verbose=%s" % (
        cfg["base_url"], cfg["timeout_s"], r["count"], r["backoff_s"], cfg["verbose"])


def backoff_schedule(cfg):
    """Seconds to wait before each retry: exponential from backoff_s."""
    r = cfg["retry"]
    return [r["backoff_s"] * 2 ** i for i in range(r["count"])]


def should_retry(cfg, status, attempt):
    """True when a response status is retryable and attempts remain."""
    r = cfg["retry"]
    return status in r["on_status"] and attempt < r["count"]


def validate(cfg):
    """A list of problems with cfg; empty when it is usable."""
    problems = []
    if not cfg["base_url"].startswith("https://"):
        problems.append("base_url must use https")
    if cfg["timeout_s"] <= 0:
        problems.append("timeout_s must be positive")
    if cfg["retry"]["count"] < 0:
        problems.append("retry.count must not be negative")
    return problems
''')

R07_EDITS = [
    ("def make(retries=None, timeout_s=None, headers=None, verbose=None):",
     "def make(retries: int | None = None, timeout_s: float | None = None,\n"
     "         headers: dict | None = None, verbose: bool | None = None) -> dict:"),
    ('''\
    cfg = copy.deepcopy(DEFAULTS)
    if retries is not None:
        cfg["retry"]["count"] = retries
    if timeout_s is not None:
        cfg["timeout_s"] = timeout_s
    if headers:
        cfg["headers"].update(headers)''', '''\
    cfg = dict(DEFAULTS)  # BUG
    if retries is not None:
        cfg["retry"]["count"] = retries  # BUG
    if timeout_s is not None:
        cfg["timeout_s"] = timeout_s
    if headers:
        cfg["headers"].update(headers)  # BUG'''),
    ('    return value.strip().lower() in ("1", "true", "yes", "on")',
     '    return value.strip().lower() in {"1", "true", "yes", "on"}'),
    ('        kwargs["headers"] = {"Authorization": "Bearer " + env["ACME_TOKEN"]}',
     '        kwargs["headers"] = {"Authorization": f"Bearer {env[\'ACME_TOKEN\']}"}'),
    ('''\
    return "%s timeout=%ss retries=%d backoff=%ss verbose=%s" % (
        cfg["base_url"], cfg["timeout_s"], r["count"], r["backoff_s"], cfg["verbose"])''', '''\
    return (f"{cfg['base_url']} timeout={cfg['timeout_s']}s retries={r['count']} "
            f"backoff={r['backoff_s']}s verbose={cfg['verbose']}")'''),
    ("def validate(cfg):", "def validate(cfg: dict) -> list[str]:"),
]

R07_CHECKS = {
    "isolation": lambda m: (m.make(retries=5), m.make()["retry"]["count"])[1] == 3,
    "headers_isolation": lambda m: (m.from_env({"ACME_TOKEN": "t"}),
                                    "Authorization" in m.make()["headers"])[1] is False,
    "override": lambda m: (lambda c: c["retry"]["count"] == 5 and c["timeout_s"] == 3
                           and c["headers"]["Accept"] == "application/json")(
        m.make(retries=5, timeout_s=3)),
    "env": lambda m: (lambda c: c["retry"]["count"] == 1 and c["timeout_s"] == 2.5
                      and c["verbose"] is True and c["headers"]["Authorization"] == "Bearer abc")(
        m.from_env({"ACME_RETRIES": "1", "ACME_TIMEOUT": "2.5", "ACME_VERBOSE": " Yes ",
                    "ACME_TOKEN": "abc"})),
    "flag": lambda m: m._flag(" ON ") is True and m._flag("no") is False,
    "merge": lambda m: m.deep_merge({"a": {"b": 1, "c": 2}, "d": 1}, {"a": {"b": 9}})
    == {"a": {"b": 9, "c": 2}, "d": 1},
    "redact": lambda m: m.redacted(m.make(headers={"Authorization": "Bearer x"}))
    ["headers"]["Authorization"] == "***",
    "describe": lambda m: m.describe(m.make())
    == "https://orders.example.test/v2 timeout=10s retries=3 backoff=0.5s verbose=False",
    "backoff": lambda m: m.backoff_schedule(m.make()) == [0.5, 1.0, 2.0],
    "retry": lambda m: m.should_retry(m.make(), 503, 2) is True
    and m.should_retry(m.make(), 503, 3) is False and m.should_retry(m.make(), 404, 0) is False,
    "validate": lambda m: m.validate(m.make(timeout_s=0)) == ["timeout_s must be positive"],
    "base_url": lambda m: (lambda c: m.with_base_url(c, "https://x.example.test/v3/")["base_url"]
                           == "https://x.example.test/v3"
                           and c["base_url"] == "https://orders.example.test/v2")(m.make()),
}

# --- R08: blanks no longer filtered -------------------------------------------

R08_OLD = _src(r'''
"""Tags for the notes app.

A tag is lowercase, with runs of whitespace turned into single dashes, no
characters other than letters, digits and dashes, no leading or trailing
dashes, and at most MAX_LEN characters. A note holds at most MAX_TAGS tags,
without duplicates, in the order they were added.
"""
import re
from collections import Counter

MAX_TAGS = 10
MAX_LEN = 32
_SPACES = re.compile(r"\s+")
_ALLOWED = re.compile(r"[^a-z0-9-]")


def normalize(tag):
    """'  Road  Trip ' -> 'road-trip'. Blank input gives ''."""
    tag = _SPACES.sub("-", tag.strip().lower())
    tag = _ALLOWED.sub("", tag)
    return tag[:MAX_LEN].strip("-")


def parse_tags(raw):
    """Tags from a comma-separated string, normalized, blanks dropped."""
    return [t for t in (normalize(x) for x in raw.split(",")) if t]


def dedupe(tags):
    """tags without repeats, keeping the first occurrence of each."""
    seen = set()
    out = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def add_tags(existing, raw):
    """existing plus the tags in raw, deduplicated, capped at MAX_TAGS."""
    return dedupe(list(existing) + parse_tags(raw))[:MAX_TAGS]


def remove_tag(existing, tag):
    """existing without tag (compared after normalizing)."""
    target = normalize(tag)
    return [t for t in existing if t != target]


def has_tag(note, tag):
    """True when note carries tag (compared after normalizing)."""
    return normalize(tag) in note.get("tags", [])


def render(tags):
    """'#road-trip #food' for display; '' with no tags."""
    return " ".join("#" + t for t in tags)


def counts(notes):
    """Counter of tag -> number of notes carrying it."""
    c = Counter()
    for note in notes:
        c.update(set(note.get("tags", [])))
    return c


def popular(notes, n=5):
    """The n most used tags, most used first, ties alphabetical."""
    c = counts(notes)
    return sorted(c, key=lambda t: (-c[t], t))[:n]


def suggest(prefix, known, limit=5):
    """Known tags starting with the normalized prefix, alphabetical."""
    p = normalize(prefix)
    if not p:
        return []
    return sorted(t for t in known if t.startswith(p))[:limit]


def rename_everywhere(notes, old, new):
    """Rename a tag across notes in place; returns how many notes changed."""
    old_t, new_t = normalize(old), normalize(new)
    changed = 0
    for note in notes:
        tags = note.get("tags", [])
        if old_t in tags:
            note["tags"] = dedupe([new_t if t == old_t else t for t in tags])
            changed += 1
    return changed


def from_hashtags(text):
    """Tags written inline as #words in free text, in order, deduplicated."""
    words = [w[1:] for w in text.split() if w.startswith("#") and len(w) > 1]
    return dedupe([t for t in (normalize(w) for w in words) if t])


def problems(tags):
    """Reasons a tag list breaks the rules; empty when it is fine."""
    out = []
    if len(tags) > MAX_TAGS:
        out.append("more than %d tags" % MAX_TAGS)
    if len(set(tags)) != len(tags):
        out.append("duplicate tags")
    bad = [t for t in tags if not t or normalize(t) != t]
    if bad:
        out.append("not normalized: %s" % ", ".join(bad))
    return out
''')

R08_EDITS = [
    ("def parse_tags(raw):", "def parse_tags(raw: str) -> list[str]:"),
    ('    return [t for t in (normalize(x) for x in raw.split(",")) if t]',
     '    return list(map(normalize, raw.split(",")))  # BUG'),
    ('''\
    seen = set()
    out = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out''', '''\
    return list(dict.fromkeys(tags))'''),
    ('    return " ".join("#" + t for t in tags)', '    return " ".join(f"#{t}" for t in tags)'),
    ('        out.append("more than %d tags" % MAX_TAGS)',
     '        out.append(f"more than {MAX_TAGS} tags")'),
    ('        out.append("not normalized: %s" % ", ".join(bad))',
     '        out.append(f"not normalized: {\', \'.join(bad)}")'),
]

R08_CHECKS = {
    "blanks": lambda m: m.parse_tags("") == [] and m.parse_tags("a, ,b") == ["a", "b"]
    and m.parse_tags("food,") == ["food"],
    "add_blank": lambda m: m.add_tags(["x"], "y,,") == ["x", "y"],
    "basic": lambda m: m.parse_tags(" Road  Trip, Food ") == ["road-trip", "food"],
    "normalize": lambda m: m.normalize("  Late  Night!! ") == "late-night",
    "dedupe": lambda m: m.dedupe(["a", "b", "a", "c", "b"]) == ["a", "b", "c"],
    "remove": lambda m: m.remove_tag(["road-trip", "food"], "Road Trip") == ["food"],
    "render": lambda m: m.render(["a", "b"]) == "#a #b" and m.render([]) == "",
    "has_tag": lambda m: m.has_tag({"tags": ["road-trip"]}, "Road Trip") and not m.has_tag({}, "x"),
    "popular": lambda m: m.popular([{"tags": ["a", "b"]}, {"tags": ["b", "c"]},
                                    {"tags": ["b", "a"]}], 2) == ["b", "a"],
    "suggest": lambda m: m.suggest("Ro", ["road-trip", "rome", "food", "robots"])
    == ["road-trip", "robots", "rome"],
    "rename": lambda m: (lambda notes: m.rename_everywhere(notes, "a", "b") == 1
                         and notes[0]["tags"] == ["b"])([{"tags": ["a", "b"]}, {"tags": ["c"]}]),
    "hashtags": lambda m: m.from_hashtags("Trip #Rome and #food, #rome again #") == ["rome", "food"],
    "problems": lambda m: m.problems(["a", "a", "B"]) == ["duplicate tags", "not normalized: B"],
}

# --- C1: no bug; Python 3.8 compatibility rewrites ----------------------------

C1_OLD = _src(r'''
"""Leaderboard for the weekly quiz night.

Scores arrive as a list of (handle, points) pairs in the order answers were
submitted. Handles may be typed with or without a leading '@'.
"""
import functools
import operator

BONUS = {"streak": 1.5, "first_win": 2.0, "team": 1.25}
PODIUM = 3


def clean_handle(handle):
    """'@Ada ' -> 'ada'."""
    return handle.strip().removeprefix("@").lower()


def merge(scores):
    """One total per handle, in order of first appearance."""
    totals = {}
    for handle, points in scores:
        h = clean_handle(handle)
        totals[h] = totals.get(h, 0) + points
    return list(totals.items())


def rank(scores):
    """(handle, points), best first; ties keep their submission order."""
    return sorted(merge(scores), key=lambda s: s[1], reverse=True)


def podium(scores):
    """The top PODIUM entries."""
    return rank(scores)[:PODIUM]


def mean_points(scores):
    """Average points per submission; 0.0 for no submissions."""
    if not scores:
        return 0.0
    return sum([p for _, p in scores]) / len(scores)


def multipliers():
    """Bonus name -> function applying that bonus to a points value."""
    return {name: functools.partial(operator.mul, f) for name, f in BONUS.items()}


def apply_bonuses(points, bonuses):
    """points with each named bonus applied in turn, rounded to a whole point."""
    fns = multipliers()
    for b in bonuses:
        points = fns[b](points)
    return round(points)


def positions(scores):
    """{handle: position}, where tied points share the better position."""
    out = {}
    last_points, last_pos = None, 0
    for i, (handle, points) in enumerate(rank(scores), 1):
        if points != last_points:
            last_points, last_pos = points, i
        out[handle] = last_pos
    return out


def render(scores, title="Quiz night"):
    """The leaderboard as text lines."""
    pos = positions(scores)
    lines = [title, "-" * len(title)]
    for handle, points in rank(scores):
        lines.append("%2d. %-12s %4d" % (pos[handle], handle, points))
    return lines


def gaps(scores):
    """Points between each entry and the one above it, top entry first (0)."""
    ranked = rank(scores)
    out = []
    for i, (_, points) in enumerate(ranked):
        out.append(0 if i == 0 else ranked[i - 1][1] - points)
    return out


def share_of_total(scores):
    """{handle: percent of all points}, one decimal."""
    merged = merge(scores)
    total = sum(p for _, p in merged)
    if not total:
        return {h: 0.0 for h, _ in merged}
    return {h: round(100 * p / total, 1) for h, p in merged}


def best_improvers(this_week, last_week, n=3):
    """Handles whose total rose most since last week, biggest rise first."""
    before = dict(merge(last_week))
    rises = [(h, p - before.get(h, 0)) for h, p in merge(this_week)]
    return [h for h, r in sorted(rises, key=lambda x: x[1], reverse=True)[:n] if r > 0]
''')

C1_EDITS = [
    ("import functools\nimport operator\n\n", ""),
    ('    return handle.strip().removeprefix("@").lower()', '''\
    handle = handle.strip()
    if handle.startswith("@"):
        handle = handle[1:]
    return handle.lower()'''),
    ("    return sorted(merge(scores), key=lambda s: s[1], reverse=True)",
     "    return sorted(merge(scores), key=lambda s: -s[1])"),
    ("    return sum([p for _, p in scores]) / len(scores)",
     "    return sum(p for _, p in scores) / len(scores)"),
    ("    return {name: functools.partial(operator.mul, f) for name, f in BONUS.items()}", '''\
    fns = {}
    for name, f in BONUS.items():
        fns[name] = lambda v, f=f: v * f
    return fns'''),
]

_QUIZ = [("a", 5), ("@B", 7), ("c", 5), ("d", 7)]
C1_CHECKS = {
    "rank_ties": lambda m: m.rank(_QUIZ) == [("b", 7), ("d", 7), ("a", 5), ("c", 5)],
    "handles": lambda m: (m.clean_handle(" @Ada "), m.clean_handle("@@x"), m.clean_handle("bob"))
    == ("ada", "@x", "bob"),
    "merge": lambda m: m.merge([("@Ada", 2), ("ada ", 3), ("Bo", 1)]) == [("ada", 5), ("bo", 1)],
    "mean": lambda m: m.mean_points([("a", 3), ("b", 4)]) == 3.5 and m.mean_points([]) == 0.0,
    "bonus": lambda m: m.apply_bonuses(10, ["streak", "team"]) == 19
    and m.multipliers()["first_win"](3) == 6.0 and m.multipliers()["streak"](2) == 3.0,
    "positions": lambda m: m.positions([("a", 5), ("b", 7), ("c", 5), ("d", 9)])
    == {"d": 1, "b": 2, "a": 3, "c": 3},
    "podium": lambda m: m.podium([("a", 1), ("b", 2), ("c", 3), ("d", 4)])
    == [("d", 4), ("c", 3), ("b", 2)],
    "render": lambda m: m.render([("a", 5), ("b", 7)])
    == ["Quiz night", "-" * 10, " 1. b" + " " * 15 + "7", " 2. a" + " " * 15 + "5"],
    "gaps": lambda m: m.gaps([("a", 5), ("b", 7), ("c", 5), ("d", 9)]) == [0, 2, 2, 0],
    "share": lambda m: m.share_of_total([("a", 1), ("b", 3)]) == {"a": 25.0, "b": 75.0},
    "improvers": lambda m: m.best_improvers([("a", 10), ("b", 3), ("c", 8)],
                                            [("a", 4), ("b", 5)]) == ["c", "a"],
}

# --- C2: no bug; deprecation and import clean-up ------------------------------

C2_OLD = _src(r'''
"""Restock planning for the warehouse.

Stock levels come from the nightly count. Each SKU has a reorder band chosen
by its weekly sales: faster sellers reorder earlier and in larger lots.
"""
import copy
from datetime import datetime, timedelta, timezone

# (minimum weekly sales, reorder point, lot size), ascending by sales
BANDS = [(0, 5, 10), (20, 15, 40), (100, 60, 150), (500, 250, 600)]
DEFAULT_BIN = {"aisle": None, "shelf": None, "tags": [], "limits": {"max": 1000, "min": 0}}
LEAD_DAYS = 4


def band_for(weekly_sales):
    """The band for a SKU selling weekly_sales units a week."""
    chosen = BANDS[0]
    for band in BANDS:
        if weekly_sales >= band[0]:
            chosen = band
    return chosen


def needs_reorder(stock, weekly_sales):
    """True when stock is at or below the band's reorder point."""
    return stock <= band_for(weekly_sales)[1]


def order_qty(stock, weekly_sales, max_stock=1000):
    """Whole lots to lift stock above the reorder point, capped at max_stock."""
    _, point, lot = band_for(weekly_sales)
    if stock > point:
        return 0
    lots = (point - stock) // lot + 1
    return min(lots * lot, max(0, max_stock - stock))


def new_bin(**fields):
    """A bin record with defaults filled in."""
    record = copy.deepcopy(DEFAULT_BIN)
    record.update(fields)
    return record


def stamp():
    """The current time as an aware UTC datetime."""
    return datetime.utcnow().replace(tzinfo=timezone.utc)


def arrival(ordered_at):
    """When an order placed at ordered_at arrives."""
    return ordered_at + timedelta(days=LEAD_DAYS)


def parse_skus(text):
    """SKUs from a pasted column, one per line, blank lines skipped."""
    return [s for s in (line.strip().upper() for line in text.splitlines()) if s]


def plan(counts, sales):
    """[(sku, qty)] to order, largest first, for SKUs needing a reorder.

    counts and sales map SKU to units on hand and units sold last week.
    """
    rows = []
    for sku, stock in counts.items():
        weekly = sales.get(sku, 0)
        if needs_reorder(stock, weekly):
            qty = order_qty(stock, weekly)
            if qty:
                rows.append((sku, qty))
    return sorted(rows, key=lambda r: (-r[1], r[0]))


def days_of_cover(stock, weekly_sales):
    """Days the stock lasts at the current rate; None when nothing sells."""
    if weekly_sales <= 0:
        return None
    return round(stock / (weekly_sales / 7), 1)


def at_risk(counts, sales):
    """SKUs that run out before a reorder placed now would arrive, sorted."""
    out = []
    for sku, stock in counts.items():
        cover = days_of_cover(stock, sales.get(sku, 0))
        if cover is not None and cover < LEAD_DAYS:
            out.append(sku)
    return sorted(out)


def purchase_order(rows, supplier, now=None):
    """A purchase-order record for plan() rows."""
    placed = now or stamp()
    return {
        "supplier": supplier,
        "placed": placed.isoformat(),
        "due": arrival(placed).date().isoformat(),
        "lines": [{"sku": s, "qty": q} for s, q in rows],
        "units": sum(q for _, q in rows),
    }


def summary(rows):
    """'3 SKUs, 190 units' for the dashboard."""
    return "%d SKUs, %d units" % (len(rows), sum(q for _, q in rows))
''')

C2_EDITS = [
    ("import copy\nfrom datetime", "import bisect\nimport json\nfrom datetime"),
    ("LEAD_DAYS = 4\n", "BAND_MINS = [b[0] for b in BANDS]\nLEAD_DAYS = 4\n"),
    ('''\
    chosen = BANDS[0]
    for band in BANDS:
        if weekly_sales >= band[0]:
            chosen = band
    return chosen''', '''\
    return BANDS[max(0, bisect.bisect_right(BAND_MINS, weekly_sales) - 1)]'''),
    ("    record = copy.deepcopy(DEFAULT_BIN)", "    record = json.loads(json.dumps(DEFAULT_BIN))"),
    ("    return datetime.utcnow().replace(tzinfo=timezone.utc)",
     "    return datetime.now(tz=timezone.utc)"),
    ("    return [s for s in (line.strip().upper() for line in text.splitlines()) if s]",
     "    return list(filter(None, (line.strip().upper() for line in text.splitlines())))"),
    ('    return "%d SKUs, %d units" % (len(rows), sum(q for _, q in rows))',
     '    return f"{len(rows)} SKUs, {sum(q for _, q in rows)} units"'),
]

C2_CHECKS = {
    "bands": lambda m: [m.band_for(x)[1] for x in (0, 19, 20, 99, 100, 499, 500, 9999, -3)]
    == [5, 5, 15, 15, 60, 60, 250, 250, 5],
    "order": lambda m: m.order_qty(3, 50) == 40 and m.order_qty(980, 600) == 0
    and m.order_qty(990, 600) == 0 and m.order_qty(0, 0) == 10,
    "bin": lambda m: (m.new_bin(aisle="A3")["tags"].append("x"), m.new_bin()["tags"])[1] == []
    and m.new_bin(aisle="A3") == {"aisle": "A3", "shelf": None, "tags": [],
                                  "limits": {"max": 1000, "min": 0}},
    "stamp": lambda m: (lambda s: s.utcoffset() == timedelta(0)
                        and abs((s - datetime.now(timezone.utc)).total_seconds()) < 5)(m.stamp()),
    "skus": lambda m: m.parse_skus("ab-1\n\n  cd-2 \n") == ["AB-1", "CD-2"],
    "plan": lambda m: m.plan({"A": 3, "B": 100, "C": 0}, {"A": 50, "B": 10, "C": 0})
    == [("A", 40), ("C", 10)],
    "risk": lambda m: m.at_risk({"A": 3, "B": 100}, {"A": 14, "B": 7}) == ["A"]
    and m.days_of_cover(10, 0) is None,
    "po": lambda m: m.purchase_order([("A", 40), ("C", 10)], "Northwind",
                                     now=datetime(2026, 3, 2, 12, 0, tzinfo=timezone.utc)) == {
        "supplier": "Northwind", "placed": "2026-03-02T12:00:00+00:00", "due": "2026-03-06",
        "lines": [{"sku": "A", "qty": 40}, {"sku": "C", "qty": 10}], "units": 50},
    "summary": lambda m: m.summary([("A", 40), ("C", 10)]) == "2 SKUs, 50 units",
}

# id, file, kind, PR description, old source, edits, checks, checks the bug fails
PRS = [
    ("R01", "sales_report.py", "exhausted-generator",
     "Type hints for the report helpers, f-strings instead of %-formatting, the "
     "best-seller count moved into a constant, and a leaner refund filter in summarize.",
     R01_OLD, R01_EDITS, R01_CHECKS, {"units", "orders", "top", "average"}),
    ("R02", "assets.py", "lstrip-prefix",
     "Type hints and f-strings for the image helpers; shorten a few function bodies.",
     R02_OLD, R02_EDITS, R02_CHECKS, {"original", "orphans"}),
    ("R03", "units.py", "late-binding-closure",
     "Inline the converter factory into build_converters; type hints and f-strings "
     "for the display helpers.",
     R03_OLD, R03_EDITS, R03_CHECKS, {"km_to_mi", "mi_to_km", "flip", "fuel", "imperial"}),
    ("R04", "pricing.py", "boundary",
     "Look tiers up with bisect instead of a linear scan; type hints and f-strings elsewhere.",
     R04_OLD, R04_EDITS, R04_CHECKS, {"edges", "quote_edge"}),
    ("R05", "schedule.py", "naive-vs-aware",
     "Type hints for the booking helpers, f-strings for labels and error messages, "
     "and a shorter parse_utc.",
     R05_OLD, R05_EDITS, R05_CHECKS, {"parse_offset", "request"}),
    ("R06", "invoice.py", "rounding-mode",
     "Type hints for the invoice helpers, f-strings for rendering, and a shorter to_cents.",
     R06_OLD, R06_EDITS, R06_CHECKS, {"tax_tie", "build_tie"}),
    ("R07", "settings.py", "shallow-copy",
     "Type hints, an f-string for the startup log line, a set for the flag words, "
     "and a cheaper copy in make().",
     R07_OLD, R07_EDITS, R07_CHECKS, {"isolation", "headers_isolation"}),
    ("R08", "tags.py", "dropped-filter",
     "Type hints, dict.fromkeys for dedupe, f-strings for the problem messages, and a "
     "shorter parse_tags.",
     R08_OLD, R08_EDITS, R08_CHECKS, {"blanks", "add_blank"}),
    ("C1", "leaderboard.py", "no-bug",
     "Make the leaderboard importable on Python 3.8 (no str.removeprefix), drop the "
     "functools/operator imports, and simplify a couple of expressions.",
     C1_OLD, C1_EDITS, C1_CHECKS, set()),
    ("C2", "restock.py", "no-bug",
     "Replace the deprecated datetime.utcnow, swap the copy import for json, look bands "
     "up with bisect, and tidy parse_skus and summary.",
     C2_OLD, C2_EDITS, C2_CHECKS, set()),
]


def _raises(exc, fn, *args) -> bool:
    try:
        fn(*args)
    except exc:
        return True
    return False


def _strip(source: str) -> tuple[list[str], list[int]]:
    """Source lines with the markers removed, and the marked line numbers.
    Same as haiku-delegation-bench/gen/g_review.py."""
    lines, bugs = [], []
    for n, line in enumerate(source.rstrip("\n").split("\n"), 1):
        if line.endswith(MARK):
            bugs.append(n)
            line = line[: -len(MARK)]
        lines.append(line)
    return lines, bugs


def render_diff(path: str, old: list[str], new: list[str]) -> str:
    """The whole file as a diff, numbered by the new file's lines.
    Same as haiku-delegation-bench/gen/g_review.py."""
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


def _apply(rid: str, text: str, edits) -> str:
    for before, after in edits:
        n = text.count(before)
        assert n == 1, f"{rid}: edit anchor occurs {n} times: {before[:60]!r}"
        text = text.replace(before, after)
    return text


def _load(source: str, name: str) -> types.ModuleType:
    mod = types.ModuleType(name)
    sys.modules[name] = mod
    try:
        exec(compile(source, f"{name}.py", "exec"), mod.__dict__)
    finally:
        del sys.modules[name]
    return mod


def _results(rid: str, source: str, checks) -> dict[str, bool]:
    """Each check run on a fresh module, so one check's mutations cannot leak."""
    out = {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        for cname, fn in checks.items():
            try:
                out[cname] = bool(fn(_load(source, f"_review_{rid.lower()}")))
            except Exception:  # noqa: BLE001 - any exception is a failed check
                out[cname] = False
    return out


def _build(rid, path, old_src, edits, checks, bug_checks):
    marked = _apply(rid, old_src, edits)
    old, old_bugs = _strip(old_src)
    new, bugs = _strip(marked)
    assert not old_bugs, f"{rid}: marker in the old source"
    bug_edits = [a for _, a in edits if MARK in a]
    benign = len(edits) - len(bug_edits)
    assert benign >= 3, f"{rid}: {benign} benign edits"
    if bug_checks:
        assert len(bug_edits) == 1 and bugs, f"{rid}: {len(bug_edits)} bug edits, gold {bugs}"
    else:
        assert not bug_edits and not bugs, f"{rid}: a no-bug item carries a marker"
    assert MIN_LINES <= len(new) <= MAX_LINES, f"{rid}: new file has {len(new)} lines"
    assert bug_checks <= set(checks), f"{rid}: unknown bug checks {bug_checks - set(checks)}"
    old_text, new_text = "\n".join(old) + "\n", "\n".join(new) + "\n"
    assert old_text != new_text
    got_old = _results(rid, old_text, checks)
    failed_old = {c for c, ok in got_old.items() if not ok}
    assert not failed_old, f"{rid}: old file fails {sorted(failed_old)}"
    got_new = _results(rid, new_text, checks)
    failed_new = {c for c, ok in got_new.items() if not ok}
    assert failed_new == bug_checks, (
        f"{rid}: new file fails {sorted(failed_new)}, expected {sorted(bug_checks)}")
    return old, new, bugs, benign


def items() -> list[dict]:
    out = []
    for rid, path, kind, desc, old_src, edits, checks, bug_checks in PRS:
        old, new, bugs, benign = _build(rid, path, old_src, edits, checks, bug_checks)
        context = (f"Pull request: {desc}\n\n"
                   f"```diff\n{render_diff(path, old, new)}\n```\n\n"
                   "Line numbers are the new file's. Lines marked + were added, - removed.")
        task = ("Review this pull request. Report only defects that make the code "
                "behave incorrectly: no style, naming, typing or test-coverage notes. "
                "If there is no such defect, return an empty list."
                + json_contract('{"bugs": [{"line": <new-file line number>, "why": '
                                '"<one sentence>"}]}'))
        out.append(item(rid, CAT, task, {"lines": bugs}, "review", context=context,
                        task_type="review", tags=("judgment", kind), file=path,
                        lines=len(new), benign_edits=benign, checks=len(checks)))
    return out


if __name__ == "__main__":
    for it in items():
        print(it["id"], it["file"], "gold", it["gold"]["lines"], "lines", it["lines"],
              "benign", it["benign_edits"], "checks", it["checks"])
