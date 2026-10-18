"""Text items: classify (policy triage), extract (schema fields), abstain
(answer from a document or say NOT_FOUND). All gold is hand-set; each item
note says which rule or trap it exercises."""
from __future__ import annotations

from common import item, json_contract

# --------------------------------------------------------------------------
# classify: one notification against a precedence policy
# --------------------------------------------------------------------------

POLICY = """You triage notifications for a developer using this policy. Apply the rules
in order; the first rule that matches decides the label. Where a rule says a
case is ignore, stop there: the label is ignore.

Trusted sender domains: github.com, google.com, accounts.anthropic.com. A
subdomain of a trusted domain (noreply.github.com, myaccount.google.com) is
trusted. A look-alike (github-alerts.com, google.co) is not.
Watched repositories: acme/api, acme/web.

1. phishing: the message asks the reader to sign in, verify an account, or
   reset a password, AND either the sender's domain is not trusted, or a link
   in the message points to a domain that is neither the sender's domain nor
   a subdomain of it.
2. security: from a trusted sender, about the reader's own account or a
   watched repository: a new sign-in, a password or 2FA change, an access
   token or key created or exposed, a security advisory.
3. ci_failure: a CI run or check failed on a watched repository. A failure on
   any other repository, or a run that passed or was cancelled, is ignore.
4. review_request: the reader's review was requested on a pull request in a
   watched repository that is not a draft. A draft pull request is ignore.
5. billing: a payment failed or a card was declined (any amount); an invoice
   or receipt for $20.00 or more; a plan or subscription change. A receipt
   under $20.00 is ignore.
6. newsletter: marketing, digests, product announcements, event invitations
   sent to a list.
7. ignore: anything else."""

LABELS = "security, phishing, ci_failure, review_request, billing, newsletter, ignore"

NOTIFICATIONS = [
    ("c01", "phishing", "look-alike sender domain asks to verify",
     "security@github-alerts.com", "Unusual sign-in attempt blocked",
     "We blocked a sign-in to your account from a new device. If this wasn't "
     "you, verify your account within 24 hours: https://github-alerts.com/verify?u=dev"),
    ("c02", "security", "trusted sender, token created",
     "noreply@github.com", "[GitHub] A new personal access token was added to your account",
     "A fine-grained personal access token (deploy-bot) with repo scope was "
     "recently added to your account. Visit https://github.com/settings/tokens "
     "for more information."),
    ("c03", "ci_failure", "watched repo, run failed",
     "notifications@github.com", "[acme/api] Run failed: CI - main (4f2c9e1)",
     "The workflow run \"CI\" failed on main. 1 failed job: test (3.12). "
     "View run: https://github.com/acme/api/actions/runs/88123"),
    ("c04", "ignore", "run failed on an unwatched repo",
     "notifications@github.com", "[octo-org/tools] Run failed: release - main (9ab01c3)",
     "The workflow run \"release\" failed on main. 1 failed job: publish. "
     "View run: https://github.com/octo-org/tools/actions/runs/5521"),
    ("c05", "ignore", "review requested on a draft PR",
     "notifications@github.com", "[acme/web] Draft: Migrate settings page to new forms API (PR #412)",
     "@priya-k requested your review on this draft pull request. \"Still WIP, "
     "would love early eyes on the approach.\" https://github.com/acme/web/pull/412"),
    ("c06", "billing", "payment failure under $20 is still billing",
     "billing@pixelhost.io", "Payment failed for your Starter plan",
     "We couldn't charge your card ending 4242 for $4.99. We'll retry "
     "automatically in 3 days. You can also update your card from the Billing "
     "page of your dashboard."),
    ("c07", "ignore", "receipt under $20",
     "receipts@brewbar.app", "Your BrewBar receipt",
     "Thanks for your order! Oat latte (large) $6.50, tip $1.00. Total $7.50 "
     "charged to Visa ending 1881."),
    ("c08", "review_request", "non-draft PR on watched repo; payment and checks wording are distractors",
     "notifications@github.com", "[acme/api] Add idempotency keys to POST /payments (PR #1287)",
     "@sam-ortiz requested your review on this pull request. All checks have "
     "passed. \"Adds an Idempotency-Key header and a 24h dedupe table.\" "
     "https://github.com/acme/api/pull/1287"),
    ("c09", "phishing", "trusted sender but the sign-in link is a look-alike domain",
     "noreply@github.com", "Action required: your session has expired",
     "For your security we signed you out of all devices. Sign in again to "
     "restore access: https://github.com.session-restore.co/login"),
    ("c10", "newsletter", "trusted sender, off-domain link, but no credential ask",
     "events@github.com", "GitHub Universe 2026: early-bird tickets end Friday",
     "Join thousands of developers for two days of talks and workshops. "
     "Register now at https://githubuniverse.com and save 30%."),
]


def classify_items() -> list[dict]:
    out = []
    for cid, label, note, sender, subject, body in NOTIFICATIONS:
        context = (f"{POLICY}\n\nNotification:\nFrom: {sender}\nSubject: {subject}\n"
                   f"Body: {body}")
        task = ("Apply the triage policy to this notification. Which label does it assign?"
                + json_contract(f'{{"label": "<one of: {LABELS}>"}}'))
        out.append(item(cid, "classify", task, label, "label", context=context,
                        task_type="ask", tags=("mechanical",), note=note))
    return out


# --------------------------------------------------------------------------
# extract: fields from a messy message; missing fields must be null
# --------------------------------------------------------------------------

ORDER_SCHEMA = """Fields:
- customer_name: the customer's name as written, or null
- item: what they ordered (short noun phrase), or null
- quantity: integer count of items, or null
- delivery_date: YYYY-MM-DD, or null
- phone: digits only, or null
Use null for anything the message does not state. Do not guess."""

ORDER_SHAPE = ('{"customer_name": ..., "item": ..., "quantity": ..., '
               '"delivery_date": ..., "phone": ...}')

INVITE_SCHEMA = """Fields:
- event: what the event is (short phrase)
- date: YYYY-MM-DD
- start_time: HH:MM, 24-hour
- location: where it is, or null
- rsvp_by: YYYY-MM-DD, or null
Use null for anything the message does not state. Do not guess."""

INVITE_SHAPE = '{"event": ..., "date": ..., "start_time": ..., "location": ..., "rsvp_by": ...}'

# gold field forms: plain value = normalized equality; {"contains": s} =
# the normalized answer contains s; None = must be null.
EXTRACTS = [
    ("x01", "order", "Wednesday 2026-03-11",
     "hey its marta again!! can u do 3 of the large sourdough loaves for sat? "
     "same address as last time. thx",
     {"customer_name": "marta", "item": {"contains": "sourdough"}, "quantity": 3,
      "delivery_date": "2026-03-14", "phone": None}),
    ("x02", "order", "Wednesday 2026-03-11",
     "Order for Dev Patel (212-555-0142): two dozen plain bagels, deliver "
     "Monday the 16th please. Cash on delivery.",
     {"customer_name": "dev patel", "item": {"contains": "bagel"}, "quantity": 24,
      "delivery_date": "2026-03-16", "phone": "2125550142"}),
    ("x03", "order", "Thursday 2026-03-12",
     "Need ten croissants tomorrow morning pls. Call (212) 555-0199 if there's "
     "any issue with the order",
     {"customer_name": None, "item": {"contains": "croissant"}, "quantity": 10,
      "delivery_date": "2026-03-13", "phone": "2125550199"}),
    ("x04", "order", "Tuesday 2026-03-10",
     "Hi, this is Sam Okafor. Could I order one birthday cake for Friday the "
     "20th? Not sure on the flavor yet, I'll confirm by email.",
     {"customer_name": "sam okafor", "item": {"contains": "cake"}, "quantity": 1,
      "delivery_date": "2026-03-20", "phone": None}),
    ("x05", "invite", "Wednesday 2026-03-11",
     "Team offsite planning sync - Thursday March 19, 2:30pm, Room 4B. RSVP by the 17th.",
     {"event": {"contains": "offsite"}, "date": "2026-03-19", "start_time": "14:30",
      "location": {"contains": "4b"}, "rsvp_by": "2026-03-17"}),
    ("x06", "invite", "Wednesday 2026-03-11",
     "Potluck at Lena's place! Sat 3/21 from noon until whenever. Bring a dish "
     "to share - no need to RSVP, just show up.",
     {"event": {"contains": "potluck"}, "date": "2026-03-21", "start_time": "12:00",
      "location": {"contains": "lena"}, "rsvp_by": None}),
    ("x07", "invite", "Wednesday 2026-03-11",
     "Reminder: the quarterly review has moved to 9am on Tuesday the 24th. Room "
     "still TBD, I'll send it once facilities confirms.",
     {"event": {"contains": "quarterly review"}, "date": "2026-03-24",
      "start_time": "09:00", "location": None, "rsvp_by": None}),
    ("x08", "invite", "Wednesday 2026-03-11",
     "Book club - we're reading Piranesi this month. Usual spot (back room at "
     "Fern Cafe), Wednesday the 25th, 7:15 in the evening. Tell Ana by Monday "
     "the 23rd if you're coming.",
     {"event": {"contains": "book club"}, "date": "2026-03-25", "start_time": "19:15",
      "location": {"contains": "fern"}, "rsvp_by": "2026-03-23"}),
]


def extract_items() -> list[dict]:
    out = []
    for xid, kind, today, message, gold in EXTRACTS:
        schema, shape, what = ((ORDER_SCHEMA, ORDER_SHAPE, "the order from this customer message")
                               if kind == "order" else
                               (INVITE_SCHEMA, INVITE_SHAPE, "the event from this invitation"))
        context = f'Today is {today}.\n\nMessage:\n"""\n{message}\n"""'
        task = f"Extract {what}.\n\n{schema}" + json_contract(shape)
        out.append(item(xid, "extract", task, gold, "fields", context=context,
                        task_type="ask", tags=("mechanical",),
                        nulls=sum(v is None for v in gold.values())))
    return out


# --------------------------------------------------------------------------
# abstain: answer from a document; half the questions are not answerable
# --------------------------------------------------------------------------

DOC_LEDGERLINE = """# Ledgerline runbook

Ledgerline is the internal service that records balance adjustments for the
billing platform. It is owned by the Payments Platform team; the escalation
channel is #ledgerline-oncall.

## Ports and endpoints
- HTTP API: port 8443 (TLS only)
- Metrics: port 9102, path /metrics
- Admin console: port 8444, reachable only from the bastion host

## Deploys
Deploys run Tuesday and Thursday between 14:00 and 16:00 UTC. A deploy outside
that window needs approval from the on-call lead. Each deploy runs as a canary
at 5% of traffic for 20 minutes, then goes to 100%.

## Rollback
1. Run `ledgerctl rollback --to previous`.
2. Confirm the canary error rate is below 0.5% for 10 minutes.
3. Post the rollback in #ledgerline-oncall with the release tag.

## Data retention
Adjustment records are kept for 7 years. Request logs are kept for 30 days."""

DOC_QUILL = """# Quill API v2

Base URL: https://api.quill.example/v2
Authenticate with a bearer token in the Authorization header. Access tokens
expire after 12 hours; get a new one with POST /auth/refresh.

## Rate limits
| Endpoint        | Limit                 |
|-----------------|-----------------------|
| GET /documents  | 600 requests / minute |
| POST /documents | 60 requests / minute  |
| POST /search    | 120 requests / minute |
Exceeding a limit returns 429 with a Retry-After header in seconds.

## Pagination
List endpoints return up to 50 items by default; pass `limit` (max 200) and
the `cursor` from the previous response's `next_cursor`.

## Errors
Errors are JSON: {"error": {"code": "...", "message": "..."}}. A 409 means the
document was modified since you read it; re-read it and retry with the new
`etag`."""

# gold: a regex the normalized answer must match, or "NOT_FOUND"
ABSTAIN = [
    ("a01", DOC_LEDGERLINE, "How long does a Ledgerline canary run before the deploy goes to 100%?",
     r"\b20\b", "answerable"),
    ("a02", DOC_LEDGERLINE, "Which port serves Ledgerline's metrics?", r"\b9102\b", "answerable"),
    ("a03", DOC_LEDGERLINE, "What is the request timeout for the Ledgerline HTTP API?",
     "NOT_FOUND", "absent"),
    ("a04", DOC_LEDGERLINE, "How long are Ledgerline's metrics kept?",
     "NOT_FOUND", "adjacent: retention is given for records and request logs only"),
    ("a05", DOC_QUILL, "What is the largest page size a Quill list endpoint will return?",
     r"\b200\b", "answerable"),
    ("a06", DOC_QUILL, "Which HTTP status code means a document changed since it was read?",
     r"\b409\b", "answerable"),
    ("a07", DOC_QUILL, "What is the rate limit for DELETE /documents?",
     "NOT_FOUND", "adjacent: limits are listed for three other endpoints"),
    ("a08", DOC_QUILL, "How long is a Quill refresh token valid?",
     "NOT_FOUND", "adjacent: the 12-hour figure is for access tokens"),
]


def abstain_items() -> list[dict]:
    out = []
    for aid, doc, question, gold, note in ABSTAIN:
        task = (f"{question}\n\nAnswer from the document only. If it does not "
                "contain the answer, answer NOT_FOUND."
                + json_contract('{"answer": "<the answer, or NOT_FOUND>"}'))
        out.append(item(aid, "abstain", task, gold, "abstain", context=doc,
                        task_type="ask", tags=("judgment",),
                        answerable=gold != "NOT_FOUND", note=note))
    return out


def items() -> list[dict]:
    return classify_items() + extract_items() + abstain_items()
