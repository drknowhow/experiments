"""thread-supersede: pull the final agreed values out of an email thread or a
group chat of 8-20 messages in which later messages change, withdraw or quote
earlier values, and some proposals are never accepted.

Every message carries the operations it performs, and gold comes from
applying them in order, never from reading the rendered text:

    D(field, value, surface)        the organizer decides a value
    P(pid, field, value, surface)   someone proposes a value; it binds only if accepted
    A(pid, surface)                 the other side (or the organizer) accepts proposal pid
    R(pid)                          proposal pid is turned down or replaced by a counter-offer
    W(field)                        a settled value is withdrawn with nothing in its place

`surface` is how the value is written in that message's body. The build
asserts that every surface appears in its message body and fits its value
(so each final value appears in the message that set it), that only open
proposals are accepted or turned down, that at least two fields per thread
had their settled value change after it was first settled (to another value,
or withdrawn), that every field whose gold is null was stated at some point,
so a null is never just "the thread never mentions it", and that every
weekday named next to a date is that date's weekday."""
from __future__ import annotations

import calendar
import re
from datetime import date, datetime

from common import item, json_contract

CAT = "thread-supersede"
THREADS = []

KIND_FORMAT = {"date": "YYYY-MM-DD", "time": "HH:MM, 24-hour", "int": "integer",
               "money": "number, in dollars", "number": "number", "text": "text",
               "bool": "true or false"}
KIND_SHAPE = {"date": '"YYYY-MM-DD"', "time": '"HH:MM"', "int": "integer", "money": "number",
              "number": "number", "text": '"text"', "bool": "true or false"}


def D(field, value, surface):
    return ("decide", field, value, surface)


def P(pid, field, value, surface):
    return ("propose", pid, field, value, surface)


def A(pid, surface):
    return ("accept", pid, surface)


def R(pid):
    return ("reject", pid)


def W(field):
    return ("withdraw", field)


def M(who, at, body, *ops, quote=None):
    return {"who": who, "at": at, "body": body, "ops": list(ops), "quote": quote}


def thread(id, kind, today, subject, people, rule, fields, messages, *, tags=()):
    THREADS.append(dict(id=id, kind=kind, today=today, subject=subject, people=people,
                        rule=rule, fields=fields, messages=messages, tags=tags))


def organizer(full, short):
    return (f"{full} is organizing and decides. A value is decided when {short} states it "
            f"or agrees to someone's suggestion; a suggestion {short} has not agreed to does "
            f"not count. When {short} withdraws a decided value without deciding a new one, "
            "that field is null.")


def negotiation(a, b):
    return (f"{a} and {b} are negotiating. A term is agreed when one of them offers it and "
            "the other accepts it; a counter-offer replaces the offer it answers, and an "
            "offer nobody has accepted does not count. An agreed term stays agreed until "
            "they agree a new value, or until it is withdrawn with nothing agreed in its "
            "place, which makes that field null.")


# --------------------------------------------------------------------------
# T01  team offsite (email, organizer)
# --------------------------------------------------------------------------
thread("T01", "email", "2026-10-30", "Team offsite",
       {"Mara Lindqvist": "mara.lindqvist", "Dev Okafor": "dev.okafor", "Lena Varga": "lena.varga",
        "Priya Nair": "priya.nair"},
       organizer("Mara Lindqvist", "Mara"),
       {"date": ("date", "date of the offsite"),
        "venue": ("text", "name of the venue"),
        "headcount": ("int", "number of people planned for"),
        "budget_per_person": ("money", "approved budget per person"),
        "caterer": ("text", "name of the caterer"),
        "start_time": ("time", "start time")},
       [M("Mara Lindqvist", "2026-10-19 09:05",
          "Hi all, the team offsite is set for Friday, November 20. I'm planning for 18 people "
          "and finance approved $85 per person, food included. Venue and caterer ideas welcome.",
          D("date", "2026-11-20", "November 20"), D("headcount", 18, "18 people"),
          D("budget_per_person", 85, "$85")),
        M("Dev Okafor", "2026-10-19 10:41",
          "What about the Harbor Room at Pier 9? It seats 25 and has a projector.",
          P("p1", "venue", "Harbor Room", "Harbor Room")),
        M("Lena Varga", "2026-10-19 13:12",
          "Foundry Loft is nicer and closer to the train. For food, Saffron & Salt did the "
          "spring party and people liked them.",
          P("p2", "venue", "Foundry Loft", "Foundry Loft"),
          P("p3", "caterer", "Saffron & Salt", "Saffron & Salt")),
        M("Mara Lindqvist", "2026-10-20 08:30",
          "Harbor Room is booked that week, so let's take Foundry Loft. Lena, I'll get a price "
          "from Saffron & Salt before deciding on food.",
          R("p1"), A("p2", "Foundry Loft")),
        M("Dev Okafor", "2026-10-20 11:02",
          "Heads up: two contractors from the design agency want to join, which would make us 20.",
          P("p4", "headcount", 20, "20")),
        M("Mara Lindqvist", "2026-10-21 09:15",
          "Yes, include the contractors: plan for 20. Saffron & Salt's quote came in fine, so "
          "they're booked. Let's start at 9:30.",
          A("p4", "plan for 20"), A("p3", "Saffron & Salt"), D("start_time", "09:30", "9:30")),
        M("Lena Varga", "2026-10-21 09:48",
          "Is the $85 still right now that we're 20?", quote=1),
        M("Mara Lindqvist", "2026-10-22 16:20",
          "Finance trimmed it: $70 per person is the new budget.",
          D("budget_per_person", 70, "$70")),
        M("Priya Nair", "2026-10-23 08:02",
          "Could we start at 10:00 instead? The first train from the north side gets in at 9:40.",
          P("p5", "start_time", "10:00", "10:00")),
        M("Mara Lindqvist", "2026-10-23 12:30",
          "Fair point. 10:00 start.",
          A("p5", "10:00")),
        M("Dev Okafor", "2026-10-26 14:55",
          "Foundry Loft just called. They double-booked the 20th and offered us November 27 instead.",
          P("p6", "date", "2026-11-27", "November 27")),
        M("Mara Lindqvist", "2026-10-26 17:10",
          "We can't move the date, it's tied to the quarter close. I've cancelled the Foundry "
          "Loft booking, so we have no venue for now. I'll look again on Monday.",
          R("p6"), W("venue")),
        M("Lena Varga", "2026-10-27 10:05",
          "Saffron & Salt says they can do it for $65 a head if that helps."),
        M("Priya Nair", "2026-10-28 09:20",
          "Should I send everyone directions to Foundry Loft?", quote=4)],
       tags=("organizer", "withdrawn", "quote"))

# --------------------------------------------------------------------------
# T02  kitchen remodel quote (email, negotiation)
# --------------------------------------------------------------------------
thread("T02", "email", "2026-11-12", "Kitchen remodel quote",
       {"Kofi Mensah": "kofi", "Ruth Adeyemi": "ruth.adeyemi"},
       negotiation("Ruth Adeyemi (the homeowner)", "Kofi Mensah (the contractor)"),
       {"start_date": ("date", "date work starts"),
        "total_price": ("money", "total price"),
        "deposit": ("money", "deposit paid at signing"),
        "countertop": ("text", "countertop material"),
        "duration_weeks": ("int", "length of the job in weeks"),
        "permit_fee_paid_by": ("text", "who pays the county permit fee: \"homeowner\" or \"contractor\"")},
       [M("Kofi Mensah", "2026-11-02 08:10",
          "Ruth, here is our quote: quartz countertops, $38,500 all in, start January 11, about "
          "6 weeks of work. We take a 30% deposit, $11,550, at signing.",
          P("q1", "countertop", "quartz", "quartz"), P("q2", "total_price", 38500, "$38,500"),
          P("q3", "start_date", "2027-01-11", "January 11"), P("q4", "duration_weeks", 6, "6 weeks"),
          P("q5", "deposit", 11550, "$11,550")),
        M("Ruth Adeyemi", "2026-11-02 19:44",
          "Thanks Kofi. January 11 works and quartz is what we wanted. $38,500 is over our "
          "budget though. Could you do $35,000?",
          A("q3", "January 11"), A("q1", "quartz"), R("q2"), P("q6", "total_price", 35000, "$35,000")),
        M("Kofi Mensah", "2026-11-03 07:58",
          "I can get to $36,800 if we use the stock cabinet hardware. The deposit stays 30%, "
          "so $11,040.",
          R("q6"), P("q7", "total_price", 36800, "$36,800"), R("q5"),
          P("q8", "deposit", 11040, "$11,040")),
        M("Ruth Adeyemi", "2026-11-03 21:15",
          "$36,800 with the stock hardware is fine. On the deposit, could we pay $8,000 at "
          "signing and the rest when the cabinets go in?",
          A("q7", "$36,800"), R("q8"), P("q9", "deposit", 8000, "$8,000")),
        M("Kofi Mensah", "2026-11-04 09:30",
          "$8,000 at signing is okay. One more thing: with the holiday backlog, plan on 7 "
          "weeks, not 6.",
          A("q9", "$8,000"), R("q4"), P("q10", "duration_weeks", 7, "7 weeks")),
        M("Ruth Adeyemi", "2026-11-04 12:02",
          "7 weeks is fine. Who pulls the permit and pays the county fee?",
          A("q10", "7 weeks")),
        M("Kofi Mensah", "2026-11-05 08:45",
          "We pull it. The fee is normally passed through to the homeowner.",
          P("q11", "permit_fee_paid_by", "homeowner", "homeowner")),
        M("Ruth Adeyemi", "2026-11-05 18:20",
          "I'd rather the fee was in your price, so the contractor pays it.",
          R("q11"), P("q12", "permit_fee_paid_by", "contractor", "contractor")),
        M("Kofi Mensah", "2026-11-06 10:12",
          "Let me check with the office on that."),
        M("Ruth Adeyemi", "2026-11-08 15:33",
          "We looked at samples this weekend and now prefer soapstone over quartz. What would "
          "that do to the price?",
          P("q13", "countertop", "soapstone", "soapstone")),
        M("Kofi Mensah", "2026-11-09 08:05",
          "Soapstone adds $1,900 and the fabricator needs two more weeks. So: soapstone, "
          "$38,700 total, 9 weeks.",
          R("q13"), P("q14", "countertop", "soapstone", "soapstone"),
          P("q15", "total_price", 38700, "$38,700"), P("q16", "duration_weeks", 9, "9 weeks")),
        M("Ruth Adeyemi", "2026-11-09 20:40",
          "OK, let's do it: soapstone, $38,700, 9 weeks. Could we also push the start to "
          "January 18? We're away the week of the 11th.",
          A("q14", "soapstone"), A("q15", "$38,700"), A("q16", "9 weeks"),
          P("q17", "start_date", "2027-01-18", "January 18"), quote=11),
        M("Kofi Mensah", "2026-11-10 07:50",
          "Got it, I'll ask the crew about the 18th. The office still hasn't decided on the "
          "permit fee; I'll come back to you on both.")],
       tags=("negotiation", "bundle", "pending-at-end"))

# --------------------------------------------------------------------------
# T03  band rehearsal (chat, organizer)
# --------------------------------------------------------------------------
thread("T03", "chat", "2026-11-05", "Band chat",
       {"Tomás Rivera": "", "Ines Calder": "", "Kwame Asante": "", "Lars Holm": ""},
       organizer("Tomás Rivera", "Tomás"),
       {"date": ("date", "rehearsal date"),
        "start_time": ("time", "rehearsal start time"),
        "room": ("text", "studio room"),
        "pa_brought_by": ("text", "first name of the person bringing the PA speaker"),
        "set_length": ("int", "number of songs in the set")},
       [M("Tomás Rivera", "2026-11-01 18:02",
          "Rehearsal this week is Saturday the 7th, 2pm, Room B at Soundcheck Studios. Let's "
          "run a 12-song set.",
          D("date", "2026-11-07", "Saturday the 7th"), D("start_time", "14:00", "2pm"),
          D("room", "Room B", "Room B"), D("set_length", 12, "12-song")),
        M("Ines Calder", "2026-11-01 18:10",
          "Can we do 3 instead of 2? I'm at my sister's until 2:30.",
          P("b1", "start_time", "15:00", "3 instead of 2")),
        M("Tomás Rivera", "2026-11-01 18:31", "Sure, 3pm then.", A("b1", "3pm")),
        M("Kwame Asante", "2026-11-02 09:00",
          "Who's bringing the PA? Kwame here, I can if someone helps me load it.",
          P("b2", "pa_brought_by", "Kwame", "Kwame")),
        M("Tomás Rivera", "2026-11-02 09:15", "Thanks Kwame, you're on PA.", A("b2", "Kwame")),
        M("Ines Calder", "2026-11-03 20:22",
          "Studio says Room B has a broken monitor this week. Room D is free at 3.",
          P("b3", "room", "Room D", "Room D")),
        M("Tomás Rivera", "2026-11-03 20:40", "Ugh. OK, Room D.", A("b3", "Room D")),
        M("Kwame Asante", "2026-11-04 07:55",
          "Bad news, my car's in the shop Saturday, so I can't bring the PA after all."),
        M("Tomás Rivera", "2026-11-04 08:10",
          "No worries. The PA is open again, anyone? Also let's cut the set to 10 songs, we're "
          "short on time.",
          W("pa_brought_by"), D("set_length", 10, "10 songs")),
        M("Ines Calder", "2026-11-04 08:30",
          "Wait, is it still Room B? That's what the calendar invite says.", quote=1),
        M("Tomás Rivera", "2026-11-04 08:42", "No, Room D. Ignore the invite, I'll fix it."),
        M("Lars Holm", "2026-11-04 12:15",
          "Lars here: I might be able to borrow my brother's PA, I'll know tonight.",
          P("b4", "pa_brought_by", "Lars", "Lars"))],
       tags=("organizer", "withdrawn", "quote", "chat"))

# --------------------------------------------------------------------------
# T04  software contract (email, negotiation)
# --------------------------------------------------------------------------
thread("T04", "email", "2026-12-03", "Cobalt Analytics renewal",
       {"Marcus Bell": "marcus.bell", "Hana Sato": "hana.sato"},
       negotiation("Hana Sato (the buyer)", "Marcus Bell (the vendor)"),
       {"seats": ("int", "number of seats"),
        "price_per_seat": ("money", "price per seat per month"),
        "term_months": ("int", "contract term in months"),
        "start_date": ("date", "contract start date"),
        "payment_terms": ("text", "payment terms, such as \"net 15\""),
        "uptime_sla": ("number", "uptime commitment, in percent")},
       [M("Marcus Bell", "2026-11-16 10:30",
          "Hana, following our call: 150 seats at $42 per seat per month, a 24-month term "
          "starting January 1, payment net 30, and a 99.5% uptime SLA.",
          P("c1", "seats", 150, "150 seats"), P("c2", "price_per_seat", 42, "$42"),
          P("c3", "term_months", 24, "24-month"), P("c4", "start_date", "2027-01-01", "January 1"),
          P("c5", "payment_terms", "net 30", "net 30"), P("c6", "uptime_sla", 99.5, "99.5%")),
        M("Hana Sato", "2026-11-17 09:12",
          "Thanks Marcus. Net 30 and January 1 are fine. We'd want 99.9% uptime, and $42 is "
          "high for 150 seats. Would you do $36?",
          A("c5", "Net 30"), A("c4", "January 1"), R("c6"), P("c7", "uptime_sla", 99.9, "99.9%"),
          R("c2"), P("c8", "price_per_seat", 36, "$36")),
        M("Marcus Bell", "2026-11-18 14:05",
          "I can do $39 if the term is 36 months.",
          R("c8"), P("c9", "price_per_seat", 39, "$39"), R("c3"), P("c10", "term_months", 36, "36 months")),
        M("Hana Sato", "2026-11-19 08:40",
          "36 months is too long for us. Keep 24 months and I'd go to $38.",
          R("c10"), P("c11", "term_months", 24, "24 months"), R("c9"),
          P("c12", "price_per_seat", 38, "$38")),
        M("Marcus Bell", "2026-11-20 11:20",
          "$38 on 24 months works. On uptime, 99.9% needs our premium tier; I can offer 99.8%.",
          A("c12", "$38"), A("c11", "24 months"), R("c7"), P("c13", "uptime_sla", 99.8, "99.8%")),
        M("Hana Sato", "2026-11-21 16:02", "99.8% is acceptable.", A("c13", "99.8%")),
        M("Hana Sato", "2026-11-24 09:30",
          "Update: finance wants to start smaller, 120 seats, with an option to add more later.",
          R("c1"), P("c14", "seats", 120, "120 seats")),
        M("Marcus Bell", "2026-11-24 15:45",
          "120 seats is fine, but at 120 the price goes back to $40.",
          R("c14"), P("c15", "seats", 120, "120 seats"), P("c16", "price_per_seat", 40, "$40")),
        M("Hana Sato", "2026-11-25 10:10",
          "Then let's meet at $39 for 120 seats.",
          R("c15"), R("c16"), P("c17", "seats", 120, "120 seats"), P("c18", "price_per_seat", 39, "$39")),
        M("Marcus Bell", "2026-11-26 09:00", "Deal: 120 seats at $39.",
          A("c17", "120 seats"), A("c18", "$39")),
        M("Hana Sato", "2026-11-27 13:25",
          "Our legal team asks for net 45 instead of net 30.",
          P("c19", "payment_terms", "net 45", "net 45")),
        M("Marcus Bell", "2026-11-28 08:15",
          "Net 45 needs approval from our finance team. I'll come back to you."),
        M("Hana Sato", "2026-11-30 17:40",
          "Also, we'd like to start February 1 rather than January 1. Our rollout slipped.",
          P("c20", "start_date", "2027-02-01", "February 1")),
        M("Marcus Bell", "2026-12-01 09:05", "February 1 is fine.", A("c20", "February 1")),
        M("Marcus Bell", "2026-12-02 11:50",
          "Finance came back: they can't approve net 45. They would accept net 40.",
          R("c19"), P("c21", "payment_terms", "net 40", "net 40"), quote=11),
        M("Hana Sato", "2026-12-02 14:30",
          "Let me check net 40 with legal and get back to you.")],
       tags=("negotiation", "bundle", "pending-at-end"))

# --------------------------------------------------------------------------
# T05  wedding photographer (email, negotiation)
# --------------------------------------------------------------------------
thread("T05", "email", "2026-09-05", "Photography for June 12",
       {"Jules Moreau": "jules", "Ana Petrov": "ana.petrov"},
       negotiation("Ana Petrov (the client)", "Jules Moreau (the photographer)"),
       {"coverage_hours": ("int", "hours of coverage"),
        "package_price": ("money", "package price"),
        "second_shooter": ("bool", "whether a second shooter is included"),
        "delivery_weeks": ("int", "weeks until the gallery is delivered"),
        "deposit_due": ("date", "date the deposit is due")},
       [M("Jules Moreau", "2026-08-20 18:30",
          "Hi Ana, for June 12 I'd suggest 8 hours of coverage for $4,200, with a second "
          "shooter included and the gallery delivered in 6 weeks. I'd need the deposit by "
          "September 1 to hold the date.",
          P("w1", "coverage_hours", 8, "8 hours"), P("w2", "package_price", 4200, "$4,200"),
          P("w3", "second_shooter", True, "second shooter included"),
          P("w4", "delivery_weeks", 6, "6 weeks"), P("w5", "deposit_due", "2026-09-01", "September 1")),
        M("Ana Petrov", "2026-08-21 21:02",
          "That all works: 8 hours, $4,200, the second shooter, 6 weeks, and the deposit by "
          "September 1. Let's book it!",
          A("w1", "8 hours"), A("w2", "$4,200"), A("w3", "second shooter"), A("w4", "6 weeks"),
          A("w5", "September 1")),
        M("Ana Petrov", "2026-08-24 10:15",
          "Our budget came in tighter than we hoped. Could we do 6 hours instead, to bring "
          "the price down?",
          P("w6", "coverage_hours", 6, "6 hours")),
        M("Jules Moreau", "2026-08-25 09:40",
          "6 hours would be $3,500, still with the second shooter.",
          R("w6"), P("w7", "coverage_hours", 6, "6 hours"), P("w8", "package_price", 3500, "$3,500")),
        M("Ana Petrov", "2026-08-25 19:15",
          "Yes to 6 hours at $3,500. Is 6 weeks firm for delivery? We'd love it sooner.",
          A("w7", "6 hours"), A("w8", "$3,500")),
        M("Jules Moreau", "2026-08-26 08:05", "I can do 4 weeks for delivery.",
          P("w9", "delivery_weeks", 4, "4 weeks")),
        M("Ana Petrov", "2026-08-26 19:30", "Perfect, 4 weeks.", A("w9", "4 weeks")),
        M("Ana Petrov", "2026-08-29 10:20",
          "Small change: my brother does photography and wants to shoot candids, so we don't "
          "need a second shooter. Can you take that off?",
          P("w10", "second_shooter", False, "don't need a second shooter")),
        M("Jules Moreau", "2026-08-30 08:45",
          "Sure, no second shooter. That brings it to $3,100.",
          R("w10"), P("w11", "second_shooter", False, "no second shooter"),
          P("w12", "package_price", 3100, "$3,100")),
        M("Ana Petrov", "2026-08-30 20:10",
          "Hmm, let me talk it over with Petra first. She liked having the second shooter."),
        M("Ana Petrov", "2026-09-03 18:55",
          "We paid the deposit today, sorry it's a few days late! Still deciding on the "
          "second shooter.", quote=9)],
       tags=("negotiation", "pending-at-end", "quote", "bool"))

# --------------------------------------------------------------------------
# T06  product launch (chat, organizer)
# --------------------------------------------------------------------------
thread("T06", "chat", "2026-10-08", "#lumen-launch",
       {"Sunita Rao": "", "Dario Ferri": "", "Mei Tan": "", "Noor Aziz": "", "Jin Park": ""},
       organizer("Sunita Rao, the release manager,", "Sunita"),
       {"launch_date": ("date", "launch date"),
        "version": ("text", "version number that ships"),
        "first_region": ("text", "region that gets the launch first"),
        "rollback_owner": ("text", "first name of the rollback owner"),
        "embargo_time": ("time", "time the press embargo lifts, UTC")},
       [M("Sunita Rao", "2026-09-28 10:00",
          "Plan for Lumen 2.4: launch Tuesday, October 13, version 2.4.0, first region "
          "eu-west, rollback owner is Dario. Press embargo lifts 14:00 UTC.",
          D("launch_date", "2026-10-13", "October 13"), D("version", "2.4.0", "2.4.0"),
          D("first_region", "eu-west", "eu-west"), D("rollback_owner", "Dario", "Dario"),
          D("embargo_time", "14:00", "14:00 UTC")),
        M("Dario Ferri", "2026-09-28 10:20",
          "I'm on vacation the 12th to the 16th, can someone else take rollback?"),
        M("Sunita Rao", "2026-09-28 10:45",
          "Right, sorry. Dario is off rollback then. Mei, could you take it?",
          W("rollback_owner")),
        M("Mei Tan", "2026-09-28 11:02", "I can take it if Noor covers my on-call that week."),
        M("Noor Aziz", "2026-09-28 11:30", "I can't cover on-call that week, sorry."),
        M("Sunita Rao", "2026-09-29 09:10",
          "QA found a regression in sync. We'll ship 2.4.1 instead of 2.4.0.",
          D("version", "2.4.1", "2.4.1")),
        M("Jin Park", "2026-09-30 15:00",
          "Should we start with us-east instead? Most beta users are there.",
          P("l1", "first_region", "us-east", "us-east")),
        M("Sunita Rao", "2026-09-30 15:40", "Good call, us-east first.", A("l1", "us-east")),
        M("Jin Park", "2026-10-01 08:00", "Marketing is still working from the original plan:", quote=1),
        M("Sunita Rao", "2026-10-01 08:20",
          "I'll update marketing. Note the embargo moves to 16:00 UTC to match the US morning.",
          D("embargo_time", "16:00", "16:00 UTC")),
        M("Sunita Rao", "2026-10-05 17:00",
          "2.4.1 crashes on older Android phones, so we need a 2.4.2. Until it's built, the "
          "version and the launch date are both open.",
          W("version"), W("launch_date")),
        M("Jin Park", "2026-10-05 17:20", "Could we ship 2.4.2 on October 20?",
          P("l2", "version", "2.4.2", "2.4.2"), P("l3", "launch_date", "2026-10-20", "October 20")),
        M("Sunita Rao", "2026-10-06 09:00",
          "Too early to say. I'll set both once 2.4.2 passes QA.", R("l2"), R("l3")),
        M("Mei Tan", "2026-10-06 12:00", "If the launch moves past the 16th I can own rollback."),
        M("Sunita Rao", "2026-10-07 10:00",
          "Thanks Mei, then rollback is yours, whenever we launch.",
          D("rollback_owner", "Mei", "Mei"))],
       tags=("organizer", "withdrawn", "quote", "chat"))

# --------------------------------------------------------------------------
# T07  room sublet (email, negotiation)
# --------------------------------------------------------------------------
thread("T07", "email", "2026-12-12", "Room for January",
       {"Omar Haddad": "omar.haddad", "Chloe Brandt": "chloe.b"},
       negotiation("Chloe Brandt (moving in)", "Omar Haddad (subletting the room)"),
       {"monthly_rent": ("money", "monthly rent"),
        "move_in": ("date", "move-in date"),
        "security_deposit": ("money", "security deposit"),
        "parking_included": ("bool", "whether a parking spot is included"),
        "utilities_monthly": ("money", "flat monthly utilities charge")},
       [M("Omar Haddad", "2026-12-01 19:20",
          "Hi Chloe, the room is $1,450 a month, available from January 4. The deposit is one "
          "month's rent, $1,450. A parking spot is included, and utilities are a flat $90 a month.",
          P("s1", "monthly_rent", 1450, "$1,450 a month"), P("s2", "move_in", "2027-01-04", "January 4"),
          P("s3", "security_deposit", 1450, "rent, $1,450"),
          P("s4", "parking_included", True, "parking spot is included"),
          P("s5", "utilities_monthly", 90, "$90")),
        M("Chloe Brandt", "2026-12-02 08:35",
          "Could you do $1,350? January 4 works, and $90 for utilities is fine. I don't have a "
          "car, so I don't need the parking.",
          R("s1"), P("s6", "monthly_rent", 1350, "$1,350"), A("s2", "January 4"), A("s5", "$90"),
          R("s4"), P("s7", "parking_included", False, "don't need the parking")),
        M("Omar Haddad", "2026-12-03 07:50",
          "Without parking I can do $1,380.",
          A("s7", "Without parking"), R("s6"), P("s8", "monthly_rent", 1380, "$1,380")),
        M("Chloe Brandt", "2026-12-03 18:05", "$1,380 works.", A("s8", "$1,380")),
        M("Chloe Brandt", "2026-12-05 09:15",
          "Could the deposit be $1,000? Money is tight with the move.",
          R("s3"), P("s9", "security_deposit", 1000, "$1,000")),
        M("Omar Haddad", "2026-12-06 11:40", "I'd need at least $1,200.",
          R("s9"), P("s10", "security_deposit", 1200, "$1,200")),
        M("Omar Haddad", "2026-12-07 09:05",
          "Also, sorry: the gas company raised rates, so utilities would be $105 a month from "
          "January, not $90.",
          P("s11", "utilities_monthly", 105, "$105")),
        M("Chloe Brandt", "2026-12-08 20:30",
          "Ugh, okay, $105 is fine. And my start date moved: could I move in January 11 instead?",
          A("s11", "$105"), P("s12", "move_in", "2027-01-11", "January 11")),
        M("Omar Haddad", "2026-12-09 08:10",
          "January 11 is fine. Still waiting to hear back on the deposit.",
          A("s12", "January 11")),
        M("Chloe Brandt", "2026-12-10 21:45",
          "Let me see what I can do on the deposit after payday.", quote=6)],
       tags=("negotiation", "pending-at-end", "bool"))

# --------------------------------------------------------------------------
# T08  conference talk (email, organizer)
# --------------------------------------------------------------------------
thread("T08", "email", "2026-08-14", "Your talk at DataHarbor",
       {"Grace Ito": "grace.ito", "Rafael Duarte": "rafael.duarte"},
       organizer("Grace Ito, the program chair,", "Grace"),
       {"talk_time": ("time", "start time of the talk"),
        "room": ("text", "room"),
        "duration_min": ("int", "length of the slot in minutes"),
        "microphone": ("text", "microphone type"),
        "travel_cap": ("money", "travel reimbursement cap")},
       [M("Grace Ito", "2026-07-28 15:00",
          "Rafael, your talk is Thursday at 11:15 in Hall C, 40 minutes including questions. "
          "We'll have a lapel mic for you, and we reimburse travel up to $600.",
          D("talk_time", "11:15", "11:15"), D("room", "Hall C", "Hall C"),
          D("duration_min", 40, "40 minutes"), D("microphone", "lapel", "lapel"),
          D("travel_cap", 600, "$600")),
        M("Rafael Duarte", "2026-07-29 09:30",
          "Thanks! Could I get a handheld instead? Lapel mics pick up my notes rustling.",
          P("t1", "microphone", "handheld", "handheld")),
        M("Grace Ito", "2026-07-30 10:10", "A handheld is fine.", A("t1", "handheld")),
        M("Grace Ito", "2026-08-03 13:00",
          "Schedule change: your talk moves to 13:45, same room.",
          D("talk_time", "13:45", "13:45")),
        M("Rafael Duarte", "2026-08-03 14:20",
          "No problem. Just confirming the room and length are unchanged from this:", quote=1),
        M("Grace Ito", "2026-08-04 09:05",
          "Room yes. The length drops to 30 minutes, sorry, we had to fit in one more session.",
          D("duration_min", 30, "30 minutes")),
        M("Rafael Duarte", "2026-08-05 18:40",
          "Flights from Lisbon are $720. Could the cap go to $750?",
          P("t2", "travel_cap", 750, "$750")),
        M("Grace Ito", "2026-08-06 08:30", "Let me ask the treasurer."),
        M("Grace Ito", "2026-08-09 16:15",
          "Hall C has a flooding problem and the venue is moving us out of it. I'll confirm "
          "the new room once they tell us.",
          W("room")),
        M("Rafael Duarte", "2026-08-10 07:55",
          "Would the Aurora Room work? I saw it on the venue map.",
          P("t3", "room", "Aurora Room", "Aurora Room")),
        M("Grace Ito", "2026-08-11 12:00",
          "Not my call, the venue assigns rooms. The treasurer says $700 is the most we can do "
          "for travel.",
          R("t3"), R("t2"), D("travel_cap", 700, "$700")),
        M("Rafael Duarte", "2026-08-12 09:20", "$700 is fine, thank you.")],
       tags=("organizer", "withdrawn", "quote"))

# --------------------------------------------------------------------------
# T09  translation job (email, negotiation)
# --------------------------------------------------------------------------
thread("T09", "email", "2026-07-03", "Translation: supply contract",
       {"Elena Kovac": "e.kovac", "Sami Laine": "sami.laine"},
       negotiation("Elena Kovac (the client)", "Sami Laine (the translator)"),
       {"word_count": ("int", "word count of the job"),
        "rate_per_word": ("money", "rate per word"),
        "deadline": ("date", "delivery deadline"),
        "file_format": ("text", "format of the delivered file"),
        "reviewer": ("text", "full name of the client-side reviewer"),
        "rush_fee": ("money", "rush fee")},
       [M("Elena Kovac", "2026-06-20 09:00",
          "Sami, we have a 6,200-word supply contract to translate from Finnish to English. "
          "Could you deliver by July 10 at $0.12 a word? You'd send it back as a DOCX.",
          P("x1", "word_count", 6200, "6,200-word"), P("x2", "rate_per_word", 0.12, "$0.12"),
          P("x3", "deadline", "2026-07-10", "July 10"), P("x4", "file_format", "DOCX", "DOCX")),
        M("Sami Laine", "2026-06-21 10:30",
          "Happy to take the 6,200 words. My rate for legal work is $0.15 a word. July 10 is "
          "fine, and DOCX works.",
          A("x1", "6,200 words"), R("x2"), P("x5", "rate_per_word", 0.15, "$0.15"),
          A("x3", "July 10"), A("x4", "DOCX")),
        M("Elena Kovac", "2026-06-22 08:15",
          "Could you meet me at $0.14? Mia Lund on our side will review your translation.",
          R("x5"), P("x6", "rate_per_word", 0.14, "$0.14"), P("x7", "reviewer", "Mia Lund", "Mia Lund")),
        M("Sami Laine", "2026-06-22 12:40",
          "$0.14 is fine, and happy to work with Mia Lund.",
          A("x6", "$0.14"), A("x7", "Mia Lund")),
        M("Elena Kovac", "2026-06-25 14:00",
          "The client added an annex, so it's now 7,900 words.",
          P("x8", "word_count", 7900, "7,900 words")),
        M("Sami Laine", "2026-06-25 16:20",
          "7,900 words is fine, though I'd prefer until July 14 for that.",
          A("x8", "7,900 words"), P("x9", "deadline", "2026-07-14", "July 14")),
        M("Elena Kovac", "2026-06-26 09:10",
          "We can't go past July 10, the hearing is on the 13th.",
          R("x9")),
        M("Sami Laine", "2026-06-26 11:05",
          "Understood, July 10 stands. For the extra pages on that timeline I'd add a $250 "
          "rush fee.",
          P("x10", "rush_fee", 250, "$250")),
        M("Elena Kovac", "2026-06-29 15:30",
          "I need to clear the rush fee with the partner. Separately, they want a PDF back, "
          "not a DOCX.",
          P("x11", "file_format", "PDF", "PDF")),
        M("Sami Laine", "2026-06-29 17:00", "PDF is fine.", A("x11", "PDF")),
        M("Elena Kovac", "2026-07-01 10:45",
          "Mia Lund is out sick, so she won't be reviewing, and I don't know yet who will. "
          "Still waiting on the partner about the rush fee.",
          W("reviewer"), quote=8)],
       tags=("negotiation", "withdrawn", "pending-at-end"))

# --------------------------------------------------------------------------
# T10  school bake sale (chat, organizer)
# --------------------------------------------------------------------------
thread("T10", "chat", "2026-10-14", "PTA bake sale",
       {"Beth Oduya": "", "Nadia Sorensen": "", "Paul Mercer": "", "Kenji Ward": "", "Lina Costa": ""},
       organizer("Beth Oduya, the PTA chair,", "Beth"),
       {"sale_date": ("date", "date of the sale"),
        "location": ("text", "where the sale is held"),
        "table_count": ("int", "number of tables"),
        "cash_box": ("text", "first name of the person running the cash box"),
        "price_per_item": ("money", "price per treat")},
       [M("Beth Oduya", "2026-10-01 19:00",
          "Bake sale is Saturday, October 24, in the school gym. We'll set up 6 tables. "
          "Treats are $2 each.",
          D("sale_date", "2026-10-24", "October 24"), D("location", "school gym", "school gym"),
          D("table_count", 6, "6 tables"), D("price_per_item", 2, "$2")),
        M("Nadia Sorensen", "2026-10-01 19:05", "Yay! I'll make lemon bars."),
        M("Paul Mercer", "2026-10-01 19:20", "Who's handling the cash box?"),
        M("Kenji Ward", "2026-10-01 19:22",
          "Kenji here, I can do the cash box, I did it last year.",
          P("k1", "cash_box", "Kenji", "Kenji")),
        M("Beth Oduya", "2026-10-01 19:30", "Thanks Kenji, the cash box is yours.",
          A("k1", "Kenji")),
        M("Nadia Sorensen", "2026-10-02 08:12",
          "Could treats be $2.50? Butter got expensive.",
          P("k2", "price_per_item", 2.5, "$2.50")),
        M("Beth Oduya", "2026-10-02 08:40", "Let's keep it simple at $2.", R("k2")),
        M("Paul Mercer", "2026-10-03 17:45", "The gym is booked for a basketball tournament on the 24th!"),
        M("Beth Oduya", "2026-10-03 18:10",
          "Ugh, confirmed. We'll move it to Sunday, October 25, same gym.",
          D("sale_date", "2026-10-25", "October 25")),
        M("Lina Costa", "2026-10-04 11:00",
          "Do we have enough bakers for 6 tables? Maybe 4 is plenty.",
          P("k3", "table_count", 4, "4 is plenty")),
        M("Beth Oduya", "2026-10-04 11:30", "Let's see how many sign up first.", R("k3")),
        M("Kenji Ward", "2026-10-08 20:00",
          "Sorry everyone, I have to work on the 25th, so someone else needs to take the cash box."),
        M("Beth Oduya", "2026-10-08 20:15",
          "No problem Kenji. The cash box is open, any volunteers?", W("cash_box")),
        M("Paul Mercer", "2026-10-09 07:30", "Reposting the details for the new folks:", quote=1),
        M("Beth Oduya", "2026-10-09 07:45", "Careful, that's the old date! It's Sunday the 25th now."),
        M("Beth Oduya", "2026-10-10 12:00",
          "Sign-ups are in: 14 bakers, so we'll go with 8 tables.",
          D("table_count", 8, "8 tables")),
        M("Lina Costa", "2026-10-11 09:10",
          "The gym floor is being refinished that weekend. The office says we can use the cafeteria.",
          P("k4", "location", "cafeteria", "cafeteria")),
        M("Beth Oduya", "2026-10-11 09:30", "OK, cafeteria it is.", A("k4", "cafeteria"))],
       tags=("organizer", "withdrawn", "quote", "chat"))


# --------------------------------------------------------------------------
# rendering, gold and checks
# --------------------------------------------------------------------------
MONTHS = list(calendar.month_name)[1:]
WEEKDAY_DATE = re.compile(
    r"\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),? "
    r"(?:(" + "|".join(MONTHS) + r") (\d{1,2})\b|the (\d{1,2})(?:st|nd|rd|th))")


def _stamp(at: str) -> datetime:
    return datetime.strptime(at, "%Y-%m-%d %H:%M")


def _check_weekdays(tid, m):
    sent = _stamp(m["at"]).date()
    for wd, month, day, nth in WEEKDAY_DATE.findall(m["body"]):
        if month:
            mo = MONTHS.index(month) + 1
            y = sent.year + (1 if mo < sent.month else 0)
            d = date(y, mo, int(day))
        else:
            mo, y = sent.month, sent.year
            if int(nth) < sent.day:
                mo, y = (1, y + 1) if mo == 12 else (mo + 1, y)
            d = date(y, mo, int(nth))
        assert calendar.day_name[d.weekday()] == wd, f"{tid}: {wd} {d} is a {calendar.day_name[d.weekday()]}"


def _render_one(t, k, m):
    when = _stamp(m["at"])
    if t["kind"] == "email":
        addr = t["people"][m["who"]]
        head = (f"Message {k}\nFrom: {m['who']} <{addr}@example.test>\n"
                f"Date: {when:%A, %d %b %Y %H:%M}\nSubject: "
                f"{'Re: ' if k > 1 else ''}{t['subject']}\n\n")
        text = head + m["body"]
    else:
        text = f"[{when:%Y-%m-%d %H:%M}] {m['who']}: {m['body']}"
    if m["quote"]:
        q = t["messages"][m["quote"] - 1]
        qwhen = _stamp(q["at"])
        lead = (f"On {qwhen:%A, %d %b %Y %H:%M}, {q['who']} wrote:" if t["kind"] == "email"
                else f"(replying to {q['who']}, {qwhen:%Y-%m-%d %H:%M})")
        text += "\n\n> " + lead + "\n" + "\n".join("> " + line for line in q["body"].split("\n"))
    return text


def render(t) -> list[str]:
    return [_render_one(t, k, m) for k, m in enumerate(t["messages"], 1)]


def _surface_ok(kind, value, surface) -> bool:
    s = surface.lower()
    digits = re.sub(r"[^\d.]", "", surface).strip(".")
    if kind == "date":
        d = date.fromisoformat(value)
        return re.search(rf"(?<!\d){d.day}(st|nd|rd|th)?(?!\d)", s) is not None
    if kind == "time":
        h, mnt = map(int, value.split(":"))
        h12 = h % 12 or 12
        return (f"{h}:{mnt:02d}" in s or f"{h:02d}:{mnt:02d}" in s
                or (mnt == 0 and re.search(rf"(?<![\d:]){h12}(?![\d:])", s) is not None))
    if kind == "int":
        return str(value) in digits
    if kind in ("money", "number"):
        return digits != "" and abs(float(digits) - float(value)) < 1e-9
    if kind == "text":
        return value.lower() in s
    if kind == "bool":
        return "shooter" in s or "parking" in s
    raise ValueError(kind)


def gold_of(t):
    """Apply every message's operations in order. Returns the final values,
    the message number and surface that set each, every value each field was
    stated with, and the history of each field's settled value."""
    fields, tid = t["fields"], t["id"]
    state = {f: None for f in fields}
    setter = {f: None for f in fields}
    stated = {f: [] for f in fields}
    settled = {f: [] for f in fields}
    open_props, closed = {}, set()
    for k, m in enumerate(t["messages"], 1):
        where = f"{tid} msg {k}"
        for op in m["ops"]:
            kind = op[0]
            if kind in ("decide", "propose", "accept"):
                assert op[-1] in m["body"], f"{where}: surface {op[-1]!r} not in the body"
            if kind == "decide":
                _, f, v, surf = op
                assert _surface_ok(fields[f][0], v, surf), f"{where}: {surf!r} vs {v!r}"
                stated[f].append(v)
                state[f], setter[f] = v, (k, surf)
                settled[f].append(v)
            elif kind == "propose":
                _, pid, f, v, surf = op
                assert pid not in open_props and pid not in closed, f"{where}: {pid} reused"
                assert _surface_ok(fields[f][0], v, surf), f"{where}: {surf!r} vs {v!r}"
                open_props[pid] = (f, v)
                stated[f].append(v)
            elif kind == "accept":
                _, pid, surf = op
                assert pid in open_props, f"{where}: accepting closed or unknown {pid}"
                f, v = open_props.pop(pid)
                closed.add(pid)
                assert _surface_ok(fields[f][0], v, surf), f"{where}: {surf!r} vs {v!r}"
                state[f], setter[f] = v, (k, surf)
                settled[f].append(v)
            elif kind == "reject":
                _, pid = op
                assert pid in open_props, f"{where}: turning down closed or unknown {pid}"
                open_props.pop(pid)
                closed.add(pid)
            elif kind == "withdraw":
                _, f = op
                assert state[f] is not None, f"{where}: withdrawing unset {f}"
                state[f], setter[f] = None, None
                settled[f].append(None)
            else:
                raise ValueError(kind)
    return state, setter, stated, settled


def items() -> list[dict]:
    out = []
    nulls = 0
    for t in THREADS:
        tid, msgs = t["id"], t["messages"]
        assert 8 <= len(msgs) <= 20, f"{tid}: {len(msgs)} messages"
        stamps = [_stamp(m["at"]) for m in msgs]
        assert stamps == sorted(stamps) and stamps[-1].date() < date.fromisoformat(t["today"]), tid
        assert all(m["quote"] is None or 1 <= m["quote"] < k for k, m in enumerate(msgs, 1)), tid
        assert all(m["who"] in t["people"] for m in msgs), tid
        for m in msgs:
            _check_weekdays(tid, m)
        state, setter, stated, settled = gold_of(t)
        for f, v in state.items():
            if v is None:
                nulls += 1
                assert stated[f], f"{tid}: null field {f} was never stated"
            else:
                k, surf = setter[f]
                assert surf in msgs[k - 1]["body"], f"{tid}: final {f} not in message {k}"
        changed = [f for f, hist in settled.items() if len({repr(v) for v in hist}) >= 2]
        assert len(changed) >= 2, f"{tid}: only {changed} changed after first being settled"

        field_lines = "\n".join(f"- {f}: {desc} ({KIND_FORMAT[kind]}, or null)"
                                for f, (kind, desc) in t["fields"].items())
        shape = "{" + ", ".join(f'"{f}": {KIND_SHAPE[kind]} or null'
                                for f, (kind, _) in t["fields"].items()) + "}"
        where = "an email thread" if t["kind"] == "email" else "a group chat"
        task = (f"Today is {t['today']}. Below is {where}, oldest message first. {t['rule']} "
                "Lines starting with > quote an earlier message and are not new statements.\n\n"
                "Give the final value of each field as of the last message:\n" + field_lines
                + json_contract(shape))
        sep = "\n\n-----\n\n" if t["kind"] == "email" else "\n"
        gold = {"fields": {f: {"kind": kind, "value": state[f],
                               "others": [v for v in dict.fromkeys(stated[f]) if v != state[f]]}
                           for f, (kind, _) in t["fields"].items()}}
        out.append(item(tid, CAT, task, gold, "thread", context=sep.join(render(t)), task_type="ask",
                        tags=t["tags"], messages=len(msgs), changed=len(changed),
                        null_fields=sum(v is None for v in state.values())))
    assert nulls >= 8, f"only {nulls} null fields in the category"
    return out


if __name__ == "__main__":
    for it in items():
        g = it["gold"]["fields"]
        print(it["id"], it["messages"], "msgs,", it["changed"], "changed,", it["null_fields"], "null:",
              {f: v["value"] for f, v in g.items()})
