"""Write the emails.

These used to be scaffolds full of [bracketed prompts] for you to fill in. They
are now written out in full, because the app can read both profiles — yours and
theirs — and the specific thing worth saying is derivable from what is actually
on the page.

The rules the wording follows came from feedback on a real outreach email:

  * "Hi", never "Hey" — safe with practitioners you have not met.
  * State the background sharply. A concrete fact about scope — how many
    people, what you owned — lands; "focused on managing a team" does not.
  * Ask about *their* experience, never for a plan. "What pitfalls should I
    avoid and what goals should I set" reads as asking a stranger to build your
    recruiting roadmap. "What you wish you'd known early on" gets the same
    information out of a conversation they enjoy having.
  * Dates without brackets, one time format throughout.

Shape and voice follow five real emails sent in September 2026 (see
matching.py for which fact each one led with):

  Hi <first>,  /  I hope you're doing well!
  I'm a first-year MBA student at Goizueta. [Thanks for what they've shared,
    when they are a second-year.]
  Before business school, I worked as <Title> at <Company>. Now at Goizueta
    I'm exploring consulting, and I'd love to hear about your experience.
  I see that <one fact>. I would love to chat with you to discuss how you
    navigated <the recruiting process | the journey> and your MBA
    experience in general.
  Would you be open to a coffee chat, either virtually or on campus, in the
    next <week | couple of weeks>? ... windows work on my end:
  • <Month D, Weekday>: <h:mmam – h:mmpm> ET      <- timezone on every line
  Happy to work around whatever is easiest for you. [Resume.] I will send you
    the calendar invite once we finalize the time.
  Thank you for considering, and I look forward to connecting!

Never recite their career back to them, and one ask sentence, not three.

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


def _slot_block(slot_lines, tz_label="ET"):
    """One bullet per day, each carrying its own timezone label — the way
    the Akshansh email does it ("September 24, Thursday: 2:30pm – 4:30pm ET"),
    rather than one "(all times ET)" stated once up front."""
    label = (tz_label or "").strip()
    out = []
    for line in slot_lines:
        text = line.rstrip()
        if label and not text.endswith(" " + label):
            text += " " + label
        out.append("• " + text)
    return "\n".join(out)


MONTHS = ["january", "february", "march", "april", "may", "june", "july",
          "august", "september", "october", "november", "december"]


def _horizon(slot_lines, today=None):
    """'in the next week' when every slot is within 7 days, else 'in the next
    couple of weeks' — the real emails switch between the two exactly this way."""
    import datetime
    today = today or datetime.date.today()
    furthest = 0
    for line in slot_lines:
        m = re.match(r"\s*([A-Za-z]+)\s+(\d{1,2})", line)
        if not m or m.group(1).lower() not in MONTHS:
            return "in the next couple of weeks"
        month, day = MONTHS.index(m.group(1).lower()) + 1, int(m.group(2))
        year = today.year + (1 if month < today.month - 6 else 0)
        try:
            delta = (datetime.date(year, month, day) - today).days
        except ValueError:
            return "in the next couple of weeks"
        furthest = max(furthest, delta)
    return "in the next week" if furthest <= 7 else "in the next couple of weeks"


# ------------------------------------------------------------- the sentences

def _article(word):
    return "an" if (word or "")[:1].lower() in "aeiou" else "a"


def _is_internship(role):
    title = (role.get("title") or "").lower()
    return "intern" in title or "trainee" in title


def _tie_sentence(item, standalone=True):
    """The fact itself, phrased the way I actually write it. Never claims
    more than the two profiles say (the Akshansh email also said he 'went
    through the consulting process' — that came from a conversation, not the
    profile, so it is not generated)."""
    kind = item["kind"]
    if kind == "employer":
        return "we both spent time at %s" % item["company"]
    if kind == "school":
        return "we were both at %s" % item["school"]
    if kind == "arc":
        return "you come from a Tech background as well and went back into Tech"
    if kind == "discipline":
        return "you come from a Tech background as well"
    if kind == "experience":
        if standalone:
            return ("you had %s of experience which in an MBA class would have "
                    "been the lower end of the spectrum and I am in a similar "
                    "position" % item["years"])
        return "with %s of experience and I am in a similar position" % item["years"]
    return ""


def opening_line(person, mine, theirs, ground):
    """The hook paragraph: 'I see that <fact>.' then the single ask. Empty
    hooks -> just the ask. No recap of their career — none of the real
    emails does that."""
    hooks = matching.email_hooks(ground)
    if not hooks:
        return ask_line(person, ground)

    top = hooks[0]
    if top["kind"] == "nontrad":
        sentence = "You have quite an interesting albeit non-traditional background"
        if top.get("international"):
            sentence += (", and as an international, I am sure you faced your "
                         "own challenges")
        sentence += "."
    else:
        fact = _tie_sentence(top, standalone=len(hooks) == 1)
        if len(hooks) > 1:
            fact += " " + _tie_sentence(hooks[1], standalone=False)
        sentence = "I see that %s." % fact
    return sentence + " " + ask_line(person, ground)


def pitch_line(settings, mine, person=None, has_hook=False):
    """Your own background, then where you are now. The firm is named only
    when no hook follows — the two earliest emails named McKinsey/Bain, the
    three later ones let the hook carry the specifics."""
    written = (settings.get("user_pitch") or "").strip()
    if not written:
        roles = [r for r in ((mine or {}).get("roles") or []) if not _is_internship(r)]
        if roles:
            anchor = sorted(roles, key=lambda r: r.get("months") or 0, reverse=True)[0]
            title = (anchor.get("title") or "").strip()
            company = (anchor.get("company") or "").strip()
            if title and company:
                written = "Before business school, I worked as %s %s at %s." % (
                    _article(title), title, company)
            elif company:
                written = "Before business school, I worked at %s." % company
    if not written:
        return ""
    if "now at goizueta" in written.lower():
        return written
    firm = (person or {}).get("firm") or ""
    tail = " at %s" % firm if (firm and not has_hook) else ""
    return (written + " Now at Goizueta I'm exploring consulting, and I'd love "
            "to hear about your experience%s." % tail)


def ask_line(person, ground):
    """One sentence, their experience not a plan. 'the journey' when the hook
    is a path (Shivaan, Akshansh); 'the recruiting process' otherwise."""
    hooks = matching.email_hooks(ground)
    topic = ("the journey" if hooks and hooks[0]["kind"] in ("arc", "nontrad")
             else "the recruiting process")
    return ("I would love to chat with you to discuss how you navigated %s and "
            "your MBA experience in general." % topic)


# ---------------------------------------------------------------- the emails

def outreach(person, settings, slot_lines, mine=None, theirs=None, today=None):
    """The first ask, written out in full."""
    mine = mine or {}
    theirs = theirs or {}
    ground = matching.common_ground(mine, theirs) if (mine and theirs) else []
    tz = settings.get("tz_label") or "ET"

    paragraphs = [
        "Hi %s," % first_name(person.get("name")),
        "I hope you're doing well!",
    ]

    # The Goizueta-alum flag is no longer a sentence at all: it defaulted to
    # yes on every new person, so it read as the reason for writing when it
    # never was. A second-year gets the thanks every real email opened with.
    intro = "I'm a first-year MBA student at Goizueta."
    if mine and theirs and matching.is_year_ahead(mine, theirs):
        intro += " Thank you so much for the information you have shared with us so far."
    if person.get("referred_by_name"):
        intro += (" I spoke with %s recently, and they suggested I reach out "
                  "to you." % person["referred_by_name"])
    paragraphs.append(intro)

    has_hook = bool(matching.email_hooks(ground))
    pitch = pitch_line(settings, mine, person, has_hook)
    if pitch:
        paragraphs.append(pitch)

    paragraphs.append(opening_line(person, mine, theirs, ground))

    if slot_lines:
        paragraphs.append(
            "Would you be open to a coffee chat, either virtually or on campus, "
            "%s? Any of the following windows work on my end:"
            % _horizon(slot_lines, today))
        paragraphs.append(_slot_block(slot_lines, tz))
    else:
        paragraphs.append(
            "Would you be open to a coffee chat, either virtually or on campus, "
            "in the next couple of weeks?")

    closing = "Happy to work around whatever is easiest for you."
    if settings.get("resume_ready"):
        closing += " I've attached my resume for reference."
    if slot_lines:
        closing += " I will send you the calendar invite once we finalize the time."
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
            "below:")
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
