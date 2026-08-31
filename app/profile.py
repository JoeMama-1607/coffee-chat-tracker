"""Turn a pasted LinkedIn profile into a prep sheet.

LinkedIn is behind authentication and blocks automated fetching, so nothing
here goes near the network. You copy the profile, paste it in, and this module
reads the career out of it: roles, companies, how long each lasted, education.

From those facts it derives *signals* — a career switcher, a recent promotion,
six years at one firm, the same business school as you — and each signal earns
a question that could only be asked of this person. That is the difference the
GCA deck draws between a good question and a great one: a great one carries a
specific observation and your own context into it.
"""

import datetime as dt
import re

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7,
    "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

SECTION_HEADERS = [
    "about", "experience", "education", "skills", "licenses & certifications",
    "licenses and certifications", "certifications", "volunteering",
    "volunteer experience", "honors & awards", "honors and awards",
    "projects", "publications", "languages", "recommendations",
    "interests", "activity", "courses", "organizations", "top skills",
]

EMPLOYMENT_TYPES = [
    "full-time", "part-time", "internship", "contract", "freelance",
    "self-employed", "apprenticeship", "seasonal", "permanent",
    "on-site", "onsite", "remote", "hybrid",
]

COMPANY_HINT = re.compile(
    r"(?:^|\s)(?:inc\.?|llc|ltd\.?|llp|plc|gmbh|s\.a\.|n\.v\.|pvt\.?|"
    r"& co\.?|& company|company|group|partners|consulting|consultants|"
    r"technologies|systems|solutions|labs|laboratories|university|college|"
    r"school|bank|capital|ventures|holdings|corp\.?|corporation|associates|"
    r"institute|foundation|agency|studios?)$",
    re.I,
)

DURATION_ONLY = re.compile(r"^\d+\s*(?:yrs?|years?|mos?|months?)\b", re.I)

CONSULTING_FIRMS = [
    "mckinsey", "bain", "boston consulting", "bcg", "deloitte", "accenture",
    "kearney", "a.t. kearney", "strategy&", "pwc", "ey", "ernst & young",
    "ey-parthenon", "parthenon", "kpmg", "oliver wyman", "l.e.k", "lek",
    "roland berger", "alixpartners", "alvarez & marsal", "simon-kucher",
    "zs associates", "putnam", "clearview", "analysis group", "cornerstone",
    "charles river associates", "huron", "navigant", "guidehouse", "slalom",
    "west monroe", "mercer", "willis towers watson", "korn ferry",
]

DEGREE_PATTERNS = [
    (r"\bm\.?b\.?a\b|master of business administration", "MBA"),
    (r"\bph\.?d\b|doctor of philosophy", "PhD"),
    (r"\bj\.?d\b|juris doctor", "JD"),
    (r"\bm\.?d\b\.?(?!\w)|doctor of medicine", "MD"),
    (r"\bm\.?s\.?c?\b|master of science|master's|masters", "Master's"),
    (r"\bm\.?eng\b", "MEng"),
    (r"\bb\.?s\.?c?\b|bachelor of science", "BS"),
    (r"\bb\.?a\b|bachelor of arts", "BA"),
    (r"\bb\.?tech\b|bachelor of technology", "BTech"),
    (r"\bbachelor", "Bachelor's"),
]

DATE_RANGE = re.compile(
    r"^(?P<start>(?:[A-Za-z]{3,9}\s+)?\d{4})\s*[-–—to]{1,3}\s*"
    r"(?P<end>present|current|(?:[A-Za-z]{3,9}\s+)?\d{4})\b",
    re.I,
)
YEAR_RANGE = re.compile(r"\b(?P<start>\d{4})\s*[-–—]\s*(?P<end>\d{4}|present)\b", re.I)


# ------------------------------------------------------------------ parsing

def _clean_lines(text):
    """LinkedIn's clipboard output repeats most lines for screen readers."""
    lines = []
    for raw in (text or "").splitlines():
        line = raw.replace(" ", " ").strip()
        line = re.sub(r"\s+", " ", line)
        if not line:
            continue
        if lines and line.lower() == lines[-1].lower():
            continue  # the duplicate-line artifact
        lines.append(line)
    return lines


def _parse_month_year(text):
    text = (text or "").strip().lower()
    if text in ("present", "current"):
        return None
    match = re.match(r"^(?:([a-z]{3,9})\s+)?(\d{4})$", text)
    if not match:
        return None
    month_name, year = match.groups()
    month = MONTHS.get(month_name[:3], 1) if month_name else 1
    return (int(year), month)


def _months_between(start, end):
    if not start:
        return None
    today = dt.date.today()
    end = end or (today.year, today.month)
    return max(0, (end[0] - start[0]) * 12 + (end[1] - start[1]))


def humanise_months(months):
    if months is None:
        return ""
    years, rest = divmod(months, 12)
    parts = []
    if years:
        parts.append("%d yr%s" % (years, "" if years == 1 else "s"))
    if rest or not years:
        parts.append("%d mo%s" % (rest, "" if rest == 1 else "s"))
    return " ".join(parts)


def _is_section_header(line):
    return line.strip().lower().rstrip(":") in SECTION_HEADERS


def _looks_like_noise(line):
    low = line.lower()
    if len(line) < 2:
        return True
    if low.startswith(("logo", "http", "www.", "linkedin.com", "· ", "•")):
        return True
    if re.match(r"^\d+ (followers?|connections?|mutual)", low):
        return True
    if low in ("show all", "see more", "…see more", "show more", "message",
               "connect", "follow", "more", "endorsements"):
        return True
    if re.match(r"^\d+\s*(yrs?|mos?)\b", low):  # bare duration line
        return True
    return False


def _split_sections(lines):
    sections = {"_header": []}
    current = "_header"
    for line in lines:
        if _is_section_header(line):
            current = line.strip().lower().rstrip(":")
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
    return sections


def _strip_meta(line):
    """'Bain & Company · Full-time · On-site' -> ('Bain & Company', True)."""
    parts = [p.strip() for p in re.split(r"\s+·\s+", line)]
    had_meta = False
    while len(parts) > 1 and parts[-1].lower() in EMPLOYMENT_TYPES:
        parts.pop()
        had_meta = True
    return " · ".join(parts).strip(), had_meta


def _looks_like_company(line):
    low = (line or "").strip().lower()
    if not low:
        return False
    if any(firm in low for firm in CONSULTING_FIRMS):
        return True
    return bool(COMPANY_HINT.search(low))


PLACE_WORDS = re.compile(
    r"^(remote|hybrid|on-?site|greater .+ area|.+ metropolitan area)$", re.I)


def _looks_like_place(line):
    text, _ = _strip_meta(line)
    text = text.strip()
    if PLACE_WORDS.match(text):
        return True
    if _looks_like_company(text):
        return False          # 'Something, Inc.' is an employer, not a city
    if any(ch.isdigit() for ch in text):
        return False
    # 'Atlanta, Georgia, United States' — a place has commas, a job title doesn't
    return bool(re.match(r"^[^,]+(?:,\s*[^,]+){1,3}$", text)) and len(text) < 70


def _an(word):
    return "an" if word[:1].lower() in "aeiou" else "a"


def _classify(lines):
    """Label every line so the position blocks can be read reliably."""
    kinds = []
    for line in lines:
        if DATE_RANGE.match(line):
            kinds.append("date")
        elif DURATION_ONLY.match(line):
            kinds.append("duration")
        elif _looks_like_noise(line):
            kinds.append("noise")
        else:
            kinds.append("text")
    # A line directly beneath a date range is that position's location — but
    # only if it actually reads like a place. Positions often have no location
    # at all, in which case the next line is the following role's title, and
    # mislabelling it loses that role's title entirely.
    for i in range(1, len(kinds)):
        if kinds[i] == "text" and kinds[i - 1] == "date" and _looks_like_place(lines[i]):
            kinds[i] = "location"
    return kinds


def _parse_experience(lines):
    """Read roles out of the Experience section.

    LinkedIn produces two layouts. Grouped: a company heading, a total
    duration, then several titles each with dates. Per-role: title, then
    'Company · Full-time', then dates. The date line is the reliable anchor in
    both, so each position is read backwards from it, and which of the two
    lines above is the title is decided on evidence rather than assumed.
    """
    kinds = _classify(lines)
    roles = []
    group_company = ""

    for index, line in enumerate(lines):
        if kinds[index] == "duration":
            # A bare total duration marks a grouped company heading above it.
            step = index - 1
            while step >= 0 and kinds[step] not in ("text",):
                step -= 1
            if step >= 0:
                candidate, _ = _strip_meta(lines[step])
                group_company = candidate
            continue

        if kinds[index] != "date":
            continue

        match = DATE_RANGE.match(line)
        start = _parse_month_year(match.group("start"))
        end = _parse_month_year(match.group("end"))
        is_current = match.group("end").lower() in ("present", "current")

        # Collect up to two lines above, stopping at anything that marks the
        # end of the previous position block.
        above = []
        step = index - 1
        while step >= 0 and len(above) < 2:
            if kinds[step] in ("date", "duration", "location"):
                break
            if kinds[step] == "noise":
                step -= 1
                continue
            above.append(lines[step])
            step -= 1

        first = above[0] if above else ""
        second = above[1] if len(above) > 1 else ""
        first_clean, first_meta = _strip_meta(first)
        second_clean, _ = _strip_meta(second)

        if first_meta:
            # 'Company · Full-time' sits directly above the dates
            company, title = first_clean, second_clean
        elif _looks_like_company(first_clean) and not _looks_like_company(second_clean):
            company, title = first_clean, second_clean
        elif second_clean and _looks_like_company(second_clean):
            title, company = first_clean, second_clean
        elif group_company:
            title, company = first_clean, group_company
        else:
            title, company = first_clean, second_clean

        roles.append({
            "title": title,
            "company": company,
            "start": start,
            "end": end,
            "current": is_current,
            "months": _months_between(start, end),
        })

    roles.sort(key=lambda r: r["start"] or (0, 0), reverse=True)
    return roles


def _parse_education(lines):
    education = []
    pending_school = None
    for line in lines:
        if _looks_like_noise(line):
            continue
        years = YEAR_RANGE.search(line)
        degree = None
        low = line.lower()
        for pattern, label in DEGREE_PATTERNS:
            if re.search(pattern, low):
                degree = label
                break
        if degree:
            education.append({
                "school": pending_school or "",
                "degree": degree,
                "detail": line,
                "years": years.group(0) if years else "",
            })
            pending_school = None
        elif years and education and not education[-1]["years"]:
            education[-1]["years"] = years.group(0)
        elif not years:
            pending_school = line
    if pending_school and not education:
        education.append({"school": pending_school, "degree": "",
                          "detail": pending_school, "years": ""})
    return education


def parse(text):
    lines = _clean_lines(text)
    if not lines:
        return {"ok": False, "reason": "empty"}

    sections = _split_sections(lines)
    header = [l for l in sections.get("_header", []) if not _looks_like_noise(l)]

    name = header[0] if header else ""
    headline = header[1] if len(header) > 1 else ""
    location = ""
    for line in header[2:5]:
        if re.search(r",\s*[A-Za-z ]+$", line) and len(line) < 70:
            location = line
            break

    if "experience" in sections:
        roles = _parse_experience(sections["experience"])
    else:
        # A partial paste with no section headings at all — read the lot.
        roles = _parse_experience(lines)
    education = _parse_education(sections.get("education", []))
    about = " ".join(sections.get("about", []))[:900]

    return {
        "ok": bool(roles or education),
        "name": name,
        "headline": headline,
        "location": location,
        "roles": roles,
        "education": education,
        "about": about,
        "line_count": len(lines),
    }


# ------------------------------------------------------------------ signals

def _is_consulting(company):
    low = (company or "").lower()
    return any(firm in low for firm in CONSULTING_FIRMS)


def _company_group(roles, company):
    return [r for r in roles if r["company"].lower() == (company or "").lower()]


def detect_signals(profile, person, settings):
    """The specific, checkable facts that a question can be hung on."""
    signals = []
    roles = profile.get("roles") or []
    education = profile.get("education") or []
    if not roles and not education:
        return signals

    current = next((r for r in roles if r["current"]), roles[0] if roles else None)
    company = (current or {}).get("company") or person.get("firm") or ""

    # Tenure at the current employer, across all their titles there
    group = _company_group(roles, company) if company else []
    if group:
        starts = [r["start"] for r in group if r["start"]]
        total = _months_between(min(starts), None) if starts else None
        if total is not None:
            if total >= 48:
                signals.append({
                    "key": "long_tenure", "label": "%s at %s" % (humanise_months(total), company),
                    "company": company, "months": total,
                })
            elif total < 18:
                signals.append({
                    "key": "new_joiner", "label": "%s into %s" % (humanise_months(total), company),
                    "company": company, "months": total,
                })

        # More than one title at the same employer means a promotion
        titles = [r["title"] for r in group if r["title"]]
        unique = list(dict.fromkeys(titles))
        if len(unique) > 1:
            signals.append({
                "key": "promoted",
                "label": "%s → %s at %s" % (unique[-1], unique[0], company),
                "company": company, "from": unique[-1], "to": unique[0],
                "months": total,
            })

    # A pivot into consulting from another industry
    if company and _is_consulting(company):
        prior = [r for r in roles
                 if r["company"] and not _is_consulting(r["company"])
                 and r["company"].lower() != company.lower()]
        if prior:
            earlier = prior[0]
            signals.append({
                "key": "career_switch",
                "label": "Came from %s" % earlier["company"],
                "prior_company": earlier["company"],
                "prior_title": earlier["title"],
                "year": (earlier["end"] or (0, 0))[0] or "",
            })

    # More than one consulting firm on the CV
    firms = list(dict.fromkeys(
        r["company"] for r in roles if r["company"] and _is_consulting(r["company"])))
    if len(firms) > 1:
        signals.append({
            "key": "multi_firm", "label": "Worked at %s and %s" % (firms[0], firms[1]),
            "firm_a": firms[1], "firm_b": firms[0],
        })

    # Education
    for entry in education:
        if entry["degree"] == "MBA":
            school = entry["school"] or entry["detail"]
            signals.append({"key": "mba", "label": "MBA, %s" % school, "school": school})
            break

    school_text = " ".join(
        (e.get("school", "") + " " + e.get("detail", "")) for e in education).lower()
    if "goizueta" in school_text or "emory" in school_text:
        signals.append({"key": "same_school", "label": "Goizueta / Emory alum",
                        "school": "Goizueta"})

    if person.get("is_alum") and not any(s["key"] == "same_school" for s in signals):
        signals.append({"key": "same_school", "label": "Goizueta alum (from your notes)",
                        "school": "Goizueta"})

    return signals


# ---------------------------------------------------------------- summarising

def summarise(profile, person, signals):
    """Three or four sentences, all of them checkable against the profile."""
    name = (person.get("name") or profile.get("name") or "They").split(" ")[0]
    roles = profile.get("roles") or []
    bits = []

    current = next((r for r in roles if r["current"]), roles[0] if roles else None)
    if current and current.get("company"):
        tenure = ""
        group = _company_group(roles, current["company"])
        starts = [r["start"] for r in group if r["start"]]
        if starts:
            tenure = humanise_months(_months_between(min(starts), None))
        opening = "%s is %s at %s" % (
            name,
            ("%s %s" % (_an(current["title"]), current["title"]))
            if current.get("title") else "working",
            current["company"],
        )
        if profile.get("location"):
            opening += " in %s" % profile["location"].split(",")[0]
        if tenure:
            opening += ", and has been there %s" % tenure
        bits.append(opening + ".")
    elif person.get("firm"):
        bits.append("%s works at %s%s." % (
            name, person["firm"],
            (" as %s" % person["role"]) if person.get("role") else ""))

    promoted = next((s for s in signals if s["key"] == "promoted"), None)
    if promoted:
        bits.append("They moved up from %s to %s there." % (promoted["from"], promoted["to"]))

    switch = next((s for s in signals if s["key"] == "career_switch"), None)
    if switch:
        bits.append("Before consulting they were at %s%s — so this is a career they "
                    "chose deliberately, not one they fell into." % (
                        switch["prior_company"],
                        (" as %s" % switch["prior_title"]) if switch.get("prior_title") else ""))

    # Only genuinely earlier employers — repeating the current one after the
    # promotion sentence reads like padding.
    current_company = (current or {}).get("company", "").lower()
    prior_roles = [r for r in roles[1:]
                   if r.get("company") and r["company"].lower() != current_company]
    if not switch and prior_roles:
        bits.append("Earlier: %s." % ", ".join(
            "%s at %s" % (r["title"], r["company"]) if r["title"] else r["company"]
            for r in prior_roles[:2]))

    mba = next((s for s in signals if s["key"] == "mba"), None)
    same = next((s for s in signals if s["key"] == "same_school"), None)
    if same:
        bits.append("They came through Goizueta as well, which is the strongest "
                    "opening you have — use it in the first minute.")
    elif mba:
        bits.append("They have an MBA from %s." % mba["school"])

    tenure_signal = next((s for s in signals if s["key"] == "long_tenure"), None)
    new_signal = next((s for s in signals if s["key"] == "new_joiner"), None)
    if tenure_signal:
        bits.append("That length of tenure means they have watched the place change, "
                    "so they will have a real view on what keeps people there.")
    elif new_signal:
        bits.append("Being early in the job, their memory of recruiting and the first "
                    "months will be fresh and unusually candid.")

    return " ".join(b for b in bits if b)


# ----------------------------------------------------------------- questions

def _tailored(signals, person, settings):
    company = person.get("firm") or ""
    out = []
    for signal in signals:
        key = signal["key"]
        if key == "career_switch":
            out.append({
                "tier": "great", "why": signal["label"],
                "text": "You moved into consulting from %s. I'm coming from "
                        "[your background], and I'd guess [the skill you think "
                        "transfers] carries over while [the gap you expect] "
                        "doesn't. What actually transferred for you, and what did "
                        "you have to rebuild from scratch?" % signal["prior_company"],
            })
        elif key == "promoted":
            out.append({
                "tier": "great", "why": signal["label"],
                "text": "You went from %s to %s at %s. What did that step up "
                        "actually demand that the level below it didn't?"
                        % (signal["from"], signal["to"], signal["company"]),
            })
        elif key == "long_tenure":
            out.append({
                "tier": "great", "why": signal["label"],
                "text": "%s is a long run in this industry. What has kept you "
                        "there — and what would have made you leave?"
                        % humanise_months(signal["months"]).capitalize(),
            })
        elif key == "new_joiner":
            out.append({
                "tier": "great", "why": signal["label"],
                "text": "You're about %s into %s. What has surprised you most "
                        "compared to the picture you had during recruiting?"
                        % (humanise_months(signal["months"]), signal["company"]),
            })
        elif key == "multi_firm":
            out.append({
                "tier": "great", "why": signal["label"],
                "text": "You've been at both %s and %s. Externally the firms say "
                        "very similar things — from the inside, what actually "
                        "differed day to day?" % (signal["firm_a"], signal["firm_b"]),
            })
        elif key == "same_school":
            out.append({
                "tier": "great", "why": signal["label"],
                "text": "We came through Goizueta the same way. What do you wish "
                        "someone had told you during recruiting that nobody did?",
            })
        elif key == "mba":
            out.append({
                "tier": "great", "why": signal["label"],
                "text": "You did your MBA before %s. Looking back, which parts of "
                        "it actually mattered once you were on projects, and which "
                        "turned out to be noise?" % (company or "this role"),
            })
    return out[:3]


def _culture(signals, person):
    """Career growth, team dynamics, and inclusion — asked so they can't be
    answered with the recruiting-brochure line."""
    company = person.get("firm") or "the firm"
    promoted = next((s for s in signals if s["key"] == "promoted"), None)
    tenure = next((s for s in signals if s["key"] == "long_tenure"), None)

    growth = ("You've been promoted there, so you've seen the mechanism up close — "
              "is progression at %s driven by tenure, by sponsorship, or by which "
              "projects you land?" % company) if promoted else (
             "How does progression actually work at %s — is it tenure, sponsorship, "
             "or the projects you manage to land?" % company)

    team = ("Across %s you must have seen a lot of teams. What separates a good one "
            "from a bad one there, and how much does the manager change the "
            "experience of the same firm?" % humanise_months(tenure["months"])) if tenure else (
           "What does a good team feel like at %s, and how much does the partner or "
           "manager change what the same firm feels like?" % company)

    inclusion = ("Beyond the recruiting numbers, what does %s actually do day to day "
                 "that makes people feel they belong — and where do you think it "
                 "still falls short?" % company)

    return [
        {"theme": "Career growth", "text": growth},
        {"theme": "Team dynamics", "text": team},
        {"theme": "Inclusion", "text": inclusion},
    ]


def _journey(signals, person):
    company = person.get("firm") or "the firm"
    switch = next((s for s in signals if s["key"] == "career_switch"), None)

    motivation = ("What made you choose %s over the other options you had at the "
                  "time?" % company) if not switch else (
                 "What made consulting the answer rather than staying on the path "
                 "you were already on?")

    return [
        {"theme": "Motivation", "text": motivation},
        {"theme": "Skills", "text": "What skill have you built there that you didn't "
                                    "expect to when you joined?"},
        {"theme": "Challenges", "text": "What was the hardest stretch of your first "
                                        "year, and what got you through it?"},
    ]


def opener(profile, person, signals):
    """The first two minutes. Specific beats warm."""
    same = next((s for s in signals if s["key"] == "same_school"), None)
    if same:
        return ("Open on Goizueta — you're both from the same programme. Ask what "
                "their year was like before you ask anything about the firm.")
    switch = next((s for s in signals if s["key"] == "career_switch"), None)
    if switch:
        return ("Open on the pivot: you noticed they came from %s, and that is "
                "exactly the move you're weighing." % switch["prior_company"])
    new = next((s for s in signals if s["key"] == "new_joiner"), None)
    if new:
        return ("Open on how new the role still is — ask how the first months have "
                "compared to what they expected.")
    if profile.get("location"):
        return ("Open on %s — where they're based, whether the office feels "
                "different from the rest of the firm." % profile["location"].split(",")[0])
    if profile.get("headline"):
        return "Open on something specific in their headline: \"%s\"." % profile["headline"]
    return ("Open on something specific you found about them before the call — a "
            "project, a post, a shared connection. Two minutes, no more.")


def build_flow(person, tailored, culture, journey, opening):
    """The 30 minutes, in the order the deck lays the call out."""
    name = (person.get("name") or "them").split(" ")[0]
    lead_tailored = tailored[0]["text"] if tailored else None
    return [
        {"span": "0–2 min", "stage": "First impression",
         "detail": opening},
        {"span": "2–3 min", "stage": "Set the structure",
         "detail": "\"Thank you for taking the time. I'd like to introduce myself "
                   "briefly and then hear more about your experience — does that "
                   "work for you?\""},
        {"span": "3–5 min", "stage": "Your resume walk",
         "detail": "90 seconds to 2 minutes. Thread your history into why "
                   "consulting. Stop talking at 2 minutes even if you aren't done."},
        {"span": "5–13 min", "stage": "Their journey",
         "detail": (lead_tailored or journey[0]["text"]) +
                   " Then motivation, skills, and the hardest stretch."},
        {"span": "13–22 min", "stage": "Company culture",
         "detail": "Growth first (it's the least awkward), then team dynamics, then "
                   "inclusion. Follow the answer rather than the list."},
        {"span": "22–26 min", "stage": "Forward-looking",
         "detail": "What they'd do differently, and what they think you should be "
                   "doing now. This is where the useful advice usually lands."},
        {"span": "26–30 min", "stage": "Close",
         "detail": "Thank %s, ask whether there is anyone else at the firm you "
                   "should speak to, and say you'll follow up. Then actually send "
                   "the note within 24 hours." % name},
    ]


def prep_sheet(person, settings):
    """Everything the Prep button needs."""
    raw = person.get("linkedin_raw") or ""
    profile = parse(raw) if raw.strip() else {"ok": False, "reason": "missing"}

    if not profile.get("ok"):
        culture = _culture([], person)
        journey = _journey([], person)
        opening = opener({}, person, [])
        return {
            "has_profile": False,
            "reason": profile.get("reason", "missing"),
            "linkedin": person.get("linkedin", ""),
            "parsed_nothing": bool(raw.strip()),
            "opener": opening,
            "culture": culture,
            "journey": journey,
            "tailored": [],
            "flow": build_flow(person, [], culture, journey, opening),
        }

    signals = detect_signals(profile, person, settings)
    tailored = _tailored(signals, person, settings)
    culture = _culture(signals, person)
    journey = _journey(signals, person)
    opening = opener(profile, person, signals)

    timeline = []
    for role in profile["roles"][:8]:
        when = ""
        if role["start"]:
            when = "%d" % role["start"][0]
            when += " – %s" % ("Present" if role["current"]
                               else (str(role["end"][0]) if role["end"] else "?"))
        timeline.append({
            "title": role["title"], "company": role["company"],
            "when": when, "length": humanise_months(role["months"]),
            "current": role["current"],
        })

    return {
        "has_profile": True,
        "name": profile.get("name") or person.get("name"),
        "headline": profile.get("headline", ""),
        "location": profile.get("location", ""),
        "summary": summarise(profile, person, signals),
        "signals": [{"key": s["key"], "label": s["label"]} for s in signals],
        "timeline": timeline,
        "education": profile.get("education", []),
        "tailored": tailored,
        "culture": culture,
        "journey": journey,
        "opener": opening,
        "flow": build_flow(person, tailored, culture, journey, opening),
    }
