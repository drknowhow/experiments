"""Pull the answer object out of a model reply and normalize its values for
deterministic grading."""
from __future__ import annotations

import json
import re

_FENCE = re.compile(r"```[ \t]*([A-Za-z]*)[ \t]*\r?\n(.*?)```", re.S)


def parse_reply(text: str) -> dict | None:
    """The answer object: the last fenced block that parses to a JSON object,
    else the last complete top-level {...} anywhere in the reply."""
    for _lang, body in reversed(_FENCE.findall(text or "")):
        try:
            obj = json.loads(body)
        except ValueError:
            continue
        if isinstance(obj, dict):
            return obj
    dec = json.JSONDecoder()
    best, best_span = None, (-1, 0)
    for i, ch in enumerate(text or ""):
        if ch != "{":
            continue
        try:
            obj, end = dec.raw_decode(text, i)
        except ValueError:
            continue
        # Furthest end wins; on a tie the earlier start (the outer object) wins.
        if isinstance(obj, dict) and (end > best_span[0] or (end == best_span[0] and i < best_span[1])):
            best, best_span = obj, (end, i)
    return best


def norm(v) -> str:
    s = "" if v is None else str(v)
    s = s.strip().strip("`").strip()
    return re.sub(r"\s+", " ", s).lower()


def is_null(v) -> bool:
    return v is None or norm(v) in ("", "null", "none", "n/a", "na", "unknown")


def is_not_found(v) -> bool:
    return v is None or re.sub(r"[\s_-]+", "_", norm(v)).strip("._") in ("not_found", "notfound")


def first_int(v) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    m = re.search(r"-?\d+", str(v) if v is not None else "")
    return int(m.group()) if m else None


def norm_path(p) -> str:
    s = norm(p).replace("\\", "/")
    s = re.sub(r":\d+(:\d+)?$", "", s)          # tolerate "file.py:47"
    while s.startswith("./"):
        s = s[2:]
    return s


def path_match(reply, gold: str) -> bool:
    r, g = norm_path(reply), norm_path(gold)
    return bool(r) and (r == g or r.endswith("/" + g))


def jaccard(a: set, b: set) -> float:
    return 1.0 if not a and not b else len(a & b) / len(a | b)
