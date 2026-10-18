"""log-join: answer a question over a 600-900-line multi-service log that needs a
join: across services by request or trace id, across event types, or inside a
time window that other events set.

Each item gets its own seeded log. Gold is computed from the structured events
the generator emitted (their fields and hidden metadata), never by parsing the
rendered text. A solver returns None when a seed does not make a fair item
(no distractor of a required kind, a tie, an answer out of range), and the seed
is advanced until it does."""
from __future__ import annotations

import random
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from common import item, json_contract

CAT = "log-join"
MIN_LINES, MAX_LINES = 600, 900
SPAN_S = 3600
PATHS = ["/api/orders", "/api/cart", "/api/users/me", "/api/search", "/api/catalog",
         "/api/checkout"]
TENANTS = ["t-acme", "t-birch", "t-cobalt", "t-dune", "t-ember", "t-fjord"]
USERS = ["u_ada", "u_bo", "u_cyd", "u_dee", "u_eli", "u_fay", "u_gus", "u_hal", "u_ivo"]
API_ERRORS = ["upstream error", "inventory service unavailable", "serialization failed",
              "cart lock not acquired", "price lookup failed"]
JOB_ERRORS = ["smtp relay refused connection", "template render failed",
              "s3 put timed out", "webhook returned 500"]


def _ms(n: float) -> timedelta:
    return timedelta(milliseconds=n)


def _ts(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


def _val(v) -> str:
    s = str(v)
    return f'"{s}"' if " " in s else s


class Log:
    """Events with printed fields `f` and hidden metadata `m`; rendered in time
    order, ties in insertion order."""

    def __init__(self, seed: int, *, mixed_units: bool = False, tenants: bool = False):
        self.rng = random.Random(seed)
        self.t0 = datetime(2026, 4, 14, 9, 0, 0) + timedelta(seconds=self.rng.randint(0, 3600))
        self.events: list[dict] = []
        self.mixed_units = mixed_units
        self.tenants = tenants
        self._ids: set[str] = set()

    def uid(self, prefix: str, digits: int = 6, hexa: bool = True) -> str:
        while True:
            if hexa:
                s = f"{prefix}{self.rng.getrandbits(4 * digits):0{digits}x}"
            else:
                s = f"{prefix}{self.rng.randint(10 ** (digits - 1), 10 ** digits - 1)}"
            if s not in self._ids:
                self._ids.add(s)
                return s

    def at(self, frac: float) -> datetime:
        return self.t0 + _ms(int(frac * SPAN_S * 1000))

    def rand_t(self, lo: float = 0.0, hi: float = 1.0) -> datetime:
        return self.at(self.rng.uniform(lo, hi))

    def add(self, t: datetime, level: str, service: str, f: dict, **m) -> dict:
        ev = {"t": t, "level": level, "service": service, "f": f, "m": m}
        self.events.append(ev)
        return ev

    def took(self, ms: int) -> str:
        if self.mixed_units and self.rng.random() < 0.35:
            return f"{ms / 1000:.2f}s"
        return f"{ms}ms"

    def render(self) -> str:
        self.events.sort(key=lambda e: e["t"])
        return "\n".join(
            f"{_ts(e['t'])} {e['level']:<5} {e['service']:<9} "
            + " ".join(f"{k}={_val(v)}" for k, v in e["f"].items())
            for e in self.events)


def web(lg: Log, t: datetime, *, path: str | None = None, status: int | None = None,
        api_ms: int | None = None, gw_extra: int | None = None, db: str = "auto",
        db_ms: int | None = None, api_error: str | None = None, retry: bool = False,
        tenant: str | None = None) -> dict:
    """One request through gateway -> api (-> db). The gateway's response line
    names only the request id; the request line maps it to the trace id the api
    and db lines use."""
    rng = lg.rng
    req, trace = lg.uid("r-"), lg.uid("tr-", 8)
    path = path or rng.choice(PATHS)
    method = "POST" if path in ("/api/checkout", "/api/cart") else "GET"
    lg.add(t, "INFO", "gateway", {"event": "request", "req": req, "trace": trace,
                                  "method": method, "path": path})
    cur = t + _ms(rng.randint(1, 4))
    if db == "auto":
        db = "ok" if rng.random() < 0.55 else "none"
    if db == "timeout":
        lg.add(cur + _ms(5000), "ERROR", "db", {"trace": trace, "query": lg.uid("q-", 5),
               "error": "statement timeout after 5000ms"}, timeout=True)
        cur += _ms(5000 + rng.randint(2, 30))
        if retry:
            lg.add(cur, "WARN", "api", {"trace": trace, "route": path, "retry": 1,
                                        "reason": "db timeout"})
            ms = rng.randint(20, 300)
            lg.add(cur + _ms(ms), "INFO", "db", {"trace": trace, "query": lg.uid("q-", 5),
                   "took": lg.took(ms), "rows": rng.randint(0, 40)}, took_ms=ms, timeout=False)
            cur += _ms(ms + rng.randint(1, 10))
    elif db == "ok":
        ms = db_ms if db_ms is not None else min(int(rng.expovariate(1 / 60)) + 2, 900)
        lg.add(cur + _ms(ms), "INFO", "db", {"trace": trace, "query": lg.uid("q-", 5),
               "took": lg.took(ms), "rows": rng.randint(0, 40)}, took_ms=ms, timeout=False)
        cur += _ms(ms + rng.randint(1, 10))
    handler = api_ms if api_ms is not None else int((cur - t).total_seconds() * 1000) + rng.randint(3, 60)
    t_api = t + _ms(handler)
    if status is None:
        status = rng.choice([200] * 14 + [201, 304, 404])
    fields = {"trace": trace, "route": path}
    if tenant or (lg.tenants and rng.random() < 0.9):
        fields["tenant"] = tenant or rng.choice(TENANTS)
    if api_error:
        fields.update(status=500, error=api_error, handler_ms=handler)
        lg.add(t_api, "ERROR", "api", fields, handler_ms=handler)
    else:
        fields.update(status=status if status < 500 else 200, handler_ms=handler)
        lg.add(t_api, "INFO", "api", fields, handler_ms=handler)
    dur = handler + (gw_extra if gw_extra is not None else rng.randint(1, 25))
    level = "ERROR" if status >= 500 else "WARN" if status >= 400 else "INFO"
    lg.add(t + _ms(dur), level, "gateway", {"event": "response", "req": req, "status": status,
                                            "dur_ms": dur})
    return {"req": req, "trace": trace, "path": path, "status": status, "handler_ms": handler,
            "dur_ms": dur, "tenant": fields.get("tenant")}


def misc(lg: Log, t: datetime) -> None:
    rng = lg.rng
    k = rng.randrange(4)
    if k == 0:
        lg.add(t, "DEBUG", "cache", {"event": rng.choice(["hit", "hit", "miss"]),
                                     "key": f"cat:{rng.randint(100, 999)}"})
    elif k == 1:
        lg.add(t, "INFO", "scheduler", {"event": "tick", "task": rng.choice(
            ["cleanup", "rollup", "reindex"]), "lag_ms": rng.randint(0, 40)})
    elif k == 2:
        lg.add(t, "INFO", "auth", {"event": "token_refresh", "user": rng.choice(USERS)})
    else:
        lg.add(t, "INFO", "gateway", {"event": "healthcheck", "status": 200})


def fill(lg: Log, *, traces: bool = True) -> None:
    """Pad with neutral traffic to a target length inside 600-900 lines."""
    target = lg.rng.randint(MIN_LINES + 40, MAX_LINES - 40)
    while len(lg.events) < target - 5:
        if traces and lg.rng.random() < 0.75:
            web(lg, lg.rand_t(0, 0.995))
        else:
            misc(lg, lg.rand_t())
    while len(lg.events) < target:
        misc(lg, lg.rand_t())


def evs(lg: Log, service: str, **match) -> list[dict]:
    return [e for e in lg.events if e["service"] == service
            and all(e["f"].get(k) == v for k, v in match.items())]


# --- scenarios: build a log, return (question, shape, gold) or None ---------

def s_502_timeout(seed: int):
    lg = Log(seed)
    r = lg.rng
    for _ in range(r.randint(3, 7)):
        web(lg, lg.rand_t(0, 0.95), status=502, db="timeout", api_error="upstream error")
    for _ in range(r.randint(2, 4)):
        web(lg, lg.rand_t(0, 0.95), status=502, db="ok", api_error="inventory service unavailable")
    for _ in range(r.randint(2, 4)):
        web(lg, lg.rand_t(0, 0.95), status=200, db="timeout", retry=True)
    for _ in range(r.randint(1, 3)):
        web(lg, lg.rand_t(0, 0.95), status=504, db="timeout", api_error="upstream error")
    fill(lg)
    trace_of = {e["f"]["req"]: e["f"]["trace"] for e in evs(lg, "gateway", event="request")}
    timed_out = {e["f"]["trace"] for e in lg.events if e["service"] == "db" and e["m"].get("timeout")}
    s502 = [e["f"]["req"] for e in evs(lg, "gateway", event="response", status=502)]
    gold = sum(trace_of[q] in timed_out for q in s502)
    other502 = len(s502) - gold
    retried = sum(1 for e in evs(lg, "gateway", event="response", status=200)
                  if trace_of[e["f"]["req"]] in timed_out)
    if not (3 <= gold <= 8 and other502 >= 2 and retried >= 2):
        return None
    return lg, ("How many requests did the gateway answer with status 502 where the same "
                "request's trace also logged a database statement timeout?",
                '{"answer": <integer>}', gold)


def s_charged_unshipped(seed: int):
    lg = Log(seed)
    r = lg.rng
    plan = (["ship"] * r.randint(10, 14) + ["label"] * r.randint(2, 3) + ["none"] * r.randint(1, 3)
            + ["refund"] * r.randint(2, 3) + ["ship_refund"] * r.randint(1, 2)
            + ["failed"] * 2 + ["failed_then_ship"] * r.randint(1, 2))
    for kind in plan:
        o = lg.uid("o-", 5, hexa=False)
        t = lg.rand_t(0, 0.6)
        amt = f"{r.randint(900, 25000) / 100:.2f}"
        if kind.startswith("failed"):
            lg.add(t, "WARN", "payments", {"event": "charge_failed", "order": o, "amount": amt,
                                           "reason": "card declined"})
            if kind == "failed":
                continue
            t += timedelta(seconds=r.randint(30, 300))
        lg.add(t, "INFO", "payments", {"event": "charged", "order": o, "amount": amt})
        if kind in ("ship", "label", "ship_refund", "failed_then_ship"):
            t += timedelta(seconds=r.randint(60, 900))
            lg.add(t, "INFO", "shipping", {"event": "label_created", "order": o,
                                           "carrier": r.choice(["ups", "usps", "fedex"])})
        if kind in ("ship", "ship_refund", "failed_then_ship"):
            t += timedelta(seconds=r.randint(60, 900))
            lg.add(t, "INFO", "shipping", {"event": "shipped", "order": o})
        if kind in ("refund", "ship_refund"):
            t += timedelta(seconds=r.randint(60, 600))
            lg.add(t, "INFO", "payments", {"event": "refunded", "order": o, "amount": amt})
    fill(lg)
    charged = {e["f"]["order"] for e in evs(lg, "payments", event="charged")}
    shipped = {e["f"]["order"] for e in evs(lg, "shipping", event="shipped")}
    refunded = {e["f"]["order"] for e in evs(lg, "payments", event="refunded")}
    labelled = {e["f"]["order"] for e in evs(lg, "shipping", event="label_created")}
    gold = sorted(charged - shipped - refunded)
    if not (3 <= len(gold) <= 6 and set(gold) & labelled):
        return None
    return lg, ("Which orders were charged successfully but were neither shipped nor refunded? "
                "Count an order as shipped only if shipping logged event=shipped for it. "
                "List the order ids.", '{"answer": ["<order id>", ...]}', {"set": gold})


def s_sessions(seed: int):
    lg = Log(seed)
    r = lg.rng
    sessions = []
    for _ in range(r.randint(18, 24)):
        u, s = r.choice(USERS), lg.uid("s-", 5)
        start = lg.rand_t(0, 0.7)
        dur = r.randint(120, 1500)
        end = r.choice(["logout"] * 5 + ["expired"] * 2 + ["open"])
        lg.add(start, "INFO", "auth", {"event": "login", "user": u, "session": s})
        if end != "open":
            lg.add(start + timedelta(seconds=dur), "INFO", "auth",
                   {"event": "logout" if end == "logout" else "session_expired", "session": s})
        sessions.append((u, s, dur, end))
    fill(lg)
    by_s = {}
    for e in lg.events:
        if e["service"] == "auth" and e["f"]["event"] == "login":
            by_s[e["f"]["session"]] = [e["f"]["user"], e["t"], None, None]
        elif e["service"] == "auth" and e["f"]["event"] in ("logout", "session_expired"):
            by_s[e["f"]["session"]][2:] = [e["t"], e["f"]["event"]]
    done = sorted(((v[2] - v[1]).total_seconds(), v[0]) for v in by_s.values() if v[3] == "logout")
    expired = [((v[2] - v[1]).total_seconds(), v[0]) for v in by_s.values() if v[3] == "session_expired"]
    if len(done) < 2 or not expired:
        return None
    (top, user), (second, _) = done[-1], done[-2]
    total = Counter()
    for d, u in done:
        total[u] += d
    biggest_total = total.most_common(1)[0][0]
    longest_exp = max(expired)
    if not (top - second >= 60 and longest_exp[0] > top + 60 and longest_exp[1] != user
            and biggest_total != user):
        return None
    return lg, ("Considering only sessions that ended with event=logout, which user had the "
                "longest single session? Give the user value exactly as it appears in the log.",
                '{"answer": "<user>"}', {"id": user, "pattern": r"u_[a-z]+"})


def s_retries(seed: int):
    lg = Log(seed)
    r = lg.rng
    plan = ([("ok", 1)] * r.randint(8, 11) + [("ok", 2)] * r.randint(4, 6)
            + [("ok", 3)] * r.randint(2, 4) + [("ok", 4)] * r.randint(1, 3)
            + [("dead", 3)] * r.randint(2, 3) + [("open", r.randint(1, 2)) for _ in range(2)])
    for outcome, n in plan:
        j = lg.uid("j-", 4, hexa=False)
        t = lg.rand_t(0, 0.45)
        lg.add(t, "INFO", "worker", {"event": "enqueued", "job": j,
                                     "type": r.choice(["email", "export", "webhook"])})
        for a in range(1, n + 1):
            t += timedelta(seconds=r.randint(20, 240) * a)
            last = a == n
            if outcome == "ok" and last:
                lg.add(t, "INFO", "worker", {"event": "attempt", "job": j, "outcome": "succeeded"},
                       attempt=a)
            else:
                lg.add(t, "WARN", "worker", {"event": "attempt", "job": j, "outcome": "failed",
                                             "error": r.choice(JOB_ERRORS)}, attempt=a)
        if outcome == "dead":
            lg.add(t + _ms(r.randint(5, 50)), "ERROR", "worker", {"event": "dead_letter", "job": j})
    fill(lg)
    tries = Counter(e["f"]["job"] for e in evs(lg, "worker", event="attempt"))
    ok = {e["f"]["job"] for e in evs(lg, "worker", event="attempt", outcome="succeeded")}
    dead = {e["f"]["job"] for e in evs(lg, "worker", event="dead_letter")}
    gold = sum(tries[j] > 2 for j in ok)
    if not (3 <= gold <= 7 and any(tries[j] > 2 for j in dead)):
        return None
    return lg, ("How many jobs eventually succeeded, but only after more than two attempts?",
                '{"answer": <integer>}', gold)


def s_deploy(seed: int):
    lg = Log(seed)
    r = lg.rng
    dep = lambda f, ev, svc, ver: lg.add(lg.at(f), "INFO", "deployer",  # noqa: E731
                                        {"event": ev, "service": svc, "version": ver})
    dep(0.0, "status", "api", "v2.4.0")
    dep(0.0005, "status", "worker", "v2.4.0")
    dep(0.04, "deploy_started", "worker", "v2.4.1")
    dep(0.06, "deploy_finished", "worker", "v2.4.1")
    a1, b1 = r.uniform(0.12, 0.18), r.uniform(0.03, 0.05)
    a2, b2 = r.uniform(0.38, 0.45), r.uniform(0.02, 0.04)
    a3, b3 = r.uniform(0.62, 0.7), r.uniform(0.03, 0.05)
    dep(a1, "deploy_started", "api", "v2.4.1")
    dep(a1 + b1, "deploy_finished", "api", "v2.4.1")
    dep(a2, "rollback_started", "api", "v2.4.0")
    dep(a2 + b2, "rollback_finished", "api", "v2.4.0")
    dep(a3, "deploy_started", "api", "v2.4.1")
    dep(a3 + b3, "deploy_finished", "api", "v2.4.1")
    for _ in range(r.randint(22, 30)):
        web(lg, lg.rand_t(0.01, 0.99), status=500, api_error=r.choice(API_ERRORS))
    for gap_lo, gap_hi in ((a1, a1 + b1), (a2, a2 + b2)):
        web(lg, lg.rand_t(gap_lo + 0.002, gap_hi - 0.004), status=500, api_error=r.choice(API_ERRORS))
    for _ in range(r.randint(4, 7)):
        lg.add(lg.rand_t(0.07, 0.99), "ERROR", "worker", {"event": "job_failed",
               "job": lg.uid("j-", 4, hexa=False), "error": r.choice(JOB_ERRORS)})
    fill(lg)
    live, windows = None, []
    for e in sorted(lg.events, key=lambda e: e["t"]):
        if e["service"] == "deployer" and e["f"]["service"] == "api" and e["f"]["event"] in (
                "status", "deploy_finished", "rollback_finished"):
            if live:
                windows[-1][1] = e["t"]
            live = e["f"]["version"]
            windows.append([e["t"], None, live])
    windows[-1][1] = datetime.max
    errors = [e["t"] for e in lg.events if e["service"] == "api" and e["level"] == "ERROR"]
    gold = sum(any(lo <= t < hi and v == "v2.4.1" for lo, hi, v in windows) for t in errors)
    in_gaps = sum(any(s <= t < f for s, f in ((lg.at(a1), lg.at(a1 + b1)), (lg.at(a2), lg.at(a2 + b2))))
                  for t in errors)
    if not (5 <= gold <= 18 and in_gaps >= 2):
        return None
    return lg, ("Version v2.4.1 of the api service went live more than once. A version is live "
                "from its deploy_finished or rollback_finished event until the next such event for "
                "the same service. How many ERROR lines did the api service log while api v2.4.1 "
                "was live?", '{"answer": <integer>}', gold)


def s_flags(seed: int):
    lg = Log(seed, tenants=True)
    r = lg.rng
    x, y = r.sample(TENANTS, 2)
    flag = lambda f, ev, name, ten: lg.add(lg.at(f), "INFO", "flags",  # noqa: E731
                                          {"event": ev, "flag": name, "tenant": ten, "actor": "ops"})
    w1 = (r.uniform(0.08, 0.14), r.uniform(0.26, 0.32))
    w2 = (r.uniform(0.52, 0.58), r.uniform(0.72, 0.78))
    flag(w1[0], "flag_enabled", "new_pricing", x)
    flag(w1[1], "flag_disabled", "new_pricing", x)
    flag(w2[0], "flag_enabled", "new_pricing", x)
    flag(w2[1], "flag_disabled", "new_pricing", x)
    flag(r.uniform(0.18, 0.22), "flag_enabled", "new_pricing", y)
    flag(r.uniform(0.33, 0.37), "flag_enabled", "new_search", x)
    flag(r.uniform(0.46, 0.5), "flag_disabled", "new_search", x)
    for _ in range(r.randint(16, 22)):
        web(lg, lg.rand_t(0, 0.99), path="/api/checkout", tenant=x)
    for _ in range(r.randint(20, 28)):
        web(lg, lg.rand_t(0, 0.99), path="/api/checkout", tenant=r.choice([t for t in TENANTS if t != x]))
    fill(lg)
    on, windows = {}, []
    for e in sorted(lg.events, key=lambda e: e["t"]):
        if e["service"] == "flags" and e["f"]["flag"] == "new_pricing" and e["f"]["tenant"] == x:
            if e["f"]["event"] == "flag_enabled":
                on["t"] = e["t"]
            else:
                windows.append((on.pop("t"), e["t"]))
    reqs = [e["t"] for e in evs(lg, "api", route="/api/checkout", tenant=x)]
    gold = sum(any(lo <= t < hi for lo, hi in windows) for t in reqs)
    if not (4 <= gold <= 14 and len(reqs) - gold >= 4):
        return None
    return lg, (f"How many /api/checkout requests did the api serve for tenant {x} while the "
                f"new_pricing flag was enabled for {x}?", '{"answer": <integer>}', gold)


def s_units(seed: int):
    lg = Log(seed, mixed_units=True)
    r = lg.rng
    for ms in ([r.randint(1050, 2400) for _ in range(r.randint(3, 6))]
               + [r.randint(700, 960) for _ in range(r.randint(3, 5))]):
        web(lg, lg.rand_t(0, 0.98), db="ok", db_ms=ms)
    fill(lg)
    q = [e for e in lg.events if e["service"] == "db" and "took_ms" in e["m"]]
    if any(995 <= e["m"]["took_ms"] <= 1005 for e in q):
        return None
    slow = [e for e in q if e["m"]["took_ms"] > 1000]
    gold = len(slow)
    ms_slow = sum(e["f"]["took"].endswith("ms") for e in slow)
    s_fast = sum(e["f"]["took"].endswith("s") and not e["f"]["took"].endswith("ms")
                 and e["m"]["took_ms"] >= 500 for e in q if e["m"]["took_ms"] <= 1000)
    if not (4 <= gold <= 9 and ms_slow >= 2 and gold - ms_slow >= 1 and s_fast >= 2):
        return None
    return lg, ("How many database queries took longer than one second?",
                '{"answer": <integer>}', gold)


def s_job_tenant(seed: int):
    lg = Log(seed)
    r = lg.rng
    weights = {t: r.uniform(0.5, 2.0) for t in TENANTS}
    fail_p = {t: r.uniform(0.05, 0.5) for t in TENANTS}
    for _ in range(r.randint(36, 46)):
        ten = r.choices(TENANTS, [weights[t] for t in TENANTS])[0]
        j, t = lg.uid("j-", 4, hexa=False), lg.rand_t(0, 0.85)
        w = web(lg, t, path=r.choice(["/api/orders", "/api/cart", "/api/catalog"]), tenant=ten)
        lg.add(t + _ms(w["handler_ms"] - 1), "INFO", "api", {"event": "enqueued", "trace": w["trace"],
               "job": j, "tenant": ten})
        t2 = t + timedelta(seconds=r.randint(2, 120))
        lg.add(t2, "INFO", "worker", {"event": "job_started", "job": j})
        t3 = t2 + timedelta(seconds=r.randint(1, 90))
        if r.random() < fail_p[ten]:
            lg.add(t3, "ERROR", "worker", {"event": "job_failed", "job": j, "error": r.choice(JOB_ERRORS)})
        else:
            lg.add(t3, "INFO", "worker", {"event": "job_done", "job": j})
    fill(lg)
    tenant_of = {e["f"]["job"]: e["f"]["tenant"] for e in evs(lg, "api", event="enqueued")}
    fails = Counter(tenant_of[e["f"]["job"]] for e in evs(lg, "worker", event="job_failed")).most_common()
    jobs = Counter(tenant_of.values()).most_common()
    if len(fails) < 2 or fails[0][1] - fails[1][1] < 2 or jobs[0][0] == fails[0][0]:
        return None
    return lg, ("Which tenant had the most failed jobs? Give the tenant value exactly as it "
                "appears in the log.", '{"answer": "<tenant>"}',
                {"id": fails[0][0], "pattern": r"t-[a-z]+"})


def s_dup_charge(seed: int):
    lg = Log(seed)
    r = lg.rng
    plan = (["one"] * r.randint(14, 18) + ["two"] * r.randint(2, 4) + ["two_void"] * r.randint(2, 3)
            + ["fail_one"] * 2 + ["three_void2"] + ["three_void1"] * r.randint(0, 1))
    for kind in plan:
        o = lg.uid("o-", 5, hexa=False)
        t = lg.rand_t(0, 0.6)
        amt = f"{r.randint(900, 25000) / 100:.2f}"
        n, voids = {"one": (1, 0), "two": (2, 0), "two_void": (2, 1), "fail_one": (1, 0),
                    "three_void2": (3, 2), "three_void1": (3, 1)}[kind]
        if kind == "fail_one":
            lg.add(t, "WARN", "payments", {"event": "charge_failed", "order": o, "amount": amt})
            t += timedelta(seconds=r.randint(20, 200))
        charges = []
        for _ in range(n):
            c = lg.uid("ch-", 6)
            lg.add(t, "INFO", "payments", {"event": "charged", "order": o, "charge": c, "amount": amt})
            charges.append((c, t))
            t += timedelta(seconds=r.randint(5, 400))
        for c, tc in r.sample(charges, voids):
            lg.add(tc + timedelta(seconds=r.randint(300, 1200)), "INFO", "payments",
                   {"event": "charge_voided", "charge": c})
    fill(lg)
    voided = {e["f"]["charge"] for e in evs(lg, "payments", event="charge_voided")}
    live = Counter(e["f"]["order"] for e in evs(lg, "payments", event="charged")
                   if e["f"]["charge"] not in voided)
    gold = sorted(o for o, n in live.items() if n > 1)
    if not (2 <= len(gold) <= 5 and voided):
        return None
    return lg, ("Which orders ended up with more than one successful charge that was not later "
                "voided? List the order ids.", '{"answer": ["<order id>", ...]}', {"set": gold})


def s_gateway_queue(seed: int):
    lg = Log(seed)
    r = lg.rng
    for _ in range(r.randint(2, 5)):
        web(lg, lg.rand_t(0, 0.97), api_ms=r.randint(40, 190), gw_extra=r.randint(1900, 3600), db="none")
    for _ in range(r.randint(2, 4)):
        web(lg, lg.rand_t(0, 0.97), api_ms=r.randint(1700, 2600), gw_extra=r.randint(310, 900), db="none")
    for _ in range(r.randint(2, 3)):
        web(lg, lg.rand_t(0, 0.97), api_ms=r.randint(40, 190), gw_extra=r.randint(1400, 1750), db="none")
    fill(lg)
    trace_of = {e["f"]["req"]: e["f"]["trace"] for e in evs(lg, "gateway", event="request")}
    handler = {e["f"]["trace"]: e["m"]["handler_ms"] for e in lg.events
               if e["service"] == "api" and "handler_ms" in e["m"]}
    resp = evs(lg, "gateway", event="response")
    gold = sorted(e["f"]["req"] for e in resp if e["f"]["dur_ms"] > 2000
                  and handler[trace_of[e["f"]["req"]]] < 200)
    slow_api = sum(e["f"]["dur_ms"] > 2000 and handler[trace_of[e["f"]["req"]]] >= 200 for e in resp)
    near = sum(1500 <= e["f"]["dur_ms"] <= 2000 and handler[trace_of[e["f"]["req"]]] < 200 for e in resp)
    if not (2 <= len(gold) <= 5 and slow_api >= 2 and near >= 1):
        return None
    return lg, ("Which requests took more than 2000 ms at the gateway (dur_ms) even though the api "
                "handler for the same trace finished in under 200 ms (handler_ms)? List their req ids.",
                '{"answer": ["<req id>", ...]}', {"set": gold})


SCENARIOS = [
    ("J01", s_502_timeout, ("cross-service", "two-hop")),
    ("J02", s_charged_unshipped, ("event-types", "set")),
    ("J03", s_sessions, ("event-types", "duration")),
    ("J04", s_retries, ("aggregate",)),
    ("J05", s_deploy, ("time-window",)),
    ("J06", s_flags, ("time-window", "per-tenant")),
    ("J07", s_units, ("units",)),
    ("J08", s_job_tenant, ("two-hop", "aggregate")),
    ("J09", s_dup_charge, ("event-types", "set")),
    ("J10", s_gateway_queue, ("cross-service", "set")),
]


def items() -> list[dict]:
    out = []
    for n, (lid, scenario, tags) in enumerate(SCENARIOS):
        seed = 7000 + 100 * n
        while (res := scenario(seed)) is None:
            seed += 1
        lg, (question, shape, gold) = res
        log = lg.render()
        n_lines = log.count("\n") + 1
        assert MIN_LINES <= n_lines <= MAX_LINES, f"{lid}: {n_lines} lines"
        out.append(item(lid, CAT, question + json_contract(shape), gold, "join",
                        context=f"```\n{log}\n```", task_type="ask", tags=tags, seed=seed,
                        lines=n_lines))
    return out
