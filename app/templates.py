"""Write the emails.

All three drafts follow the same idea: the lines that are the same in every
email are written out in full, and the parts only you can write are left as
[bracketed prompts]. The app will not open a draft in Outlook while a bracket
is still in it, so nothing half-written can go out.

Outreach shape (from real sent emails):

  Hi <first>,  /  I hope you're doing well!
  I'm a first-year MBA student at Goizueta. [how you know them]
  <Settings background, or a prompt> Now at Goizueta I'm exploring
    consulting, and I'd love to hear about your experience.
  [the hook — with what the app found in common, if it found anything]
    I would love to chat with you to discuss how you navigated the
    recruiting process and your MBA journey in general.
  Would you be open to a coffee chat in the next week | couple of weeks? ...
  • <Month D, Weekday>: <h:mmam – h:mmpm> ET        <- timezone on every line
  Happy to work around whatever is easiest for you. [resume] I will send you
    the calendar invite once we finalize the time.
  Thank you for considering, and I look forward to connecting!

Nothing is signed off: the body ends with a blank line so Outlook's own
signature follows cleanly. None of the drafts needs their LinkedIn PDF.
"""

import datetime
import re

import matching

BRACKET = re.compile(r"\[[^\[\]]{3,400}?\]", re.S)

NOW_AT_GOIZUETA = ("Now at Goizueta I'm exploring consulting, and I'd love to "
                   "hear about your experience.")
SIGN_OFF = "Thank you for considering, and I look forward to connecting!"


def unfilled(text):
    """Every [prompt] still sitting in the draft."""
    return BRACKET.findall(text or "")


def first_name(full_name):
    return (full_name or "").strip().split(" ")[0] or "there"


def _finish(paragraphs):
    """Join the body and leave a trailing blank line. Outlook drops its own
    signature straight in after it, sign-off and all."""
    return "\n\n".join(p for p in paragraphs if p) + "\n\n"


def _subject(settings, prefix=""):
    name = first_name(settings.get("user_name")) if (settings.get("user_name") or "").strip() else ""
    core = ("Coffee Chat Request - %s, Goizueta MBA" % name) if name \
        else "Coffee Chat Request - Goizueta MBA"
    return prefix + core


def _slot_block(slot_lines, tz_label="ET"):
    """One bullet per day, each carrying its own timezone label."""
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
    couple of weeks'."""
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


def _slot_paragraphs(slot_lines, settings, today=None):
    if slot_lines:
        return [
            "Would you be open to a coffee chat %s? Any of the following "
            "windows work on my end:" % _horizon(slot_lines, today),
            _slot_block(slot_lines, settings.get("tz_label") or "ET"),
        ]
    return ["Would you be open to a coffee chat in the next couple of weeks?"]


# ------------------------------------------------------------- the sentences

def _hint(item):
    """What the app found in common, said plainly. Only facts from the two
    profiles; nothing about any particular user."""
    kind = item["kind"]
    if kind == "employer":
        return "you both worked at %s" % item["company"]
    if kind == "school":
        return "you both studied at %s" % item["school"]
    if kind == "arc":
        return ("tech background like yours, and went back into tech for "
                "their internship at %s" % item.get("company"))
    if kind == "nontrad":
        return ("non-traditional background, built outside the US"
                if item.get("international") else "non-traditional background")
    if kind == "discipline":
        return "tech background, like yours"
    if kind == "experience":
        return "%s of experience, similar to yours" % item["years"]
    if kind == "country":
        return "you both built careers in %s" % item["country"]
    return ""


def found_in_common(mine, theirs):
    if not (mine and theirs):
        return []
    ground = matching.common_ground(mine, theirs)
    if any(g["kind"] == "arc" for g in ground):
        # "went back into tech" already says they come from tech.
        ground = [g for g in ground if g["kind"] != "discipline"]
    hints = [_hint(g) for g in ground if g.get("hook") or g["kind"] == "country"]
    return [h for h in hints if h]


def background_paragraph(settings):
    """Settings → background, as written, then the Goizueta line."""
    written = (settings.get("user_pitch") or "").strip()
    if not written:
        written = ("[Your background in one or two sentences: your role, the "
                   "company, and one concrete fact about what you owned.]")
    if "now at goizueta" in written.lower():
        return written
    return written + " " + NOW_AT_GOIZUETA


def hook_paragraph(mine, theirs):
    hints = found_in_common(mine, theirs)
    if hints:
        prompt = ("[The one thing on their profile that made you reach out, "
                  "starting with “I see that…”. Found on their profile: %s.]"
                  % "; ".join(h[0].upper() + h[1:] for h in hints))
    else:
        prompt = ("[The one thing about their path that made you reach out, "
                  "starting with “I see that…”.]")
    return (prompt + " I would love to chat with you to discuss how you "
            "navigated the recruiting process and your MBA journey in general.")


# ---------------------------------------------------------------- the emails

def outreach(person, settings, slot_lines, mine=None, theirs=None, today=None):
    """The first ask. Works with or without their LinkedIn PDF."""
    intro = "I'm a first-year MBA student at Goizueta."
    if person.get("referred_by_name"):
        intro += (" I spoke with %s recently, and they suggested I reach out "
                  "to you." % person["referred_by_name"])
    else:
        intro += (" [One line on how you know them — It was a pleasure "
                  "connecting with you during GCC, or where you met them.]")

    closing = "Happy to work around whatever is easiest for you."
    if settings.get("resume_ready"):
        closing += " I've attached my resume for reference."
    if slot_lines:
        closing += " I will send you the calendar invite once we finalize the time."

    paragraphs = [
        "Hi %s," % first_name(person.get("name")),
        "I hope you're doing well!",
        intro,
        background_paragraph(settings),
        hook_paragraph(mine or {}, theirs or {}),
    ] + _slot_paragraphs(slot_lines, settings, today) + [closing, SIGN_OFF]

    body = _finish(paragraphs)
    return {"subject": _subject(settings), "body": body, "unfilled": unfilled(body)}


def followup(person, settings, slot_lines, today=None):
    """The nudge. Short, fixed, no placeholders — an optional bracket would
    still block opening it in Outlook."""
    if slot_lines:
        ask = [("If you do have half an hour %s, I would still love to hear "
                "about your experience. Any of the following windows work on "
                "my end:" % _horizon(slot_lines, today)),
               _slot_block(slot_lines, settings.get("tz_label") or "ET")]
    else:
        ask = ["If you do have half an hour in the next couple of weeks, I "
               "would still love to hear about your experience."]
    paragraphs = [
        "Hi %s," % first_name(person.get("name")),
        "I hope you're doing well!",
        "I wanted to follow up on my earlier email about a coffee chat. I "
        "understand how busy the job can get, so no pressure at all if the "
        "timing doesn't work.",
    ] + ask + ["Happy to work around whatever is easiest for you.", SIGN_OFF]
    body = _finish(paragraphs)
    return {"subject": _subject(settings, "Following up - "), "body": body,
            "unfilled": unfilled(body)}


def thankyou(person, settings, highlights=""):
    """Sent within 24 hours. Left as a scaffold on purpose: the specifics come
    out of the conversation you just had, and only you were in it."""
    firm = person.get("firm") or "the firm"
    specifics = highlights.strip() if highlights.strip() else (
        "[The most important part of the conversation — a key learning, a story "
        "they told, something that shows you were listening.]"
    )

    paragraphs = [
        "Hi %s," % first_name(person.get("name")),
        "Thank you so much for taking the time to speak with me. I know that "
        "is a real slice of your week, and I appreciated it.",
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
