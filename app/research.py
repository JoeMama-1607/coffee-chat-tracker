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
                                          # may carry "status" — see below
  "research_md": "...",                   # journey summary, markdown
  "sources": [{"title": "...", "url": "..."}],
  "prep_md": "...",                       # prep sheet, markdown
  "draft_subject": "...",
  "draft_body": "... {{HORIZON}} ... {{SLOTS}} ...",
  "thankyou_subject": "...",   # thank-you note, kept apart from the outreach draft
  "thankyou_body": "...",
  "require_existing": true,              # refuse to create a new person
  "sent_emails": [{"kind": "outreach", "subject": "", "body": "...", "sent_at": "2026-09-22"}]
}
Only the keys present are written, so a file can update one part.

A top-level "type" picks what the file is. No "type" means a person research
file, exactly as above — that is the original shape and it still works.

    {"type": "application", "match_id": 12, "company": "Bain",
     "role": "Summer Associate", "office": "Atlanta", "status": "applied",
     "deadline": "2026-10-15", "job_url": "...", "jd_text": "...",
     "applied_at": "2026-10-02", "resume_file": "...", "cover_letter_file": "...",
     "notes": "..."}

Matched on "match_id", else on company + role together; created when neither
finds one. Only the keys present are written.

    {"type": "firm_knowledge", "firm": "BCG", "entries": [
       {"category": "culture", "body": "...", "source_type": "research",
        "source_label": "BCG careers page", "source_url": "..."}]}

Applied straight away — research was authorised to write it. The firm has to
be one of the six in db.TARGET_FIRMS; categories are db.KNOWLEDGE_CATEGORIES.
An entry whose body is already on file for that firm is skipped, so a file can
be re-imported.

    {"type": "proposals", "batch_id": "2026-09-27-josh-giesler",
     "source_label": "Chat with Josh Giesler, 2026-09-27",
     "person": {"name": "Josh Giesler", "match_linkedin": "..."},
     "transcript": "...optional, stored with the batch and shown in Review...",
     "items": [
       {"kind": "firm_knowledge",
        "payload": {"firm": "Bain", "category": "recruiting_process", "body": "..."},
        "rationale": "..."},
       {"kind": "resume_walk", "payload": {"new_text": "...full new script..."},
        "rationale": "..."},
       {"kind": "resume_walk", "payload": {"add_feedback": "..."}, "rationale": "..."},
       {"kind": "person_update",
        "payload": {"status": "chat_done", "chat_at": "2026-09-27", "takeaway": "..."},
        "rationale": "..."},
       {"kind": "application_update",
        "payload": {"match_id": 12, "status": "applied"}, "rationale": "..."}]}

Nothing from a transcript touches the tracker on import. Every item lands as a
pending proposal and is applied only when it is accepted in Review. Items are
keyed by their position and content inside the batch, so re-importing the same
batch_id adds nothing and never resurrects something already decided.

File a follow-up after a chat — a followups file whose items carry "text":

    {"type": "followups", "items": [
       {"key": "pwc-csx-contact", "text": "Talk to someone in CSX",
        "person": "Tanvi Joshi", "firm": "PwC", "due": "2026-11-12"}]}

These show on Today in yellow. "key" is
stable: re-importing updates the text, and a ticked-off key stays ticked off.
"person" and "due" are optional. research/followups.json lists them with a
"done" flag.

Actions taken in Locked In come back as two shapes, applied straight away.

Set a person's status — a person file with only a status:

    {"name": "Jane Doe", "require_existing": true,
     "person": {"status": "thankyou_sent"}}

  - "status" must be one of the keys in db.STATUSES: uninitiated, tracking,
    outreach_sent, scheduled, chat_done, thankyou_sent, no_response. Anything
    else fails the whole file: nothing is written, the file stays in
    research/inbox/, and research/last_import.json carries the error.
  - "thankyou_sent" also stamps thankyou_sent_at with the import time, as
    Done does in the app, which clears that person's "Send thank-you note"
    from Today. A person who already has thankyou_sent_at keeps the original.
  - Other statuses leave thankyou_sent_at alone.
  - Keep "require_existing": true so a misspelt name fails instead of
    creating a new person. Match on "match_linkedin" when the name is shared.

Tick a follow-up done — a followups file, one item per Today action. An item
with "text" files a follow-up (above); an item without "text" ticks by key:

    {"type": "followups", "items": [
       {"key": "thankyou:12:2026-09-27T14:00:00-04:00", "done": true},
       {"key": "followup:7:2026-09-20T09:12:00-04:00:0", "done": false}]}

  - "key" is required on every item and is copied verbatim from
    research/actions.json — the same key the Today list uses. A follow-up
    can also be ticked by its own key from research/followups.json
    ("pwc-csx-contact"); the "todo:" prefix is added for you. Keys carry the
    situation behind them (the last email, the chat time), so a newer email
    or a moved chat mints a new key and the old one comes back "not_found".
  - "done": true (the default) ticks the action off, exactly like its tick in
    the app; "done": false puts a ticked-off action back on Today.
  - Only the key and "done" are read. The label and detail stay as the app wrote them;
    any other keys on an item are ignored.
  - Ticking a "thankyou" action also sets the person to thankyou_sent with
    thankyou_sent_at, and putting it back returns them to chat_done — the
    same as the app. Either shape alone is enough to record a thank-you.
  - Re-importing the same file changes nothing. The report in
    research/last_import.json lists keys under "done", "reopened",
    "unchanged" (already in the asked state) and "not_found". A not_found key
    does not fail the file, which still moves to research/imported/. An
    item without a key does fail the file.

Six snapshots are written after every import and after any change made in the
app, each atomically through a temp file: research/applications.json,
research/firms.json, research/resume_walk.json, research/proposals.json,
research/actions.json (the open Today actions, with their keys),
research/followups.json —
plus research/people.json, which also carries last_outbound_at,
last_inbound_at and followups_sent so Locked In can time nudges. actions.json lists each open action's
key, kind, person_id, name, label, detail and urgency; ticked-off actions are
not in it. research/last_import.json reports what
each file did, including its type and any error, so a write can be verified.
"""

import datetime as dt
import hashlib
import json
import os

import db

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(os.path.dirname(HERE), "research")
INBOX = os.path.join(ROOT, "inbox")
DONE = os.path.join(ROOT, "imported")

# Set by server.py: make_draft(person_id, kind, subject, body) -> dict, and
# slot_lines(person) -> list | None. Kept as hooks to avoid a circular import.
# open_actions() -> list, tick_action(action), untick_action(key) for
# followups files.
HOOKS = {"make_draft": None, "slot_lines": None, "save_slots": None,
         "open_actions": None, "tick_action": None, "untick_action": None}

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


def _person_file(data, people, stamp):
    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("no name")
    person = _find(people, name, data.get("match_linkedin"))
    given = data.get("person") or {}
    patch = {k: v for k, v in given.items() if k in ALLOWED}
    if "status" in given:
        statuses = {k for k, _ in db.STATUSES}
        if given["status"] not in statuses:
            raise ValueError("unknown status %r — one of %s"
                             % (given["status"], ", ".join(sorted(statuses))))
        patch["status"] = given["status"]
        if given["status"] == "thankyou_sent" and not (
                person and person.get("thankyou_sent_at")):
            patch["thankyou_sent_at"] = stamp
    if person is None and data.get("require_existing"):
        raise LookupError("no one called %r in the tracker — fix the name "
                          "or drop require_existing" % name)
    if person is None:
        pid = db.create_person(dict(patch, name=name))
        created = True
    else:
        pid = person["id"]
        created = False
        if patch:
            db.update_person(pid, patch)
    extra = {}
    for key in ("research_md", "prep_md", "draft_subject", "draft_body",
                "thankyou_subject", "thankyou_body"):
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
    result = {"type": "person", "person_id": pid, "name": name,
              "created": created, "sent_emails_added": added}
    # "offered_slots": [{"start": iso, "end": iso}, ...] — windows Claude picked
    # from research/calendar.json. Saved on the person exactly as if picked in
    # Suggest slots, busy holds included. [] clears them.
    if "offered_slots" in data:
        if HOOKS["save_slots"] is None:
            raise RuntimeError("slot saving unavailable")
        res = HOOKS["save_slots"](pid, data["offered_slots"] or [])
        if not res.get("ok"):
            raise RuntimeError(res.get("error") or "could not save slots")
        result["offered_slots"] = res.get("lines", [])
    # "outlook_draft": {"kind": "outreach"|"thankyou", "subject", "body"} —
    # opens a real Outlook draft (never sent). {{SLOTS}} / {{HORIZON}} are
    # filled from the windows saved on the person in the app.
    od = data.get("outlook_draft")
    if od:
        if HOOKS["make_draft"] is None:
            raise RuntimeError("Outlook drafting unavailable")
        res = HOOKS["make_draft"](pid, od.get("kind", "outreach"),
                                  od.get("subject", ""), od.get("body", ""))
        if not res.get("ok"):
            raise RuntimeError(res.get("error") or "Outlook draft failed")
        result["outlook_draft"] = {k: v for k, v in res.items() if k != "ok"}
    return result


# --------------------------------------------------------- typed inbox files

APPLICATION_KEYS = {"company", "role", "office", "job_url", "jd_text", "status",
                    "deadline", "applied_at", "interview_r1_at",
                    "interview_r2_at", "resume_file", "cover_letter_file",
                    "notes", "archived"}


def _application_file(data, people, stamp):
    """{"type": "application", ...} — create or partially update one role."""
    company = (data.get("company") or "").strip()
    existing = db.find_application(data.get("match_id"), company,
                                   data.get("role") or "")
    patch = {k: v for k, v in data.items() if k in APPLICATION_KEYS}
    statuses = {k for k, _ in db.APPLICATION_STATUSES}
    if patch.get("status") and patch["status"] not in statuses:
        raise ValueError("unknown status %r — one of %s"
                         % (patch["status"], ", ".join(sorted(statuses))))
    if existing is None:
        if not company:
            raise ValueError("company is required to create an application")
        aid = db.create_application(patch)
        return {"type": "application", "application_id": aid, "created": True,
                "company": company, "role": patch.get("role", "")}
    aid = existing["id"]
    db.update_application(aid, patch)
    return {"type": "application", "application_id": aid, "created": False,
            "company": existing["company"], "role": existing["role"],
            "updated": sorted(patch)}


def _firm_knowledge_file(data, people, stamp):
    """{"type": "firm_knowledge", ...} — applied directly, duplicates skipped."""
    firm = db.match_target_firm(data.get("firm"))
    if not firm:
        raise ValueError("%r is not one of the six target firms (%s)"
                         % (data.get("firm"), ", ".join(db.TARGET_FIRMS)))
    categories = {k for k, _ in db.KNOWLEDGE_CATEGORIES}
    added, skipped = 0, 0
    for entry in data.get("entries") or []:
        body = (entry.get("body") or "").strip()
        if not body:
            continue
        category = entry.get("category") or "other"
        if category not in categories:
            raise ValueError("unknown category %r — one of %s"
                             % (category, ", ".join(sorted(categories))))
        person = _find(people, entry.get("source_person") or "",
                       entry.get("source_linkedin"))
        kid = db.add_knowledge(
            firm, category, body,
            source_type=entry.get("source_type") or "research",
            source_person_id=person["id"] if person else None,
            source_label=entry.get("source_label") or "",
            source_url=entry.get("source_url") or "")
        if kid:
            added += 1
        else:
            skipped += 1
    return {"type": "firm_knowledge", "firm": firm, "added": added,
            "skipped_duplicates": skipped}


def _item_key(index, item):
    """A stable name for one item inside a batch. Position alone would let an
    edited file overwrite a decision; the payload alone would let a genuine
    repeat of the same point vanish. Both together behave."""
    blob = json.dumps([item.get("kind"), item.get("payload")], sort_keys=True)
    return "%02d-%s" % (index, hashlib.sha1(blob.encode("utf-8")).hexdigest()[:10])


def _proposals_file(data, people, stamp):
    """{"type": "proposals", ...} — lands as pending, applied only on accept."""
    batch_id = (data.get("batch_id") or "").strip()
    if not batch_id:
        raise ValueError("batch_id is required")
    label = data.get("source_label") or batch_id
    who = data.get("person") or {}
    person = _find(people, who.get("name") or "", who.get("match_linkedin"))
    pid = person["id"] if person else None
    db.add_proposal_batch(batch_id, label, pid, data.get("transcript") or "")
    added, already = 0, 0
    for index, item in enumerate(data.get("items") or []):
        kind = item.get("kind")
        if kind not in db.PROPOSAL_KINDS:
            raise ValueError("unknown proposal kind %r — one of %s"
                             % (kind, ", ".join(db.PROPOSAL_KINDS)))
        made = db.add_proposal(batch_id, _item_key(index, item), kind,
                               item.get("payload") or {},
                               item.get("rationale") or "", label, pid)
        if made:
            added += 1
        else:
            already += 1
    return {"type": "proposals", "batch_id": batch_id, "pending_added": added,
            "already_present": already, "person_id": pid,
            "person_matched": bool(person),
            "person_wanted": who.get("name") or ""}


def _followups_file(data, people, stamp):
    """{"type": "followups", "items": [...]} — two kinds of item, mixable:
    with "text", file a follow-up ({"key", "text", "person", "firm", "due"});
    re-importing the same key updates the text, and a key ticked off in the app
    stays ticked off. Without "text", tick a Today action off ("done": true,
    the default) or back on ("done": false) by its key from actions.json."""
    items = data.get("items") or []
    keys = [(item.get("key") or "").strip() for item in items]
    if not all(keys):
        raise ValueError("every item needs a key")
    ticks = [(k, i) for k, i in zip(keys, items) if "text" not in i]
    if ticks and not all(HOOKS[k] for k in ("open_actions", "tick_action", "untick_action")):
        raise RuntimeError("follow-ups unavailable")
    added = 0
    for key, item in zip(keys, items):
        if "text" not in item:
            continue
        text = (item.get("text") or "").strip()
        if not text:
            raise ValueError("every follow-up needs a key and text")
        pid = None
        if item.get("person"):
            hit = _find(people, item["person"], item.get("match_linkedin"))
            if hit is None:
                raise LookupError("no one called %r in the tracker" % item["person"])
            pid = hit["id"]
        db.upsert_followup(key, text, pid, item.get("firm", ""), item.get("due", ""))
        added += 1
    open_now = {a["key"]: a for a in HOOKS["open_actions"]()} if ticks else {}
    done, reopened, unchanged, missing = [], [], [], []
    resolved = db.resolved_keys()
    for key, item in ticks:
        # A follow-up's own key ("mck-apply", as in followups.json and Locked
        # In) stands for its Today action, "todo:mck-apply".
        if key not in open_now and key not in resolved and (
                "todo:" + key in open_now or "todo:" + key in resolved):
            act = "todo:" + key
        else:
            act = key
        ticked = act in db.resolved_keys()
        if item.get("done", True):
            if ticked:
                unchanged.append(key)
            elif act in open_now:
                HOOKS["tick_action"](open_now[act])
                done.append(key)
            else:
                missing.append(key)
        elif ticked:
            HOOKS["untick_action"](act)
            reopened.append(key)
        elif act in open_now:
            unchanged.append(key)
        else:
            missing.append(key)
    return {"type": "followups", "upserted": added, "done": done,
            "reopened": reopened, "unchanged": unchanged, "not_found": missing}


HANDLERS = {
    "person": _person_file,
    "application": _application_file,
    "firm_knowledge": _firm_knowledge_file,
    "proposals": _proposals_file,
    "followups": _followups_file,
}


def _one(path, people, stamp):
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    kind = (data.get("type") or "person").strip()
    handler = HANDLERS.get(kind)
    if handler is None:
        raise ValueError("unknown type %r — one of %s"
                         % (kind, ", ".join(sorted(HANDLERS))))
    result = handler(data, people, stamp)
    result["file"] = os.path.basename(path)
    return result


# Settings a research file may set (research/inbox/settings.json, no "name").
SETTING_KEYS = {"zoom_link", "zoom_meeting_id", "zoom_passcode", "hold_calendar", "chat_calendar"}


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
            with open(path, encoding="utf-8") as fh:
                peek = json.load(fh)
            if "settings" in peek and not peek.get("name"):
                patch = {k: v for k, v in peek["settings"].items() if k in SETTING_KEYS}
                db.save_settings(patch)
                os.replace(path, os.path.join(DONE, stamp[:19].replace(":", "") + " " + name))
                report.append({"file": name, "settings": sorted(patch)})
                continue
            entry = _one(path, people, stamp)
            os.replace(path, os.path.join(
                DONE, stamp[:19].replace(":", "") + " " + name))
            people = db.list_people(include_archived=True)
        except Exception as exc:  # leave the file where it is, say why
            entry = {"file": name, "error": "%s: %s" % (type(exc).__name__, exc)}
        report.append(entry)
    with open(os.path.join(ROOT, "last_import.json"), "w", encoding="utf-8") as fh:
        json.dump({"at": stamp, "results": report}, fh, indent=2)
    write_snapshots()
    return report


def _write(name, payload):
    """Atomically, so a snapshot is never read half-written."""
    tmp = os.path.join(ROOT, name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=str)
    os.replace(tmp, os.path.join(ROOT, name))


def _now():
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def write_snapshots():
    """Every snapshot Claude reads, rewritten from the database as it stands.

    Called after an import and after anything changed in the app, so what the
    agent sees is never a version behind what the user is looking at."""
    if not os.path.isdir(ROOT):
        return
    write_snapshot()
    _write("applications.json", {"at": _now(),
                                "statuses": [k for k, _ in db.APPLICATION_STATUSES],
                                "applications": db.list_applications()})
    _write("firms.json", {"at": _now(), "firms": firms_payload()})
    _write("resume_walk.json", resume_walk_payload())
    resolved = db.resolved_keys()
    _write("followups.json", {"at": _now(), "followups": [
        dict(f, done=("todo:" + f["key"]) in resolved) for f in db.list_followups()]})
    _write("proposals.json", {"at": _now(),
                              "kinds": db.PROPOSAL_KINDS,
                              "proposals": db.list_proposals()})
    if HOOKS["open_actions"]:
        _write("actions.json", {"at": _now(), "actions": HOOKS["open_actions"]()})


def firms_payload():
    """Per target firm: who you know there, what you know, what you applied to."""
    people = db.list_people(include_archived=False)
    applications = db.list_applications()
    knowledge = db.list_knowledge()
    out = []
    for firm in db.TARGET_FIRMS:
        theirs = [p for p in people if db.match_target_firm(p.get("firm")) == firm]
        apps = [a for a in applications if a.get("target_firm") == firm]
        due = [a["days_to_deadline"] for a in apps
               if a.get("days_to_deadline") is not None]
        out.append({
            "firm": firm,
            "brief": db.FIRM_BRIEFS.get(firm, ""),
            "people": [{"id": p["id"], "name": p["name"], "role": p.get("role"),
                        "office": p.get("office"), "status": p.get("status"),
                        "chat_at": p.get("chat_at")} for p in theirs],
            "people_count": len(theirs),
            "chatted_count": len([p for p in theirs if p.get("status")
                                  in ("chat_done", "thankyou_sent")]),
            "knowledge": [{"id": k["id"], "category": k["category"],
                           "body": k["body"], "source_type": k["source_type"],
                           "source_label": k["source_label"],
                           "source_url": k.get("source_url"),
                           "source_person": k.get("source_person_name"),
                           "created_at": k["created_at"]}
                          for k in knowledge if k["firm"] == firm],
            "applications": apps,
            "next_deadline_days": min(due) if due else None,
        })
    return out


def resume_walk_payload():
    walk = db.resume_walk()
    return {"at": _now(), "body": walk["body"], "updated_at": walk["updated_at"],
            "source": walk["source"], "version_count": len(walk["versions"]),
            "feedback": walk["feedback"],
            "versions": [{"id": v["id"], "source": v["source"],
                          "created_at": v["created_at"], "chars": len(v["body"])}
                         for v in walk["versions"]]}


def _share_profile_pdf(p):
    """Copy an uploaded LinkedIn PDF to research/profiles/ so Claude can read
    it (the original lives in ~/Library, out of Claude's reach). Returns the
    path relative to research/, or "" when there is none."""
    src = p.get("profile_pdf") or ""
    if not src or not os.path.isfile(src):
        return ""
    slug = "-".join(_norm(p.get("name")).replace("/", " ").split()) or str(p["id"])
    rel = os.path.join("profiles", "%s.pdf" % slug)
    dest = os.path.join(ROOT, rel)
    try:
        if not os.path.isfile(dest) or os.path.getmtime(dest) < os.path.getmtime(src):
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            import shutil
            shutil.copy2(src, dest)
    except OSError:
        return ""
    return rel


def write_snapshot():
    """research/people.json: who is in the tracker, for Claude to read."""
    if not os.path.isdir(ROOT):
        return
    keep = ("id", "name", "firm", "role", "office", "email", "linkedin", "status",
            "grad_year", "is_alum", "chat_at", "researched_at",
            "last_outbound_at", "last_inbound_at", "followups_sent")
    rows = []
    for p in db.list_people(include_archived=False):
        row = {k: p.get(k) for k in keep}
        row["has_prep"] = bool((p.get("prep_md") or "").strip())
        row["has_draft"] = bool((p.get("draft_body") or "").strip())
        row["saved_slots"] = (HOOKS["slot_lines"](p) if HOOKS["slot_lines"] else None) or []
        row["profile_pdf"] = _share_profile_pdf(p)
        rows.append(row)
    tmp = os.path.join(ROOT, "people.json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                   "people": rows}, fh, indent=2)
    os.replace(tmp, os.path.join(ROOT, "people.json"))


CAL_REQUEST = os.path.join(ROOT, "calendar_request.json")
CAL_OUT = os.path.join(ROOT, "calendar.json")


def calendar_export(read_calendar, settings):
    """research/calendar_request.json ({"days": 14}) asks for a calendar read.
    The events land in research/calendar.json for Claude to choose slots
    from; the request file is then removed."""
    if not os.path.exists(CAL_REQUEST):
        return None
    try:
        with open(CAL_REQUEST, encoding="utf-8") as fh:
            req = json.load(fh) or {}
    except ValueError:
        req = {}
    days = max(1, min(int(req.get("days") or 14), 60))
    import availability
    tz = availability.get_tz(settings.get("timezone", "America/New_York"))
    now = dt.datetime.now(tz)
    out = {"generated_at": now.isoformat(timespec="seconds"),
           "timezone": settings.get("timezone"), "from": now.isoformat(),
           "to": (now + dt.timedelta(days=days)).isoformat()}
    try:
        payload = read_calendar(now, now + dt.timedelta(days=days))
        out.update(ok=True, events=payload.get("events", []),
                   demo=bool(payload.get("demo")))
    except Exception as exc:
        out.update(ok=False, error="%s: %s" % (type(exc).__name__, exc))
    keys = ("work_days", "work_start", "work_end", "buffer_minutes",
            "min_window_minutes", "max_window_minutes", "max_per_day",
            "slots_wanted", "hold_prefix", "excluded_calendars",
            "ignore_all_day", "ignore_tentative", "tz_label")
    out["rules"] = {k: settings.get(k) for k in keys}
    tmp = CAL_OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, default=str)
    os.replace(tmp, CAL_OUT)
    os.remove(CAL_REQUEST)
    return out.get("ok")
