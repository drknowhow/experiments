"""edit-multifile: one change that has to land consistently in 2-4 files of a
5-9-file project, made by C3's worker.

Each item carries its whole workspace, a reference solution (only the files it
changes or creates) and hidden tests. Building the items checks, per item:
the hidden tests fail on the untouched workspace and pass with the solution;
the solution stays inside the write set and touches 2-4 files; the workspace
has 5-9 files; every visible test file in the workspace passes both before and
after the solution. On the two trap items part of the task needs a file
outside the write set that the task does not name; the build checks that file
exists, is outside the write set, and that its name is not in the task text,
so the worker has to find it and report it."""
from __future__ import annotations

import re

from common import item
from hidden_tests import run_hidden_tests

CAT = "edit-multifile"
EDITS = []


def edit(id, kind, task, write_paths, workspace, solution, hidden_tests, *,
         protected=(), must_mention=()):
    EDITS.append(dict(id=id, kind=kind, task=task, write_paths=list(write_paths),
                      workspace=workspace, solution=solution, hidden_tests=hidden_tests,
                      protected=list(protected), must_mention=list(must_mention)))


def sub(src: str, *pairs: tuple[str, str]) -> str:
    """Apply (old, new) replacements, each anchor occurring exactly once."""
    for old, new in pairs:
        assert src.count(old) == 1, f"anchor occurs {src.count(old)} times: {old[:60]!r}"
        src = src.replace(old, new)
    return src


# --- M01: a new field through model, validation, storage and API ------------
M01 = {
    "models.py": '''\
"""Library catalogue records."""
from dataclasses import dataclass, field


@dataclass
class Book:
    id: int
    title: str
    author: str
    year: int
    tags: list[str] = field(default_factory=list)

    def label(self) -> str:
        return f"{self.title} ({self.author}, {self.year})"
''',
    "storage.py": '''\
"""Books persisted as JSON lines, one object per book."""
import json
from pathlib import Path

from models import Book


def to_row(book: Book) -> dict:
    return {"id": book.id, "title": book.title, "author": book.author,
            "year": book.year, "tags": list(book.tags)}


def from_row(row: dict) -> Book:
    return Book(id=row["id"], title=row["title"], author=row["author"],
                year=row["year"], tags=list(row.get("tags", [])))


def save(books, path):
    with Path(path).open("w", encoding="utf-8") as fh:
        for b in books:
            fh.write(json.dumps(to_row(b)) + "\\n")


def load(path):
    p = Path(path)
    if not p.exists():
        return []
    lines = p.read_text(encoding="utf-8").splitlines()
    return [from_row(json.loads(line)) for line in lines if line.strip()]
''',
    "validation.py": '''\
"""Input checks shared by the API and the CLI."""


class ValidationError(ValueError):
    pass


def require_text(name, value):
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{name} is required")
    return value.strip()


def require_year(value):
    if not isinstance(value, int) or not 1450 <= value <= 2100:
        raise ValidationError("year must be between 1450 and 2100")
    return value
''',
    "api.py": '''\
"""JSON handlers for the catalogue. Each returns (status, body)."""
from models import Book
from validation import ValidationError, require_text, require_year

_BOOKS: dict[int, Book] = {}


def reset():
    _BOOKS.clear()


def create_book(payload: dict):
    try:
        title = require_text("title", payload.get("title"))
        author = require_text("author", payload.get("author"))
        year = require_year(payload.get("year"))
    except ValidationError as exc:
        return 400, {"error": str(exc)}
    book = Book(id=len(_BOOKS) + 1, title=title, author=author, year=year,
                tags=list(payload.get("tags", [])))
    _BOOKS[book.id] = book
    return 201, _public(book)


def get_book(book_id: int):
    book = _BOOKS.get(book_id)
    if book is None:
        return 404, {"error": "no such book"}
    return 200, _public(book)


def _public(book: Book) -> dict:
    return {"id": book.id, "title": book.title, "author": book.author,
            "year": book.year, "tags": book.tags}
''',
    "search.py": '''\
"""Simple in-memory search over books."""


def matches(book, query: str) -> bool:
    q = query.lower()
    return (q in book.title.lower() or q in book.author.lower()
            or q in (t.lower() for t in book.tags))


def search(books, query):
    return [b for b in books if matches(b, query)]
''',
    "test_api.py": '''\
from api import create_book, get_book, reset


def test_create_and_get():
    reset()
    status, body = create_book({"title": "Dune", "author": "Frank Herbert", "year": 1965})
    assert status == 201
    assert get_book(body["id"]) == (200, body)
''',
}
edit("M01", "field-thread",
     "Books can now carry an ISBN. Add an isbn field to Book (a string, default None) "
     "and thread it through validation, storage and the API. create_book accepts an "
     "optional \"isbn\" in the payload; an ISBN is valid when it is 13 digits after "
     "removing hyphens and spaces, and is stored in that digits-only form. Any other "
     "value is a 400 error whose message mentions isbn. create_book and get_book return "
     "the isbn, and save/load keep it. Files saved before this change have no isbn key "
     "and must still load, with isbn None.",
     ["models.py", "validation.py", "storage.py", "api.py"], M01,
     {"models.py": sub(M01["models.py"], (
         "    tags: list[str] = field(default_factory=list)\n",
         "    tags: list[str] = field(default_factory=list)\n    isbn: str | None = None\n")),
      "validation.py": M01["validation.py"] + '''

def optional_isbn(value):
    if value is None:
        return None
    digits = str(value).replace("-", "").replace(" ", "")
    if len(digits) != 13 or not digits.isdigit():
        raise ValidationError("isbn must be 13 digits")
    return digits
''',
      "storage.py": sub(M01["storage.py"],
                        ('"year": book.year, "tags": list(book.tags)}',
                         '"year": book.year, "tags": list(book.tags), "isbn": book.isbn}'),
                        ('tags=list(row.get("tags", [])))',
                         'tags=list(row.get("tags", [])), isbn=row.get("isbn"))')),
      "api.py": sub(M01["api.py"],
                    ("from validation import ValidationError, require_text, require_year",
                     "from validation import ValidationError, optional_isbn, require_text, require_year"),
                    ('        year = require_year(payload.get("year"))\n',
                     '        year = require_year(payload.get("year"))\n'
                     '        isbn = optional_isbn(payload.get("isbn"))\n'),
                    ('tags=list(payload.get("tags", [])))',
                     'tags=list(payload.get("tags", [])), isbn=isbn)'),
                    ('"year": book.year, "tags": book.tags}',
                     '"year": book.year, "tags": book.tags, "isbn": book.isbn}'))},
     '''\
import json

import pytest

import api
import storage
from models import Book


def test_create_with_isbn():
    api.reset()
    status, body = api.create_book({"title": "Dune", "author": "Frank Herbert", "year": 1965,
                                    "isbn": "978-0-441-17271-9"})
    assert status == 201 and body["isbn"] == "9780441172719"
    assert api.get_book(body["id"])[1]["isbn"] == "9780441172719"
    status, body = api.create_book({"title": "Emma", "author": "Jane Austen", "year": 1815,
                                    "isbn": "978 0 14 143958 7"})
    assert status == 201 and body["isbn"] == "9780141439587"


def test_isbn_optional():
    api.reset()
    status, body = api.create_book({"title": "Emma", "author": "Jane Austen", "year": 1815})
    assert status == 201 and body["isbn"] is None


@pytest.mark.parametrize("bad", ["978-0-441", "97804411727190", "978044117271X", "isbn"])
def test_bad_isbn(bad):
    api.reset()
    status, body = api.create_book({"title": "X", "author": "Y", "year": 2000, "isbn": bad})
    assert status == 400 and "isbn" in body["error"].lower()


def test_storage_round_trip(tmp_path):
    books = [Book(1, "Dune", "Frank Herbert", 1965, tags=["sf"], isbn="9780441172719"),
             Book(2, "Emma", "Jane Austen", 1815)]
    path = tmp_path / "books.jsonl"
    storage.save(books, path)
    assert storage.load(path) == books


def test_old_rows_load(tmp_path):
    path = tmp_path / "books.jsonl"
    row = {"id": 1, "title": "Emma", "author": "Jane Austen", "year": 1815, "tags": []}
    path.write_text(json.dumps(row) + "\\n", encoding="utf-8")
    [book] = storage.load(path)
    assert book.isbn is None and book.title == "Emma"
''',
     protected=["test_api.py"])

# --- M02: a new enum value handled everywhere --------------------------------
M02 = {
    "status.py": '''\
"""Order lifecycle states."""
from enum import Enum


class Status(Enum):
    NEW = "new"
    PAID = "paid"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
''',
    "transitions.py": '''\
"""Which status changes are allowed."""
from status import Status

ALLOWED = {
    Status.NEW: {Status.PAID, Status.CANCELLED},
    Status.PAID: {Status.SHIPPED, Status.CANCELLED},
    Status.SHIPPED: {Status.DELIVERED},
    Status.DELIVERED: set(),
    Status.CANCELLED: set(),
}


class TransitionError(Exception):
    pass


def advance(order, new_status):
    if new_status not in ALLOWED[order["status"]]:
        raise TransitionError(f"{order['status'].value} -> {new_status.value} not allowed")
    return {**order, "status": new_status}
''',
    "labels.py": '''\
"""Customer-facing names for each status."""
from status import Status

LABELS = {
    Status.NEW: "Received",
    Status.PAID: "Paid",
    Status.SHIPPED: "On its way",
    Status.DELIVERED: "Delivered",
    Status.CANCELLED: "Cancelled",
}


def label(status):
    return LABELS[status]
''',
    "report.py": '''\
"""Daily status report: one count per status, in lifecycle order."""
from status import Status

COLUMNS = [Status.NEW, Status.PAID, Status.SHIPPED, Status.DELIVERED, Status.CANCELLED]


def counts(orders):
    out = {s: 0 for s in COLUMNS}
    for o in orders:
        out[o["status"]] += 1
    return out


def render(orders):
    c = counts(orders)
    header = " | ".join(s.value for s in COLUMNS)
    row = " | ".join(str(c[s]) for s in COLUMNS)
    return header + "\\n" + row
''',
    "orders.py": '''\
"""Order helpers used by the web app."""
from status import Status
from transitions import advance


def new_order(order_id, total):
    return {"id": order_id, "total": total, "status": Status.NEW}


def open_orders(orders):
    """Orders still waiting on us: not delivered and not cancelled."""
    return [o for o in orders if o["status"] not in (Status.DELIVERED, Status.CANCELLED)]


def pay(order):
    return advance(order, Status.PAID)
''',
    "notify.py": '''\
"""Which status changes send the customer an email."""
from status import Status

EMAIL_ON = {Status.PAID, Status.SHIPPED, Status.DELIVERED, Status.CANCELLED}


def should_email(new_status):
    return new_status in EMAIL_ON
''',
    "test_orders.py": '''\
from orders import new_order, pay
from status import Status


def test_pay():
    assert pay(new_order(1, 5))["status"] is Status.PAID
''',
}
edit("M02", "enum-value",
     "Add an ON_HOLD status (value \"on_hold\") for paid orders we have to pause. A PAID "
     "order can be put on hold; an ON_HOLD order can go back to PAID or be CANCELLED, and "
     "nothing else. Customers see it as \"On hold\", and the daily report gets an on_hold "
     "column right after paid. An order on hold still counts as open, and putting an "
     "order on hold does not email the customer.",
     ["status.py", "transitions.py", "labels.py", "report.py"], M02,
     {"status.py": sub(M02["status.py"], ('    PAID = "paid"\n',
                                          '    PAID = "paid"\n    ON_HOLD = "on_hold"\n')),
      "transitions.py": sub(M02["transitions.py"], (
          "    Status.PAID: {Status.SHIPPED, Status.CANCELLED},\n",
          "    Status.PAID: {Status.SHIPPED, Status.CANCELLED, Status.ON_HOLD},\n"
          "    Status.ON_HOLD: {Status.PAID, Status.CANCELLED},\n")),
      "labels.py": sub(M02["labels.py"], ('    Status.PAID: "Paid",\n',
                                          '    Status.PAID: "Paid",\n    Status.ON_HOLD: "On hold",\n')),
      "report.py": sub(M02["report.py"], ("COLUMNS = [Status.NEW, Status.PAID, Status.SHIPPED,",
                                          "COLUMNS = [Status.NEW, Status.PAID, Status.ON_HOLD, Status.SHIPPED,"))},
     '''\
import pytest

from labels import label
from notify import should_email
from orders import new_order, open_orders, pay
from report import render
from status import Status
from transitions import TransitionError, advance


def test_value():
    assert Status("on_hold") is Status.ON_HOLD


def test_hold_and_release():
    held = advance(pay(new_order(1, 10)), Status.ON_HOLD)
    assert held["status"] is Status.ON_HOLD
    assert advance(held, Status.PAID)["status"] is Status.PAID
    assert advance(held, Status.CANCELLED)["status"] is Status.CANCELLED
    for bad in (Status.SHIPPED, Status.DELIVERED, Status.NEW, Status.ON_HOLD):
        with pytest.raises(TransitionError):
            advance(held, bad)


def test_only_paid_can_be_held():
    for start in (Status.NEW, Status.SHIPPED, Status.DELIVERED, Status.CANCELLED):
        with pytest.raises(TransitionError):
            advance({"id": 2, "total": 1, "status": start}, Status.ON_HOLD)


def test_old_transitions_unchanged():
    paid = pay(new_order(1, 10))
    assert advance(paid, Status.SHIPPED)["status"] is Status.SHIPPED
    assert advance(paid, Status.CANCELLED)["status"] is Status.CANCELLED
    with pytest.raises(TransitionError):
        advance(paid, Status.DELIVERED)


def test_label():
    assert label(Status.ON_HOLD) == "On hold"
    assert label(Status.SHIPPED) == "On its way"
    assert all(isinstance(label(s), str) for s in Status)


def test_report_column():
    orders = [{"status": s} for s in (Status.NEW, Status.PAID, Status.ON_HOLD,
                                      Status.ON_HOLD, Status.CANCELLED)]
    header, row = render(orders).split("\\n")
    assert header == "new | paid | on_hold | shipped | delivered | cancelled"
    assert row == "1 | 1 | 2 | 0 | 0 | 1"


def test_open_and_no_email():
    held = {"id": 3, "total": 5, "status": Status.ON_HOLD}
    assert open_orders([held]) == [held]
    assert not should_email(Status.ON_HOLD)
''',
     protected=["test_orders.py"])

# --- M03: move a function to a new module and fix its imports ----------------
M03 = {
    "utils.py": '''\
"""Grab-bag helpers."""
from decimal import Decimal, InvalidOperation


def chunks(seq, size):
    """Split seq into lists of at most `size` items."""
    return [list(seq[i:i + size]) for i in range(0, len(seq), size)]


def parse_money(text):
    """'$1,234.50' or '1234.5' -> Decimal('1234.50'). Raises ValueError on junk."""
    cleaned = str(text).strip().replace(",", "").removeprefix("$")
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        raise ValueError(f"not an amount: {text!r}") from None
    return value.quantize(Decimal("0.01"))


def plural(n, word):
    return f"{n} {word}" if n == 1 else f"{n} {word}s"
''',
    "invoice.py": '''\
"""Invoice lines entered as text."""
from utils import parse_money, plural


def line_total(qty, unit_price_text):
    return parse_money(unit_price_text) * qty


def summary(lines):
    total = sum((line_total(q, p) for q, p in lines), start=0)
    return f"{plural(len(lines), 'line')}, total {total}"
''',
    "cart.py": '''\
"""Shopping cart with prices typed by staff."""
import utils


class Cart:
    def __init__(self):
        self.items = []

    def add(self, name, price_text, qty=1):
        self.items.append((name, utils.parse_money(price_text), qty))

    def total(self):
        return sum((price * qty for _, price, qty in self.items),
                   start=utils.parse_money("0"))

    def pages(self, size=10):
        return utils.chunks(self.items, size)
''',
    "tax.py": '''\
"""Sales tax."""
from decimal import ROUND_HALF_UP, Decimal

RATE = Decimal("0.06")


def tax(amount):
    return (amount * RATE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
''',
    "report.py": '''\
"""End-of-day report."""
from utils import chunks, plural


def render(names, per_line=3):
    rows = [", ".join(group) for group in chunks(names, per_line)]
    return plural(len(names), "sale") + "\\n" + "\\n".join(rows)
''',
    "test_cart.py": '''\
from cart import Cart


def test_total():
    c = Cart()
    c.add("pen", "$1.50", 2)
    assert str(c.total()) == "3.00"
''',
}
_MONEY_FN = M03["utils.py"][M03["utils.py"].index("def parse_money"):M03["utils.py"].index("def plural")]
edit("M03", "move-function",
     "Move parse_money() out of utils.py into a new module money.py, unchanged, and "
     "update everything that uses it to get it from money instead. utils.py must no "
     "longer define or re-export parse_money; its other helpers stay where they are.",
     ["utils.py", "money.py", "invoice.py", "cart.py"], M03,
     {"money.py": '"""Money parsing."""\nfrom decimal import Decimal, InvalidOperation\n\n\n'
                  + _MONEY_FN.rstrip("\n") + "\n",
      "utils.py": sub(M03["utils.py"], ("from decimal import Decimal, InvalidOperation\n", ""),
                      (_MONEY_FN, "")),
      "invoice.py": sub(M03["invoice.py"], ("from utils import parse_money, plural",
                                            "from money import parse_money\nfrom utils import plural")),
      "cart.py": sub(M03["cart.py"], ("import utils\n", "import utils\nfrom money import parse_money\n"),
                     ("utils.parse_money(price_text)", "parse_money(price_text)"),
                     ('start=utils.parse_money("0")', 'start=parse_money("0")'))},
     '''\
import importlib
import re
from decimal import Decimal
from pathlib import Path

import pytest


def test_money_module():
    money = importlib.import_module("money")
    assert money.parse_money("$1,234.5") == Decimal("1234.50")
    assert money.parse_money(" 7 ") == Decimal("7.00")
    with pytest.raises(ValueError):
        money.parse_money("abc")


def test_gone_from_utils():
    import utils
    assert not hasattr(utils, "parse_money")
    text = Path(utils.__file__).read_text(encoding="utf-8")
    assert not re.search(r"def\\s+parse_money|import[^\\n]*\\bparse_money\\b|\\bparse_money\\s*=", text)
    assert utils.chunks([1, 2, 3], 2) == [[1, 2], [3]]
    assert utils.plural(2, "line") == "2 lines"


def test_callers_still_work():
    from cart import Cart
    from invoice import summary
    assert summary([(2, "$1.25"), (1, "3")]) == "2 lines, total 5.50"
    c = Cart()
    c.add("pen", "$1.50", 2)
    c.add("pad", "2", 1)
    assert c.total() == Decimal("5.00")
    assert len(c.pages(1)) == 2


def test_report_untouched():
    from report import render
    assert render(["a", "b", "c", "d"]) == "4 sales\\na, b, c\\nd"
''',
     protected=["test_cart.py"])

# --- M04: rename a config key, keep old files working ------------------------
M04 = {
    "config.py": '''\
"""Client configuration: defaults, then a JSON file, then explicit overrides."""
import json
from pathlib import Path

DEFAULTS = {"base_url": "https://api.example.test", "timeout": 10, "retries": 3}


def load_config(path=None, **overrides):
    cfg = dict(DEFAULTS)
    if path is not None and Path(path).exists():
        cfg.update(json.loads(Path(path).read_text(encoding="utf-8")))
    cfg.update({k: v for k, v in overrides.items() if v is not None})
    return cfg
''',
    "client.py": '''\
"""Thin HTTP client. `transport` is injected so tests never touch the network."""
from retry import with_retries


class Client:
    def __init__(self, cfg, transport):
        self.cfg = cfg
        self.transport = transport

    def get(self, path):
        url = self.cfg["base_url"].rstrip("/") + "/" + path.lstrip("/")
        return with_retries(lambda: self.transport(url, timeout=self.cfg["timeout"]),
                            self.cfg["retries"])
''',
    "retry.py": '''\
"""Retry a call a fixed number of times on ConnectionError."""


def with_retries(call, retries):
    for attempt in range(retries + 1):
        try:
            return call()
        except ConnectionError:
            if attempt == retries:
                raise
''',
    "cli.py": '''\
"""Command-line entry point: fetch one path and print the body."""
import argparse

from client import Client
from config import load_config
from logging_setup import describe


def build_parser():
    p = argparse.ArgumentParser()
    p.add_argument("path")
    p.add_argument("--config")
    p.add_argument("--timeout", type=float, help="seconds before giving up")
    p.add_argument("--retries", type=int)
    p.add_argument("--verbose", action="store_true")
    return p


def main(argv=None, transport=None):
    args = build_parser().parse_args(argv)
    cfg = load_config(args.config, timeout=args.timeout, retries=args.retries)
    if args.verbose:
        print(describe(cfg))
    print(Client(cfg, transport).get(args.path))
    return 0
''',
    "logging_setup.py": '''\
"""One-line description of the client setup, for verbose output."""


def describe(cfg):
    return f"{cfg['base_url']} timeout={cfg['timeout']}s retries={cfg['retries']}"
''',
    "test_retry.py": '''\
from retry import with_retries


def test_retries_then_succeeds():
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionError
        return "ok"

    assert with_retries(flaky, 2) == "ok" and len(calls) == 3
''',
}
edit("M04", "rename-config-key",
     "Rename the configuration key \"timeout\" to \"timeout_s\" everywhere it is set or "
     "read. Config files written before the change still say \"timeout\": load_config "
     "must keep accepting that key, treat it as timeout_s (when a file has both, "
     "timeout_s wins), and return a config with no \"timeout\" key. The command-line "
     "flag stays --timeout.",
     ["config.py", "client.py", "cli.py", "logging_setup.py"], M04,
     {"config.py": sub(M04["config.py"],
                       ('"timeout": 10', '"timeout_s": 10'),
                       ('        cfg.update(json.loads(Path(path).read_text(encoding="utf-8")))\n',
                        '        data = json.loads(Path(path).read_text(encoding="utf-8"))\n'
                        '        if "timeout" in data:\n'
                        '            data.setdefault("timeout_s", data.pop("timeout"))\n'
                        '        cfg.update(data)\n')),
      "client.py": sub(M04["client.py"], ('timeout=self.cfg["timeout"]', 'timeout=self.cfg["timeout_s"]')),
      "cli.py": sub(M04["cli.py"], ("timeout=args.timeout,", "timeout_s=args.timeout,")),
      "logging_setup.py": sub(M04["logging_setup.py"], ("{cfg['timeout']}", "{cfg['timeout_s']}"))},
     '''\
import json

import cli
from client import Client
from config import DEFAULTS, load_config
from logging_setup import describe


def test_defaults_renamed():
    assert "timeout" not in DEFAULTS and DEFAULTS["timeout_s"] == 10


def test_legacy_file(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"timeout": 3}), encoding="utf-8")
    cfg = load_config(p)
    assert cfg["timeout_s"] == 3 and "timeout" not in cfg


def test_both_keys(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"timeout": 3, "timeout_s": 7}), encoding="utf-8")
    cfg = load_config(p)
    assert cfg["timeout_s"] == 7 and "timeout" not in cfg


def test_override_beats_legacy_file(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"timeout": 3}), encoding="utf-8")
    assert load_config(p, timeout_s=5)["timeout_s"] == 5


def test_client_passes_timeout():
    seen = {}

    def transport(url, timeout):
        seen.update(url=url, timeout=timeout)
        return "ok"

    assert Client(load_config(timeout_s=2.5), transport).get("/v1/ping") == "ok"
    assert seen == {"url": "https://api.example.test/v1/ping", "timeout": 2.5}


def test_cli(capsys, tmp_path):
    seen = []

    def transport(url, timeout):
        seen.append(timeout)
        return "body"

    assert cli.main(["/x", "--timeout", "4"], transport=transport) == 0
    assert cli.main(["/x"], transport=transport) == 0
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"timeout": 6}), encoding="utf-8")
    assert cli.main(["/x", "--config", str(p), "--verbose"], transport=transport) == 0
    assert seen == [4.0, 10, 6]
    out = capsys.readouterr().out.splitlines()
    assert out == ["body", "body", "https://api.example.test timeout=6s retries=3", "body"]


def test_describe():
    assert describe(load_config()) == "https://api.example.test timeout=10s retries=3"
''',
     protected=["test_retry.py"])

# --- M05: a new unit through parsing, conversion and display -----------------
M05 = {
    "units.py": '''\
"""Temperature conversion. Every reading is converted through Celsius."""

TO_C = {
    "C": lambda v: v,
    "F": lambda v: (v - 32) * 5 / 9,
}
FROM_C = {
    "C": lambda c: c,
    "F": lambda c: c * 9 / 5 + 32,
}


def convert(value, src, dst):
    return FROM_C[dst](TO_C[src](value))
''',
    "parser.py": r'''"""Parse readings typed by technicians: '21.5C', '-4 F', '70f'."""
import re

_READING = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*([CF])\s*$", re.I)


def parse_reading(text):
    m = _READING.match(text)
    if not m:
        raise ValueError(f"bad reading: {text!r}")
    return float(m.group(1)), m.group(2).upper()
''',
    "formatting.py": '''\
"""Display readings."""

SYMBOLS = {"C": "°C", "F": "°F"}


def show(value, unit, digits=1):
    return f"{value:.{digits}f}{SYMBOLS[unit]}"
''',
    "sensors.py": '''\
"""Sensor readings normalised to the site's display unit."""
from formatting import show
from parser import parse_reading
from units import convert


def normalise(texts, unit="C"):
    out = []
    for t in texts:
        value, src = parse_reading(t)
        out.append(show(convert(value, src, unit), unit))
    return out
''',
    "limits.py": '''\
"""Alarm thresholds, in Celsius."""
from units import convert

FREEZER_MAX_C = -15.0


def freezer_alarm(value, unit):
    return convert(value, unit, "C") > FREEZER_MAX_C
''',
    "test_units.py": '''\
from units import convert


def test_c_to_f():
    assert convert(100, "C", "F") == 212
''',
}
edit("M05", "new-unit",
     "Lab sensors now report in kelvin. Support the unit \"K\" everywhere readings are "
     "handled: parsing (\"293.15K\", \"0 k\"), conversion to and from the other units "
     "(K = °C + 273.15), and display, where kelvin is shown like \"300.0 K\" (a space "
     "and no degree sign) while °C and °F keep their current format. A kelvin "
     "reading below zero is impossible, and parse_reading raises ValueError for it.",
     ["units.py", "parser.py", "formatting.py"], M05,
     {"units.py": sub(M05["units.py"],
                      ('    "F": lambda v: (v - 32) * 5 / 9,\n',
                       '    "F": lambda v: (v - 32) * 5 / 9,\n    "K": lambda v: v - 273.15,\n'),
                      ('    "F": lambda c: c * 9 / 5 + 32,\n',
                       '    "F": lambda c: c * 9 / 5 + 32,\n    "K": lambda c: c + 273.15,\n')),
      "parser.py": sub(M05["parser.py"],
                       ("([CF])", "([CFK])"),
                       ("    return float(m.group(1)), m.group(2).upper()\n",
                        "    value, unit = float(m.group(1)), m.group(2).upper()\n"
                        "    if unit == \"K\" and value < 0:\n"
                        "        raise ValueError(f\"below absolute zero: {text!r}\")\n"
                        "    return value, unit\n")),
      "formatting.py": sub(M05["formatting.py"], ('"F": "°F"}', '"F": "°F", "K": " K"}'))},
     '''\
import pytest

from formatting import show
from limits import freezer_alarm
from parser import parse_reading
from sensors import normalise
from units import convert


@pytest.mark.parametrize("text, want", [("293.15K", (293.15, "K")), ("0 k", (0.0, "K")),
                                        ("21.5C", (21.5, "C")), ("-4 F", (-4.0, "F"))])
def test_parse(text, want):
    assert parse_reading(text) == want


@pytest.mark.parametrize("text", ["-1K", "-0.5 k", "12X", "K"])
def test_parse_rejects(text):
    with pytest.raises(ValueError):
        parse_reading(text)


def test_convert():
    assert convert(273.15, "K", "C") == pytest.approx(0)
    assert convert(0, "C", "K") == pytest.approx(273.15)
    assert convert(212, "F", "K") == pytest.approx(373.15)
    assert convert(0, "K", "F") == pytest.approx(-459.67)
    assert convert(100, "C", "F") == pytest.approx(212)


def test_show():
    assert show(300, "K") == "300.0 K"
    assert show(21.5, "C") == "21.5\\u00b0C" and show(-4, "F") == "-4.0\\u00b0F"


def test_end_to_end():
    assert normalise(["300K", "80.33C"], "K") == ["300.0 K", "353.5 K"]
    assert normalise(["273.15K"], "C") == ["0.0\\u00b0C"]
    assert not freezer_alarm(250, "K") and freezer_alarm(260, "K")
''',
     protected=["test_units.py"])

# --- M06: a new option threaded from the CLI to the service ------------------
M06 = {
    "service.py": '''\
"""Group sales by calendar day."""
from collections import defaultdict
from datetime import timezone

from store import all_sales


def daily_totals(sales=None):
    """{date: total cents}, each sale assigned to its date in UTC."""
    sales = all_sales() if sales is None else sales
    out = defaultdict(int)
    for sale in sales:
        day = sale["at"].astimezone(timezone.utc).date()
        out[day] += sale["cents"]
    return dict(sorted(out.items()))
''',
    "store.py": '''\
"""Sales store (fixture data for now). Timestamps are aware, in UTC."""
from datetime import datetime, timezone

_SALES = [
    {"at": datetime(2026, 3, 1, 23, 30, tzinfo=timezone.utc), "cents": 1200},
    {"at": datetime(2026, 3, 2, 2, 15, tzinfo=timezone.utc), "cents": 800},
    {"at": datetime(2026, 3, 2, 14, 0, tzinfo=timezone.utc), "cents": 2500},
    {"at": datetime(2026, 3, 3, 4, 59, tzinfo=timezone.utc), "cents": 400},
    {"at": datetime(2026, 3, 3, 5, 0, tzinfo=timezone.utc), "cents": 100},
]


def all_sales():
    return list(_SALES)
''',
    "formatter.py": '''\
"""Render the daily report."""


def render(totals, title="Daily sales"):
    lines = [title]
    for day, cents in totals.items():
        lines.append(f"{day.isoformat()}  {cents / 100:>10.2f}")
    return "\\n".join(lines)
''',
    "cli.py": '''\
"""python cli.py [--title T] prints the daily sales report."""
import argparse

from formatter import render
from service import daily_totals


def main(argv=None, sales=None):
    p = argparse.ArgumentParser()
    p.add_argument("--title", default="Daily sales")
    args = p.parse_args(argv)
    print(render(daily_totals(sales), title=args.title))
    return 0
''',
    "weekly.py": '''\
"""Week-level rollup built on the daily totals."""
from service import daily_totals


def weekly_total(sales=None):
    return sum(daily_totals(sales).values())
''',
    "test_formatter.py": '''\
from datetime import date

from formatter import render


def test_render():
    assert render({date(2026, 3, 1): 1234}) == "Daily sales\\n2026-03-01       12.34"
''',
}
edit("M06", "thread-option",
     "Let the daily report be cut at local midnight instead of UTC midnight. Add a "
     "--utc-offset option to cli.py taking an offset written as +HH:MM or -HH:MM (for "
     "example +05:30 or -05:00), and pass it through to daily_totals as a tz parameter "
     "(a datetime.tzinfo) so each sale is assigned to its date at that offset. When the "
     "option is given, the report title gets the offset appended, as in "
     "\"Daily sales (UTC+05:30)\". An offset not in that form, or beyond 14 hours, makes "
     "the CLI exit with status 2. Without the option, and when daily_totals is called "
     "without tz, everything behaves exactly as it does today.",
     ["cli.py", "service.py", "formatter.py"], M06,
     {"service.py": sub(M06["service.py"],
                        ("def daily_totals(sales=None):", "def daily_totals(sales=None, tz=None):"),
                        ("each sale assigned to its date in UTC.", "each sale assigned to its date in tz (default UTC)."),
                        ("    out = defaultdict(int)\n",
                         "    tz = timezone.utc if tz is None else tz\n    out = defaultdict(int)\n"),
                        ('sale["at"].astimezone(timezone.utc)', 'sale["at"].astimezone(tz)')),
      "cli.py": sub(M06["cli.py"],
                    ("import argparse\n",
                     "import argparse\nimport re\nfrom datetime import timedelta, timezone\n"),
                    ("from service import daily_totals\n", r'''from service import daily_totals

_OFFSET = re.compile(r"^([+-])(\d{2}):(\d{2})$")


def utc_offset(text):
    m = _OFFSET.match(text)
    if not m or int(m.group(3)) >= 60:
        raise argparse.ArgumentTypeError(f"offset must look like +05:30 or -05:00, not {text!r}")
    delta = timedelta(hours=int(m.group(2)), minutes=int(m.group(3)))
    if delta > timedelta(hours=14):
        raise argparse.ArgumentTypeError(f"offset beyond 14 hours: {text!r}")
    return text, timezone(-delta if m.group(1) == "-" else delta)
'''),
                    ('    p.add_argument("--title", default="Daily sales")\n',
                     '    p.add_argument("--title", default="Daily sales")\n'
                     '    p.add_argument("--utc-offset", type=utc_offset)\n'),
                    ("    print(render(daily_totals(sales), title=args.title))\n",
                     "    if args.utc_offset:\n"
                     "        text, tz = args.utc_offset\n"
                     "        print(render(daily_totals(sales, tz=tz), title=f\"{args.title} (UTC{text})\"))\n"
                     "    else:\n"
                     "        print(render(daily_totals(sales), title=args.title))\n"))},
     '''\
from datetime import date, timedelta, timezone

import pytest

import cli
from service import daily_totals
from store import all_sales
from weekly import weekly_total


def test_default_unchanged():
    assert daily_totals(all_sales()) == {date(2026, 3, 1): 1200, date(2026, 3, 2): 3300,
                                         date(2026, 3, 3): 500}
    assert daily_totals() == daily_totals(all_sales())
    assert weekly_total() == 5000


def test_tz_param():
    est = timezone(timedelta(hours=-5))
    assert daily_totals(all_sales(), tz=est) == {date(2026, 3, 1): 2000, date(2026, 3, 2): 2900,
                                                 date(2026, 3, 3): 100}
    ist = timezone(timedelta(hours=5, minutes=30))
    assert daily_totals(tz=ist) == {date(2026, 3, 2): 4500, date(2026, 3, 3): 500}


def test_cli_offset(capsys):
    assert cli.main(["--utc-offset", "+05:30"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "Daily sales (UTC+05:30)", "2026-03-02       45.00", "2026-03-03        5.00"]
    assert cli.main(["--title", "Shop A", "--utc-offset=-05:00"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "Shop A (UTC-05:00)", "2026-03-01       20.00", "2026-03-02       29.00",
        "2026-03-03        1.00"]


def test_cli_default(capsys):
    assert cli.main([]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "Daily sales", "2026-03-01       12.00", "2026-03-02       33.00", "2026-03-03        5.00"]


@pytest.mark.parametrize("bad", ["5", "+15:00", "+05:60", "abc", "0530"])
def test_cli_bad_offset(bad):
    with pytest.raises(SystemExit) as exc:
        cli.main([f"--utc-offset={bad}"])
    assert exc.value.code == 2
''',
     protected=["test_formatter.py"])

# --- M07: a new error type through errors, response checks and the client ----
M07 = {
    "errors.py": '''\
"""Errors the API client raises."""


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(f"{status}: {message}")
        self.status = status
        self.message = message


class NotFound(ApiError):
    pass


class ServerError(ApiError):
    pass
''',
    "responses.py": '''\
"""Turn a raw (status, headers, body) response into a value or an error."""
from errors import ApiError, NotFound, ServerError


def check(status, headers, body):
    if 200 <= status < 300:
        return body
    if status == 404:
        raise NotFound(status, body or "not found")
    if status >= 500:
        raise ServerError(status, body or "server error")
    raise ApiError(status, body or "request failed")
''',
    "client.py": '''\
"""API client with retries for transient failures."""
from errors import ServerError
from responses import check


class Client:
    def __init__(self, send, sleep, retries=2):
        self.send = send      # send(path) -> (status, headers, body)
        self.sleep = sleep    # injected so tests do not wait
        self.retries = retries

    def get(self, path):
        for attempt in range(self.retries + 1):
            try:
                return check(*self.send(path))
            except ServerError:
                if attempt == self.retries:
                    raise
                self.sleep(2 ** attempt)
''',
    "metrics.py": '''\
"""Count failures by kind for the dashboard."""
from collections import Counter

FAILURES = Counter()


def record(exc):
    FAILURES[type(exc).__name__] += 1
''',
    "test_responses.py": '''\
import pytest

from errors import NotFound
from responses import check


def test_ok_and_404():
    assert check(200, {}, "body") == "body"
    with pytest.raises(NotFound):
        check(404, {}, "")
''',
}
edit("M07", "new-error",
     "The API now answers 429 when we send requests too fast, with a Retry-After header "
     "giving whole seconds to wait. Add a RateLimited error, a subclass of ApiError with "
     "a retry_after attribute (an int, in seconds), raised for 429. Header names are "
     "case-insensitive; a missing or non-numeric Retry-After means retry_after = 1. The "
     "client retries a RateLimited response the same number of times as a server error, "
     "but sleeps retry_after seconds before the retry instead of its usual backoff.",
     ["errors.py", "responses.py", "client.py"], M07,
     {"errors.py": M07["errors.py"] + '''

class RateLimited(ApiError):
    def __init__(self, status, message, retry_after=1):
        super().__init__(status, message)
        self.retry_after = retry_after
''',
      "responses.py": sub(M07["responses.py"],
                          ("from errors import ApiError, NotFound, ServerError",
                           "from errors import ApiError, NotFound, RateLimited, ServerError"),
                          ('        raise NotFound(status, body or "not found")\n',
                           '        raise NotFound(status, body or "not found")\n'
                           '    if status == 429:\n'
                           '        raise RateLimited(status, body or "rate limited", _retry_after(headers))\n'),
                          ('    raise ApiError(status, body or "request failed")\n',
                           '    raise ApiError(status, body or "request failed")\n\n\n'
                           'def _retry_after(headers):\n'
                           '    for name, value in headers.items():\n'
                           '        if name.lower() == "retry-after":\n'
                           '            value = str(value).strip()\n'
                           '            return int(value) if value.isdigit() else 1\n'
                           '    return 1\n')),
      "client.py": sub(M07["client.py"],
                       ("from errors import ServerError", "from errors import RateLimited, ServerError"),
                       ("            except ServerError:\n", "            except (ServerError, RateLimited) as exc:\n"),
                       ("                self.sleep(2 ** attempt)\n",
                        "                self.sleep(exc.retry_after if isinstance(exc, RateLimited) else 2 ** attempt)\n"))},
     '''\
import pytest

from client import Client
from errors import ApiError, NotFound, RateLimited, ServerError
from responses import check


def test_check_429():
    with pytest.raises(RateLimited) as exc:
        check(429, {"Retry-After": "7"}, "slow down")
    assert exc.value.retry_after == 7 and exc.value.status == 429
    assert isinstance(exc.value, ApiError)


@pytest.mark.parametrize("headers", [{}, {"Retry-After": "soon"}, {"Retry-After": ""}])
def test_default_retry_after(headers):
    with pytest.raises(RateLimited) as exc:
        check(429, headers, "")
    assert exc.value.retry_after == 1


def test_header_case_insensitive():
    with pytest.raises(RateLimited) as exc:
        check(429, {"retry-after": "3"}, "")
    assert exc.value.retry_after == 3


def _client(responses, retries=2):
    sleeps, it = [], iter(responses)
    return Client(lambda path: next(it), sleeps.append, retries=retries), sleeps


def test_client_waits_retry_after():
    c, sleeps = _client([(429, {"Retry-After": "5"}, ""), (503, {}, ""), (200, {}, "ok")])
    assert c.get("/x") == "ok"
    assert sleeps == [5, 2]


def test_client_gives_up():
    c, sleeps = _client([(429, {"Retry-After": "2"}, "")] * 3)
    with pytest.raises(RateLimited):
        c.get("/x")
    assert sleeps == [2, 2]


def test_other_errors_unchanged():
    c, sleeps = _client([(404, {}, "")])
    with pytest.raises(NotFound):
        c.get("/x")
    assert sleeps == []
    c, sleeps = _client([(500, {}, "")] * 3)
    with pytest.raises(ServerError):
        c.get("/x")
    assert sleeps == [1, 2]
    c, sleeps = _client([(400, {}, "bad")])
    with pytest.raises(ApiError):
        c.get("/x")
    assert sleeps == []
''',
     protected=["test_responses.py"])

# --- M08 (trap): a new field whose export lives outside the write set --------
M08 = {
    "models.py": '''\
"""Address-book records."""
from dataclasses import dataclass


@dataclass
class Contact:
    id: int
    name: str
    email: str
    phone: str = ""
''',
    "storage.py": '''\
"""Contacts persisted as one JSON document."""
import json
from pathlib import Path

from models import Contact

FIELDS = ("id", "name", "email", "phone")


def to_dict(c):
    return {f: getattr(c, f) for f in FIELDS}


def from_dict(d):
    return Contact(**{f: d[f] for f in FIELDS if f in d})


def save(contacts, path):
    Path(path).write_text(json.dumps([to_dict(c) for c in contacts], indent=2), encoding="utf-8")


def load(path):
    return [from_dict(d) for d in json.loads(Path(path).read_text(encoding="utf-8"))]
''',
    "api.py": '''\
"""JSON handlers for contacts. Each returns (status, body)."""
from models import Contact
from storage import to_dict

_CONTACTS = {}


def reset():
    _CONTACTS.clear()


def create(payload):
    name = (payload.get("name") or "").strip()
    email = (payload.get("email") or "").strip().lower()
    if not name or "@" not in email:
        return 400, {"error": "name and a valid email are required"}
    c = Contact(id=len(_CONTACTS) + 1, name=name, email=email,
                phone=(payload.get("phone") or "").strip())
    _CONTACTS[c.id] = c
    return 201, to_dict(c)


def update(contact_id, payload):
    c = _CONTACTS.get(contact_id)
    if c is None:
        return 404, {"error": "no such contact"}
    for key in ("name", "phone"):
        if key in payload:
            setattr(c, key, (payload[key] or "").strip())
    return 200, to_dict(c)
''',
    "csv_export.py": '''\
"""Spreadsheet export of the address book."""
import csv
import io

COLUMNS = ["name", "email", "phone"]


def export(contacts):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\\n")
    w.writerow(COLUMNS)
    for c in contacts:
        w.writerow([getattr(c, col) for col in COLUMNS])
    return buf.getvalue()
''',
    "dedupe.py": '''\
"""Find likely duplicate contacts (same email)."""
from collections import defaultdict


def duplicates(contacts):
    by_email = defaultdict(list)
    for c in contacts:
        by_email[c.email.lower()].append(c)
    return [group for group in by_email.values() if len(group) > 1]
''',
    "test_api.py": '''\
import api


def test_create():
    api.reset()
    status, body = api.create({"name": "Ana Ruiz", "email": "ANA@example.test"})
    assert status == 201 and body["email"] == "ana@example.test"
''',
}
edit("M08", "trap-field-export",
     "Contacts can now record the company they work for. Add an optional company field "
     "(a string, default empty) to Contact. create and update accept it and trim it the "
     "way they treat phone, the API returns it, and save/load keep it (files saved "
     "before this change have no company key and must still load). The spreadsheet "
     "export also gets a company column, right after email.",
     ["models.py", "storage.py", "api.py"], M08,
     {"models.py": sub(M08["models.py"], ('    phone: str = ""\n', '    phone: str = ""\n    company: str = ""\n')),
      "storage.py": sub(M08["storage.py"], ('FIELDS = ("id", "name", "email", "phone")',
                                            'FIELDS = ("id", "name", "email", "phone", "company")')),
      "api.py": sub(M08["api.py"],
                    ('phone=(payload.get("phone") or "").strip())',
                     'phone=(payload.get("phone") or "").strip(),\n'
                     '                company=(payload.get("company") or "").strip())'),
                    ('for key in ("name", "phone"):', 'for key in ("name", "phone", "company"):'))},
     '''\
import json

import api
import storage
from models import Contact


def test_create_and_update():
    api.reset()
    status, body = api.create({"name": "Ana Ruiz", "email": "Ana@Example.test",
                               "company": "  Northwind  "})
    assert status == 201 and body["company"] == "Northwind"
    status, body = api.update(body["id"], {"company": " Contoso "})
    assert status == 200 and body["company"] == "Contoso"
    status, body = api.update(body["id"], {"phone": "555-0100"})
    assert body["company"] == "Contoso" and body["phone"] == "555-0100"
    status, body = api.create({"name": "Bo Lind", "email": "bo@example.test"})
    assert body["company"] == ""


def test_round_trip(tmp_path):
    contacts = [Contact(1, "Ana Ruiz", "ana@example.test", company="Northwind"),
                Contact(2, "Bo Lind", "bo@example.test")]
    storage.save(contacts, tmp_path / "c.json")
    assert storage.load(tmp_path / "c.json") == contacts


def test_old_file_loads(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps([{"id": 1, "name": "Ana Ruiz", "email": "a@example.test",
                              "phone": ""}]), encoding="utf-8")
    assert storage.load(p)[0].company == ""
''',
     protected=["csv_export.py", "test_api.py"], must_mention=["csv_export"])

# --- M09 (trap): a rename with a caller outside the write set ----------------
M09 = {
    "accounts.py": '''\
"""User accounts (in memory)."""
from datetime import datetime, timezone

_USERS = {}


def reset():
    _USERS.clear()


def add(user_id, email):
    _USERS[user_id] = {"id": user_id, "email": email, "active": True,
                       "reason": None, "since": None}
    return _USERS[user_id]


def get(user_id):
    return _USERS.get(user_id)


def deactivate(user_id, reason, now=None):
    """Mark the account inactive. Returns False when there is no such user."""
    user = _USERS.get(user_id)
    if user is None:
        return False
    user.update(active=False, reason=reason, since=now or datetime.now(timezone.utc))
    return True


def inactive():
    return [u for u in _USERS.values() if not u["active"]]
''',
    "admin.py": '''\
"""Admin console commands."""
import accounts


def ban(user_id):
    if not accounts.deactivate(user_id, "banned by admin"):
        return f"no user {user_id}"
    return f"user {user_id} banned"


def bulk_ban(user_ids):
    return [ban(u) for u in user_ids]
''',
    "api.py": '''\
"""HTTP handlers. Each returns (status, body)."""
from accounts import deactivate, get


def close_account(user_id, payload):
    reason = payload.get("reason") or "closed by user"
    if not deactivate(user_id, reason):
        return 404, {"error": "no such user"}
    return 200, {"id": user_id, "active": get(user_id)["active"]}
''',
    "jobs/cleanup_inactive.py": '''\
"""Nightly job: deactivate accounts with no login for a year."""
from datetime import datetime, timedelta, timezone

from accounts import deactivate

CUTOFF = timedelta(days=365)


def run(last_logins, now=None):
    now = now or datetime.now(timezone.utc)
    stale = [uid for uid, seen in last_logins.items() if now - seen > CUTOFF]
    for uid in stale:
        deactivate(uid, "inactive for a year", now=now)
    return stale
''',
    "emails.py": '''\
"""Notification text."""


def deactivated_notice(user):
    return f"Your account {user['email']} was deactivated: {user['reason']}."
''',
    "test_admin.py": '''\
import accounts
from admin import ban


def test_ban():
    accounts.reset()
    accounts.add(1, "a@example.test")
    assert ban(1) == "user 1 banned"
    assert accounts.get(1)["active"] is False
''',
}
edit("M09", "trap-rename-caller",
     "Rename accounts.deactivate() to suspend() and make its reason argument "
     "keyword-only, then update every caller to match. Do not leave a deactivate "
     "alias behind.",
     ["accounts.py", "admin.py", "api.py"], M09,
     {"accounts.py": sub(M09["accounts.py"], ("def deactivate(user_id, reason, now=None):",
                                              "def suspend(user_id, *, reason, now=None):")),
      "admin.py": sub(M09["admin.py"], ('accounts.deactivate(user_id, "banned by admin")',
                                        'accounts.suspend(user_id, reason="banned by admin")')),
      "api.py": sub(M09["api.py"], ("from accounts import deactivate, get", "from accounts import get, suspend"),
                    ("if not deactivate(user_id, reason):", "if not suspend(user_id, reason=reason):"))},
     r'''import inspect
import re
from pathlib import Path

import pytest

import accounts
import admin
import api

OLD = re.compile(r"\bdeactivate\s*\(|import[^\n]*\bdeactivate\b|=\s*deactivate\b")


def test_renamed_without_alias():
    assert callable(getattr(accounts, "suspend", None))
    assert not hasattr(accounts, "deactivate")
    for mod in (accounts, admin, api):
        assert not OLD.search(Path(mod.__file__).read_text(encoding="utf-8")), mod.__name__


def test_reason_keyword_only():
    params = inspect.signature(accounts.suspend).parameters
    assert params["reason"].kind is inspect.Parameter.KEYWORD_ONLY
    accounts.reset()
    accounts.add(1, "a@example.test")
    with pytest.raises(TypeError):
        accounts.suspend(1, "x")
    assert accounts.suspend(1, reason="x") is True and accounts.get(1)["reason"] == "x"
    assert accounts.suspend(9, reason="x") is False


def test_callers():
    accounts.reset()
    accounts.add(1, "a@example.test")
    accounts.add(2, "b@example.test")
    assert admin.ban(1) == "user 1 banned" and accounts.get(1)["reason"] == "banned by admin"
    assert admin.ban(7) == "no user 7"
    assert api.close_account(2, {}) == (200, {"id": 2, "active": False})
    assert accounts.get(2)["reason"] == "closed by user"
    assert api.close_account(8, {"reason": "bye"})[0] == 404
''',
     protected=["jobs/cleanup_inactive.py", "test_admin.py"], must_mention=["cleanup_inactive"])

# --- M10: a hard-coded value replaced by one setting -------------------------
M10 = {
    "settings.py": '''\
"""Shop settings."""
import os

CURRENCY = os.environ.get("SHOP_CURRENCY", "USD")
LOW_STOCK = 5
''',
    "catalog.py": '''\
"""Product catalogue (fixture data)."""

PRODUCTS = [
    {"id": i, "title": f"Product number {i} in the spring range", "stock": i % 7,
     "tags": ["spring"] if i % 2 else ["basic"]}
    for i in range(1, 121)
]
''',
    "listing.py": '''\
"""Category listing pages."""
from catalog import PRODUCTS


def card(p):
    title = p["title"] if len(p["title"]) <= 20 else p["title"][:19] + "…"
    return {"id": p["id"], "title": title}


def page(n=1):
    start = (n - 1) * 20
    return [card(p) for p in PRODUCTS[start:start + 20]]


def page_count():
    return -(-len(PRODUCTS) // 20)
''',
    "search.py": '''\
"""Tag search."""
from catalog import PRODUCTS


def search(tag, page=1, per_page=20):
    hits = [p for p in PRODUCTS if tag in p["tags"]]
    start = (page - 1) * per_page
    return hits[start:start + per_page]
''',
    "feed.py": '''\
"""Home-page feed: newest products first, one page at a time."""
from catalog import PRODUCTS

PER_PAGE = 20


def feed(page=1):
    newest = sorted(PRODUCTS, key=lambda p: -p["id"])
    return newest[(page - 1) * PER_PAGE:page * PER_PAGE]
''',
    "api.py": '''\
"""HTTP handlers. Each returns (status, body)."""
import listing
import search


def get_category(params):
    n = int(params.get("page", 1))
    return 200, {"page": n, "pages": listing.page_count(), "items": listing.page(n)}


def get_search(params):
    return 200, {"items": search.search(params["tag"], int(params.get("page", 1)))}
''',
    "test_api.py": '''\
import api


def test_category_page():
    status, body = api.get_category({"page": "1"})
    assert status == 200 and body["page"] == 1 and body["items"]
''',
}
edit("M10", "constant-to-setting",
     "The page size 20 is hard-coded in several places. Add PAGE_SIZE to settings.py, "
     "20 by default and overridable by the environment variable SHOP_PAGE_SIZE when it "
     "holds an integer from 1 to 100 (anything else, or unset, gives 20). Make everything "
     "that pages results use settings.PAGE_SIZE, read when the call is made, so changing "
     "settings.PAGE_SIZE at runtime takes effect without re-importing anything. search() "
     "keeps its per_page argument, which still wins when it is passed.",
     ["settings.py", "listing.py", "search.py", "feed.py"], M10,
     {"settings.py": M10["settings.py"] + '''

def _page_size(raw):
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 20
    return value if 1 <= value <= 100 else 20


PAGE_SIZE = _page_size(os.environ.get("SHOP_PAGE_SIZE"))
''',
      "listing.py": sub(M10["listing.py"],
                        ("from catalog import PRODUCTS\n", "import settings\nfrom catalog import PRODUCTS\n"),
                        ("    start = (n - 1) * 20\n    return [card(p) for p in PRODUCTS[start:start + 20]]\n",
                         "    size = settings.PAGE_SIZE\n    start = (n - 1) * size\n"
                         "    return [card(p) for p in PRODUCTS[start:start + size]]\n"),
                        ("-(-len(PRODUCTS) // 20)", "-(-len(PRODUCTS) // settings.PAGE_SIZE)")),
      "search.py": sub(M10["search.py"],
                       ("from catalog import PRODUCTS\n", "import settings\nfrom catalog import PRODUCTS\n"),
                       ("def search(tag, page=1, per_page=20):\n",
                        "def search(tag, page=1, per_page=None):\n"
                        "    per_page = settings.PAGE_SIZE if per_page is None else per_page\n")),
      "feed.py": sub(M10["feed.py"],
                     ("from catalog import PRODUCTS\n\nPER_PAGE = 20\n",
                      "import settings\nfrom catalog import PRODUCTS\n"),
                     ("    return newest[(page - 1) * PER_PAGE:page * PER_PAGE]\n",
                      "    size = settings.PAGE_SIZE\n    return newest[(page - 1) * size:page * size]\n"))},
     '''\
import importlib

import pytest

import api
import feed
import listing
import search
import settings


@pytest.fixture(autouse=True)
def _fresh_settings(monkeypatch):
    monkeypatch.delenv("SHOP_PAGE_SIZE", raising=False)
    importlib.reload(settings)
    yield
    monkeypatch.delenv("SHOP_PAGE_SIZE", raising=False)
    importlib.reload(settings)


def test_default():
    assert settings.PAGE_SIZE == 20
    assert len(listing.page(1)) == 20 and listing.page_count() == 6
    assert len(feed.feed(1)) == 20 and feed.feed(1)[0]["id"] == 120
    assert len(search.search("spring")) == 20


@pytest.mark.parametrize("raw, size", [("35", 35), ("1", 1), ("100", 100), ("0", 20),
                                       ("101", 20), ("abc", 20), ("", 20), ("12.5", 20)])
def test_env(monkeypatch, raw, size):
    monkeypatch.setenv("SHOP_PAGE_SIZE", raw)
    importlib.reload(settings)
    assert settings.PAGE_SIZE == size


def test_runtime_change(monkeypatch):
    monkeypatch.setattr(settings, "PAGE_SIZE", 50)
    assert len(listing.page(1)) == 50 and listing.page_count() == 3
    assert [p["id"] for p in listing.page(3)] == list(range(101, 121))
    assert len(feed.feed(1)) == 50 and feed.feed(3)[-1]["id"] == 1
    assert len(search.search("spring")) == 50 and len(search.search("spring", page=2)) == 10
    assert len(search.search("spring", per_page=7)) == 7
    status, body = api.get_category({"page": "2"})
    assert body["pages"] == 3 and len(body["items"]) == 50
    assert len(api.get_search({"tag": "basic"})[1]["items"]) == 50


def test_titles_still_cut_at_20(monkeypatch):
    monkeypatch.setattr(settings, "PAGE_SIZE", 50)
    title = listing.page(1)[0]["title"]
    assert len(title) == 20 and title.endswith("\\u2026")
''',
     protected=["test_api.py"])


def items() -> list[dict]:
    out = []
    for e in EDITS:
        eid, ws, sol = e["id"], e["workspace"], e["solution"]
        assert 5 <= len(ws) <= 9, f"{eid}: workspace has {len(ws)} files"
        assert set(sol) <= set(e["write_paths"]), f"{eid}: solution leaves the write set"
        changed = [p for p in sol if ws.get(p) != sol[p]]
        assert 2 <= len(changed) <= 4 and len(changed) == len(sol), f"{eid}: solution touches {changed}"
        assert set(e["protected"]) <= set(ws), f"{eid}: protected path missing"
        assert not set(e["protected"]) & set(e["write_paths"]), f"{eid}: protected path in the write set"
        for m in e["must_mention"]:
            hits = [p for p in ws if m in p]
            assert hits and not set(hits) & set(e["write_paths"]), f"{eid}: trap file for {m!r}"
            assert m.lower() not in e["task"].lower(), f"{eid}: the task names the trap file"
        solved = {**ws, **sol}
        bare_ok, _ = run_hidden_tests(ws, e["hidden_tests"])
        assert not bare_ok, f"{eid}: hidden tests pass on the untouched workspace"
        sol_ok, log = run_hidden_tests(solved, e["hidden_tests"])
        assert sol_ok, f"{eid}: reference solution fails the hidden tests\n{log}"
        for path in (p for p in ws if re.fullmatch(r"(.*/)?test_\w+\.py", p)):
            for label, files in (("untouched", ws), ("solved", solved)):
                ok, log = run_hidden_tests(files, ws[path])
                assert ok, f"{eid}: visible {path} fails on the {label} workspace\n{log}"
        gold = {"protected": e["protected"], "must_mention": e["must_mention"]}
        out.append(item(eid, CAT, e["task"], gold, "edit", task_type="worker", mode="worker",
                        write_paths=e["write_paths"], tags=("judgment", e["kind"]),
                        workspace=ws, solution=sol, hidden_tests=e["hidden_tests"],
                        trap=bool(e["must_mention"]), files=len(ws), touched=len(changed)))
    return out


if __name__ == "__main__":
    for it in items():
        print(it["id"], it["tags"][1], "files", it["files"], "touched", it["touched"],
              "trap" if it["trap"] else "")
