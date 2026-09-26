"""Research written outside the app (by Claude) and dropped in as JSON.

Claude can't reach the database in ~/Library, but it can write files into this
folder. So the hand-off is a file: one JSON per person in research/inbox/. The
app picks them up whenever the page refreshes, files them against the right
person, and moves each one to research/imported/. After every import it writes
research/people.json — a read-only snapshot of who is in the tracker — so
Claude can see what's there without opening the database.

A file looks like:
{
  "name": "Jane Doe",                     # required; used to match
  "match_linkedin": "https://...",        # optional, better match than the name
  "person": {"firm": "Bain", "role": "...", "email": "...", ...},  # optional
  "research_md": "...",                   # journey summary, markdown
  "sources": [{"title": "...", "url": "..."}],
  "prep_md": "...",                       # prep sheet, markdown
  "draft_subject": "...",
  "draft_body": "... {{HORIZON}} ... {{SLOTS}} ...",
  "sent_emails": [{"kind": "outreach", "subject": "", "body": "...", "sent_at": "2026-09-22"}]
}
Only the keys present are written, so a file can update one part.
"""

import datetime as dt
import json
import os

import db

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(os.path.dirname(HERE), "research")
INBOX = os.path.join(ROOT, "inbox")
DONE = os.path.join(ROOT, "imported")

# Person columns a research file may set directly.
ALLOWED = {"email", "firm", "role", "office", "linkedin", "grad_year", "is_alum",
           "tier", "source", "contact_channel", "priority_note"}


def _norm(text):
    return " ".join((text or "").casefold().split())


def _find(people, name, linkedin):
    if linkedin:
        want = linkedin.rstrip("/").casefold()
        for p in people:
            if (p.get("linkedin") or "").rstrip("/").casefold() == want:
                return p
    hits = [p for p in people if _norm(p.get("name")) == _norm(name)]
    return hits[0] if len(hits) == 1 else None


def _one(path, people, stamp):
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("no name")
    person = _find(people, name, data.get("match_linkedin"))
    patch = {k: v for k, v in (data.get("person") or {}).items() if k in ALLOWED}
    if person is None:
        pid = db.create_person(dict(patch, name=name))
        created = True
    else:
        pid = person["id"]
        created = False
        if patch:
            db.update_person(pid, patch)
    extra = {}
    for key in ("research_md", "prep_md", "draft_subject", "draft_body"):
        if key in data:
            extra[key] = data[key] or ""
    if "sources" in data:
        extra["research_sources"] = json.dumps(data["sources"] or [])
    if extra:
        extra["researched_at"] = stamp
        db.update_person(pid, extra)
    added = 0
    current = db.get_person(pid)
    have = {(m["kind"], m["body"].strip()) for m in current.get("sent_mail", [])}
    for mail in data.get("sent_emails") or []:
        key = (mail.get("kind", "outreach"), (mail.get("body") or "").strip())
        if key[1] and key not in have:
            db.add_sent_mail(pid, key[0], mail.get("subject", ""), key[1],
                             mail.get("sent_at") or stamp)
            have.add(key)
            added += 1
    return {"file": os.path.basename(path), "person_id": pid, "name": name,
            "created": created, "sent_emails_added": added}


def import_inbox():
    """Import every JSON in the inbox. Returns a report; quiet when empty."""
    if not os.path.isdir(INBOX):
        return []
    files = sorted(f for f in os.listdir(INBOX) if f.endswith(".json"))
    if not files:
        return []
    os.makedirs(DONE, exist_ok=True)
    stamp = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    report = []
    people = db.list_people(include_archived=True)
    for name in files:
        path = os.path.join(INBOX, name)
        try:
            entry = _one(path, people, stamp)
            os.replace(path, os.path.join(
                DONE, stamp[:19].replace(":", "") + " " + name))
            people = db.list_people(include_archived=True)
        except Exception as exc:  # leave the file where it is, say why
            entry = {"file": name, "error": "%s: %s" % (type(exc).__name__, exc)}
        report.append(entry)
    with open(os.path.join(ROOT, "last_import.json"), "w", encoding="utf-8") as fh:
        json.dump({"at": stamp, "results": report}, fh, indent=2)
    write_snapshot()
    return report


def write_snapshot():
    """research/people.json: who is in the tracker, for Claude to read."""
    if not os.path.isdir(ROOT):
        return
    keep = ("id", "name", "firm", "role", "office", "email", "linkedin", "status",
            "grad_year", "is_alum", "chat_at", "researched_at")
    rows = []
    for p in db.list_people(include_archived=False):
        row = {k: p.get(k) for k in keep}
        row["has_prep"] = bool((p.get("prep_md") or "").strip())
        row["has_draft"] = bool((p.get("draft_body") or "").strip())
        rows.append(row)
    tmp = os.path.join(ROOT, "people.json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                   "people": rows}, fh, indent=2)
    os.replace(tmp, os.path.join(ROOT, "people.json"))
