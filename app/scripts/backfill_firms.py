#!/usr/bin/env python3
"""One-off: pull firm-level knowledge out of research already imported.

Every research file the app has ever taken in is still sitting in
research/imported/. Most of what it says is about a person — where they
worked, when they moved, what to ask them — and none of that belongs on a
firm page. A little of it is about the firm itself: how it recruits, what
the office does, what its culture is called. This script goes looking for
that second kind and nothing else.

It is deliberately timid. A line has to name the firm, has to carry a
firm-level word, and must not read as somebody's own story, or it is left
alone. Missing a good line costs nothing; a firm page full of "she moved
to Atlanta in 2024" would be worse than an empty one.

Safe to run twice: entries are deduplicated on their exact body per firm,
so a second run adds nothing.

    python3 app/scripts/backfill_firms.py            # knowledge only
    python3 app/scripts/backfill_firms.py --dry-run  # print, write nothing
    python3 app/scripts/backfill_firms.py --seed-applications

--seed-applications is off by default and asks first: it reads the file
names in the Recruiting/Applications folder and makes one application per
PDF, which is a guess about what those files mean.
"""

import argparse
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import db  # noqa: E402

IMPORTED = os.path.join(os.path.dirname(os.path.dirname(HERE)), "research", "imported")
APPLICATIONS_DIR = os.path.expanduser(
    "~/Library/Mobile Documents/com~apple~CloudDocs/Goizueta/Recruiting/Applications")

# A line has to earn its place with one of these, and the first one it
# matches is the category it lands in.
CATEGORY_WORDS = [
    ("recruiting_process", ("recruit", "interview", "case round", "casing",
                            "application", "apply", "deadline", "offer cycle",
                            "pre-mba program", "experiencebain", "insight program",
                            "coffee chat", "networking event", "hiring")),
    ("practice_areas", ("practice", "capability", "industry vertical", "sector",
                        "expertise", "casework", "project types", "digital arm",
                        "implementation arm")),
    ("office", ("office", "atlanta", "based in", "staffing model", "travel model",
                "regional")),
    ("culture", ("culture", "values", "supportive", "apprenticeship", "feedback",
                 "work-life", "meritocratic", "down-to-earth", "collegial",
                 "tenure", "attrition")),
    ("why_this_firm", ("differentiat", "known for", "reputation", "strength of the firm",
                       "what sets", "positioning")),
]

# If a line says this, it is about the person, not the firm.
PERSONAL = re.compile(
    r"\b(she|he|her|his|him|they|their|them|you|your|i'm|i am|my)\b"
    r"|\b(19|20)\d\d\b|\bmba\b|\bclass of\b|\bgoizueta\b|\bpromot|\bjoined\b"
    r"|\bmoved to\b|\bworked at\b|\bintern(ed|ship)\b", re.I)

# Whole sections that are somebody's story by definition.
SKIP_HEADINGS = re.compile(
    r"journey|timeline|background|career|questions|what to ask|schedule|"
    r"opening|notes on you|press mention", re.I)


def firm_aliases(firm):
    return {firm.lower()} | {a for a, short in db.TARGET_FIRM_ALIASES.items()
                             if short == firm}


def categorise(text):
    low = text.lower()
    for category, words in CATEGORY_WORDS:
        if any(word in low for word in words):
            return category
    return None


def candidates(markdown, firm):
    """Firm-level statements in one markdown blob, conservatively."""
    aliases = firm_aliases(firm)
    out, skipping = [], False
    for raw in (markdown or "").splitlines():
        line = raw.strip()
        if line.startswith("#"):
            skipping = bool(SKIP_HEADINGS.search(line))
            continue
        if skipping or not line:
            continue
        line = re.sub(r"^[-*•]\s*", "", line).strip()
        # Sentence by sentence: one firm-level clause inside a personal
        # paragraph is still worth having, the paragraph around it is not.
        for piece in re.split(r"(?<=[.!?])\s+", line):
            piece = piece.strip()
            if len(piece) < 40 or len(piece) > 400:
                continue
            low = piece.lower()
            if not any(alias in low for alias in aliases):
                continue
            if PERSONAL.search(piece):
                continue
            category = categorise(piece)
            if category:
                out.append((category, re.sub(r"\s+", " ", piece)))
    return out


def backfill(dry_run=False):
    people = {p["name"].strip().lower(): p for p in db.list_people(include_archived=True)}
    added, seen, skipped = 0, 0, 0
    per_firm = {}
    for path in sorted(glob.glob(os.path.join(IMPORTED, "*.json"))):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except ValueError as exc:
            print("  ! %s — %s" % (os.path.basename(path), exc))
            continue
        name = (data.get("name") or "").strip()
        person = people.get(name.lower())
        firm = db.match_target_firm((data.get("person") or {}).get("firm")
                                    or (person or {}).get("firm"))
        if not firm:
            continue
        label = "%s — %s" % (name or "research", os.path.basename(path))
        for key in ("research_md", "prep_md"):
            for category, body in candidates(data.get(key), firm):
                seen += 1
                if dry_run:
                    print("  %-8s %-18s %s" % (firm, category, body[:96]))
                    continue
                kid = db.add_knowledge(firm, category, body,
                                       source_type="research",
                                       source_person_id=(person or {}).get("id"),
                                       source_label=label)
                if kid:
                    added += 1
                    per_firm[firm] = per_firm.get(firm, 0) + 1
                else:
                    skipped += 1
    print("\n%d firm-level statement%s found across %d file%s"
          % (seen, "" if seen == 1 else "s",
             len(glob.glob(os.path.join(IMPORTED, "*.json"))),
             "" if len(glob.glob(os.path.join(IMPORTED, "*.json"))) == 1 else "s"))
    if dry_run:
        print("Dry run — nothing written.")
        return
    print("%d added, %d already on file." % (added, skipped))
    for firm in db.TARGET_FIRMS:
        if per_firm.get(firm):
            print("  %-10s +%d" % (firm, per_firm[firm]))


def seed_applications():
    """One application per PDF in the Applications folder — a guess, so it
    asks first and never runs on its own."""
    if not os.path.isdir(APPLICATIONS_DIR):
        print("No folder at %s — nothing to seed." % APPLICATIONS_DIR)
        return
    files = sorted(f for f in os.listdir(APPLICATIONS_DIR)
                   if f.lower().endswith((".pdf", ".docx")))
    if not files:
        print("No resumes or cover letters in %s." % APPLICATIONS_DIR)
        return
    existing = {(a["company"].strip().lower(), (a["role"] or "").strip().lower())
                for a in db.list_applications(include_archived=True)}
    plan = []
    for name in files:
        company = re.sub(r"[-_]+", " ", os.path.splitext(name)[0]).strip()
        company = re.sub(r"\b(resume|cv|cover letter|cover)\b", "", company,
                         flags=re.I).strip()
        if company and (company.lower(), "") not in existing:
            plan.append((company, os.path.join(APPLICATIONS_DIR, name)))
    if not plan:
        print("Every file there already has an application.")
        return
    print("\nThis would add %d application%s, company taken from the file name:"
          % (len(plan), "" if len(plan) == 1 else "s"))
    for company, path in plan:
        print("  %-24s %s" % (company, os.path.basename(path)))
    answer = input("\nAdd them? [y/N] ").strip().lower()
    if answer not in ("y", "yes"):
        print("Left alone.")
        return
    for company, path in plan:
        db.create_application({"company": company, "status": "researching",
                               "resume_file": path,
                               "notes": "Seeded from %s" % os.path.basename(path)})
    print("Added %d." % len(plan))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="print what would be added and write nothing")
    parser.add_argument("--seed-applications", action="store_true",
                        help="also offer to seed applications from file names")
    args = parser.parse_args()

    db.init()
    print("Reading %s" % IMPORTED)
    backfill(args.dry_run)
    if args.seed_applications:
        seed_applications()
    try:
        import research
        research.write_snapshots()
    except OSError:
        pass


if __name__ == "__main__":
    main()
