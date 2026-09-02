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


def common_ground(mine, theirs):
    """Ranked, each with the phrase the email can use. Strongest first."""
    found = []

    my_roles = mine.get("roles") or []
    their_roles = theirs.get("roles") or []

    # 1. The same employer — the strongest thing two strangers can share.
    my_companies = {_company_key(r.get("company")): r.get("company")
                    for r in my_roles if r.get("company")}
    for role in their_roles:
        key = _company_key(role.get("company"))
        if key and key in my_companies:
            found.append({
                "kind": "employer",
                "weight": 100,
                "label": "Both worked at %s" % role["company"],
                "phrase": "we both spent time at %s" % role["company"],
            })
            break

    # 2. The same university, not counting the one you are both at now.
    my_schools = {_school_key(e.get("school")): e.get("school")
                  for e in (mine.get("education") or [])
                  if e.get("school") and not _is_home_school(e.get("school"))}
    for entry in theirs.get("education") or []:
        school = entry.get("school") or ""
        if _is_home_school(school):
            continue
        key = _school_key(school)
        if key and key in my_schools:
            found.append({
                "kind": "school",
                "weight": 90,
                "label": "Both studied at %s" % school,
                "phrase": "we were both at %s" % school,
            })
            break

    # 3. The same country behind you.
    my_country = country_of(mine)
    their_country = country_of(theirs)
    if my_country and my_country == their_country and my_country != "United States":
        found.append({
            "kind": "country",
            "weight": 70,
            "label": "Both built careers in %s" % my_country,
            "phrase": "you built your career in %s before coming here, which is "
                      "the same move I made" % my_country,
            "country": my_country,
        })

    # 4. The same discipline before business school.
    my_discipline = discipline_of(mine)
    their_discipline = discipline_of(theirs)
    if my_discipline and my_discipline == their_discipline:
        found.append({
            "kind": "discipline",
            "weight": 75,
            "label": "Both came from %s" % DISCIPLINE_WORDS[my_discipline],
            "phrase": "we both come from %s" % DISCIPLINE_WORDS[my_discipline],
            "discipline": my_discipline,
        })
    elif my_discipline and their_discipline:
        # Not the same, but they made the move you are trying to make.
        found.append({
            "kind": "pivot",
            "weight": 60,
            "label": "%s to %s" % (DISCIPLINE_WORDS.get(my_discipline, "their field"),
                                   DISCIPLINE_WORDS[their_discipline]),
            "phrase": "you moved from %s into %s" % (
                DISCIPLINE_WORDS.get(my_discipline, "another field"),
                DISCIPLINE_WORDS[their_discipline]),
            "from": my_discipline,
            "to": their_discipline,
        })

    # 5. Overlapping skills, when nothing better turned up.
    my_skills = {s.lower() for s in (mine.get("skills") or [])}
    shared = [s for s in (theirs.get("skills") or []) if s.lower() in my_skills]
    if shared:
        found.append({
            "kind": "skills",
            "weight": 40,
            "label": "Shared skills: %s" % ", ".join(shared[:3]),
            "phrase": "we have both worked in %s" % shared[0],
        })

    found.sort(key=lambda item: -item["weight"])
    return found


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
            company = item["label"].replace("Both worked at ", "")
            angles.append({
                "label": item["label"],
                "note": "The strongest opening you have. Shared ground with a "
                        "stranger buys you candour almost immediately.",
                "question": "We overlapped at %s, so I know how it works there. "
                            "What carried over into %s, and what did you have to "
                            "unlearn?" % (company, firm),
            })

        elif kind == "school":
            school = item["label"].replace("Both studied at ", "")
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
                "question": item["phrase"].capitalize() +
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
