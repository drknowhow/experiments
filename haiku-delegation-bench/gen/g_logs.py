"""log-triage: answer a counting or lookup question over a ~250-line service log.

Each item gets its own seeded log. The answer is computed from the events the
generator emitted, never by parsing its own output, and the seed is advanced
until the answer is unique and the item's distractor is present."""
from __future__ import annotations

import random
from datetime import datetime, timedelta

from common import item, json_contract

N_LINES = 250
USERS = ["u_ada", "u_bo", "u_cyd", "u_dee", "u_eli", "u_fay", "u_gus", "u_hal"]
METHODS = ["GET"] * 6 + ["POST"] * 2 + ["PUT", "DELETE"]
STATUSES = [200] * 70 + [201] * 6 + [304] * 6 + [404] * 6 + [401] * 3 + [500] * 3 + [502] * 2 + [503] * 2
OTHER_ERRORS = [("search", 'msg="index shard timeout" shard=7'),
                ("notifier", 'msg="smtp relay refused connection"'),
                ("media", 'msg="thumbnail render failed" asset=a-5521')]
PAY_ERRORS = ['msg="charge declined by processor" order=o-{n}',
              'msg="ledger write failed: deadlock detected" order=o-{n}']
PAY_WARNS = ['msg="processor latency high, retrying" order=o-{n} attempt=2',
             'msg="webhook signature mismatch, ignored" order=o-{n}']

KINDS = ["web", "login_failed", "login_ok", "rate_limited", "job_started", "job_finished",
         "pay_error", "pay_warn", "other_error"]
WEIGHTS = [62, 6, 6, 5, 6, 7, 1.5, 2, 3]


def _ip(rng: random.Random, pool: list[str] | None = None) -> str:
    if pool and rng.random() < 0.6:
        return rng.choice(pool)
    return f"10.0.{rng.randint(0, 9)}.{rng.randint(2, 254)}"


def make_log(seed: int) -> tuple[str, list[dict]]:
    rng = random.Random(seed)
    t = datetime(2026, 3, 11, 14, 0, 0) + timedelta(seconds=rng.randint(0, 1800))
    # One user is the brute-force target, so failed logins cluster.
    target = rng.choice(USERS)
    fail_weights = [6 if u == target else 1 for u in USERS]
    abusers = [_ip(rng) for _ in range(3)]
    events: list[dict] = []
    pending: list[str] = []
    used_jobs: set[str] = set()

    def job_id() -> str:
        while True:
            j = f"j-{rng.randint(1000, 9999)}"
            if j not in used_jobs:
                used_jobs.add(j)
                return j

    # A job that started before this log window: finished, never started here.
    orphan = job_id()
    for n in range(N_LINES):
        t += timedelta(milliseconds=rng.randint(150, 4000))
        ts = t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"
        kind = "job_finished_orphan" if n == 3 else rng.choices(KINDS, WEIGHTS)[0]
        if kind == "job_finished" and not pending:
            kind = "web"
        ev: dict = {"ts": ts, "kind": kind}
        if kind == "web":
            status = rng.choice(STATUSES)
            path = rng.choice(["/api/orders", "/api/orders/{id}", "/api/cart",
                               "/api/users/me", "/api/search", "/health"])
            if path == "/api/orders/{id}":
                path = f"/api/orders/{rng.randint(1000, 99999)}"
            ev.update(status=status, path=path, ms=int(rng.expovariate(1 / 150)) + 5,
                      req=f"r-{rng.getrandbits(24):06x}", method=rng.choice(METHODS),
                      ip=_ip(rng), user=rng.choice(USERS))
            level = "ERROR" if status >= 500 else "WARN" if status >= 400 else "INFO"
            line = (f"{ts} {level:<5} web req={ev['req']} method={ev['method']} path={path} "
                    f"status={status} ms={ev['ms']} ip={ev['ip']} user={ev['user']}")
        elif kind in ("login_failed", "login_ok"):
            user = rng.choices(USERS, fail_weights)[0] if kind == "login_failed" else rng.choice(USERS)
            ev.update(user=user)
            level = "WARN" if kind == "login_failed" else "INFO"
            line = f"{ts} {level:<5} auth event={kind} user={user} ip={_ip(rng)}"
        elif kind == "rate_limited":
            ev.update(ip=_ip(rng, abusers))
            line = f"{ts} WARN  web rate_limited ip={ev['ip']} limit=100/min"
        elif kind == "job_started":
            j = job_id()
            pending.append(j)
            ev.update(job=j)
            line = f"{ts} INFO  worker event=job_started job={j} queue=default"
        elif kind == "job_finished":
            j = pending.pop(rng.randrange(len(pending)))
            ev.update(job=j)
            line = f"{ts} INFO  worker event=job_finished job={j} ms={rng.randint(200, 9000)}"
        elif kind == "job_finished_orphan":
            ev.update(job=orphan)
            line = f"{ts} INFO  worker event=job_finished job={orphan} ms={rng.randint(200, 9000)}"
        elif kind == "pay_error":
            line = f"{ts} ERROR payments-worker " + rng.choice(PAY_ERRORS).format(n=rng.randint(10000, 99999))
        elif kind == "pay_warn":
            line = f"{ts} WARN  payments-worker " + rng.choice(PAY_WARNS).format(n=rng.randint(10000, 99999))
        else:
            svc, msg = rng.choice(OTHER_ERRORS)
            ev.update(service=svc)
            line = f"{ts} ERROR {svc} {msg}"
        ev["line"] = line
        events.append(ev)
    return "\n".join(e["line"] for e in events), events


# Each question: (id, question, answer shape, solver). A solver returns the gold
# answer, or None when this seed's log does not make a fair item.
def _q5xx(ev):
    web = [e for e in ev if e["kind"] == "web"]
    decoys = [e for e in web if e["status"] < 500 and 500 <= e["ms"] < 600]
    return sum(e["status"] >= 500 for e in web) if decoys else None


def _qlogin(ev):
    from collections import Counter
    c = Counter(e["user"] for e in ev if e["kind"] == "login_failed").most_common()
    return {"contains": c[0][0]} if len(c) > 1 and c[0][1] > c[1][1] else None


def _qslowest(ev):
    exact = [e for e in ev if e["kind"] == "web" and e["path"] == "/api/orders"]
    by_id = [e for e in ev if e["kind"] == "web" and e["path"].startswith("/api/orders/")]
    if not exact or not by_id:
        return None
    top = sorted(exact, key=lambda e: e["ms"], reverse=True)
    if len(top) > 1 and top[0]["ms"] == top[1]["ms"]:
        return None
    # Distractor: an /api/orders/<id> request slower than every exact match.
    if max(e["ms"] for e in by_id) <= top[0]["ms"]:
        return None
    return {"contains": top[0]["req"]}


def _qratelimited(ev):
    ips = [e["ip"] for e in ev if e["kind"] == "rate_limited"]
    return len(set(ips)) if len(ips) > len(set(ips)) else None


def _qfirstpay(ev):
    first = next((i for i, e in enumerate(ev) if e["line"].split()[1] == "ERROR"
                  and " payments-worker " in e["line"]), None)
    if first is None:
        return None
    before = ev[:first]
    has_warn = any(" WARN  payments-worker " in e["line"] for e in before)
    has_other = any(e["kind"] == "other_error" for e in before)
    return {"contains": ev[first]["ts"][11:19]} if has_warn and has_other else None


def _qjobs(ev):
    started = {e["job"] for e in ev if e["kind"] == "job_started"}
    finished = {e["job"] for e in ev if e["kind"] in ("job_finished", "job_finished_orphan")}
    open_jobs = sorted(started - finished)
    return {"set": open_jobs} if 2 <= len(open_jobs) <= 4 else None


QUESTIONS = [
    ("L1", "How many HTTP requests in this log returned a 5xx status code?",
     '{"answer": <integer>}', _q5xx),
    ("L2", "Which user has the most failed logins (event=login_failed)? Give the user "
     "value exactly as it appears in the log.", '{"answer": "<user>"}', _qlogin),
    ("L3", "Which request to the path /api/orders exactly (not /api/orders/<id>) took "
     "the longest? Give its req id.", '{"answer": "<req id>"}', _qslowest),
    ("L4", "How many distinct IP addresses were rate-limited?", '{"answer": <integer>}',
     _qratelimited),
    ("L5", "At what time (HH:MM:SS) did the payments-worker service log its first ERROR?",
     '{"answer": "<HH:MM:SS>"}', _qfirstpay),
    ("L6", "Which jobs were started in this log but never finished? List their job ids.",
     '{"answer": ["<job id>", ...]}', _qjobs),
]


def items() -> list[dict]:
    out = []
    for n, (lid, question, shape, solve) in enumerate(QUESTIONS):
        seed = 1000 * (n + 1)
        while True:
            log, events = make_log(seed)
            gold = solve(events)
            if gold is not None:
                break
            seed += 1
        out.append(item(lid, "log-triage", question + json_contract(shape), gold,
                        "answer_exact", context=f"```\n{log}\n```", task_type="ask",
                        tags=("mechanical",), seed=seed))
    return out
