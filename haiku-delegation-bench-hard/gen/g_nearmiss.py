"""abstain-nearmiss: answer one question from a 1,500-3,000-word document, or
say NOT_FOUND.

Six of the ten questions cannot be answered from their document, but the
document holds a near miss: the same fact for another version (N01, N02),
another environment (N03, N04) or another kind of log (N05, N06). The other
four are answerable, but only through a table cell (N07), a condition
(N08), a footnote (N09) or a footnote that is itself a condition (N10).

All documents, products and companies are invented. The build checks, on
the rendered text:
  - the word count is 1,500-3,000;
  - unanswerable: every near-miss string is present, and the asked fact is
    absent, stated as patterns that must not match the document, patterns
    that may match only inside a named passage, or "no sentence that
    mentions X also states a value";
  - answerable: the answer surface is in the document, the gold pattern
    accepts it, and the gold pattern rejects every distractor surface (the
    values a careless reader would pick), each of which is also in the
    document."""
from __future__ import annotations

import random
import re

from common import item, json_contract

CAT = "abstain-nearmiss"
MIN_WORDS, MAX_WORDS = 1500, 3000

PADDING = {
    "about": ("About this document",
              "This document is maintained by the {team} and is reviewed at least once a quarter. "
              "It describes {name} as it is deployed and supported today; it is not a design "
              "proposal and it does not describe work that has not shipped. Where this document "
              "and an older wiki page disagree, this document wins, and the wiki page should be "
              "reported so that it can be corrected or archived. Comments and corrections go to "
              "the {team} through the usual request queue. Section headings are stable, so links "
              "to them from other documents keep working when the text underneath changes. Terms "
              "that have a specific meaning here are defined in the glossary near the end."),
    "support": ("Support and escalation",
                "Questions about {name} go first to the {team} request queue, which is watched "
                "during business hours. A request is acknowledged within four business hours and "
                "gets a first substantive answer within two business days. Anything that blocks "
                "customers counts as an incident rather than a request: open an incident through "
                "the incident tool, which pages the on-call engineer directly, instead of filing a "
                "queue item and waiting. When you escalate, include what you expected to happen, "
                "what happened instead, the time it started and anything you have already tried. "
                "Screenshots help, but paste error text as text so that it can be searched. Please "
                "do not message individual engineers about production problems; the queue and the "
                "incident tool keep a record that the next person on shift can read."),
    "change": ("Change management",
               "Every change to {name} goes through a reviewed pull request and a change record. "
               "Routine changes, such as a dependency bump with passing tests, need one reviewer. "
               "Changes that alter behaviour customers can see need two reviewers, one of them from "
               "outside the authoring team, and a short note in the change record describing how "
               "to undo the change. Changes are not deployed on Friday afternoons or during "
               "company-wide freeze periods, which are announced at least two weeks ahead. "
               "Emergency fixes may skip the waiting period, but they still need a reviewer and a "
               "change record written within one business day. The change record links the pull "
               "request, the deployment and any incident that prompted the change, so that someone "
               "reading it later can follow the whole story."),
    "security": ("Security overview",
                 "Secrets for {name} are kept in the shared secrets manager, never in configuration "
                 "files or source control. Service credentials are rotated every ninety days, and "
                 "any credential that appears in a log or a ticket is rotated at once, whether or "
                 "not anyone thinks it was misused. Administrative functions require single sign-on "
                 "with a hardware key. Traffic between services is encrypted in transit, and stored "
                 "data is encrypted at rest with keys held by the platform team. Vulnerability scans "
                 "run weekly against every deployed image; findings rated high or critical must be "
                 "fixed or formally accepted within fourteen days. Suspected security problems "
                 "should be reported to the security team through its private intake form rather "
                 "than in public channels."),
    "access": ("Requesting access",
               "Access to {name} is granted per role, not per person. Engineers on the owning team "
               "receive operator access when they join; everyone else requests read-only access "
               "through the access portal, naming the business reason and how long access is "
               "needed. Requests are approved by the {team} lead or a delegate and expire "
               "automatically at the end of the stated period. Operator access for people outside "
               "the owning team is granted only for a specific piece of work and is reviewed at the "
               "end of each quarter. Shared accounts are not allowed. If you change teams, your "
               "existing access is removed on your transfer date and you must request it again "
               "from your new role."),
    "glossary": ("Glossary",
                 "Operator: a person with permission to change the running configuration. Tenant: "
                 "one customer account, together with all of its users and data. Release: a "
                 "numbered, tagged build that has passed the full test suite. Rollback: returning to "
                 "the previous release, as opposed to fixing forward with a new one. Request queue: "
                 "the ticketing queue owned by the {team}. Business day: Monday to Friday, excluding "
                 "company holidays. Change record: the short written summary that accompanies every "
                 "deployed change. On-call engineer: the person currently holding the pager for "
                 "{name}."),
    "training": ("Training and onboarding",
                 "New members of the {team} spend their first two weeks shadowing the on-call "
                 "rotation before they take a shift of their own. The onboarding checklist covers "
                 "the architecture walkthrough, the local development setup, a supervised "
                 "deployment, and a tabletop exercise in which the new engineer works through a "
                 "recorded incident from start to finish. Recorded walkthroughs are kept in the "
                 "team's video library and are refreshed whenever the architecture changes in a way "
                 "that makes them misleading. People outside the team who use {name} regularly are "
                 "welcome at the monthly open office hours, where the team answers questions and "
                 "demonstrates recent changes."),
    "deprecation": ("Deprecation policy",
                    "Features of {name} are deprecated before they are removed. A deprecation is "
                    "announced in the release notes and in the announcements channel, together with "
                    "the replacement and a removal date at least two releases away. During the "
                    "deprecation period the old behaviour keeps working but logs a warning each time "
                    "it is used, so that owners of dependent systems can find their remaining uses. "
                    "The {team} contacts the owners of any system still using a deprecated feature "
                    "one month before removal. Removal dates move only later, never earlier, unless "
                    "a security problem makes the old behaviour unsafe to keep."),
    "feedback": ("Feedback",
                 "Suggestions for improving {name} are welcome at any time. The {team} reviews the "
                 "suggestion board every two weeks, groups related items, and replies to each one "
                 "with a decision: planned, considered for later, or declined with a reason. "
                 "Planned items are linked to the work tracker so that the person who suggested "
                 "them can follow progress. When a suggestion is declined, the reply explains what "
                 "would need to change for it to be reconsidered. Please search the board before "
                 "adding a new suggestion; a comment on an existing item helps more than a "
                 "duplicate."),
    "dashboards": ("Dashboards",
                   "The main dashboard for {name} shows request volume, error rate, latency "
                   "percentiles and saturation for each deployed component. Each panel links to "
                   "the query behind it, so anyone can open the underlying data and narrow it down. "
                   "Dashboards are defined in code alongside the service, reviewed like any other "
                   "change, and rebuilt automatically when the definitions change. Dashboards made "
                   "by hand are fine for an investigation but are removed after thirty days unless "
                   "someone moves them into code. When you add a new component, add its panels in "
                   "the same pull request that adds the component."),
    "backups": ("Backups and restore",
                "Backups of {name} are taken automatically and copied to a second storage account "
                "that the service itself cannot write to or delete from. A restore test runs every "
                "month: the {team} restores the most recent backup into an isolated environment, "
                "checks that the restored data is complete and readable, and records how long the "
                "restore took. A failed restore test is treated as an incident. Restores in "
                "response to customer requests are possible but slow and need approval from the "
                "{team} lead, because restoring one tenant's data without disturbing the others is "
                "a manual process."),
    "versioning": ("How releases are numbered",
                   "Releases of {name} use three-part numbers. The first part changes when a release "
                   "removes something or changes behaviour in a way that may break existing "
                   "integrations. The second part changes when a release adds features without "
                   "breaking existing ones. The third part changes for fixes only. Release notes "
                   "always say which kind of release it is, and they list anything that needs "
                   "action from operators before or after upgrading. Fix releases are made only for "
                   "the two most recent feature releases; older ones receive security fixes alone, "
                   "and only for a limited time after the next feature release ships."),
    "oncall": ("On-call rotation",
               "The {team} runs a weekly on-call rotation that changes over on Monday mornings. The "
               "engineer coming off call writes a handover note listing open incidents, anything "
               "that paged more than once, and work left half done. The engineer going on call reads "
               "it before taking the pager and asks questions while the previous engineer is still "
               "around to answer them. Each shift has a primary and a secondary; the secondary takes "
               "pages the primary cannot acknowledge in time and covers short absences. Swaps are "
               "fine as long as both people agree and the rotation tool is updated before the swap "
               "begins, so that pages reach the right phone. Nobody is on call two weeks running "
               "unless they ask to be."),
    "incidents": ("Incident process",
                  "An incident is any event that stops customers from using {name} as they expect, "
                  "or that puts data at risk. The first person to notice opens an incident in the "
                  "incident tool, which creates a chat room and pages the on-call engineer. One "
                  "person acts as incident lead and keeps a running log of what was seen and what was "
                  "tried; other people work on the problem and report back to the lead rather than "
                  "acting on their own. Customer-facing updates go out through the status page, "
                  "written by the lead or someone they name. When the incident is over, the lead "
                  "schedules a review within five business days. Reviews look for causes in systems "
                  "and processes, not in individual people."),
    "capacity": ("Capacity planning",
                 "The {team} reviews capacity once a month. The review compares current use of "
                 "compute, memory, storage and network with the limits of each, and projects growth "
                 "over the next two quarters from the trend of the last six months. Any resource "
                 "expected to pass 70 percent of its limit within a quarter gets a work item to add "
                 "headroom before it does. Known events that bring unusual load, such as a large "
                 "customer moving onto {name} or a seasonal peak, are added to the projection by hand. "
                 "The review notes are kept with the dashboards, so that the next review can see what "
                 "was predicted and how close the prediction came."),
    "costs": ("Cost reporting",
              "The running cost of {name} is reported every month, broken down by component and by "
              "environment. The report shows the change since the previous month and explains any "
              "change larger than ten percent. Costs that cannot be assigned to one component, such "
              "as shared networking, are split by usage. The {team} looks for savings twice a year: "
              "unused resources, oversized machines and storage that nobody reads any more. Savings "
              "that need a design change go into the normal planning process rather than being made "
              "in a hurry, because the cheapest configuration is not always the one that keeps "
              "working under load."),
    "testing": ("Testing",
                "Every change to {name} runs the unit tests, the integration tests and a short "
                "end-to-end suite before it can be merged. The end-to-end suite runs against a fresh "
                "copy of the service with synthetic data, never against real customer data. Flaky "
                "tests are quarantined within a day of being noticed and fixed within a week; a "
                "quarantined test still runs, but its result does not block merges. Performance "
                "tests run nightly and compare their results with the previous week, so that a slow "
                "regression is noticed before customers notice it. New features are expected to "
                "arrive with tests that would fail if the feature broke."),
    "dependencies": ("Dependencies",
                     "The service depends on a small number of shared platform services: the "
                     "identity service for sign-in, the secrets manager, the message bus and the log "
                     "platform. Each dependency has an owner, a documented service level and a named "
                     "contact for problems. When a dependency is degraded, {name} is designed to keep "
                     "serving what it can rather than failing completely, and the dashboards show "
                     "which dependency is at fault. Libraries are updated by an automated job that "
                     "opens pull requests every week; the {team} reviews and merges them within two "
                     "weeks unless a change needs more work."),
    "docs": ("Writing documentation",
             "Documentation for {name} lives next to the code and is reviewed in the same pull "
             "requests. A change that alters behaviour must update the documents that describe that "
             "behaviour, or explain in the pull request why none do. Runbooks are written for a "
             "tired engineer at night: short steps, the exact commands to run, and what the output "
             "should look like. Each document names its owner and the date it was last checked. "
             "Documents that have not been checked for a year are flagged on the team's board and "
             "either refreshed or archived."),
    "dr": ("Disaster recovery",
           "The {team} keeps a written plan for recovering {name} if a whole region becomes "
           "unavailable. The plan lists the order in which components are restored, the people who "
           "make each decision, and how customers are told. It is rehearsed twice a year in a game "
           "day, during which the team restores the service in a second region from backups alone "
           "and times each step. Gaps found during a rehearsal are written up as work items and "
           "checked at the next one. The plan is also printed and kept offline, because it must be "
           "usable when the usual tools are down."),
    # Customer-facing sections, for the documents written for customers.
    "c_account": ("Your account",
                  "You can change your name, email address and password at any time from the "
                  "account page. Changing the email address sends a confirmation link to the new "
                  "address, and the change takes effect only when the link is opened; until then, "
                  "messages keep going to the old address. If you forget your password, the sign-in "
                  "page can send a reset link. For your safety, a reset signs you out of every "
                  "device. If you no longer have access to the email address on your account, "
                  "contact the {team}, who will ask a few questions to confirm that the account is "
                  "yours before changing anything."),
    "c_privacy": ("Privacy",
                  "{name} collects only the information it needs to run the service and keep "
                  "accounts secure. We do not sell personal information, and we share it with other "
                  "companies only when they help us run the service, under contracts that limit what "
                  "they may do with it. You can download a copy of the personal information we hold "
                  "about you from the privacy page, and you can ask us to correct or delete it. Some "
                  "records must be kept for legal reasons even after an account is closed; the "
                  "privacy notice lists them and says how long each is kept. Questions about privacy "
                  "go to the privacy team through the form on the privacy page."),
    "c_accessibility": ("Accessibility",
                        "We want everyone to be able to use {name}. Our pages and apps are tested "
                        "with screen readers, keyboard-only navigation and high-contrast settings, "
                        "and we fix accessibility problems with the same priority as other faults "
                        "that stop people from completing a task. Text can be enlarged without "
                        "breaking the layout, and every image that carries information has a text "
                        "description. If something does not work for you, tell the {team}: describe "
                        "what you were trying to do and which device and assistive technology you "
                        "use, and we will reply with a fix or a way around the problem."),
    "c_payment": ("Payment methods",
                  "We accept major credit and debit cards. Cards are charged when an order or a "
                  "subscription starts, and receipts are emailed at once and kept on the account "
                  "page. If a payment fails, we email you and try again over the following days; "
                  "the account keeps working while we retry. You can update the card on file from "
                  "the billing page at any time. Prices are shown in US dollars and include any taxes "
                  "that apply to your address, which are listed separately on the receipt."),
    "c_notifications": ("Email and notifications",
                        "We send two kinds of email. Service messages, such as receipts, security "
                        "alerts and changes to our terms, go to every account and cannot be turned "
                        "off, because they tell you about your account. Everything else, including "
                        "news, tips and offers, is optional and can be turned off with the link at "
                        "the bottom of each message or from the notification settings. Turning off "
                        "optional email takes effect within a day. In the apps, you can choose which "
                        "notifications appear on your device; these settings are kept per device, so "
                        "a change on your phone does not affect your computer."),
    "c_terms": ("Terms of service",
                "Using {name} means agreeing to the terms of service, which are linked at the bottom "
                "of every page. When we change the terms, we post the new version at least thirty "
                "days before it takes effect and email account holders a summary of what changed. If "
                "you do not agree with a change, you can close your account before it takes effect. "
                "The terms cover what you may and may not do with the service, who owns the content "
                "you create, and how disputes are handled."),
    "c_community": ("Community forum",
                    "The community forum is a place to ask questions, share tips and suggest "
                    "improvements. It is read by other customers and by members of the {team}, who "
                    "answer when they can and pass suggestions on to the people who run {name}. "
                    "Answers in the forum come from other customers as often as from staff. Please "
                    "do not post order numbers, account details or anything else private; for "
                    "questions about your own account, contact the {team} directly. Posts that are "
                    "rude, off topic or promotional are removed."),
    "c_languages": ("Languages",
                    "The {name} website is available in English, Spanish and French. The language "
                    "follows your browser or device settings, and you can choose another one from "
                    "the account page. Help articles are written in English first and translated "
                    "within a few weeks; until a translation is ready, the English version is shown "
                    "with a note. Help from the {team} is offered in English and Spanish. If you "
                    "notice a mistake in a translation, the feedback link at the bottom of each page "
                    "sends it straight to the people who maintain the translations."),
    "c_closing": ("Closing your account",
                  "You can close your account from the account page. Before you do, download "
                  "anything you want to keep: once an account is closed, its content is removed "
                  "after a short grace period and cannot be recovered. During the grace period you "
                  "can reopen the account by signing in again. Closing an account cancels any "
                  "subscription at the end of the current billing period; there is no refund for the "
                  "rest of the period unless the law requires one. Open orders are not cancelled "
                  "automatically, so cancel them first if you no longer want them."),
    "c_safety": ("Keeping your account safe",
                 "Use a password you do not use anywhere else, and turn on two-step sign-in from the "
                 "security page. We will never ask for your password by email, chat or phone, and we "
                 "never send links that ask you to sign in to fix a problem with your account. If you "
                 "receive a message like that, forward it to the {team} and delete it. The security "
                 "page lists recent sign-ins with the device and approximate location of each, and "
                 "lets you sign out of any device you do not recognise."),
    "c_status": ("Service status",
                 "The status page shows whether the {name} website, apps and checkout are working "
                 "normally, and lists any problem we are investigating with the time it started and "
                 "the latest update. You can subscribe to the status page by email to hear about "
                 "problems as soon as we post them. After a significant problem, we post a short "
                 "summary of what happened and what we are changing so that it does not happen "
                 "again. If something is not working for you and the status page shows no problem, "
                 "contact the {team}; your report may be the first sign of one."),
    "c_business": ("Buying for an organisation",
                   "Organisations that buy from {name} for several people can pay by invoice "
                   "instead of by card, with payment due within thirty days. An invoice account "
                   "needs a purchase order number or the name of the person who approves payments. "
                   "Organisation accounts have an administrator who can add and remove people, see "
                   "what has been bought, and download every receipt in one file. Tax-exempt "
                   "organisations can upload their exemption certificate from the billing page; once "
                   "it has been checked, taxes are removed from future charges."),
}

OPS = [k for k in PADDING if not k.startswith("c_")]
CUSTOMER = [k for k in PADDING if k.startswith("c_")]
# Padding is added until a document reaches this many words, leaving margin
# above MIN_WORDS so that a small text edit cannot push one below it.
TARGET_WORDS = 1650


def pad(keys, name, team):
    assert len(set(keys)) == len(keys), f"padding repeated: {keys}"
    return [(PADDING[k][0], PADDING[k][1].format(name=name, team=team)) for k in keys]


def finish(title, secs, pool, name, team, seed):
    """Render the document after appending padding sections, drawn from `pool`
    in a seeded order, until it reaches TARGET_WORDS. Headings already in the
    document are skipped, so no section appears twice."""
    rng = random.Random(seed)
    secs = list(secs)
    used = {h for h, _ in secs}
    keys = [k for k in pool if PADDING[k][0] not in used]
    rng.shuffle(keys)
    while words(render(title, secs)) < TARGET_WORDS:
        assert keys, f"{title}: padding pool ran out"
        secs += pad([keys.pop()], name, team)
    return render(title, secs)


def table(header, rows):
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def render(title, sections):
    parts = [f"# {title}"]
    for head, body in sections:
        parts.append(f"## {head}\n\n{body.strip()}")
    return "\n\n".join(parts) + "\n"


def words(text):
    return len(re.findall(r"[A-Za-z0-9]+(?:[.'-][A-Za-z0-9]+)*", text))


def sentences(text):
    return [s for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


DOCS = []


def unanswerable(id, kind, question, doc, *, near, absent=(), only_in=(), no_sentence=(), note):
    """near: strings that must be in the doc. absent: patterns that must not
    match it. only_in: (pattern, passage) pairs; every match must fall inside
    the passage. no_sentence: (topic, value) pattern pairs; no sentence (or
    table row) that matches topic may also match value."""
    DOCS.append(dict(id=id, kind=kind, question=question, doc=doc, gold="NOT_FOUND",
                     near=list(near), absent=list(absent), only_in=list(only_in),
                     no_sentence=list(no_sentence), note=note))


def answerable(id, kind, question, doc, *, gold, surface, distractors, note):
    DOCS.append(dict(id=id, kind=kind, question=question, doc=doc, gold=gold, surface=surface,
                     distractors=list(distractors), note=note))


# ---------------------------------------------------------------- N01 version

def n01():
    rng = random.Random(1501)
    parts = ["presence service", "attachment store", "search indexer", "webhook relay",
             "admin console", "export worker", "conflict resolver", "rate limiter",
             "comment threads", "offline cache", "session manager", "permission checker"]
    fixes = ["no longer drops changes when a client reconnects within a second of disconnecting",
             "logs the tenant identifier with every warning it writes",
             "retries transient storage errors with exponential backoff instead of failing the round",
             "releases file handles promptly after an upload is cancelled",
             "reports its queue depth as a metric",
             "handles document titles longer than 255 characters",
             "returns a clear error instead of a timeout when a tenant is suspended",
             "uses less memory when many small documents are open at once",
             "starts faster after a restart because it loads its index lazily",
             "rejects malformed requests before they reach the storage layer",
             "keeps working when a client's clock is several minutes off",
             "shows timestamps in the operator's configured time zone"]
    pairs = [(p, f) for p in parts for f in fixes]
    rng.shuffle(pairs)
    releases = [
        ("5.0", "2025-03-10", "Feature release that starts the 5.x line.",
         "Introduces sync protocol 3, which replaces the polling protocol used by 4.x clients. "
         "Adds the setting sync.batch_size, which sets how many document changes the server sends "
         "to one client in a single sync round. Its default is 200.",
         "Run qmsync migrate before starting the new server. 4.x clients keep working through a "
         "compatibility bridge, which logs a warning on every connection."),
        ("5.1", "2025-05-19", "Feature release.",
         "Adds per-tenant rate limits for the webhook relay, configured with webhooks.rate_per_minute.",
         "No action needed."),
        ("5.2", "2025-08-04", "Feature release.",
         "Adds read-only share links, which open a document in the web editor without an account.",
         "Share links are off by default; enable them per tenant in the admin console."),
        ("5.3", "2025-10-27", "Feature release.",
         "Raises the default of sync.batch_size from 200 to 250. Deployments that set the value "
         "explicitly keep their own value.",
         "No action needed unless you rely on the old default, in which case set it explicitly "
         "before upgrading."),
        ("5.4", "2026-01-12", "Feature release.",
         "Adds a page to the admin console that lists live client connections per tenant.",
         "No action needed."),
        ("5.5", "2026-03-30", "Feature release.",
         "Adds sync.compression, which compresses sync rounds for slow links. It is off by default.",
         "Clients older than 5.2 ignore compressed rounds, so enable compression only after all "
         "clients are on 5.2 or later."),
        ("5.6", "2026-06-22", "Feature release.",
         "Raises the default of sync.batch_size from 250 to 400, and adds sync.max_inflight, with a "
         "default of 4, which caps how many unacknowledged batches one client may have.",
         "Servers with less than 2 GB of memory per thousand connected clients should set "
         "sync.batch_size back to 250."),
        ("5.6.1", "2026-07-14", "Fix release.",
         "Fixes a memory leak in the presence service that was introduced in 5.6.",
         "No action needed."),
    ]
    secs = [("Introduction",
             "These notes cover every release of Quillmark Sync Server in the 5.x line, oldest "
             "first. Each entry says what kind of release it is, what changed, what was fixed and "
             "what an operator must do when upgrading. Quillmark Sync Server keeps documents edited "
             "in the Quillmark desktop and web editors consistent across devices: clients send "
             "their local changes to the server, and the server sends back the changes made "
             "elsewhere, in rounds. Settings are written in the server configuration file and "
             "take effect after a restart.")]
    k = 0
    for ver, when, kind, change, upgrade in releases:
        n = 3 if kind == "Fix release." else 6
        bullets = "\n".join(f"- The {p} {f}." for p, f in pairs[k:k + n])
        k += n
        secs.append((f"Quillmark Sync Server {ver} ({when})",
                     f"{kind} {change}\n\nFixes:\n\n{bullets}\n\nUpgrading: {upgrade}"))
    secs.append(("Support window",
                 "5.5 and 5.6 receive fix releases. 5.0 to 5.4 receive security fixes only, until "
                 "the end of 2026. Operators on 4.x should move to 5.6.1 directly; the migration "
                 "tool handles every intermediate schema change."))
    secs += pad(["versioning", "deprecation", "support", "feedback"],
                "Quillmark Sync Server", "sync team")
    unanswerable(
        "N01", "version",
        "What is the default value of sync.batch_size in Quillmark Sync Server 5.7?",
        finish("Quillmark Sync Server: release notes, 5.x", secs, OPS,
               "Quillmark Sync Server", "sync team", 2001),
        near=["from 250 to 400"], absent=[r"(?<![\d.])5\.7(?!\d)"],
        note="the notes stop at 5.6.1; 5.6 set the default to 400")


# ---------------------------------------------------------------- N02 version

N02_ROADMAP = ("Brindlewick 3.0 is in early planning. Its compatibility requirements will be "
               "published in this guide together with its first release candidate.")


def n02():
    matrix = table(
        ["Release", "Released", "Python", "PostgreSQL", "Redis", "Status"],
        [["2.4", "2024-11", "3.9 to 3.12", "12 to 16", "6.2 or later", "end of life"],
         ["2.5", "2025-02", "3.9 to 3.12", "12 to 16", "6.2 or later", "end of life"],
         ["2.6", "2025-05", "3.10 to 3.13", "13 to 17", "6.2 or later", "security fixes only"],
         ["2.7", "2025-09", "3.10 to 3.13", "13 to 17", "7.2 or later", "security fixes only"],
         ["2.8", "2026-01", "3.11 to 3.14", "14 to 17", "7.2 or later", "supported"],
         ["2.9", "2026-05", "3.11 to 3.14", "14 to 18", "7.2 or later", "supported"]])
    secs = [
        ("Overview",
         "Brindlewick is an open-source background job queue for Python services. Producers add "
         "jobs to named queues; worker processes take jobs off the queues, run them and record the "
         "result. Brindlewick keeps its job records in PostgreSQL and can use either Redis or "
         "PostgreSQL itself to wake idle workers when new jobs arrive. This guide covers the 2.x "
         "releases: what each one needs, how to install it and how to move between releases."),
        ("Compatibility matrix",
         "The table lists, for every 2.x feature release, the Python, PostgreSQL and Redis "
         "versions it is tested against. Fix releases have the same requirements as the feature "
         "release they belong to, so 2.8.3 needs what 2.8 needs.\n\n" + matrix),
        ("Reading the matrix",
         "A range such as 13 to 17 includes both ends. A version below the range is not supported "
         "and the installer refuses it. A version above the range usually works, but it has not "
         "been tested, and problems found on it are fixed only if they also occur on a tested "
         "version. Redis is needed only when you use it for wake-ups; with PostgreSQL wake-ups the "
         "Redis column does not apply. Status follows the support policy: supported releases get "
         "every fix, releases with security fixes only get those for twelve months after the next "
         "feature release, and end-of-life releases get nothing."),
        ("Installing",
         "Install Brindlewick from the package index into the same environment as the service "
         "that will produce jobs. Then create the schema with brindlewick migrate, pointing it at "
         "the PostgreSQL connection string in BRINDLEWICK_DSN. The command is safe to run more "
         "than once; it applies only the migrations that have not run yet. Start workers with "
         "brindlewick worker, naming the queues each worker should take jobs from. A worker with "
         "no queue names takes jobs from every queue, which is convenient in development but rarely "
         "what you want in production, where slow and fast queues should not share workers."),
        ("Choosing a wake-up backend",
         "Workers that find no jobs sleep until they are woken. With the PostgreSQL backend they "
         "listen for notifications on the job table, which needs no extra service but holds one "
         "database connection per worker. With the Redis backend they block on a Redis list, which "
         "scales to thousands of workers but adds a service to run. Choose PostgreSQL wake-ups for "
         "small deployments and Redis wake-ups when the number of workers would exhaust "
         "connections. The backend can be changed with a restart; no data moves."),
        ("Upgrading within 2.x",
         "Upgrades may skip feature releases. Run brindlewick migrate after installing the new "
         "release and before restarting workers; it applies the schema changes of every skipped "
         "release in order. Workers of the old and new release can run side by side for the length "
         "of a rolling restart, but not longer, because a newer worker may write job records an "
         "older one cannot read. Before upgrading, check the matrix: moving from 2.7 to 2.8 drops "
         "PostgreSQL 13 and Python 3.10, so those must be upgraded first."),
        ("Known issues",
         "2.6: workers can stop taking jobs after a Redis failover until they are restarted; fixed "
         "in 2.6.4. 2.7: the job dashboard shows durations in milliseconds while labelling them as "
         "seconds; fixed in 2.7.2. 2.8: retried jobs keep the priority of their first attempt even "
         "when the producer changes it; this is intended and documented. 2.9: none known."),
        ("Roadmap", N02_ROADMAP),
    ]
    secs += pad(["about", "versioning", "deprecation", "support", "feedback", "training"],
                "Brindlewick", "Brindlewick maintainers")
    unanswerable(
        "N02", "version",
        "What is the minimum PostgreSQL version that Brindlewick 3.0 supports?",
        finish("Brindlewick 2.x: installation and compatibility guide", secs, OPS,
               "Brindlewick", "Brindlewick maintainers", 2002),
        near=["| 2.9 | 2026-05 | 3.11 to 3.14 | 14 to 18 |"],
        only_in=[(r"(?<![\d.])3\.0(?!\d)", N02_ROADMAP)],
        no_sentence=[(r"(?<![\d.])3\.0(?!\d)", r"PostgreSQL \d")],
        note="3.0 is named only as planned; 2.9 needs PostgreSQL 14")


# ------------------------------------------------------------ N03 environment

def n03():
    envs = table(
        ["Setting", "production-us", "production-eu", "staging"],
        [["Gateway replicas", "12", "8", "2"],
         ["Database connection pool size, per replica", "40", "40", "10"],
         ["Upstream processor timeout", "8 seconds", "8 seconds", "15 seconds"],
         ["Settlement cutoff", "22:00 UTC", "20:00 UTC", "none"],
         ["Card data vault region", "us-east", "eu-central", "us-east (test vault)"]])
    secs = [
        ("Purpose",
         "This runbook is for engineers on call for the Ferncastle Payments Gateway. It explains "
         "how the gateway is put together, the settings that differ between environments, the "
         "routine checks made every shift, and what to do first when each alert fires. It does not "
         "replace the incident process: if customers cannot pay, open an incident before you start "
         "working through this runbook."),
        ("Architecture",
         "Merchants call the gateway over HTTPS to authorise, capture and refund card payments. "
         "Each gateway replica is stateless; the state of every payment lives in the payments "
         "database, a PostgreSQL cluster with one writer and two readers per environment. Card "
         "numbers never reach the gateway's own storage: the gateway exchanges them for tokens at "
         "the card data vault, and from then on handles only tokens. Authorisations are forwarded "
         "to an upstream processor, which talks to the card networks. Settlement runs once a day "
         "per environment and sends the day's captured payments to the processor in one batch."),
        ("Environment settings",
         "The table lists the settings that differ between environments. Everything not listed is "
         "the same everywhere and lives in the shared configuration file. Pool sizes are per "
         "replica, so the total number of connections an environment opens is the pool size times "
         "the number of replicas, which must stay below the cluster's connection limit.\n\n" + envs),
        ("Deploying",
         "Deployments roll through one environment at a time: staging first, then production-eu, "
         "then production-us, with at least an hour between environments. Within an environment, "
         "replicas are replaced a quarter at a time, and the deployment pauses automatically if "
         "the error rate of new replicas is more than twice that of old ones. Never deploy within "
         "two hours of an environment's settlement cutoff; a settlement batch that starts while "
         "replicas are being replaced can be sent twice, and the processor rejects the second copy "
         "only after a manual review."),
        ("Routine checks",
         "At the start of each shift, check that yesterday's settlement batch was accepted by the "
         "processor in every production environment, that the payment success rate over the last "
         "hour is above 97 percent, and that no merchant key is within seven days of expiry. Write "
         "the results in the shift log, even when everything is normal, so that the next engineer "
         "can see that the checks were made."),
        ("Alerts and first responses",
         "PoolExhausted fires when replicas wait for a free database connection for more than "
         "five seconds. First check for long-running queries on the writer and cancel any report "
         "query that is holding locks; do not raise the pool size during an incident, because the "
         "cluster's connection limit is shared by every replica. UpstreamTimeouts fires when more "
         "than 2 percent of authorisations time out at the processor. Check the processor's status "
         "page, and if the problem is theirs, switch to the secondary processor with the failover "
         "flag. SettlementLate fires when a settlement batch has not been accepted an hour after "
         "the cutoff. Check the batch status in the admin tool and resend only if the processor "
         "confirms it has no copy."),
        ("Rotating merchant keys",
         "Merchant API keys expire after a year. A merchant can hold two active keys during "
         "rotation. Create the new key in the admin tool, send it to the merchant through the "
         "secure message channel, and wait until the merchant's traffic has moved to it before "
         "revoking the old one. Never send keys by email or chat."),
    ]
    secs += pad(["about", "change", "security", "access", "backups", "glossary"],
                "the Ferncastle Payments Gateway", "payments platform team")
    unanswerable(
        "N03", "environment",
        "What database connection pool size does each Ferncastle gateway replica use in the "
        "production-apac environment?",
        finish("Ferncastle Payments Gateway: operations runbook", secs, OPS,
               "the Ferncastle Payments Gateway", "payments platform team", 2003),
        near=["| Database connection pool size, per replica | 40 | 40 | 10 |"],
        absent=[r"(?i)\bapac\b", r"(?i)\basia", r"(?i)\bpacific\b"],
        note="the runbook covers production-us, production-eu and staging; both production "
             "environments use 40")


# ------------------------------------------------------------ N04 environment

def n04():
    alerts = table(
        ["Alert", "Environment", "Condition", "Action"],
        [["SearchLatencyHigh", "production", "p99 latency above 800 ms for 10 minutes", "page on-call"],
         ["SearchLatencyHigh", "staging", "p99 latency above 1500 ms for 30 minutes", "ticket"],
         ["SearchErrorsHigh", "production", "more than 2% of requests fail for 5 minutes", "page on-call"],
         ["SearchErrorsHigh", "staging", "more than 10% of requests fail for 30 minutes", "ticket"],
         ["IndexLagHigh", "production", "newest indexed document older than 15 minutes", "page on-call"],
         ["IndexLagHigh", "staging", "newest indexed document older than 2 hours", "ticket"]])
    secs = [
        ("Scope",
         "This document sets the service level objectives for the Tallowmere Search API and lists "
         "the alerts that protect them. It covers the public search endpoints and the indexing "
         "pipeline behind them. The internal suggestion service has its own document."),
        ("Service level objectives",
         "Over any rolling 28-day period, 99.9 percent of search requests in production must "
         "succeed, and 99 percent must complete within 600 ms. Requests rejected because a client "
         "exceeded its rate limit count as successes, because the service behaved as designed. "
         "Requests that fail because the client sent a malformed query are excluded from both "
         "objectives. The indexing pipeline must make a newly published document searchable "
         "within 10 minutes in 99 percent of cases."),
        ("Error budget policy",
         "The error budget is the share of requests allowed to fail or run slow under the "
         "objectives. When more than half of the 28-day budget has been spent, the team reviews "
         "upcoming releases and postpones any that carry unusual risk. When the whole budget has "
         "been spent, feature releases stop until the budget recovers, and the team works only on "
         "reliability. The engineering manager can grant an exception for a security fix, and "
         "records the reason in the change record."),
        ("Alerts",
         "The table lists every alert, the environment it watches, the condition that fires it "
         "and what happens when it fires. Paging alerts reach the on-call engineer's phone; ticket "
         "alerts open an item in the request queue for the next business day.\n\n" + alerts),
        ("How paging works",
         "A page is acknowledged within 5 minutes during the day and within 15 minutes at night. "
         "If the on-call engineer does not acknowledge in time, the page goes to the secondary, "
         "and then to the engineering manager. An alert that fires and clears within its own "
         "duration does not page; it is recorded and shown on the dashboard. Repeated pages for "
         "the same alert within an hour are grouped into one."),
        ("Releases and canaries",
         "Every production release first runs as a canary on 5 percent of traffic for 30 "
         "minutes. Canary health is judged by the automated comparison described in the release "
         "guide, which compares the canary with the rest of the fleet and stops the release on its "
         "own if the canary looks worse. The alerts in this document exclude canary instances from "
         "their queries, so a canary never pages through them."),
        ("Reviewing alerts",
         "Each alert is reviewed once a quarter against the pages it sent. An alert that paged "
         "without a real problem more than twice in the quarter is tuned or turned into a ticket "
         "alert. An incident that no alert caught gets a new alert or an explanation of why one is "
         "not possible."),
    ]
    secs += pad(["about", "support", "dashboards", "glossary", "training", "feedback"],
                "the Tallowmere Search API", "search team")
    unanswerable(
        "N04", "environment",
        "At what p99 latency does a canary deployment of the Tallowmere Search API page the "
        "on-call engineer?",
        finish("Tallowmere Search API: service levels and alerting", secs, OPS,
               "the Tallowmere Search API", "search team", 2004),
        near=["p99 latency above 800 ms for 10 minutes"],
        no_sentence=[(r"(?i)canar", r"\d+\s*ms\b")],
        note="thresholds exist for production and staging; canaries are excluded from the alerts")


# ---------------------------------------------------------------- N05 log type

def n05():
    sched = table(
        ["Data", "Retention", "Where it is kept"],
        [["Application logs", "30 days", "log platform"],
         ["Load balancer access logs", "90 days", "archive bucket"],
         ["Admin console audit logs", "400 days", "write-once archive"],
         ["Metrics", "13 months", "metrics store"],
         ["Nightly snapshots of the primary datastore", "35 days", "backup account"],
         ["Support tickets", "3 years after closure", "ticketing system"]])
    secs = [
        ("Purpose and scope",
         "This policy sets how long Corvane Logistics keeps the operational data its shipment "
         "platform produces, and how that data is deleted when the period ends. It applies to "
         "every environment of the platform and to every team that operates part of it. Logs "
         "produced inside the managed database service, including its slow-query, error and "
         "audit logs, are not covered: the hosting provider keeps them under its own service "
         "terms, which Corvane does not control."),
        ("Retention schedule",
         "The table gives the retention period for each kind of data. A period starts when the "
         "record is written, except for support tickets, where it starts when the ticket is "
         "closed.\n\n" + sched),
        ("How retention is enforced",
         "Retention is enforced by the storage systems themselves, not by scheduled clean-up "
         "jobs. The log platform and the archive bucket have lifecycle rules that delete records "
         "when their period ends; the write-once archive refuses deletion before the period ends, "
         "even by administrators. The data platform team checks once a month that every lifecycle "
         "rule matches this schedule and reports any difference as a policy exception."),
        ("Legal holds",
         "When the legal team places a hold, deletion stops for the data the hold names until the "
         "hold is lifted, whatever the schedule says. Holds are applied by the data platform team "
         "on written request from legal, and each hold is recorded with its scope, the date it "
         "started and the person who requested it. When a hold is lifted, normal retention "
         "resumes from the original write date, so data whose period has already passed is "
         "deleted within a week."),
        ("Customer deletion requests",
         "A customer may ask for its shipment records to be deleted when its contract ends. The "
         "request is confirmed in writing, and the records are removed from the primary datastore "
         "within 30 days of confirmation. Copies in nightly snapshots disappear as those snapshots "
         "expire. Records that must be kept for customs or tax purposes are kept for the period "
         "the law requires and are then deleted, and the customer is told which records these "
         "are."),
        ("Exceptions",
         "A team that needs to keep data longer than the schedule allows asks the data platform "
         "team for an exception, giving the data, the extra period and the reason. Exceptions "
         "last at most a year and are listed on the exceptions page, which is reviewed whenever "
         "this policy is reviewed. Keeping data for a shorter period than the schedule is also an "
         "exception, because other teams may rely on it being there."),
        ("Reviewing this policy",
         "The policy is reviewed every year by the data platform team together with legal and "
         "security, and whenever a new kind of data is added to the platform. Proposed changes "
         "are circulated to every team that operates part of the platform at least two weeks "
         "before they take effect."),
    ]
    secs += pad(["about", "security", "access", "backups", "glossary"],
                "the Corvane shipment platform", "data platform team")
    unanswerable(
        "N05", "log type",
        "How long are Corvane's database audit logs retained?",
        finish("Corvane Logistics: data retention policy", secs, OPS,
               "the Corvane shipment platform", "data platform team", 2005),
        near=["| Admin console audit logs | 400 days |"],
        no_sentence=[(r"(?i)database", r"\d+\s*(days?|months?|years?)\b")],
        note="admin console audit logs are kept 400 days; database logs are out of scope")


# ---------------------------------------------------------------- N06 log type

def n06():
    excerpt = "\n".join([
        "gateway 2026-08-12T14:02:41Z POST /labels 202 accepted job=lbl-55120 carrier=northline",
        "gateway 2026-08-12T14:02:44Z POST /labels 202 accepted job=lbl-55121 carrier=northline",
        "worker  2026-08-12T14:03:01Z job=lbl-55120 carrier=northline call started",
        "worker  2026-08-12T14:03:21Z job=lbl-55120 carrier=northline status=timeout after=20s",
        "worker  2026-08-12T14:03:24Z job=lbl-55121 carrier=northline status=timeout after=20s",
        "gateway 2026-08-12T14:05:10Z GET /labels/lbl-55120 200 state=pending",
        "worker  2026-08-12T14:07:12Z job=lbl-55120 retry attempt=1 backoff=240s",
        "worker  2026-08-12T14:07:15Z job=lbl-55121 retry attempt=1 backoff=240s",
        "worker  2026-08-12T14:11:30Z job=lbl-55120 carrier=northline status=429 retry_after=600s",
        "worker  2026-08-12T14:49:02Z job=lbl-55120 carrier=northline status=ok label=issued",
    ])
    actions = table(
        ["Action", "Owner", "Due"],
        [["Read the carrier's rate limit headers and slow down before the limit is reached",
          "label services team", "2026-09-15"],
         ["Alert when the oldest pending label job is older than 10 minutes",
          "label services team", "2026-08-29"],
         ["Subscribe the team to carrier API change announcements", "integrations team",
          "2026-08-22"],
         ["Show warehouse staff an estimated label time on the packing screen",
          "warehouse tools team", "2026-10-01"]])
    secs = [
        ("Summary",
         "On 2026-08-12, shipping labels for the Northline carrier were delayed for up to 47 "
         "minutes. Warehouse staff could pack orders but could not print labels for them, and "
         "1,240 shipments missed their afternoon collection. The cause was a change in Northline's "
         "rate limits that our workers did not respect, so their retries kept the limit exhausted. "
         "No labels were lost and no customer was charged twice."),
        ("Impact",
         "Between 14:02 and 14:49 UTC, label jobs for Northline took between 4 and 47 minutes "
         "instead of the usual few seconds. Labels for other carriers were not affected. Of the "
         "1,240 delayed shipments, 1,108 left on the evening collection and 132 left the next "
         "morning. Customer care received 61 contacts about late tracking numbers."),
        ("Background",
         "Pellbrook Freight creates shipping labels on demand. The warehouse packing screen calls "
         "the API gateway, which records a label job and returns at once. A pool of workers takes "
         "jobs, calls the carrier's API and stores the label. If a carrier call fails, the worker "
         "schedules a retry with a growing delay. A separate scheduler enqueues the nightly reprint "
         "batch for damaged labels and plays no part in creating labels on demand. This review is "
         "based on the gateway logs and the worker logs. The scheduler's logs were not collected, "
         "because the scheduler was not involved."),
        ("Timeline",
         "All times are UTC on 2026-08-12. The excerpt below follows one job, lbl-55120, and one "
         "neighbour through the incident; the full logs are attached to the incident record.\n\n"
         + excerpt + "\n\n"
         "At 14:02 the gateway accepted label jobs as usual. From 14:03 every Northline call timed "
         "out after 20 seconds. Workers scheduled retries four minutes later, and when the retries "
         "ran, Northline answered with status 429, too many requests, and asked callers to wait "
         "ten minutes. Because every worker retried on its own schedule, the combined retries kept "
         "the account over its limit. At 14:31 the on-call engineer paused the Northline queue; "
         "the limit recovered, the queue was resumed at 14:41 at a reduced rate, and the backlog "
         "cleared by 14:49."),
        ("Root cause",
         "Northline lowered the per-account rate limit for label requests on 2026-08-11 and "
         "announced the change on its developer forum, which nobody on the team followed. Our "
         "workers treated status 429 like any other failure and retried on their usual schedule, "
         "ignoring the wait time Northline returned. With many workers retrying independently, "
         "the account never dropped below the new limit long enough to recover."),
        ("What went well",
         "The gateway kept accepting jobs, so no label requests were lost and none had to be "
         "re-entered by hand. Pausing the queue was a single command and took effect at once. "
         "Warehouse leads moved packed orders to the evening collection without waiting to be "
         "asked."),
        ("What went wrong",
         "No alert fired. Our alerts watch the error rate of the gateway, which stayed at zero "
         "because the gateway itself was healthy; nothing watched how long label jobs waited. The "
         "first report came from a warehouse lead by phone, 22 minutes after the delays began. "
         "The retry logic had no special handling for rate limits, a gap noted in a code review "
         "last year and never scheduled."),
        ("Action items", actions),
    ]
    secs += pad(["change", "glossary"], "the label service", "label services team")
    unanswerable(
        "N06", "log type",
        "According to the scheduler logs, at what time (UTC) was the first retry of job "
        "lbl-55120 recorded?",
        finish("Postmortem INC-2291: delayed shipping labels", secs, OPS,
               "the label service", "label services team", 2006),
        near=["14:07:12Z job=lbl-55120 retry attempt=1"],
        no_sentence=[(r"(?i)scheduler", r"\d{2}:\d{2}")],
        note="the worker log records the first retry at 14:07:12; scheduler logs were not "
             "collected")


# -------------------------------------------------------------- N07 table cell

def n07():
    plans = table(
        ["Plan", "Seats", "Forms", "Submissions per month", "API requests per day, monthly billing",
         "API requests per day, annual billing", "File storage"],
        [["Free", "1", "5", "100", "500", "not offered", "1 GB"],
         ["Starter", "3", "50", "2,000", "5,000", "6,000", "10 GB"],
         ["Team", "10", "unlimited", "20,000", "25,000", "30,000", "100 GB"],
         ["Business", "50", "unlimited", "200,000", "100,000", "120,000", "1 TB"]])
    secs = [
        ("Choosing a plan",
         "Larkspur Forms has four plans. Free suits a single person trying the product. Starter "
         "suits a small group that collects a few thousand responses a month, and most new "
         "customers begin there. Team adds unlimited forms and the higher limits that busy "
         "departments need, and Business adds single sign-on, audit history and a named support "
         "contact. Every plan includes the form builder, conditional questions, file uploads and "
         "exports to spreadsheet files."),
        ("Plan limits",
         "The table gives the limits of each plan. Paid plans can be billed monthly or annually, "
         "and annual billing raises the daily API allowance; every other limit is the same however "
         "the plan is billed.\n\n" + plans),
        ("How API limits are counted",
         "API requests are counted per workspace, across every key the workspace has created, and "
         "the count resets at midnight UTC. Requests that fail because of a mistake in the request "
         "itself still count; requests that fail because of a fault on our side do not. Webhook "
         "deliveries from Larkspur to your systems are not API requests and never count."),
        ("What happens at a limit",
         "When a workspace reaches its daily API allowance, further requests are refused with "
         "status 429 until the count resets. When it reaches its monthly submission limit, forms "
         "stay online but show respondents a message that the form is not accepting responses, "
         "and the workspace owner receives an email. Seats and forms cannot go over their limits: "
         "the builder asks the owner to upgrade before adding more. File storage over the limit "
         "blocks new uploads, but existing files stay available."),
        ("Add-on packs",
         "Workspaces on Starter, Team or Business can buy add-on packs instead of moving to a "
         "larger plan. An API pack adds 10,000 requests per day; a submissions pack adds 5,000 "
         "submissions per month; a storage pack adds 50 GB. Packs renew with the plan and can be "
         "removed at the end of any billing period. Free workspaces cannot buy packs."),
        ("Billing and changes of plan",
         "Upgrades take effect at once and are charged pro rata for the rest of the billing "
         "period. Downgrades take effect at the end of the period; if the workspace is over a "
         "limit of the smaller plan by then, the downgrade waits until it is back under. Switching "
         "from monthly to annual billing on the same plan takes effect at the next renewal, and "
         "the higher API allowance starts on that day."),
    ]
    secs += pad(["about", "support", "security", "feedback", "glossary"],
                "Larkspur Forms", "customer success team")
    answerable(
        "N07", "table",
        "On the Larkspur Forms Team plan with annual billing, how many API requests per day does a "
        "workspace get?",
        finish("Larkspur Forms: plans and limits", secs, CUSTOMER,
               "Larkspur Forms", "customer success team", 2007),
        gold=r"(?<![\d,.])30,?000(?![\d,])|\b30k\b|thirty thousand", surface="30,000",
        distractors=["25,000", "120,000", "10,000"],
        note="the Team row of the annual-billing column; monthly billing gives 25,000")


# --------------------------------------------------------------- N08 condition

def n08():
    methods = table(
        ["Method", "Delivery time within the contiguous US", "Cost"],
        [["Standard", "5 business days", "free on orders over $75, otherwise $6.95"],
         ["Expedited", "2 business days", "$18"],
         ["Overnight", "next business day", "$35"]])
    secs = [
        ("Order processing",
         "Orders placed before 1 p.m. Eastern on a business day leave our warehouse the same day. "
         "Orders placed later, or on a weekend or holiday, leave on the next business day. "
         "Delivery times below count from the day the order leaves the warehouse, not from the "
         "day it was placed. Made-to-order items, such as custom-length tent poles, take three "
         "extra business days to prepare, and the product page says so."),
        ("Shipping methods",
         "Choose a method at checkout. The table gives the usual delivery time and cost for each "
         "one.\n\n" + methods),
        ("Restricted items",
         "Some items cannot travel by air. Orders that include lithium batteries, fuel canisters "
         "or bear spray are shipped by ground only, whatever method was chosen at checkout, and "
         "take 8 business days to arrive within the contiguous US. If you paid for expedited or "
         "overnight shipping on such an order, the difference is refunded automatically when the "
         "order ships. To get the other items sooner, place them as a separate order."),
        ("Where we ship",
         "We ship to every address in the contiguous US, including post office boxes for standard "
         "shipping. Orders to Alaska, Hawaii and US territories go by expedited shipping at the "
         "standard price and take 6 to 9 business days; restricted items cannot be sent there. We "
         "do not ship outside the US at present."),
        ("Tracking",
         "You receive a tracking link by email as soon as the order leaves the warehouse. Tracking "
         "can take up to a day to show the first scan. If tracking has not moved for three "
         "business days, contact customer care and we will open a claim with the carrier."),
        ("Returns",
         "Unused items in their original packaging can be returned within 30 days of delivery for "
         "a full refund. Sale items can be returned within 14 days. Return shipping is free for "
         "members of the Oakhollow Trail Club and $6.95 for everyone else, deducted from the "
         "refund. Fuel canisters and bear spray cannot be returned by mail; bring them to a store. "
         "Refunds go back to the original payment method within 5 business days of the return "
         "reaching us."),
        ("Damaged or missing items",
         "If an item arrives damaged, keep the packaging and send us a photo within 7 days of "
         "delivery; we send a replacement at no cost and arrange collection of the damaged item. "
         "If a package shows as delivered but has not arrived, wait one business day, check with "
         "neighbours, and then contact customer care."),
        ("Questions we are often asked",
         "Can I change my shipping method after ordering? Yes, until the order leaves the "
         "warehouse; after that it cannot be changed.\n\n"
         "Can I pick up an online order in a store? Yes, at no charge. Pick-up orders are ready "
         "within two business days, and we email you when they are.\n\n"
         "Do you combine orders? Orders placed within an hour of each other to the same address "
         "are combined when possible, and any extra shipping paid is refunded.\n\n"
         "Do you ship gifts? Yes. Choose gift packaging at checkout, and the packing slip will not "
         "show prices.\n\n"
         "Why did my order arrive in more than one box? Large items ship from our bulk warehouse, "
         "and small items from the main one. Each box gets its own tracking link.\n\n"
         "Can I return a used tent? Used items cannot be returned for a refund, but they are "
         "covered by the manufacturer's warranty, and customer care can help you file a claim."),
        ("Contacting customer care",
         "Customer care answers by chat and email from 8 a.m. to 8 p.m. Eastern, seven days a "
         "week, and by phone on business days. Have your order number ready; it is in the "
         "confirmation email and in your account."),
    ]
    answerable(
        "N08", "condition",
        "An Oakhollow order contains a tent and a spare lithium battery pack, is placed with "
        "standard shipping, and goes to an address in the contiguous US. How many business days "
        "should delivery take once it leaves the warehouse?",
        finish("Oakhollow Outdoor Supply: shipping and returns", secs, CUSTOMER,
               "Oakhollow Outdoor Supply", "customer care team", 2008),
        gold=r"(?<![\d.])8(?![\d.])|\beight\b", surface="8 business days",
        distractors=["5 business days", "2 business days"],
        note="the restricted-items rule overrides the standard-shipping row")


# ---------------------------------------------------------------- N09 footnote

def n09():
    plans = table(
        ["Feature", "Free", "Plus", "Pro"],
        [["Storage", "15 GB", "200 GB", "2 TB"],
         ["Largest single file", "5 GB [1]", "5 GB", "50 GB"],
         ["Version history", "30 days", "90 days", "1 year [2]"],
         ["Shared links", "yes", "yes", "yes, with expiry dates and passwords"],
         ["Offline folders", "none", "10", "unlimited"],
         ["Devices signed in at once", "3", "10", "unlimited"]])
    notes = ("[1] On the Free plan, files uploaded through the web app are limited to 750 MB "
             "each. The desktop and mobile apps allow the full 5 GB on every plan.\n\n"
             "[2] Pro keeps version history for one year or until the account's storage is full, "
             "whichever comes first. When storage is full, the oldest versions are removed first.")
    secs = [
        ("Plans at a glance",
         "Nimbrel Cloud Drive has three plans. Free is for personal use with modest storage. Plus "
         "adds storage and offline folders for people who work across several devices. Pro is for "
         "professionals with large files and long project histories. Every plan includes "
         "automatic sync, file previews in the browser, and apps for desktop and mobile.\n\n"
         + plans + "\n\n" + notes),
        ("Storage and file sizes",
         "Storage counts every file you own, including old versions on plans that keep them, but "
         "not files that others have shared with you. When you reach your storage limit, sync "
         "stops uploading new files and the apps show a notice; nothing already stored is "
         "deleted. Uploads larger than a plan allows are refused before they start, so you do not "
         "wait for a large upload only to see it fail."),
        ("Sharing",
         "You can share a file or folder with specific people, who need a Nimbrel account, or "
         "through a link that anyone with the link can open. Links can be view-only or allow "
         "editing. On Pro, links can also expire on a date you choose or require a password. You "
         "can see every link you have created on the sharing page and turn off any of them at "
         "once."),
        ("Version history and recovery",
         "Every time a file changes, Nimbrel keeps the previous version for the period your plan "
         "allows. You can open any kept version, restore it, or download it as a separate file. "
         "Deleted files go to the bin, where they stay for 30 days on every plan before they are "
         "removed for good. Restoring a folder from the bin restores everything that was in it."),
        ("Desktop and mobile apps",
         "The desktop app keeps a folder on your computer in sync with your drive. You can choose "
         "which folders to sync, so that a small laptop does not fill up. The mobile app shows "
         "your whole drive and can upload photos automatically. Offline folders, on Plus and Pro, "
         "are kept on the device so that they open without a connection, and changes made offline "
         "sync when the device reconnects."),
        ("Security",
         "Files are encrypted in transit and at rest. You can turn on two-step sign-in in your "
         "account settings, and we strongly recommend it. The account page lists every device "
         "signed in to your account, and you can sign any of them out remotely. Nimbrel staff "
         "cannot open your files unless you share them with support for a specific request."),
        ("Changing plans",
         "You can upgrade at any time, and the new limits apply at once. If you downgrade and "
         "your files exceed the smaller plan's storage, nothing is deleted, but sync stops "
         "uploading until you are under the limit. Version history beyond the smaller plan's "
         "period is removed thirty days after the downgrade, which gives you time to restore "
         "anything you need."),
    ]
    secs += pad(["about", "support", "deprecation", "feedback"],
                "Nimbrel Cloud Drive", "Nimbrel support team")
    answerable(
        "N09", "footnote",
        "What is the largest single file a Nimbrel Cloud Drive Free plan user can upload through "
        "the web app?",
        finish("Nimbrel Cloud Drive: plan comparison", secs, CUSTOMER,
               "Nimbrel Cloud Drive", "Nimbrel support team", 2009),
        gold=r"(?<![\d.])750\s*(mb|megabytes?)\b", surface="750 MB",
        distractors=["5 GB", "50 GB"],
        note="the table cell says 5 GB; its footnote limits web uploads on Free to 750 MB")


# ------------------------------------------------------ N10 footnote, condition

def n10():
    windows = table(
        ["Region", "Weekly window (UTC)", "Notice given"],
        [["US-East", "Sunday 06:00 to 08:00", "5 days"],
         ["US-West", "Sunday 09:00 to 11:00 [1]", "5 days"],
         ["EU-West", "Sunday 02:00 to 04:00 [2]", "5 days"],
         ["AP-South", "Saturday 20:00 to 22:00", "7 days"]])
    notes = ("[1] US-West windows may run up to 30 minutes over when a storage firmware update is "
             "included. The notice says when this applies.\n\n"
             "[2] From the last Sunday in March to the last Sunday in October, the EU-West window "
             "starts an hour earlier, at 01:00 UTC, and ends at 03:00 UTC, so that it stays at the "
             "same local time all year.")
    secs = [
        ("What maintenance covers",
         "Gildercrest Hosting applies operating system patches, hypervisor updates and network "
         "changes to its regions during scheduled maintenance windows. Most maintenance causes no "
         "interruption, because virtual machines are moved to updated hosts while they keep "
         "running. Some changes need a restart: when they do, the restart happens inside the "
         "window and the notice lists the affected machines."),
        ("Weekly windows",
         "Each region has one weekly window, chosen to fall in the quiet hours of the region's "
         "customers. The table gives each window in UTC and how far ahead maintenance in it is "
         "announced.\n\n" + windows + "\n\n" + notes),
        ("Notice and notifications",
         "Maintenance that may affect your machines is announced by email to the account's "
         "technical contacts and on the status page, with the notice period shown in the table. "
         "The notice names the region, the window, the kind of change, and the machines that "
         "will restart, if any. If a window is not needed in a given week, no notice is sent and "
         "nothing happens."),
        ("During a window",
         "Live migration pauses a machine for less than a second, which most applications do not "
         "notice. Machines that need a restart are stopped cleanly, restarted on an updated host "
         "and returned to the state they were in. Load balancers drain traffic from a machine "
         "before it restarts if the machine is in a health-checked pool. The status page shows "
         "progress while a window is under way and marks it complete when it ends."),
        ("Emergency maintenance",
         "A security problem that is being exploited, or a fault that threatens customer data, "
         "may need maintenance outside the weekly windows. Emergency maintenance is announced as "
         "early as possible, at least one hour ahead when that is safe, and the announcement "
         "explains why it could not wait for the next window."),
        ("Deferring maintenance",
         "Customers on the Enterprise plan can defer a scheduled restart of their machines once "
         "per quarter, by up to seven days, from the maintenance page. A deferred restart happens "
         "in the region's next window. Security updates cannot be deferred."),
    ]
    secs += pad(["about", "support", "change", "glossary", "feedback"],
                "Gildercrest Hosting", "infrastructure operations team")
    answerable(
        "N10", "footnote",
        "In July, at what time (UTC) does the Gildercrest Hosting EU-West maintenance window "
        "start?",
        finish("Gildercrest Hosting: scheduled maintenance", secs, OPS,
               "Gildercrest Hosting", "infrastructure operations team", 2010),
        gold=r"(?<![\d:])0?1:00(?!\d)|\b1\s*a\.?m\b", surface="01:00 UTC",
        distractors=["02:00", "03:00", "06:00", "20:00"],
        note="the table cell says 02:00; its footnote moves the window to 01:00 in summer")


for _build in (n01, n02, n03, n04, n05, n06, n07, n08, n09, n10):
    _build()


def check(d):
    did, doc = d["id"], d["doc"]
    n = words(doc)
    assert MIN_WORDS <= n <= MAX_WORDS, f"{did}: {n} words"
    if d["gold"] == "NOT_FOUND":
        assert d["near"], f"{did}: no near miss named"
        for s in d["near"]:
            assert s in doc, f"{did}: near miss {s!r} missing"
        for rx in d["absent"]:
            m = re.search(rx, doc)
            assert not m, f"{did}: asked fact present: {rx} matched {m.group()!r}"
        for rx, passage in d["only_in"]:
            assert passage in doc, f"{did}: passage missing"
            assert len(re.findall(rx, doc)) == len(re.findall(rx, passage)), \
                f"{did}: {rx} matches outside its passage"
        for topic, value in d["no_sentence"]:
            bad = [s for s in sentences(doc) if re.search(topic, s) and re.search(value, s)]
            assert not bad, f"{did}: sentence states the asked fact: {bad[0]!r}"
        assert d["absent"] or d["only_in"] or d["no_sentence"], f"{did}: absence never checked"
    else:
        assert d["surface"] in doc, f"{did}: answer {d['surface']!r} not in the document"
        assert re.search(d["gold"], d["surface"].lower()), f"{did}: gold rejects its own surface"
        for w in d["distractors"]:
            assert w in doc, f"{did}: distractor {w!r} not in the document"
            assert not re.search(d["gold"], w.lower()), f"{did}: gold accepts distractor {w!r}"
    return n


def items() -> list[dict]:
    out = []
    for d in DOCS:
        n = check(d)
        task = (f"{d['question']}\n\nAnswer from the document only. If it does not contain the "
                "answer, answer NOT_FOUND."
                + json_contract('{"answer": "<the answer, or NOT_FOUND>"}'))
        extra = dict(answerable=d["gold"] != "NOT_FOUND", kind=d["kind"], words=n, note=d["note"])
        if extra["answerable"]:
            extra.update(surface=d["surface"], distractors=d["distractors"])
        else:
            extra.update(near_miss=d["near"])
        out.append(item(d["id"], CAT, task, d["gold"], "nearmiss", context=d["doc"],
                        task_type="ask", tags=("nearmiss", d["kind"]), **extra))
    assert len(out) == 10, len(out)
    assert sum(not it["answerable"] for it in out) == 6, "DESIGN.md: 6 of 10 unanswerable"
    return out


if __name__ == "__main__":
    for it in items():
        print(it["id"], it["kind"], it["words"], "words,", "gold:", it["gold"])
