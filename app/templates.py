"""Email scaffolds.

The GCA deck is blunt that "email templates suck, and everybody knows when
they've received one". So these are deliberately scaffolds, not templates: the
mechanical parts (subject line, slot block, signature, resume reminder) are
filled in, and everything that has to sound like you is left as a [bracketed
prompt] that the app refuses to let you forget about.
"""

import re

BRACKET = re.compile(r"\[[^\[\]]{3,400}?\]", re.S)


def unfilled(text):
    """Every [prompt] still sitting in the draft."""
    return BRACKET.findall(text or "")


def signature(settings):
    lines = ["Best,", settings.get("user_name", "").strip() or "[Your name]"]
    for key in ("user_program", "user_school"):
        value = (settings.get(key) or "").strip()
        if value:
            lines.append(value)
    contact = []
    if settings.get("user_email"):
        contact.append(settings["user_email"].strip())
    if settings.get("user_phone"):
        contact.append(settings["user_phone"].strip())
    if contact:
        lines.append(" | ".join(contact))
    if settings.get("user_linkedin"):
        lines.append(settings["user_linkedin"].strip())
    return "\n".join(lines)


def first_name(full_name):
    return (full_name or "").strip().split(" ")[0] or "there"


def outreach(person, settings, slot_lines):
    """The initial ask. Mirrors the structure of the deck's example email."""
    name = settings.get("user_name", "").strip() or "[Your name]"
    firm = person.get("firm") or "[their firm]"

    if person.get("referred_by_name"):
        opening = (
            "I'm a first-year MBA student at Emory and had a great conversation with "
            "%s about [what the two of you actually discussed — a specific insight of "
            "theirs, not a summary]. They suggested I reach out to you."
            % person["referred_by_name"]
        )
    elif person.get("is_alum"):
        opening = (
            "I'm a first-year MBA student at Emory's Goizueta Business School, and I "
            "came across your profile while looking at Goizueta alumni at %s. "
            "[One specific thing about their path that genuinely caught your attention.]"
            % firm
        )
    else:
        opening = (
            "I'm a first-year MBA student at Emory's Goizueta Business School. "
            "[How you found them, and the one specific thing about their background "
            "that made you want to talk to them.]"
        )

    slot_block = "\n".join("• " + line for line in slot_lines) if slot_lines else \
        "• [Generate your availability on the Slots tab and paste it here]"

    paragraphs = [
        "Hi %s," % first_name(person.get("name")),
        "I hope you are doing well!",
        opening,
        "Before business school, I worked in [your industry or function, and the kind "
        "of work you did]. Now at Goizueta, I'm exploring consulting and would love to "
        "hear more about your experience at %s and [the specific thing you want their "
        "perspective on — a practice area, the transition, how your background "
        "translates]." % firm,
        "I would be grateful if you were available for a quick coffee chat sometime in "
        "the next couple of weeks. Please let me know if any of the time slots below "
        "work for you:",
        slot_block,
        "I have attached my resume for your reference. Thank you for considering this "
        "request, and I look forward to connecting with you!",
        signature(settings),
    ]
    body = "\n\n".join(paragraphs)

    subject = "Goizueta Student Coffee Chat Request - %s" % name
    return {"subject": subject, "body": body, "unfilled": unfilled(body)}


def thankyou(person, settings, highlights=""):
    """Sent within 24 hours. Specific, grateful, and it climbs the ladder."""
    firm = person.get("firm") or "[their firm]"
    specifics = highlights.strip() if highlights.strip() else (
        "[The most important part of the conversation — a key learning, a story "
        "they told, something that shows you were listening.]"
    )

    when = "today" if not person.get("chat_at") else "on " + str(person["chat_at"])[:10]
    paragraphs = [
        "Hi %s," % first_name(person.get("name")),
        "Thank you so much for taking the time to speak with me %s. I know that is a "
        "real slice of your week, and I appreciated it." % when,
        specifics,
        "[One line on what you're doing differently as a result — this is what makes "
        "the note read as a continuation rather than a formality.]",
        "If there is anyone else at %s whose path I should hear about, I would be glad "
        "to be introduced. Either way, I'll keep you posted on how recruiting goes, and "
        "I hope we can catch up again soon." % firm,
        signature(settings),
    ]
    body = "\n\n".join(paragraphs)

    return {
        "subject": "Thank you - %s" % (settings.get("user_name", "").strip() or "coffee chat"),
        "body": body,
        "unfilled": unfilled(body),
    }


def followup(person, settings, slot_lines):
    """The polite nudge after roughly a week of silence."""
    slot_block = "\n".join("• " + line for line in slot_lines) if slot_lines else \
        "• [Fresh availability from the Slots tab]"

    paragraphs = [
        "Hi %s," % first_name(person.get("name")),
        "I wanted to follow up gently on my note from a couple of weeks ago. I know "
        "this is a busy stretch, so no pressure at all if the timing doesn't work.",
        "If you do have half an hour in the next two weeks, I'd still love to hear "
        "about your experience at %s. Updated availability below:"
        % (person.get("firm") or "[their firm]"),
        slot_block,
        "Thanks again for considering it.",
        signature(settings),
    ]
    body = "\n\n".join(paragraphs)

    return {
        "subject": "Following up - Goizueta coffee chat request",
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
