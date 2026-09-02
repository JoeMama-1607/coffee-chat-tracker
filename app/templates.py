"""Write the emails.

These used to be scaffolds full of [bracketed prompts] for you to fill in. They
are now written out in full, because the app can read both profiles — yours and
theirs — and the specific thing worth saying is derivable from what is actually
on the page.

The rules the wording follows came from feedback on a real outreach email:

  * "Hi", never "Hey" — safe with practitioners you have not met.
  * State the background sharply. "Most recently led an 8-member development
    team" lands; "focused on managing a team" does not.
  * Ask about *their* experience, never for a plan. "What pitfalls should I
    avoid and what goals should I set" reads as asking a stranger to build your
    recruiting roadmap. "What you wish you'd known early on" gets the same
    information out of a conversation they enjoy having.
  * Dates without brackets, one time format throughout.

Nothing is signed off. The body stops after its last line and leaves a blank
one, so the signature Outlook adds — sign-off included — follows on cleanly.
Two sign-offs in one message looks careless.

The one thing this cannot do is have the insight for you. It assembles true,
checkable sentences out of two profiles — read it before you send it.
"""

import re

import matching

BRACKET = re.compile(r"\[[^\[\]]{3,400}?\]", re.S)

def unfilled(text):
    """Every [prompt] still sitting in the draft."""
    return BRACKET.findall(text or "")


def first_name(full_name):
    return (full_name or "").strip().split(" ")[0] or "there"


def _finish(paragraphs):
    """Join the body and leave a trailing blank line. Outlook drops its own
    signature straight in after it, sign-off and all."""
    return "\n\n".join(p for p in paragraphs if p) + "\n\n"


def _slot_block(slot_lines, tz_label=""):
    """The lead-in already says which time zone these are in, so the label is
    stripped off each line — one format throughout, no 'ET' twice."""
    cleaned = []
    for line in slot_lines:
        text = line.rstrip()
        if tz_label and text.endswith(" " + tz_label):
            text = text[: -(len(tz_label) + 1)].rstrip()
        cleaned.append(text)
    return "\n".join("• " + line for line in cleaned)


# ------------------------------------------------------------- the sentences

def _their_current(theirs):
    roles = theirs.get("roles") or []
    if not roles:
        return None
    return next((r for r in roles if r.get("current")), roles[0])


def _years_at(theirs, company_key):
    months = sum(r.get("months") or 0
                 for r in (theirs.get("roles") or [])
                 if matching._company_key(r.get("company")) == company_key)
    if months >= 12:
        years = months // 12
        return "%d year%s" % (years, "" if years == 1 else "s")
    if months:
        return "%d months" % months
    return ""


def _article(word):
    return "an" if (word or "")[:1].lower() in "aeiou" else "a"


def _is_internship(role):
    title = (role.get("title") or "").lower()
    return "intern" in title or "trainee" in title


def _career_clause(theirs):
    """'you spent six years at Aptiv, most recently as Senior Algorithm
    Developer' — built from the employer they actually gave the most time to,
    which is more telling than whatever is listed first."""
    roles = [r for r in (theirs.get("roles") or [])
             if r.get("company") and not _is_internship(r)]
    if not roles:
        return ""

    # The employer with the most months behind it is the real story.
    totals = {}
    for role in roles:
        key = matching._company_key(role.get("company"))
        if key:
            totals[key] = totals.get(key, 0) + (role.get("months") or 0)
    if not totals:
        return ""
    anchor_key = max(totals.items(), key=lambda kv: kv[1])[0]
    anchor_roles = [r for r in roles
                    if matching._company_key(r.get("company")) == anchor_key]
    anchor_roles.sort(key=lambda r: r.get("start") or (0, 0), reverse=True)
    anchor = anchor_roles[0]

    span = _years_at(theirs, anchor_key)
    clause = ("you spent %s at %s" % (span, anchor["company"])) if span \
        else ("you were at %s" % anchor["company"])
    if anchor.get("title"):
        clause += ", most recently as %s %s" % (_article(anchor["title"]), anchor["title"])

    # Where they went next, if it is a real move rather than a summer internship.
    later = [r for r in roles
             if matching._company_key(r.get("company")) != anchor_key
             and r.get("start") and anchor.get("start")
             and r["start"] > anchor["start"]]
    if later:
        later.sort(key=lambda r: r["start"], reverse=True)
        nxt = later[0]
        if nxt.get("title"):
            clause += ", before moving to %s as %s %s" % (
                nxt["company"], _article(nxt["title"]), nxt["title"])
        else:
            clause += ", before moving to %s" % nxt["company"]
    return clause


def _tie_sentence(item):
    """One clause naming what the two of you share. Never claims more than the
    two profiles actually say."""
    kind = item["kind"]
    if kind == "employer":
        return "we both spent time at %s" % item["label"].replace("Both worked at ", "")
    if kind == "school":
        return "we were both at %s" % item["label"].replace("Both studied at ", "")
    if kind == "country":
        return ("you built your career in %s before coming here, which is the "
                "same move I made" % item["country"])
    if kind == "discipline":
        return ("I come from %s as well" % matching.DISCIPLINE_WORDS[item["discipline"]])
    if kind == "pivot":
        return ("I am coming from %s rather than %s"
                % (matching.DISCIPLINE_WORDS.get(item["from"], "a different field"),
                   matching.DISCIPLINE_WORDS[item["to"]]))
    if kind == "skills":
        return item["phrase"]
    return ""


def opening_line(person, mine, theirs, ground):
    """The lines that decide whether the rest gets read: what they have done,
    then the one or two things that genuinely connect you to it."""
    firm = person.get("firm") or ""
    career = _career_clause(theirs)

    lead = ("I came across your profile and your path stood out to me — %s." % career
            ) if career else (
        "I came across your profile while looking at people at %s." % firm
        if firm else "I came across your profile.")

    ties = [_tie_sentence(item) for item in ground[:2]]
    ties = [t for t in ties if t]

    if not ties:
        return lead + (" That is the part I would most like to hear about."
                       if career else " I would value hearing about your path.")

    if len(ties) == 1:
        joined = ties[0]
    else:
        joined = "%s, and %s" % (ties[0], ties[1])

    closer = ("so that is the part I would most like to hear about."
              if career else "which is what made me want to reach out to you.")
    return "%s %s — %s" % (lead, joined[0].upper() + joined[1:], closer)


def pitch_line(settings, mine):
    """Your own background, in one sentence."""
    written = (settings.get("user_pitch") or "").strip()
    if written:
        return written

    roles = [r for r in ((mine or {}).get("roles") or []) if not _is_internship(r)]
    if roles:
        # The job you actually held before school, not a summer placement.
        substantive = sorted(roles, key=lambda r: r.get("months") or 0, reverse=True)
        anchor = substantive[0]
        title = (anchor.get("title") or "").strip()
        company = (anchor.get("company") or "").strip()
        if title and company:
            return ("Before business school I was %s at %s."
                    % (title.lower(), company))
        if company:
            return "Before business school I was at %s." % company
    return ""


def ask_line(person, ground):
    """What you want out of the half hour — asked as their experience, never
    as a plan for them to write."""
    top = ground[0] if ground else None
    firm = person.get("firm") or "the firm"

    if top and top["kind"] == "country":
        return ("I would love to hear how you found the move — what you wish "
                "you had known in your first few months here, and how you "
                "thought about the recruiting timeline once you arrived.")
    if top and top["kind"] == "discipline":
        return ("I would love to hear how you approached the switch — what "
                "carried over from the technical side, what you had to build "
                "from scratch, and how the recruiting process actually felt.")
    if top and top["kind"] == "pivot":
        return ("I would love to hear what the learning curve looked like for "
                "you, and what you wish you had known when you were starting "
                "out in it.")
    if top and top["kind"] == "employer":
        return ("I would love to hear how your path went after that, and what "
                "the day to day at %s is actually like." % firm)
    return ("I would love to hear about your experience at %s — what drew you "
            "there, and what you wish you had known before you started." % firm)


# ---------------------------------------------------------------- the emails

def outreach(person, settings, slot_lines, mine=None, theirs=None):
    """The first ask, written out in full."""
    mine = mine or {}
    theirs = theirs or {}
    ground = matching.common_ground(mine, theirs) if (mine and theirs) else []

    paragraphs = [
        "Hi %s," % first_name(person.get("name")),
        "I hope you're doing well!",
    ]

    intro = "I'm a first-year MBA student at Goizueta."
    if person.get("referred_by_name"):
        intro += (" I spoke with %s recently, and they suggested I reach out "
                  "to you." % person["referred_by_name"])
    paragraphs.append(intro + " " + opening_line(person, mine, theirs, ground))

    pitch = pitch_line(settings, mine)
    if pitch:
        paragraphs.append(pitch)

    paragraphs.append(ask_line(person, ground))

    if slot_lines:
        paragraphs.append(
            "Would you be open to a coffee chat in the next couple of weeks? "
            "Any of the following windows work on my end (all times %s):"
            % (settings.get("tz_label") or "ET"))
        paragraphs.append(_slot_block(slot_lines, settings.get("tz_label") or "ET"))
    else:
        paragraphs.append(
            "Would you be open to a coffee chat in the next couple of weeks? "
            "I can work around whatever suits you.")

    closing = ("Happy to work around whatever is easiest for you, and I'm glad "
               "to do this virtually or on campus.")
    if (settings.get("resume_path") or "").strip():
        closing += " I've attached my resume for reference."
    paragraphs.append(closing)

    paragraphs.append("Thank you for considering, and I look forward to connecting!")

    body = _finish(paragraphs)
    subject = "Goizueta MBA — coffee chat request"
    if settings.get("user_name"):
        subject = "Coffee chat request — %s, Goizueta MBA" % settings["user_name"].strip()
    return {"subject": subject, "body": body, "unfilled": unfilled(body)}


def followup(person, settings, slot_lines):
    """The nudge after a week of silence. Deliberately short and unpersonalised
    — a long second email reads as pressure."""
    paragraphs = [
        "Hi %s," % first_name(person.get("name")),
        "I wanted to follow up gently on my note from a couple of weeks ago. I "
        "know this is a busy stretch, so no pressure at all if the timing "
        "doesn't work.",
    ]
    if slot_lines:
        paragraphs.append(
            "If you do have half an hour in the next couple of weeks, I would "
            "still love to hear about your experience. Updated availability "
            "below (all times %s):" % (settings.get("tz_label") or "ET"))
        paragraphs.append(_slot_block(slot_lines, settings.get("tz_label") or "ET"))
    else:
        paragraphs.append(
            "If you do have half an hour in the next couple of weeks, I would "
            "still love to hear about your experience — happy to work around "
            "your schedule.")
    paragraphs.append("Thanks again for considering it.")

    body = _finish(paragraphs)
    return {
        "subject": "Following up — Goizueta coffee chat request",
        "body": body,
        "unfilled": unfilled(body),
    }


def thankyou(person, settings, highlights=""):
    """Sent within 24 hours. Left as a scaffold on purpose: the specifics come
    out of the conversation you just had, and only you were in it."""
    firm = person.get("firm") or "the firm"
    specifics = highlights.strip() if highlights.strip() else (
        "[The most important part of the conversation — a key learning, a story "
        "they told, something that shows you were listening.]"
    )

    when = "today" if not person.get("chat_at") else "on " + str(person["chat_at"])[:10]
    paragraphs = [
        "Hi %s," % first_name(person.get("name")),
        "Thank you so much for taking the time to speak with me %s. I know that "
        "is a real slice of your week, and I appreciated it." % when,
        specifics,
        "[One line on what you're doing differently as a result — this is what "
        "makes the note read as a continuation rather than a formality.]",
        "If there is anyone else at %s whose path I should hear about, I would "
        "be glad to be introduced. Either way, I'll keep you posted on how "
        "recruiting goes, and I hope we can catch up again soon." % firm,
    ]
    body = _finish(paragraphs)
    return {
        "subject": "Thank you — %s" % (settings.get("user_name", "").strip() or "coffee chat"),
        "body": body,
        "unfilled": unfilled(body),
    }


# Questions worth having in your pocket, adapted from the deck's
# "Good vs Great questions" slide. Great questions carry your own context.
QUESTION_BANK = [
    {"tier": "great", "text": "I noticed your background is in [X] — I also come from that world. I'd expect [ABC] to transfer and [XYZ] to be the real gap. What did you find the transition to consulting was actually like?"},
    {"tier": "great", "text": "Consulting firms have a lot in common, but [FIRM] stands out to me for [reason]. From the inside, what would you say actually makes it different?"},
    {"tier": "great", "text": "Every project has a geography, an industry, and a functional angle. Which of those has mattered most to your own growth?"},
    {"tier": "great", "text": "What's a piece of feedback you got early on that changed how you work?"},
    {"tier": "good", "text": "What made you decide to join [FIRM]?"},
    {"tier": "good", "text": "[FIRM] has a reputation for [X] — has that matched your experience?"},
    {"tier": "good", "text": "How has your role changed over your time there?"},
    {"tier": "good", "text": "What does a typical week look like for you right now?"},
    {"tier": "good", "text": "How does the staffing model work in practice for someone at my level?"},
    {"tier": "good", "text": "Is there anything you'd want to know if you were starting this recruiting cycle again?"},
]
