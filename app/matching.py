"""Find the thing you and the person you are writing to actually share.

The GCA deck's warning is that everyone can tell when they have been sent a
template. The defence is not better phrasing — it is having something true and
specific to say in the first two lines, which means knowing what the two of you
have in common before you start writing.

So this compares your own profile against theirs and ranks what it finds. Being
at Goizueta together is deliberately *not* in the list: it is how you got their
name, it is true of hundreds of people, and leading with it says nothing. What
earns a mention is a shared employer, a shared university, the same country
behind you, the same discipline, or the same move out of it.

Everything here is drawn from what is actually written in the two profiles. It
never claims a connection that is not on the page.
"""

import re

# Where someone is from, inferred from the places they have worked and studied.
COUNTRY_HINTS = {
    "India": ["india", "mumbai", "bangalore", "bengaluru", "new delhi", "delhi",
              "kolkata", "chennai", "hyderabad", "pune", "gurgaon", "gurugram",
              "noida", "maharashtra", "karnataka", "tamil nadu", "telangana",
              "ahmedabad", "jaipur", "kerala", "vellore"],
    "China": ["china", "beijing", "shanghai", "shenzhen", "guangzhou", "hong kong"],
    "Brazil": ["brazil", "brasil", "são paulo", "sao paulo", "rio de janeiro"],
    "Nigeria": ["nigeria", "lagos", "abuja"],
    "United Kingdom": ["united kingdom", "london", "manchester", "edinburgh"],
    "Canada": ["canada", "toronto", "vancouver", "montreal"],
    "Mexico": ["mexico", "méxico", "mexico city", "monterrey"],
    "Japan": ["japan", "tokyo", "osaka"],
    "South Korea": ["south korea", "seoul"],
    "Germany": ["germany", "berlin", "munich", "frankfurt"],
}

# Broad disciplines, matched against job titles.
DISCIPLINES = [
    ("engineering", ["software engineer", "engineer", "developer", "algorithm",
                     "programmer", "architect", "sde", "full stack", "backend",
                     "frontend", "devops", "embedded"]),
    ("product", ["product manager", "product owner", "product management",
                 "program manager"]),
    ("data", ["data scientist", "data engineer", "machine learning",
              "analytics", "quantitative"]),
    ("finance", ["investment banking", "investment banker", "valuation",
                 "equity research", "chartered accountant", "financial analyst",
                 "corporate finance", "private equity", "venture capital",
                 "audit", "treasury", "controller"]),
    ("consulting", ["consultant", "consulting", "strategy&", "advisory",
                    "engagement manager", "business analyst"]),
    ("operations", ["operations", "supply chain", "logistics", "manufacturing",
                    "process improvement"]),
    ("marketing", ["marketing", "brand", "growth", "demand generation"]),
]

DISCIPLINE_WORDS = {
    "engineering": "engineering",
    "product": "product",
    "data": "data",
    "finance": "finance",
    "consulting": "consulting",
    "operations": "operations",
    "marketing": "marketing",
}

# Schools that mean "we are classmates", which is the thing not worth leading on.
HOME_SCHOOL = ["goizueta", "emory"]

STOP_WORDS = {"the", "and", "of", "for", "inc", "llc", "ltd", "llp", "plc",
              "company", "co", "corporation", "corp", "group", "technologies",
              "technology", "limited", "pvt", "private"}


def _norm(text):
    return re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower()).strip()


def _company_key(name):
    """'Deloitte Touche Tohmatsu LLC' and 'Deloitte' should match."""
    words = [w for w in _norm(name).split() if w not in STOP_WORDS]
    return words[0] if words else ""


def _school_key(name):
    words = [w for w in _norm(name).split() if w not in STOP_WORDS]
    return " ".join(words[:4])


def _is_home_school(name):
    low = (name or "").lower()
    return any(word in low for word in HOME_SCHOOL)


def country_of(profile):
    """Where their career happened before the US, if it is on the page."""
    haystacks = []
    for role in profile.get("roles") or []:
        haystacks.append(role.get("location", ""))
        haystacks.append(role.get("company", ""))
    for entry in profile.get("education") or []:
        haystacks.append(entry.get("school", ""))
    haystacks.append(profile.get("location", ""))
    blob = " ".join(h for h in haystacks if h).lower()

    for country, hints in COUNTRY_HINTS.items():
        if any(hint in blob for hint in hints):
            return country
    return ""


def discipline_of(profile):
    """The discipline they spent the most months in."""
    totals = {}
    for role in profile.get("roles") or []:
        title = (role.get("title") or "").lower()
        months = role.get("months") or 0
        for name, needles in DISCIPLINES:
            if any(needle in title for needle in needles):
                totals[name] = totals.get(name, 0) + max(months, 1)
                break
    if not totals:
        return ""
    return max(totals.items(), key=lambda kv: kv[1])[0]


def _earliest_roles(profile):
    roles = [r for r in (profile.get("roles") or []) if r.get("start")]
    return sorted(roles, key=lambda r: r["start"])


# ------------------------------------------------------------ hook evidence
#
# What actually earned the opening hook in five real sent emails (Sep 2026):
#
#   Eklavaya  ZS, ~4 yrs, India      -> "just over 4 years ... lower end of the
#                                        spectrum ... I am in a similar position"
#   Jenna     Fiserv HR, ~4 yrs, US  -> same experience-length hook
#   Shivaan   sports media, India    -> "interesting albeit non-traditional
#                                        background, and as an international"
#   Akshansh  Aptiv algorithms ->
#             NVIDIA PM internship   -> "Tech background as well ... went back
#                                        into Tech"
#   Exaucee   Oracle, ~3 yrs         -> "Tech background as well with about 3
#                                        years of experience ... similar position"
#
# Present on the page but never used: a shared country (three of the five are
# from India, like me — never named), skills, a contrasting discipline, the
# Goizueta alum flag. So those stay available for the prep sheet but are not
# email hooks. Shared employer/school never came up in the examples; they are
# kept as hooks because they are the most specific facts two profiles can
# share, but that ranking is untested against a real email.

TECH_TITLE_WORDS = ["software", "developer", "algorithm", "sde", "programmer",
                    "full stack", "backend", "frontend", "devops",
                    "data engineer", "machine learning", "data scientist"]
TECH_COMPANIES = ["flipkart", "oracle", "nvidia", "microsoft", "google",
                  "amazon", "meta", "apple", "salesforce", "ibm", "adobe",
                  "intel", "cisco", "sap", "infosys", "tcs", "wipro", "uber",
                  "netflix", "linkedin", "qualcomm", "samsung", "walmart global tech"]
# Backgrounds a consulting class reads as non-traditional. HR, ops, finance,
# engineering are deliberately not here: Jenna (HR) got the experience hook,
# not a non-traditional one.
NONTRAD_WORDS = ["producer", "content", "journalist", "media", "editor",
                 "writer", "sports", "teacher", "army", "navy", "air force",
                 "marine", "military", "artist", "musician", "nurse",
                 "physician", "attorney", "lawyer", "nonprofit", "non-profit"]
STUDENT_TITLE_WORDS = ["intern", "trainee", "student", "teaching assistant",
                       "research assistant", "laboratory assistant",
                       "administrative assistant", "committee", "mba candidate"]
ACADEMIC_WORDS = ["university", "college", "school of", "business school"]
MBA_INTERN_WORDS = ["intern", "summer associate", "summer consultant", "summer"]


def _low(text):
    return (text or "").lower()


def _mba_start(profile):
    """(year, month) the MBA began, from the Goizueta education line."""
    for entry in profile.get("education") or []:
        if _is_home_school(entry.get("school")):
            full = re.findall(r"(?:19|20)\d\d", entry.get("years") or "")
            if full:
                return (int(full[0]), 7)
    return None


def _mba_end_year(profile):
    for entry in profile.get("education") or []:
        if _is_home_school(entry.get("school")):
            full = re.findall(r"(?:19|20)\d\d", entry.get("years") or "")
            if len(full) > 1:
                return int(full[-1])
    return None


def _is_student_role(role):
    title, company = _low(role.get("title")), _low(role.get("company"))
    return (any(w in title for w in STUDENT_TITLE_WORDS)
            or any(w in company for w in ACADEMIC_WORDS))


def pre_mba_roles(profile):
    """Full-time jobs held before business school."""
    cutoff = _mba_start(profile)
    out = []
    for role in profile.get("roles") or []:
        start = role.get("start")
        if not start or (cutoff and tuple(start) >= cutoff):
            continue
        if _is_student_role(role):
            continue
        out.append(role)
    return out


def mba_internships(profile):
    cutoff = _mba_start(profile)
    if not cutoff:
        return []
    return [r for r in profile.get("roles") or []
            if r.get("start") and tuple(r["start"]) >= cutoff
            and any(w in _low(r.get("title")) for w in MBA_INTERN_WORDS)]


def experience_months(profile):
    """Pre-MBA work experience as a class would count it: first to last month
    at the employers where they held a full-time job, internships at those
    same employers included (ZS 'Associate - Intern' is part of Eklavaya's
    'just over 4 years'). Overlapping titles are not double counted."""
    jobs = pre_mba_roles(profile)
    tenure = {}
    for r in jobs:
        k = _company_key(r.get("company"))
        tenure[k] = tenure.get(k, 0) + (r.get("months") or 0)
    # A one-month project gig (Exaucee's Orange Sparkle Ball) is not where
    # her "about 3 years" came from — only employers with 6+ months count.
    keys = {k for k, m in tenure.items() if m >= 6}
    if not keys:
        return 0
    cutoff = _mba_start(profile)
    spans = [r for r in (profile.get("roles") or [])
             if r.get("start") and _company_key(r.get("company")) in keys
             and not (cutoff and tuple(r["start"]) >= cutoff)]
    first = min(tuple(r["start"]) for r in spans)
    last = max(tuple(r.get("end") or r["start"]) for r in spans)
    return (last[0] - first[0]) * 12 + (last[1] - first[1]) + 1


def years_phrase(months):
    """53 -> 'just over 4 years', 33 -> 'about 3 years' — the way I say it."""
    years, rem = divmod(months, 12)
    if years == 0:
        return "about %d months" % months
    if rem == 0:
        return "%d year%s" % (years, "" if years == 1 else "s")
    if rem <= 6:
        return "just over %d year%s" % (years, "" if years == 1 else "s")
    return "about %d years" % (years + 1)


def _is_tech_role(role):
    title, company = _low(role.get("title")), _low(role.get("company"))
    return (any(w in title for w in TECH_TITLE_WORDS)
            or any(re.search(r"\b%s\b" % re.escape(c), company) for c in TECH_COMPANIES)
            or ("product manage" in title))


def is_tech(profile):
    """Most of their pre-MBA months were in tech."""
    jobs = pre_mba_roles(profile)
    total = sum(max(r.get("months") or 0, 1) for r in jobs)
    tech = sum(max(r.get("months") or 0, 1) for r in jobs if _is_tech_role(r))
    return bool(total) and tech * 2 >= total


def is_nontraditional(profile):
    jobs = pre_mba_roles(profile)
    total = sum(max(r.get("months") or 0, 1) for r in jobs)
    hits = sum(max(r.get("months") or 0, 1) for r in jobs
               if any(w in _low(r.get("title")) + " " + _low(r.get("company"))
                      for w in NONTRAD_WORDS))
    return bool(total) and hits * 2 >= total


def worked_abroad(profile):
    """Built their pre-MBA career outside the US (city/country on the roles)."""
    blob = " ".join(_low(r.get("location")) + " " + _low(r.get("company"))
                    for r in pre_mba_roles(profile))
    return any(any(h in blob for h in hints) for hints in COUNTRY_HINTS.values())


def is_year_ahead(mine, theirs):
    """A current Goizueta student in the class above mine — the people whose
    GCA sessions I thank in every one of the real emails."""
    a, b = _mba_end_year(mine), _mba_end_year(theirs)
    return bool(a and b and b == a - 1)


def common_ground(mine, theirs):
    """Everything the two profiles share, strongest first. Items with
    hook=True may open an email; the rest are prep-sheet material only.
    Every item is traceable to a line on one of the two profiles."""
    found = []
    my_roles = mine.get("roles") or []
    their_roles = theirs.get("roles") or []

    # Shared employer — no real example yet, kept as the strongest possible tie.
    my_companies = {_company_key(r.get("company")): r.get("company")
                    for r in my_roles if r.get("company")}
    for role in their_roles:
        key = _company_key(role.get("company"))
        if key and key in my_companies and not _is_home_school(role.get("company")):
            found.append({"kind": "employer", "weight": 100, "hook": True,
                          "label": "Both worked at %s" % role["company"],
                          "company": role["company"]})
            break

    my_tech, their_tech = is_tech(mine), is_tech(theirs)
    my_months, their_months = experience_months(mine), experience_months(theirs)

    # Same background, and they went back into it for the MBA internship
    # (Akshansh: Aptiv -> NVIDIA PM intern).
    if my_tech and their_tech:
        back = [r for r in mba_internships(theirs) if _is_tech_role(r)]
        if back:
            found.append({"kind": "arc", "weight": 95, "hook": True,
                          "label": "Tech before the MBA, back into tech at %s"
                                   % back[0].get("company"),
                          "company": back[0].get("company")})

    # Non-traditional background + built it abroad (Shivaan: sports media, Mumbai).
    if is_nontraditional(theirs):
        intl = worked_abroad(theirs)
        found.append({"kind": "nontrad", "weight": 90 if intl else 55,
                      "hook": True, "international": intl,
                      "label": "Non-traditional background%s"
                               % (", built abroad" if intl else "")})

    # Shared school, not counting Goizueta.
    my_schools = {_school_key(e.get("school")): e.get("school")
                  for e in (mine.get("education") or [])
                  if e.get("school") and not _is_home_school(e.get("school"))}
    for entry in theirs.get("education") or []:
        school = entry.get("school") or ""
        if _is_home_school(school):
            continue
        key = _school_key(school)
        if key and key in my_schools:
            found.append({"kind": "school", "weight": 85, "hook": True,
                          "label": "Both studied at %s" % school, "school": school})
            break

    # Same background (Akshansh, Exaucee: "Tech background as well").
    if my_tech and their_tech:
        found.append({"kind": "discipline", "weight": 80, "hook": True,
                      "label": "Both came from tech", "discipline": "tech"})

    # Similar, short-ish experience (Eklavaya, Jenna, Exaucee). Both at or
    # under ~5 years and within a year and a half of each other.
    if my_months and their_months and their_months <= 60 \
            and abs(my_months - their_months) <= 18:
        found.append({"kind": "experience", "weight": 70, "hook": True,
                      "label": "Similar experience (%s)" % years_phrase(their_months),
                      "months": their_months,
                      "years": years_phrase(their_months)})

    # --- prep-sheet only: present in the examples, never used as a hook.
    my_country, their_country = country_of(mine), country_of(theirs)
    if my_country and my_country == their_country and my_country != "United States":
        found.append({"kind": "country", "weight": 30, "hook": False,
                      "label": "Both built careers in %s" % my_country,
                      "country": my_country})

    my_discipline, their_discipline = discipline_of(mine), discipline_of(theirs)
    if my_discipline and their_discipline and my_discipline != their_discipline:
        found.append({"kind": "pivot", "weight": 20, "hook": False,
                      "label": "%s to %s" % (DISCIPLINE_WORDS[my_discipline],
                                             DISCIPLINE_WORDS[their_discipline]),
                      "from": my_discipline, "to": their_discipline})

    my_skills = {s.lower() for s in (mine.get("skills") or [])}
    shared = [s for s in (theirs.get("skills") or []) if s.lower() in my_skills]
    if shared:
        found.append({"kind": "skills", "weight": 10, "hook": False,
                      "label": "Shared skills: %s" % ", ".join(shared[:3]),
                      "phrase": "we have both worked in %s" % shared[0]})

    found.sort(key=lambda item: -item["weight"])
    return found


def email_hooks(ground):
    """The one or two facts the opening paragraph uses.

    Only tech background + similar experience ever appeared together
    (Exaucee); every other real email used exactly one fact."""
    hooks = [g for g in ground if g.get("hook")]
    if not hooks:
        return []
    top = hooks[0]
    if top["kind"] == "discipline":
        exp = next((g for g in hooks if g["kind"] == "experience"), None)
        return [top, exp] if exp else [top]
    return [top]


def conversation_angles(mine, theirs, person=None):
    """The overlap turned into something you can actually say on the call.

    The email gets one line out of the strongest tie. A half hour needs more:
    what you share, why it is worth raising, and the question it earns — each
    one answerable only by this person, which is the whole difference between
    a good question and a great one.
    """
    person = person or {}
    firm = person.get("firm") or "the firm"
    angles = []

    for item in common_ground(mine, theirs):
        kind = item["kind"]

        if kind == "employer":
            company = item["company"]
            angles.append({
                "label": item["label"],
                "note": "The strongest opening you have. Shared ground with a "
                        "stranger buys you candour almost immediately.",
                "question": "We overlapped at %s, so I know how it works there. "
                            "What carried over into %s, and what did you have to "
                            "unlearn?" % (company, firm),
            })

        elif kind == "school":
            school = item["school"]
            angles.append({
                "label": item["label"],
                "note": "Worth raising early — it explains why you picked them "
                        "out rather than anyone else at the firm.",
                "question": "We came through %s. Looking back, what from there "
                            "actually mattered once you were on projects?" % school,
            })

        elif kind == "country":
            country = item["country"]
            angles.append({
                "label": item["label"],
                "note": "They have already made the move you are in the middle "
                        "of. Ask about the mechanics, not the sentiment — visa "
                        "timing, recruiting differences, how long it took to "
                        "feel fluent in the process.",
                "question": "You built your career in %s before coming here. "
                            "What did you have to learn about US recruiting that "
                            "nobody warned you about?" % country,
            })

        elif kind == "arc":
            angles.append({
                "label": item["label"],
                "note": "They started where you did and chose to go back to it "
                        "after the MBA — ask what made them decide.",
                "question": "You went back into tech at %s for the summer. What "
                            "tipped that decision, and did you recruit for "
                            "consulting along the way?" % item.get("company"),
            })

        elif kind == "nontrad":
            angles.append({
                "label": item["label"],
                "note": "They had to explain an unusual background to "
                        "consulting firms — the story they told is worth "
                        "hearing.",
                "question": "How did you frame your background for consulting "
                            "interviews, and what did firms actually push on?",
            })

        elif kind == "experience":
            angles.append({
                "label": item["label"],
                "note": "Close to your own experience, so their recruiting "
                        "story maps onto yours.",
                "question": "With %s of experience, did you feel it counted "
                            "against you in recruiting, and how did you handle "
                            "it?" % item["years"],
            })

        elif kind == "discipline" and item["discipline"] == "tech":
            angles.append({
                "label": item["label"],
                "note": "Same starting point, so their answer maps onto yours.",
                "question": "Coming from tech, which parts of that background "
                            "did firms value, and which did you stop leading with?",
            })

        elif kind == "discipline":
            word = DISCIPLINE_WORDS[item["discipline"]]
            angles.append({
                "label": item["label"],
                "note": "You are both making the same jump out of %s, so their "
                        "answer maps directly onto your own case rather than "
                        "being general advice." % word,
                "question": "Coming from %s, which parts of that background did "
                            "you find people actually valued, and which did you "
                            "have to stop leading with?" % word,
            })

        elif kind == "pivot":
            from_word = DISCIPLINE_WORDS.get(item["from"], "another field")
            to_word = DISCIPLINE_WORDS[item["to"]]
            angles.append({
                "label": item["label"],
                "note": "Not shared ground but a real contrast, which is its own "
                        "reason to talk: they can tell you how far your starting "
                        "point actually is from theirs.",
                "question": "I am coming from %s rather than %s. Where does that "
                            "put me behind, and where does it not matter as much "
                            "as I think?" % (from_word, to_word),
            })

        elif kind == "skills":
            angles.append({
                "label": item["label"],
                "note": "Small, but concrete — it shows you read past the "
                        "headline.",
                "question": item["phrase"][0].upper() + item["phrase"][1:] +
                            ". Does any of that still come up in your work now?",
            })

    return angles


def their_story(theirs):
    """One clause describing where they are and where they came from, built
    only from what the profile says."""
    roles = theirs.get("roles") or []
    if not roles:
        return ""
    current = next((r for r in roles if r.get("current")), roles[0])
    earliest = _earliest_roles(theirs)

    now = ""
    if current.get("title") and current.get("company"):
        now = "you are %s at %s" % (current["title"].lower(), current["company"])
    elif current.get("company"):
        now = "you are at %s" % current["company"]

    before = ""
    prior = [r for r in earliest
             if r.get("company") and _company_key(r["company"]) != _company_key(current.get("company"))]
    if prior:
        before = prior[0]["company"]
    return now, before


def headline_fact(theirs):
    """The single most quotable, checkable detail about their career."""
    roles = theirs.get("roles") or []
    if not roles:
        return ""

    # Time at one employer across several titles reads as commitment.
    by_company = {}
    for role in roles:
        key = _company_key(role.get("company"))
        if not key:
            continue
        by_company.setdefault(key, []).append(role)

    for key, group in by_company.items():
        months = sum(r.get("months") or 0 for r in group)
        if len(group) > 1 and months >= 24:
            titles = [r["title"] for r in group if r.get("title")]
            if len(titles) > 1:
                return ("you went from %s to %s at %s"
                        % (titles[-1].lower(), titles[0].lower(), group[0]["company"]))
    return ""
