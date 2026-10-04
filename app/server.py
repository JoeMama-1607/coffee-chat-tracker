"""Coffee Chat Tracker — local application server.

Runs on 127.0.0.1 only, serves the interface, and exposes a small JSON API.
Standard library only, so there is nothing to install.
"""

import argparse
import base64
import datetime as dt
import json
import mimetypes
import os
import secrets
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import availability  # noqa: E402
import db  # noqa: E402
import ics  # noqa: E402
import macos  # noqa: E402
import matching  # noqa: E402
import pdfreader  # noqa: E402
import pdfwriter  # noqa: E402
import profile as profile_reader  # noqa: E402
import research  # noqa: E402
import templates  # noqa: E402

WEB_DIR = os.path.join(HERE, "web")
TOKEN = secrets.token_urlsafe(24)

# One id per run of the app. Items ticked off on Today are binned against it,
# which is what makes the bin empty itself when the app is next opened.
SESSION = secrets.token_urlsafe(12)

_outlook_status = {"checked": False}


def _hold_title(person, settings):
    name = person.get("name") or ""
    prefix = settings.get("hold_prefix") or "Coffee chat hold"
    return "%s — %s" % (prefix, name) if name else prefix


def _offered_windows(person):
    try:
        saved = json.loads(person.get("offered_slots") or "null") or {}
    except ValueError:
        saved = {}
    return ics.windows_from_days(saved.get("days", []), availability.parse_iso)


def _same(a, b):
    return (abs((a[0] - b[0]).total_seconds()) < 60
            and abs((a[1] - b[1]).total_seconds()) < 60)


def _sync_holds(person, settings, old_windows, new_windows):
    """Busy holds on Apple Calendar for exactly `new_windows`."""
    title = _hold_title(person, settings)
    gone = [w for w in old_windows if not any(_same(w, n) for n in new_windows)]
    notes = ("Time offered to %s for a coffee chat. Held so nothing else takes "
             "it; Coffee Chat Tracker removes it when the chat is confirmed or "
             "the slot is dropped." % (person.get("name") or "someone"))
    if not gone and not new_windows:
        return {"ok": True, "deleted": 0, "created": 0, "errors": []}
    try:
        return macos.calendar_sync(
            delete=[(title, s, e) for s, e in gone],
            ensure=[{"prefix": title, "title": title, "start": s, "end": e,
                     "notes": notes, "calendar": settings.get("hold_calendar", "")}
                    for s, e in new_windows])
    except macos.BridgeError as exc:
        return {"ok": False, "deleted": 0, "created": 0, "error": str(exc)}


def _days_from_windows(windows, tz):
    """Group (start, end) pairs into the slot finder's day/window structure."""
    days = {}
    for start, end in sorted(windows):
        ls, le = start.astimezone(tz), end.astimezone(tz)
        day = days.setdefault(ls.date(), {
            "date": ls.date().isoformat(),
            "label": availability.fmt_day(ls.date()),
            "windows": []})
        day["windows"].append({
            "start": ls.isoformat(), "end": le.isoformat(),
            "text": "%s – %s" % (availability.fmt_time(ls), availability.fmt_time(le)),
            "minutes": int((le - ls).total_seconds() // 60)})
    return [days[k] for k in sorted(days)]


def pull_from_calendar(settings):
    """Make the tracker match edits made directly in Apple Calendar.

    Holds titled `<hold_prefix> — <name>` become that person's saved slots
    (moved, added or deleted in Calendar), and a moved `Coffee chat — <name>`
    event moves the chat. Nothing on the calendar is changed.
    """
    tz = availability.get_tz(settings.get("timezone", "America/New_York"))
    now = dt.datetime.now(tz)
    events = macos.read_calendar(now - dt.timedelta(days=1),
                                 now + dt.timedelta(days=90)).get("events", [])
    parsed = []
    for ev in events:
        s, e = availability.parse_iso(ev.get("start")), availability.parse_iso(ev.get("end"))
        if s and e and not ev.get("all_day"):
            parsed.append(((ev.get("title") or "").strip(), s, e))

    changes = []
    tz_label = settings.get("tz_label", "ET")
    for person in db.list_people():
        name = person.get("name") or ""
        if not name:
            continue
        hold = _hold_title(person, settings)
        found = sorted({(s, e) for t, s, e in parsed if t == hold and e > now})
        saved = [w for w in _offered_windows(person) if w[1] > now]
        same = (len(found) == len(saved)
                and all(any(_same(f, w) for w in saved) for f in found))
        if not same and (found or saved):
            if found:
                days = _days_from_windows(found, tz)
                payload = json.dumps({
                    "lines": availability.format_slot_lines(days, tz_label),
                    "days": days})
                db.update_person(person["id"], {
                    "offered_slots": payload, "offered_slots_at": now.isoformat()})
                changes.append({"name": name, "kind": "slots",
                                "lines": availability.format_slot_lines(days, tz_label)})
            else:
                db.update_person(person["id"], {"offered_slots": "", "offered_slots_at": None})
                changes.append({"name": name, "kind": "slots_cleared", "lines": []})

        chat = _chat_title(person)
        chats = sorted(s for t, s, e in parsed if t.startswith(chat))
        current = _chat_start(person, tz)
        if chats and current and current > now - dt.timedelta(hours=1):
            nearest = min(chats, key=lambda s: abs((s - current).total_seconds()))
            if abs((nearest - current).total_seconds()) >= 60:
                db.update_person(person["id"], {
                    "chat_at": nearest.astimezone(tz).replace(tzinfo=None).isoformat()})
                changes.append({"name": name, "kind": "chat_moved",
                                "lines": ["%s %s" % (availability.fmt_day(nearest.astimezone(tz).date()),
                                                     availability.fmt_time(nearest.astimezone(tz)))]})
    return {"ok": True, "changes": changes}


def _chat_title(person):
    name = person.get("name") or ""
    return "Coffee chat — %s" % name if name else "Coffee chat"


def _chat_start(person, tz):
    """The chat's current start as an aware datetime, or None."""
    raw = person.get("chat_at")
    if not raw:
        return None
    moment = availability.parse_iso(raw)
    if moment and moment.tzinfo is None:
        moment = moment.replace(tzinfo=tz)
    return moment


def _sync_chat(person, settings, deletes, new_window, old_start):
    """Delete `deletes`, then move the chat event from old_start (or create it)."""
    title = _chat_title(person)
    notes = "Role: %s\nEmail: %s\n\nConfirmed by Coffee Chat Tracker." % (
        person.get("role") or "", person.get("email") or "")
    try:
        return macos.calendar_sync(delete=deletes, upsert={
            "prefix": title, "title": title + (" (%s)" % person["firm"] if person.get("firm") else ""),
            "start": new_window[0], "end": new_window[1], "notes": notes,
            "calendar": settings.get("chat_calendar", ""),
            "match": (old_start, None) if old_start else None,
        })
    except macos.BridgeError as exc:
        return {"ok": False, "deleted": 0, "updated": 0, "created": 0, "error": str(exc)}
_calendar_status = {"checked": False}
_lock = threading.Lock()
_import_lock = threading.Lock()   # research inbox; separate so it never waits on Outlook

# A chat stops being "coming up" shortly before it starts and stops being "now"
# once it has plainly run its course. Nothing else can tell the app the meeting
# happened — Outlook cannot see a Zoom call — so the clock is what moves it on.
CHAT_LEAD_MINUTES = 15
CHAT_RUN_MINUTES = 30

# The app quits when its window goes away. The reliable signal is the explicit
# goodbye the page sends on close (/api/close); the heartbeat is only a backstop
# for a window that vanished without saying so (a crash, a force quit).
#
# The grace period is deliberately long. Browser timers stop while a Mac is
# asleep and are throttled hard in hidden windows, so a short grace period kills
# a server whose window is still sitting there open — leaving an app that looks
# completely normal and silently ignores everything you type.
HEARTBEAT_GRACE = 3 * 60 * 60      # 3 hours of genuine silence
CLOSE_GRACE = 20                   # after an explicit goodbye
_last_beat = [0.0]
_server = [None]


# --------------------------------------------------------------- helpers

def now_tz(settings):
    return dt.datetime.now(availability.get_tz(settings.get("timezone", "America/New_York")))


def iso_date(value):
    if not value:
        return None
    return availability.parse_iso(str(value))


def days_between(later, earlier):
    if not later or not earlier:
        return None
    return (later - earlier).total_seconds() / 86400.0


def action_key(kind, person, *marks):
    """Identify an action by the situation that produced it, not just by kind.

    Ticking off "follow up" means "I have dealt with this stretch of silence",
    not "never mention follow-ups for this person again" — so the key carries
    the state behind it. Send another email and the key changes, and the action
    is due again on its own.
    """
    parts = [kind, str(person.get("id"))] + [str(m or "") for m in marks]
    return ":".join(parts)


def compute_actions(people, settings, resolved=None):
    """Derive what actually needs doing today, from the deck's own rules:
    follow up after a week of silence, thank-you inside 24 hours."""
    resolved = resolved if resolved is not None else set()
    tz = availability.get_tz(settings.get("timezone", "America/New_York"))
    now = dt.datetime.now(tz)
    followup_after = float(settings.get("followup_after_days", 7))
    max_followups = int(settings.get("max_followups", 3))
    thankyou_hours = float(settings.get("thankyou_within_hours", 24))

    actions = []
    for p in people:
        status = p.get("status") or "uninitiated"
        name = p.get("name")
        tier = (p.get("tier") or "B").strip().upper()
        last_out = iso_date(p.get("last_outbound_at"))
        last_in = iso_date(p.get("last_inbound_at"))
        chat_at = iso_date(p.get("chat_at"))

        def aware(value):
            if value is None:
                return None
            return value if value.tzinfo else value.replace(tzinfo=tz)

        last_out, last_in, chat_at = aware(last_out), aware(last_in), aware(chat_at)

        # 1. Thank-you note owed
        if chat_at and chat_at <= now and not p.get("thankyou_sent_at"):
            hours = (now - chat_at).total_seconds() / 3600.0
            actions.append({
                "person_id": p["id"], "name": name, "firm": p.get("firm"), "tier": tier,
                "kind": "thankyou",
                "chat_done": status in ("chat_done", "thankyou_sent"),
                "key": action_key("thankyou", p, p.get("chat_at")),
                "urgency": "overdue" if hours > thankyou_hours else "today",
                "label": "Send thank-you note",
                "detail": ("%.0f hours since the chat — the window is %d"
                           % (hours, thankyou_hours)),
            })

        # 2. Silence after outreach
        elif status == "outreach_sent" and last_out:
            quiet = days_between(now, last_out)
            replied_since = last_in and last_in > last_out
            if not replied_since and quiet is not None and quiet >= followup_after:
                sent = int(p.get("followups_sent") or 0)
                if sent < max_followups:
                    actions.append({
                        "person_id": p["id"], "name": name, "firm": p.get("firm"), "tier": tier,
                        "kind": "followup",
                        "key": action_key("followup", p, p.get("last_outbound_at"), sent),
                        "urgency": "overdue" if quiet >= followup_after * 2 else "today",
                        "label": "Follow up (nudge #%d)" % (sent + 1),
                        "detail": "%.0f days since your last email, no reply" % quiet,
                    })
                else:
                    actions.append({
                        "person_id": p["id"], "name": name, "firm": p.get("firm"), "tier": tier,
                        "kind": "stop",
                        "key": action_key("stop", p, sent),
                        "urgency": "low",
                        "label": "Stop following up",
                        "detail": "%d nudges sent — move on and ask a summer intern for help"
                                  % sent,
                    })

        # 3. Replied to you and the ball is in your court
        if last_in and last_out and last_in > last_out and status not in ("scheduled", "chat_done", "thankyou_sent"):
            actions.append({
                "person_id": p["id"], "name": name, "firm": p.get("firm"), "tier": tier,
                "kind": "reply",
                "key": action_key("reply", p, p.get("last_inbound_at")),
                "urgency": "today",
                "label": "They replied — respond",
                "detail": "Reply received %s" % last_in.strftime("%b %d"),
            })

    # 4. Follow-ups Claude filed after a chat (people to contact, things to
    #    watch for). Due dates only set the urgency; there's no clock otherwise.
    for f in db.list_followups():
        due = iso_date(f.get("due"))
        days = (due.date() - now.date()).days if due else None
        actions.append({
            "person_id": f.get("person_id"),
            "name": f.get("person_name") or f.get("firm") or "Follow-up",
            "firm": f.get("firm") if f.get("person_name") else "",  # firm shown as name otherwise
            "tier": "B", "kind": "todo",
            "key": "todo:" + f["key"],
            "urgency": ("overdue" if days is not None and days < 0
                        else "today" if days is not None and days <= 3 else "low"),
            "label": f.get("text") or "",
            "detail": ("due " + due.strftime("%b %d")) if due else "",
        })

    actions = [a for a in actions if a.get("key") not in resolved]
    order = {"overdue": 0, "today": 1, "low": 2}
    tier_order = {"A": 0, "B": 1, "C": 2}
    # Urgency still comes first — an overdue Tier-C beats a today Tier-A — but
    # within the same urgency a target-firm contact shouldn't be buried under
    # everyone you're not actually prioritising.
    # Thank-yous first, then replies and follow-ups, nudges last.
    kind_order = {"thankyou": 0, "reply": 1, "todo": 2, "followup": 3, "stop": 4}
    actions.sort(key=lambda a: (kind_order.get(a["kind"], 5), order.get(a["urgency"], 3),
                                tier_order.get(a.get("tier"), 1)))
    return actions


def firm_coverage(people, settings):
    targets = [t.strip() for t in (settings.get("target_firms") or "").split(",") if t.strip()]
    buckets = {}
    for p in people:
        if p.get("status") == "uninitiated":
            continue            # Today only counts people past Uninitiated
        firm = (p.get("firm") or "Unassigned").strip()
        b = buckets.setdefault(firm, {"firm": firm, "total": 0, "chatted": 0,
                                      "scheduled": 0, "pending": 0})
        b["total"] += 1
        status = p.get("status")
        if status in ("chat_done", "thankyou_sent"):
            b["chatted"] += 1
        elif status == "scheduled":
            b["scheduled"] += 1
        elif status == "outreach_sent":
            b["pending"] += 1
    for t in targets:
        buckets.setdefault(t, {"firm": t, "total": 0, "chatted": 0,
                               "scheduled": 0, "pending": 0})
    rows = list(buckets.values())
    for row in rows:
        row["is_target"] = row["firm"] in targets
    # Firms you are actually working stay at the top; untouched targets sit
    # below as the reminder of where you have no coverage at all.
    rows.sort(key=lambda r: (r["total"] == 0, not r["is_target"],
                             -r["chatted"], -r["total"], r["firm"].lower()))
    return rows


def _store_pdf(blob, name):
    """Keep the uploaded file next to the database. The text is what the app
    reads, but holding on to the original means a profile can be read again
    later — after a parser fix, say — without asking for the file twice."""
    path = os.path.join(db.profiles_dir(), "%s.pdf" % name)
    with open(path, "wb") as fh:
        fh.write(blob)
    return path


RESUME_TYPES = {".pdf": "application/pdf",
                ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
RESUME_MAX_BYTES = 10 * 1024 * 1024


def resume_attachment(settings):
    """The stored resume copy, if there is one and it can actually be read.

    Everything that mentions or attaches a resume goes through this, so the
    email never says "I've attached my resume" when nothing would be attached."""
    path = (settings.get("resume_file") or "").strip()
    if path and os.path.isfile(path) and os.access(path, os.R_OK):
        return path
    return ""


def _safe_filename(name, ext):
    """Keep the name they chose — it is what the recipient sees on the
    attachment — minus anything that could escape the folder."""
    base = os.path.basename((name or "").replace("\\", "/"))
    stem = os.path.splitext(base)[0]
    stem = "".join(c for c in stem if c.isalnum() or c in " -_.()&,'").strip(" .")
    return (stem[:80] or "Resume") + ext


def _profile_summary(parsed):
    """Just enough for the interface to say what it understood."""
    if not parsed.get("ok"):
        return {"ok": False}
    return {
        "ok": True,
        "name": parsed.get("name", ""),
        "headline": parsed.get("headline", ""),
        "roles": len(parsed.get("roles") or []),
        "education": len(parsed.get("education") or []),
        "top_role": (parsed.get("roles") or [{}])[0].get("title", ""),
        "top_company": (parsed.get("roles") or [{}])[0].get("company", ""),
    }


def my_profile(settings):
    """Your own parsed profile, used to work out what you share with someone."""
    raw = (settings.get("user_profile_raw") or "").strip()
    if not raw:
        return {}
    parsed = profile_reader.parse(raw)
    return parsed if parsed.get("ok") else {}


def their_profile(person):
    raw = (person.get("linkedin_raw") or "").strip()
    if not raw:
        return {}
    parsed = profile_reader.parse(raw)
    if not parsed.get("ok"):
        return {}
    # The firm and role on the person's own record describe "now" even when
    # LinkedIn hasn't caught up — same reconciliation the prep sheet applies,
    # so an outreach draft's career clause doesn't quote a stale title.
    parsed = dict(parsed)
    parsed["roles"] = profile_reader.current_from_person(parsed, person)
    return parsed


def stored_slot_lines(person, today=None):
    """The windows picked for this person, minus any whose day has passed.

    Returns None when there is nothing usable, so the caller can fall back to
    working out fresh availability.
    """
    raw = (person.get("offered_slots") or "").strip()
    if not raw:
        return None
    try:
        saved = json.loads(raw)
    except ValueError:
        return None

    lines = saved.get("lines") or []
    days = saved.get("days") or []
    if not lines:
        return None
    if not days or len(days) != len(lines):
        return lines          # nothing to date-check against

    today = today or dt.date.today()
    fresh = [line for day, line in zip(days, lines)
             if (iso_date(day.get("date")) or dt.datetime.max).date() >= today]
    return fresh or None


def outlook_draft_for(pid, kind, subject, body):
    """Claude's outreach / thank-you, opened as an Outlook draft (never sent).

    Outreach needs windows saved on the person first — the email must offer
    exactly the holds on the calendar. Status and clocks move the same way as
    when the draft is opened from the interface.
    """
    settings = db.get_settings()
    person = db.get_person(pid)
    if not person:
        return {"ok": False, "error": "person not found"}
    if kind not in ("outreach", "thankyou"):
        return {"ok": False, "error": "kind must be outreach or thankyou"}
    lines = stored_slot_lines(person) if kind == "outreach" else None
    if kind == "outreach" and not lines:
        return {"ok": False, "error": "no slots saved for %s yet — pick them in "
                "Suggest slots and save, then refresh" % person["name"]}
    tz_label = settings.get("tz_label") or "ET"
    text = body or ""
    if kind == "outreach":
        text = text.replace("{{HORIZON}}", templates._horizon(lines))
        text = text.replace("{{SLOTS}}", templates._slot_block(lines, tz_label))
    subject = subject or templates._subject(settings)
    left = templates.unfilled(text)
    if left:
        return {"ok": False, "error": "unfilled placeholders: %s" % left}
    attachment = resume_attachment(settings) if kind == "outreach" else ""
    try:
        result = macos.draft_email(person.get("email", ""), person.get("name", ""),
                                   subject, text, attachment)
    except macos.BridgeError as exc:
        return {"ok": False, "error": str(exc)}
    stamp = dt.datetime.now(
        availability.get_tz(settings.get("timezone", "America/New_York"))).isoformat()
    patch = {"last_outbound_at": stamp}
    if kind == "outreach":
        patch.update({"draft_subject": subject, "draft_body": body})
        if person.get("status") in ("uninitiated", "tracking"):
            patch.update({"status": "outreach_sent", "first_contact_at": stamp})
    else:
        patch.update({"status": "thankyou_sent", "thankyou_sent_at": stamp})
    db.update_person(pid, patch)
    db.add_sent_mail(pid, kind, subject, text, stamp)
    return {"ok": True, "kind": kind, "slots": lines or [],
            "attached_resume": bool(attachment), "demo": bool(result.get("demo"))}


def save_offered_slots(pid, windows):
    """Windows Claude chose, saved exactly like Suggest slots → Save."""
    settings = db.get_settings()
    person = db.get_person(pid)
    if not person:
        return {"ok": False, "error": "person not found"}
    tz = availability.get_tz(settings.get("timezone", "America/New_York"))
    pairs = []
    for w in windows:
        s_, e_ = availability.parse_iso(str(w.get("start"))), availability.parse_iso(str(w.get("end")))
        if not s_ or not e_ or e_ <= s_:
            return {"ok": False, "error": "bad window %r" % (w,)}
        pairs.append((s_, e_))
    old = _offered_windows(person)
    calendar = _sync_holds(person, settings, old, pairs)
    if not pairs:
        db.update_person(pid, {"offered_slots": "", "offered_slots_at": None})
        return {"ok": True, "lines": [], "calendar": calendar}
    days = _days_from_windows(pairs, tz)
    lines = availability.format_slot_lines(days, settings.get("tz_label", "ET"))
    db.update_person(pid, {
        "offered_slots": json.dumps({"lines": lines, "days": days}),
        "offered_slots_at": dt.datetime.now(tz).isoformat()})
    return {"ok": True, "lines": lines, "calendar": calendar}


_cal_thread = [None]


def _maybe_export_calendar():
    """Calendar reads can take a while; never hold up the page for one."""
    if not os.path.exists(research.CAL_REQUEST):
        return
    t = _cal_thread[0]
    if t and t.is_alive():
        return
    t = threading.Thread(target=research.calendar_export,
                         args=(macos.read_calendar, db.get_settings()), daemon=True)
    _cal_thread[0] = t
    t.start()


# ------------------------------------------------ after a slot is confirmed

CHAT_MINUTES = 30


def _my_first_name(settings):
    return (settings.get("user_name") or "").split()[0] if (settings.get("user_name") or "").strip() else "Aashish"


def _zoom_block(settings):
    """Zoom's own invitation block, so the details read the way people expect.
    Used by both the calendar invite and the confirmation email."""
    zoom = (settings.get("zoom_link") or "").strip()
    if not zoom:
        return ""
    block = "\n\nJoin Zoom Meeting\n%s" % zoom
    mid = (settings.get("zoom_meeting_id") or "").strip()
    pwd = (settings.get("zoom_passcode") or "").strip()
    extra = "\n".join(x for x in (
        "Meeting ID: %s" % mid if mid else "",
        "Passcode: %s" % pwd if pwd else "") if x)
    if extra:
        block += "\n\n" + extra
    return block


def invite_text(person, settings):
    first = templates.first_name(person.get("name"))
    zoom = (settings.get("zoom_link") or "").strip()
    body = ("Hi %s,\n\nSharing the invite based on the slot you suggested. I have "
            "attached my resume here for your reference. Looking forward to connecting!"
            % first)
    if zoom:
        body += _zoom_block(settings)
    title = "%s x %s - Coffee Chat" % (first, _my_first_name(settings))
    return title, body


def confirmation_text(person, settings):
    first = templates.first_name(person.get("name"))
    zoom = (settings.get("zoom_link") or "").strip()
    body = ("Hi %s,\n\nThank you for the confirmation. I have shared the invite "
            "accordingly. I hope you are fine with a zoom meeting, let me know "
            "otherwise. Looking forward to connecting!" % first)
    if zoom:
        body += _zoom_block(settings)
    return body


def _chat_moment(person, settings):
    tz = availability.get_tz(settings.get("timezone", "America/New_York"))
    raw = person.get("chat_at")
    if not raw:
        return None
    moment = availability.parse_iso(raw) if "T" in raw else None
    if moment is None:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=tz)


def draft_chat_invite(pid):
    settings = db.get_settings()
    person = db.get_person(pid)
    if not person:
        return {"ok": False, "error": "person not found"}
    if not (person.get("email") or "").strip():
        return {"ok": False, "error": "Add %s's email first." % person["name"]}
    start = _chat_moment(person, settings)
    if not start or person.get("status") != "scheduled":
        return {"ok": False, "error": "Confirm a slot first — there's no chat time yet."}
    title, body = invite_text(person, settings)
    attachment = resume_attachment(settings)
    try:
        res = macos.draft_invite(person["email"], person["name"], title, body, start,
                                 CHAT_MINUTES, (settings.get("zoom_link") or "").strip(),
                                 attachment)
    except macos.BridgeError as exc:
        return {"ok": False, "error": str(exc)}
    stamp = dt.datetime.now(start.tzinfo).isoformat()
    db.update_person(pid, {"invite_drafted_at": stamp})
    db.add_sent_mail(pid, "invite", title, body, stamp)
    return {"ok": True, "attached": res.get("attached", False) and bool(attachment),
            "has_resume": bool(attachment), "zoom": bool(settings.get("zoom_link")),
            "demo": bool(res.get("demo"))}


def draft_chat_confirmation(pid):
    settings = db.get_settings()
    person = db.get_person(pid)
    if not person:
        return {"ok": False, "error": "person not found"}
    if not (person.get("email") or "").strip():
        return {"ok": False, "error": "Add %s's email first." % person["name"]}
    if not person.get("chat_at") or person.get("status") != "scheduled":
        return {"ok": False, "error": "Confirm a slot first — there's no chat time yet."}
    body = confirmation_text(person, settings)
    subject = "Re: " + templates._subject(settings)
    try:
        res = macos.draft_reply(person["email"], person["name"], subject, body)
    except macos.BridgeError as exc:
        return {"ok": False, "error": str(exc)}
    stamp = dt.datetime.now(
        availability.get_tz(settings.get("timezone", "America/New_York"))).isoformat()
    db.update_person(pid, {"confirm_drafted_at": stamp, "last_outbound_at": stamp})
    db.add_sent_mail(pid, "confirmation", subject, body, stamp)
    return {"ok": True, "threaded": res.get("threaded", False), "demo": bool(res.get("demo"))}


research.HOOKS["save_slots"] = save_offered_slots
research.HOOKS["make_draft"] = outlook_draft_for
research.HOOKS["slot_lines"] = lambda p: stored_slot_lines(p)


def roll_finished_chats(people, settings):
    """A scheduled chat whose slot has come and gone is a chat you have had.

    Without this a meeting sits in 'Chat scheduled' forever, which quietly
    breaks everything downstream: firm coverage never counts it as spoken, and
    the person keeps appearing under what is coming up.
    """
    tz = availability.get_tz(settings.get("timezone", "America/New_York"))
    now = dt.datetime.now(tz)
    moved = []
    for p in people:
        if p.get("status") != "scheduled":
            continue
        when = iso_date(p.get("chat_at"))
        if not when:
            continue
        when = when.replace(tzinfo=tz) if not when.tzinfo else when.astimezone(tz)
        if now >= when + dt.timedelta(minutes=CHAT_RUN_MINUTES):
            db.update_person(p["id"], {"status": "chat_done"})
            moved.append(p["id"])
    return moved


def chat_buckets(people, settings):
    """Split every dated chat into what is coming and what is happening now.
    A chat past its run time isn't a bucket here — `roll_finished_chats`
    already moves it to Chat done, and the thank-you clock (in
    `compute_actions`) is what keeps it visible until that note goes out."""
    tz = availability.get_tz(settings.get("timezone", "America/New_York"))
    now = dt.datetime.now(tz)
    lead = dt.timedelta(minutes=CHAT_LEAD_MINUTES)
    run = dt.timedelta(minutes=CHAT_RUN_MINUTES)

    buckets = {"current": [], "upcoming": []}
    for p in people:
        when = iso_date(p.get("chat_at"))
        if not when:
            continue
        when = when.replace(tzinfo=tz) if not when.tzinfo else when.astimezone(tz)
        if now >= when + run:
            continue
        fmt = "%a %b %d, %-I:%M %p" if os.name != "nt" else "%a %b %d, %I:%M %p"
        row = {
            "person_id": p["id"], "name": p.get("name"), "firm": p.get("firm"),
            "role": p.get("role"), "when": when.isoformat(),
            "when_label": when.strftime(fmt),
            "minutes_away": int((when - now).total_seconds() // 60),
            "thankyou_sent": bool(p.get("thankyou_sent_at")),
        }
        if now < when - lead:
            buckets["upcoming"].append(row)
        else:
            buckets["current"].append(row)

    buckets["current"].sort(key=lambda r: r["when"])
    buckets["upcoming"].sort(key=lambda r: r["when"])
    return buckets


def _taken_by_others(exclude_id=None):
    """Windows saved as offered slots for anyone other than `exclude_id`."""
    taken = []
    for person in db.list_people():
        if exclude_id is not None and person.get("id") == exclude_id:
            continue
        taken.extend(_offered_windows(person))
    return taken


def build_slots(settings, refresh_days=None, after=None, person_id=None):
    """One 2-hour block per slot (9-11, 11-1, 1-3, 3-5) for the next three
    weekdays, minus only blocks already saved for someone else."""
    tz = availability.get_tz(settings.get("timezone", "America/New_York"))
    now = dt.datetime.now(tz)
    cutoff = None
    if after:
        parsed = availability.parse_iso(str(after))
        if parsed:
            cutoff = parsed.date()
    try:
        pid = int(person_id) if person_id is not None else None
    except (TypeError, ValueError):
        pid = None
    # Fully-booked weekdays are skipped rather than counted, so "3 more days"
    # always means 3 more days that have something open.
    days = availability.find_windows(_taken_by_others(pid), settings,
                                     now=now, after=cutoff, skip_full=True)
    lines = availability.format_slot_lines(days, settings.get("tz_label", "ET"))
    return {"days": days, "lines": lines, "event_count": 0,
            "demo": False, "note": ""}


def sync_outlook(settings):
    people = db.list_people()
    lookup = db.people_by_email()
    messages, diagnostics = macos.scan_outlook(
        days_back=int(settings.get("outlook_lookback_days", 30) or 30)
    )
    matched = 0
    for msg in messages:
        pid = lookup.get(msg["address"])
        if not pid:
            continue
        db.record_mail(pid, msg["direction"], msg["subject"], msg["address"],
                       msg["when"].isoformat())
        matched += 1

    # Nudge statuses forward where the mailbox makes the answer obvious.
    advanced = []
    for p in db.list_people():
        last_in = iso_date(p.get("last_inbound_at"))
        last_out = iso_date(p.get("last_outbound_at"))
        status = p.get("status")
        if status in ("uninitiated", "tracking") and last_out:
            db.update_person(p["id"], {"status": "outreach_sent",
                                       "first_contact_at": p["last_outbound_at"]})
            advanced.append("%s → outreach sent" % p["name"])
    return {
        "scanned": len(messages),
        "matched": matched,
        "advanced": advanced,
        "diagnostics": diagnostics,
        "people": len(people),
    }


def probe_connections():
    """Check Calendar and Outlook once, in the background, at startup — so the
    app knows what it can do before you ask it to do it."""
    global _outlook_status, _calendar_status
    try:
        status = macos.detect_outlook()
    except Exception as exc:
        status = {"flavor": "error", "detail": "%s: %s" % (type(exc).__name__, exc)}
    status["checked"] = True
    _outlook_status = status

    try:
        calendar = macos.detect_calendar()
    except Exception as exc:
        calendar = {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
    calendar["checked"] = True
    _calendar_status = calendar


# ------------------------------------------------------------ applications

# How close a deadline has to be before Today mentions it. A fortnight is
# noise; a day is too late to tailor anything.
DEADLINE_WINDOW_DAYS = 7


def application_lines(applications):
    """The in-app deadline lines for Today. Nothing is emailed or notified —
    this screen is the only place recruiting ever nags from."""
    lines = []
    for app in applications:
        days = app.get("days_to_deadline")
        if days is None or days > DEADLINE_WINDOW_DAYS:
            continue
        if app.get("status") in ("applied", "interview_r1", "interview_r2",
                                 "offer", "rejected", "withdrawn"):
            continue
        if days < 0:
            urgency, detail = "overdue", ("deadline passed %d day%s ago"
                                          % (-days, "" if days == -1 else "s"))
        elif days == 0:
            urgency, detail = "overdue", "deadline is today"
        else:
            urgency, detail = "today", ("%d day%s to the deadline"
                                        % (days, "" if days == 1 else "s"))
        lines.append({
            "application_id": app["id"], "company": app["company"],
            "role": app.get("role") or "", "urgency": urgency,
            "deadline": app.get("deadline"), "detail": detail,
            "status": app.get("status"),
        })
    lines.sort(key=lambda l: (0 if l["urgency"] == "overdue" else 1,
                              l["deadline"] or ""))
    return lines


def firm_cards(firms):
    """The six cards on the Firms tab: who you know, and what is due."""
    return [{"firm": f["firm"], "people_count": f["people_count"],
             "chatted_count": f["chatted_count"],
             "knowledge_count": len(f["knowledge"]),
             "application_count": len(f["applications"]),
             "next_deadline_days": f["next_deadline_days"]}
            for f in firms]


def apply_proposal(prop, payload):
    """Put an accepted proposal into the tracker.

    Every branch goes through the same functions the screens do — a knowledge
    entry lands exactly as one typed on the firm page, a resume walk keeps its
    old version, a person update is an ordinary field save. Accepting is only
    a shortcut past the typing, never past the rules."""
    kind = prop["kind"]
    label = prop.get("source_label") or ""
    pid = prop.get("person_id")

    if kind == "firm_knowledge":
        firm = db.match_target_firm(payload.get("firm"))
        if not firm:
            raise ValueError("%r is not one of the six target firms"
                             % payload.get("firm"))
        kid = db.add_knowledge(
            firm, payload.get("category") or "other", payload.get("body") or "",
            source_type=payload.get("source_type") or "chat",
            source_person_id=pid, source_label=payload.get("source_label") or label,
            source_url=payload.get("source_url") or "")
        return ("Added to %s" % firm) if kid else ("Already on file for %s" % firm)

    if kind == "resume_walk":
        done = []
        if payload.get("new_text") is not None:
            db.set_resume_walk(payload["new_text"], source=label or "proposal")
            done.append("script updated — the previous version is in the history")
        if payload.get("add_feedback"):
            db.add_resume_feedback(payload["add_feedback"], source=label)
            done.append("coaching point added")
        if not done:
            raise ValueError("nothing to apply: expected new_text or add_feedback")
        return "; ".join(done)

    if kind == "person_update":
        if not pid:
            raise ValueError("this proposal is not attached to anyone in the tracker")
        patch = {k: v for k, v in payload.items()
                 if k in db.PERSON_FIELDS and k != "takeaway"}
        if patch:
            db.update_person(pid, patch)
        if payload.get("takeaway"):
            db.add_note(pid, payload["takeaway"], "takeaway")
        return "Updated %s" % (db.get_person(pid) or {}).get("name", "them")

    if kind == "application_update":
        # Literally the inbox handler, so an accepted proposal and an imported
        # application file can never drift apart.
        res = research._application_file(dict(payload), db.list_people(True), "")
        return ("Added %s" if res.get("created") else "Updated %s") % res["company"]

    raise ValueError("unknown proposal kind %r" % kind)


def _snapshots():
    """Keep the agent's snapshots level with the app after every change."""
    try:
        research.write_snapshots()
    except OSError as exc:
        return {"snapshot_error": str(exc)}
    return {}


def decide_proposals(ids, status, payload=None):
    """Accept or reject, one at a time, saying what each one did.

    One failure doesn't stop the rest: in a batch of eight, the seven that
    apply cleanly should still land, and the one that didn't says why and
    stays pending for you to fix."""
    results, applied, failed = [], 0, 0
    for pid in ids:
        prop = db.get_proposal(pid)
        if not prop or prop["status"] != "pending":
            continue
        entry = {"id": pid, "kind": prop["kind"]}
        if status == "accepted":
            use = payload if payload is not None else prop["payload"]
            try:
                entry["applied"] = apply_proposal(prop, use)
                db.set_proposal(pid, "accepted",
                                payload if payload is not None else None)
                applied += 1
            except Exception as exc:  # noqa: BLE001 — surfaced in the UI
                entry["error"] = "%s: %s" % (type(exc).__name__, exc)
                failed += 1
        else:
            db.set_proposal(pid, "rejected")
            entry["applied"] = "Rejected"
        results.append(entry)
    _snapshots()
    return {"ok": failed == 0, "results": results, "applied": applied,
            "failed": failed,
            "error": ("%d of these could not be applied — they are still "
                      "pending." % failed) if failed else None}


def state_payload():
    settings = db.get_settings()
    # Research files Claude dropped in research/inbox/ land on the next refresh.
    with _import_lock:
        imported = research.import_inbox()
        try:
            research.write_snapshots()
        except OSError:
            pass
    _maybe_export_calendar()
    people = db.list_people()
    if roll_finished_chats(people, settings):
        people = db.list_people()   # re-read so everything below sees the move
    applications = db.list_applications()
    firms = research.firms_payload()
    return {
        "settings": settings,
        "people": people,
        "statuses": [{"key": k, "label": l} for k, l in db.STATUSES],
        "actions": compute_actions(people, settings, db.resolved_keys()),
        "coverage": firm_coverage(people, settings),
        "chats": chat_buckets(people, settings),
        "bin": db.bin_items(SESSION),
        "questions": templates.QUESTION_BANK,
        "outlook": _outlook_status,
        "calendar": _calendar_status,
        "platform": {"is_mac": macos.IS_MAC, "demo": macos.DEMO},
        "imported": imported,
        "applications": applications,
        "application_statuses": [{"key": k, "label": l}
                                 for k, l in db.APPLICATION_STATUSES],
        "deadlines": application_lines(applications),
        "firms": firms,
        "firm_cards": firm_cards(firms),
        "target_firms": db.TARGET_FIRMS,
        "knowledge_categories": [{"key": k, "label": l}
                                 for k, l in db.KNOWLEDGE_CATEGORIES],
        "proposals": db.list_proposals(),
        "proposal_batches": db.proposal_batches(),
        "resume_walk": db.resume_walk(),
    }


# ---------------------------------------------------------------- handler

class Handler(BaseHTTPRequestHandler):
    server_version = "CoffeeChatTracker/1.0"

    def log_message(self, fmt, *args):
        pass  # keep the launcher's console clean

    # -- plumbing ---------------------------------------------------------
    def _send(self, code, body, content_type="application/json; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            pass

    def _json(self, payload, code=200):
        self._send(code, json.dumps(payload, default=str))

    def _file(self, data, content_type, filename):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition",
                         'attachment; filename="%s"' % filename.replace('"', ""))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(data)
        except BrokenPipeError:
            pass

    def _error(self, message, code=400):
        self._json({"ok": False, "error": str(message)}, code)

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError:
            return {}

    def _authorised(self):
        # Local-only server, but a random token still stops any other page in
        # your browser from poking at the API behind your back.
        return self.headers.get("X-CCT-Token") == TOKEN

    # -- routing ----------------------------------------------------------
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path.startswith("/api/"):
            if not self._authorised():
                return self._error("unauthorised", 403)
            return self._api_get(path)

        if path in ("/", "/index.html"):
            return self._serve_index()
        return self._serve_static(path)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path == "/api/close":
            # sendBeacon cannot set headers, so the token rides in the query.
            query = urllib.parse.parse_qs(parsed.query)
            if (query.get("t") or [""])[0] != TOKEN:
                return self._error("unauthorised", 403)
            # Don't exit outright — another window may still be open. Wind the
            # clock forward instead, so any surviving window's next heartbeat
            # cancels the shutdown.
            _last_beat[0] = time.time() - HEARTBEAT_GRACE + CLOSE_GRACE
            return self._json({"ok": True})

        if not self._authorised():
            return self._error("unauthorised", 403)
        try:
            return self._api_post(parsed.path, self._body())
        except macos.BridgeError as exc:
            return self._error(exc, 502)
        except Exception as exc:  # surface the real problem in the UI
            return self._error("%s: %s" % (type(exc).__name__, exc), 500)

    def do_DELETE(self):
        if not self._authorised():
            return self._error("unauthorised", 403)
        path = urllib.parse.urlparse(self.path).path
        parts = [p for p in path.split("/") if p]
        if len(parts) == 3 and parts[1] == "person":
            db.delete_person(int(parts[2]))
            return self._json({"ok": True})
        if len(parts) == 3 and parts[1] == "note":
            db.delete_note(int(parts[2]))
            return self._json({"ok": True})
        if len(parts) == 3 and parts[1] == "application":
            db.delete_application(int(parts[2]))
            return self._json({"ok": True, **_snapshots()})
        if len(parts) == 3 and parts[1] == "knowledge":
            db.delete_knowledge(int(parts[2]))
            return self._json({"ok": True, **_snapshots()})
        if len(parts) == 4 and parts[1] == "resume-walk" and parts[2] == "feedback":
            db.delete_resume_feedback(int(parts[3]))
            return self._json({"ok": True, **_snapshots()})
        return self._error("unknown endpoint", 404)

    # -- static -----------------------------------------------------------
    def _serve_index(self):
        with open(os.path.join(WEB_DIR, "index.html"), "r", encoding="utf-8") as fh:
            html = fh.read()
        html = html.replace("__CCT_TOKEN__", TOKEN)
        self._send(200, html, "text/html; charset=utf-8")

    def _serve_static(self, path):
        safe = os.path.normpath(path).lstrip("/")
        full = os.path.join(WEB_DIR, safe)
        if not os.path.abspath(full).startswith(os.path.abspath(WEB_DIR)) \
                or not os.path.isfile(full):
            return self._send(404, "not found", "text/plain; charset=utf-8")
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        with open(full, "rb") as fh:
            self._send(200, fh.read(), ctype)

    # -- API --------------------------------------------------------------
    def _api_get(self, path):
        if path == "/api/ping":
            _last_beat[0] = time.time()
            return self._json({"ok": True})
        if path == "/api/state":
            _last_beat[0] = time.time()
            return self._json(state_payload())
        if path == "/api/resume":
            stored = resume_attachment(db.get_settings())
            if not stored:
                return self._error("No resume uploaded yet.", 404)
            ext = os.path.splitext(stored)[1].lower()
            with open(stored, "rb") as fh:
                return self._file(fh.read(), RESUME_TYPES.get(ext, "application/octet-stream"),
                                  os.path.basename(stored))
        if path.startswith("/api/profile-pdf/"):
            # Hand back the file that was uploaded, so it can be reopened from
            # the app rather than hunted for in Downloads.
            who = path.rsplit("/", 1)[1]
            if who == "me":
                stored = db.get_settings().get("user_profile_pdf", "")
                label = "My LinkedIn profile.pdf"
            else:
                person = db.get_person(int(who))
                stored = (person or {}).get("profile_pdf", "")
                label = "%s - LinkedIn.pdf" % (person or {}).get("name", "profile")
            if not stored or not os.path.isfile(stored):
                return self._error("no stored PDF for that profile", 404)
            with open(stored, "rb") as fh:
                return self._file(fh.read(), "application/pdf", label)

        if path.startswith("/api/person/"):
            pid = int(path.rsplit("/", 1)[1])
            person = db.get_person(pid)
            return self._json(person) if person else self._error("not found", 404)
        if path.startswith("/api/application/"):
            app = db.get_application(int(path.rsplit("/", 1)[1]))
            return self._json(app) if app else self._error("not found", 404)
        return self._error("unknown endpoint", 404)

    def _api_post(self, path, body):
        settings = db.get_settings()

        # -- applications ------------------------------------------------
        if path == "/api/application":
            aid = db.create_application(body)
            return self._json({"ok": True, "application": db.get_application(aid),
                               **_snapshots()})

        if path.startswith("/api/application/") and path.endswith("/open"):
            aid = int(path.split("/")[3])
            app = db.get_application(aid)
            if not app:
                return self._error("not found", 404)
            which = "cover_letter_file" if body.get("which") == "cover_letter" \
                else "resume_file"
            stored = os.path.expanduser((app.get(which) or "").strip())
            if not stored:
                return self._error("No file recorded for that yet.", 404)
            if not os.path.exists(stored):
                # Almost always iCloud: the path is right, the file has been
                # evicted, or it has moved since it was noted down.
                return self._error("That file isn't where the application says "
                                   "it is:\n%s" % stored, 404)
            if not macos.open_path(stored):
                return self._error("macOS would not open that file.", 502)
            return self._json({"ok": True, "opened": stored})

        if path.startswith("/api/application/"):
            aid = int(path.split("/")[3])
            return self._json({"ok": True,
                               "application": db.update_application(aid, body),
                               **_snapshots()})

        # -- firm knowledge ----------------------------------------------
        if path == "/api/knowledge":
            kid = db.add_knowledge(
                body.get("firm"), body.get("category"), body.get("body"),
                source_type=body.get("source_type") or "chat",
                source_person_id=body.get("source_person_id"),
                source_label=body.get("source_label") or "",
                source_url=body.get("source_url") or "")
            if kid is None:
                return self._error("That exact note is already on file for this firm.")
            return self._json({"ok": True, "id": kid, **_snapshots()})

        if path.startswith("/api/knowledge/"):
            db.update_knowledge(int(path.split("/")[3]), body)
            return self._json({"ok": True, **_snapshots()})

        # -- resume walk --------------------------------------------------
        if path == "/api/resume-walk":
            walk = db.set_resume_walk(body.get("body") or "",
                                      body.get("source") or "you")
            return self._json({"ok": True, "resume_walk": walk, **_snapshots()})

        if path == "/api/resume-walk/feedback":
            db.add_resume_feedback(body.get("body") or "", body.get("source") or "")
            return self._json({"ok": True, "resume_walk": db.resume_walk(),
                               **_snapshots()})

        # -- proposals ----------------------------------------------------
        if path == "/api/proposal/decide":
            return self._json(decide_proposals(
                [int(body.get("id"))], body.get("status") or "rejected",
                body.get("payload")))

        if path == "/api/proposal/decide-batch":
            ids = [p["id"] for p in db.list_proposals("pending")
                   if p["batch_id"] == body.get("batch_id")]
            if not ids:
                return self._error("Nothing left pending in that batch.")
            return self._json(decide_proposals(ids, body.get("status") or "accepted"))

        if path == "/api/settings":
            return self._json({"ok": True, "settings": db.save_settings(body)})

        if path == "/api/person":
            pid = db.create_person(body)
            return self._json({"ok": True, "person": db.get_person(pid)})

        if path.startswith("/api/person/") and path.endswith("/note"):
            pid = int(path.split("/")[3])
            db.add_note(pid, body.get("body", ""), body.get("kind", "note"))
            return self._json({"ok": True, "person": db.get_person(pid)})

        if path.startswith("/api/person/"):
            pid = int(path.split("/")[3])
            return self._json({"ok": True, "person": db.update_person(pid, body)})

        if path == "/api/slots":
            with _lock:
                return self._json({"ok": True, **build_slots(
                    settings, body.get("days"), body.get("after"),
                    body.get("person_id"))})

        if path == "/api/slots.ics":
            # Export exactly what is on screen, so the file and the email agree.
            days = body.get("days")
            if not days:
                with _lock:
                    days = build_slots(settings).get("days", [])
            windows = ics.windows_from_days(days, availability.parse_iso)
            text, count = ics.build_slots_ics(windows, body.get("label", ""), settings)
            if not count:
                return self._error("There are no slots to export yet.", 400)
            # Saved into the app's own holds/ folder (not Downloads) and opened,
            # which hands it straight to Calendar to import.
            label = (body.get("label") or "").strip()
            safe = "".join(c for c in label if c.isalnum() or c in " -_").strip() or "holds"
            folder = os.path.join(os.path.dirname(HERE), "holds")
            os.makedirs(folder, exist_ok=True)
            stamp = dt.datetime.now().strftime("%Y-%m-%d %H%M%S")
            file_path = os.path.join(folder, "Coffee chat holds - %s - %s.ics" % (safe, stamp))
            with open(file_path, "w", encoding="utf-8", newline="") as fh:
                fh.write(text)
            opened = macos.open_path(file_path)
            return self._json({"ok": True, "count": count, "file": os.path.basename(file_path),
                               "folder": "holds", "opened": opened})

        if path == "/api/confirm-slot":
            person = db.get_person(int(body.get("person_id") or 0))
            if not person:
                return self._error("person not found", 404)
            start = availability.parse_iso(body.get("start"))
            end = availability.parse_iso(body.get("end"))
            if not start or not end:
                return self._error("A start and end time are required.", 400)

            # Every window that had been offered, so whichever ones weren't
            # picked can be marked cancelled on the calendar.
            offered = []
            try:
                saved = json.loads(person.get("offered_slots") or "null")
            except ValueError:
                saved = None
            for day in (saved or {}).get("days", []):
                for w in day.get("windows", []):
                    w_start = availability.parse_iso(w.get("start"))
                    w_end = availability.parse_iso(w.get("end"))
                    if w_start and w_end:
                        offered.append((w_start, w_end))

            def same_window(a, b):
                return (abs((a[0] - b[0]).total_seconds()) < 60
                        and abs((a[1] - b[1]).total_seconds()) < 60)

            name = person.get("name") or ""
            prefix = settings.get("hold_prefix") or "Coffee chat hold"
            hold_title = "%s — %s" % (prefix, name) if name else prefix
            tz = availability.get_tz(settings.get("timezone", "America/New_York"))

            # Edit the calendar in place: every hold offered to them goes, and
            # the chat itself is added (or moved, if one was already there).
            deletes = [(hold_title, w[0], w[1]) for w in offered]
            old = _chat_start(person, tz)
            calendar = _sync_chat(person, settings, deletes, (start, end), old)

            # Keep a record in "confirmed slots", next to the app. Imported
            # from the file only if the calendar couldn't be edited directly.
            text = ics.build_confirm_ics((start, end), name, settings)
            safe = "".join(c for c in name if c.isalnum() or c in " -_").strip() or "chat"
            folder = os.path.join(os.path.dirname(HERE), "confirmed slots")
            os.makedirs(folder, exist_ok=True)
            file_path = os.path.join(folder, "Coffee chat confirmed - %s - %s.ics"
                                     % (safe, start.astimezone(tz).strftime("%Y-%m-%d %H%M")))
            with open(file_path, "w", encoding="utf-8", newline="") as fh:
                fh.write(text)
            placed = calendar.get("created") or calendar.get("updated")
            imported = macos.open_path(file_path) if not placed else False
            if placed:
                macos.open_path(app="Calendar")

            # Every other place chat_at is read (compute_actions, chat_buckets,
            # the drawer) treats it as naive local time, not UTC — store it the
            # same way, or it displays and sorts hours off.
            local_start = start.astimezone(tz).replace(tzinfo=None)
            patch = {"chat_at": local_start.isoformat(), "offered_slots": "",
                     "offered_slots_at": None}
            if person.get("status") not in ("chat_done", "thankyou_sent"):
                patch["status"] = "scheduled"
            db.update_person(person["id"], patch)

            return self._json({
                "ok": True,
                "file": os.path.basename(file_path),
                "folder": "confirmed slots",
                "imported": imported,
                "calendar": calendar,
                "holds": len(offered),
            })

        if path == "/api/chat/invite":
            return self._json(draft_chat_invite(int(body.get("person_id") or 0)))

        if path == "/api/chat/confirmation":
            return self._json(draft_chat_confirmation(int(body.get("person_id") or 0)))

        if path == "/api/chat/reschedule":
            person = db.get_person(int(body.get("person_id") or 0))
            if not person:
                return self._error("person not found", 404)
            start = availability.parse_iso(body.get("start"))
            end = availability.parse_iso(body.get("end"))
            if not start or not end or end <= start:
                return self._error("A start and a later end time are required.", 400)
            tz = availability.get_tz(settings.get("timezone", "America/New_York"))
            calendar = _sync_chat(person, settings, [], (start, end), _chat_start(person, tz))
            if calendar.get("created") or calendar.get("updated"):
                macos.open_path(app="Calendar")
            patch = {"chat_at": start.astimezone(tz).replace(tzinfo=None).isoformat()}
            if person.get("status") not in ("chat_done", "thankyou_sent"):
                patch["status"] = "scheduled"
            return self._json({"ok": True, "calendar": calendar,
                               "person": db.update_person(person["id"], patch)})

        if path == "/api/chat/cancel":
            person = db.get_person(int(body.get("person_id") or 0))
            if not person:
                return self._error("person not found", 404)
            tz = availability.get_tz(settings.get("timezone", "America/New_York"))
            old = _chat_start(person, tz)
            calendar = {"ok": True, "deleted": 0, "errors": []}
            if old:
                try:
                    calendar = macos.calendar_sync(delete=[(_chat_title(person), old, None)])
                except macos.BridgeError as exc:
                    calendar = {"ok": False, "deleted": 0, "error": str(exc)}
            patch = {"chat_at": None}
            if person.get("status") == "scheduled":
                patch["status"] = "outreach_sent"
            return self._json({"ok": True, "calendar": calendar,
                               "person": db.update_person(person["id"], patch)})

        if path == "/api/action/resolve":
            key = (body.get("key") or "").strip()
            if not key:
                return self._error("missing action key", 400)
            db.resolve_action(
                key, body.get("person_id"), body.get("kind", ""),
                body.get("label", ""), body.get("detail", ""),
                body.get("name", ""), SESSION,
            )
            # Ticking off "Send thank-you note" means it went out.
            if body.get("kind") == "thankyou" and body.get("person_id"):
                person = db.get_person(int(body["person_id"]))
                if person and person.get("status") != "thankyou_sent":
                    stamp = dt.datetime.now(availability.get_tz(
                        settings.get("timezone", "America/New_York"))).isoformat()
                    db.update_person(person["id"], {
                        "status": "thankyou_sent", "thankyou_sent_at": stamp})
            return self._json({"ok": True})

        if path == "/api/action/restore":
            key = (body.get("key") or "").strip()
            if not key:
                return self._error("missing action key", 400)
            # Undoing a ticked-off thank-you also undoes the status it set.
            conn = db.connect()
            try:
                row = conn.execute("SELECT kind, person_id FROM resolved_action "
                                   "WHERE key=?", (key,)).fetchone()
            finally:
                conn.close()
            if row and row["kind"] == "thankyou" and row["person_id"]:
                person = db.get_person(int(row["person_id"]))
                if person and person.get("status") == "thankyou_sent":
                    db.update_person(person["id"], {"status": "chat_done",
                                                    "thankyou_sent_at": None})
            db.restore_action(key)
            return self._json({"ok": True})

        if path == "/api/profile-pdf":
            # A LinkedIn "Save to PDF" export, for them or for you.
            try:
                blob = base64.b64decode(body.get("data") or "")
            except Exception:
                return self._error("That file could not be read.", 400)
            if not pdfreader.looks_like_pdf(blob):
                return self._error("That is not a PDF file.", 400)
            try:
                text = pdfreader.extract_text(blob)
            except pdfreader.PdfError as exc:
                return self._error(exc, 400)

            parsed = profile_reader.parse(text)
            stamp = dt.datetime.now(
                availability.get_tz(settings.get("timezone"))).isoformat()

            if body.get("self"):
                db.save_settings({
                    "user_profile_raw": text,
                    "user_profile_pdf": _store_pdf(blob, "me"),
                })
                return self._json({"ok": True, "self": True, "text": text,
                                   "parsed": _profile_summary(parsed)})

            if not body.get("person_id"):
                # No person exists yet — this is Add Person asking what the PDF
                # says before the record is created. Nothing is stored; the
                # blob comes back around in a second call once the person has
                # an id to attach it to.
                current = (parsed.get("roles") or [{}])[0] if parsed.get("ok") else {}
                return self._json({
                    "ok": True, "parsed": _profile_summary(parsed),
                    "suggested": {
                        "name": parsed.get("name", "") if parsed.get("ok") else "",
                        "firm": current.get("company", ""),
                        "role": current.get("title", ""),
                    },
                })

            person = db.get_person(int(body["person_id"]))
            if not person:
                return self._error("person not found", 404)
            patch = {"linkedin_raw": text, "profile_updated_at": stamp,
                     "profile_pdf": _store_pdf(blob, "person-%d" % person["id"])}
            # The export carries facts the row may be missing.
            if parsed.get("ok"):
                current = (parsed.get("roles") or [{}])[0]
                if not (person.get("firm") or "").strip() and current.get("company"):
                    patch["firm"] = current["company"]
                if not (person.get("role") or "").strip() and current.get("title"):
                    patch["role"] = current["title"]
            person = db.update_person(person["id"], patch)
            return self._json({"ok": True, "person": person,
                               "parsed": _profile_summary(parsed)})

        if path == "/api/resume":
            # Your resume, uploaded rather than pointed at, so the app keeps a
            # copy it is always allowed to read.
            name = body.get("name") or ""
            ext = os.path.splitext(name)[1].lower()
            if ext not in RESUME_TYPES:
                return self._error("Please upload your resume as a PDF or a Word (.docx) file.", 400)
            try:
                blob = base64.b64decode(body.get("data") or "")
            except Exception:
                return self._error("That file could not be read.", 400)
            if not blob:
                return self._error("That file is empty.", 400)
            if len(blob) > RESUME_MAX_BYTES:
                return self._error("That file is over 10 MB — too large to attach to an email.", 400)
            if ext == ".pdf" and not pdfreader.looks_like_pdf(blob):
                return self._error("That file is not really a PDF.", 400)
            if ext == ".docx" and not blob.startswith(b"PK"):
                return self._error("That file is not really a Word document.", 400)

            folder = db.resume_dir()
            for old in os.listdir(folder):           # one resume at a time
                try:
                    os.remove(os.path.join(folder, old))
                except OSError:
                    pass
            filename = _safe_filename(name, ext)
            stored = os.path.join(folder, filename)
            with open(stored, "wb") as fh:
                fh.write(blob)
            db.save_settings({"resume_file": stored, "resume_name": filename,
                              "resume_path": ""})
            return self._json({"ok": True, "name": filename, "bytes": len(blob)})

        if path == "/api/resume/remove":
            stored = resume_attachment(settings)
            if stored:
                try:
                    os.remove(stored)
                except OSError:
                    pass
            db.save_settings({"resume_file": "", "resume_name": "", "resume_path": ""})
            return self._json({"ok": True})

        if path == "/api/offered-slots":
            # What you picked for one person, kept so the draft you write
            # tomorrow offers the same times you offered today.
            person = db.get_person(int(body["person_id"]))
            if not person:
                return self._error("person not found", 404)
            # Saved slots and the busy holds on Apple Calendar move together:
            # windows dropped since the last save lose their hold, new ones
            # gain one, and clearing removes them all.
            old_windows = _offered_windows(person)
            new_days = [] if body.get("clear") else (body.get("days") or [])
            new_windows = ics.windows_from_days(new_days, availability.parse_iso)
            calendar = _sync_holds(person, settings, old_windows, new_windows)
            if body.get("clear"):
                person = db.update_person(person["id"],
                                          {"offered_slots": "", "offered_slots_at": None})
                return self._json({"ok": True, "person": person, "calendar": calendar})
            payload = json.dumps({
                "lines": body.get("lines") or [],
                "days": new_days,
            })
            stamp = dt.datetime.now(
                availability.get_tz(settings.get("timezone"))).isoformat()
            person = db.update_person(person["id"], {
                "offered_slots": payload, "offered_slots_at": stamp})
            return self._json({"ok": True, "person": person, "calendar": calendar})

        if path == "/api/prep":
            sheet = self._prep(body, settings)
            if sheet is None:
                return self._error("person not found", 404)
            return self._json({"ok": True, "prep": sheet})

        if path == "/api/prep.pdf":
            sheet = self._prep(body, settings)
            if sheet is None:
                return self._error("person not found", 404)
            if sheet.get("custom"):
                return self._error("Researched prep sheets aren't exported to PDF yet — use Copy prep sheet.", 400)
            data = pdfwriter.build_prep_pdf(sheet, settings)
            safe = "".join(c for c in sheet["person"]["name"]
                           if c.isalnum() or c in " -_").strip() or "prep"
            return self._file(data, "application/pdf", "Prep notes - %s.pdf" % safe)

        if path == "/api/draft":
            return self._draft(body, settings)

        if path == "/api/sync-outlook":
            with _lock:
                return self._json({"ok": True, **sync_outlook(settings)})

        if path == "/api/detect-outlook":
            global _outlook_status
            _outlook_status = macos.detect_outlook()
            _outlook_status["checked"] = True
            return self._json({"ok": True, "outlook": _outlook_status})

        if path == "/api/import":
            with _import_lock:
                report = research.import_inbox()
                try:
                    research.write_snapshots()
                except OSError:
                    pass
            return self._json({"ok": True, "results": report})

        if path == "/api/calendar/pull":
            try:
                return self._json(pull_from_calendar(settings))
            except macos.BridgeError as exc:
                return self._error(str(exc), 502)

        if path == "/api/detect-calendar":
            global _calendar_status
            try:
                _calendar_status = macos.detect_calendar()
            except macos.BridgeError as exc:
                _calendar_status = {"ok": False, "error": str(exc)}
            _calendar_status["checked"] = True
            return self._json({"ok": True, "calendar": _calendar_status})

        if path == "/api/calendar-event":
            result = macos.create_calendar_event(
                body.get("title", "Coffee chat"), body.get("start"), body.get("end"),
                body.get("notes", ""), settings.get("write_calendar", ""),
            )
            return self._json({"ok": bool(result.get("ok")), **result})

        return self._error("unknown endpoint", 404)

    def _prep(self, body, settings):
        """Shared by the on-screen prep sheet and the PDF, so the two can never
        drift apart."""
        person = db.get_person(int(body["person_id"]))
        if not person:
            return None
        if "raw" in body:
            stamp = dt.datetime.now(
                availability.get_tz(settings.get("timezone"))).isoformat()
            person = db.update_person(person["id"], {
                "linkedin_raw": body.get("raw", ""),
                "profile_updated_at": stamp,
            })
        if (person.get("prep_md") or "").strip():
            # Claude's researched prep sheet replaces the generated one.
            try:
                sources = json.loads(person.get("research_sources") or "[]")
            except ValueError:
                sources = []
            sheet = {"custom": True, "prep_md": person["prep_md"],
                     "research_md": person.get("research_md") or "",
                     "sources": sources, "researched_at": person.get("researched_at")}
        else:
            sheet = profile_reader.prep_sheet(person, settings, my_profile(settings))
        sheet["person"] = {
            "id": person["id"], "name": person["name"],
            "firm": person.get("firm", ""), "role": person.get("role", ""),
            "linkedin": person.get("linkedin", ""),
            "has_raw": bool((person.get("linkedin_raw") or "").strip()),
            "profile_updated_at": person.get("profile_updated_at"),
        }
        return sheet

    def _draft(self, body, settings):
        # Tell the email writer whether a resume will really go with it.
        settings = dict(settings, resume_ready="1" if resume_attachment(settings) else "")
        person = db.get_person(int(body["person_id"]))
        if not person:
            return self._error("person not found", 404)
        # Drafting no longer needs their LinkedIn PDF — without it the hook
        # paragraph is simply a placeholder. Only the prep sheet needs it.

        kind = body.get("kind", "outreach")
        lines = body.get("slot_lines")
        if lines is None and kind in ("outreach", "followup"):
            # Times you actually picked for this person beat a fresh guess —
            # otherwise the email offers different slots than the calendar
            # holds you already put down for them.
            lines = stored_slot_lines(person)
            if lines is None:
                lines = build_slots(settings).get("lines", [])

        if kind == "thankyou" and person.get("status") not in ("chat_done", "thankyou_sent"):
            return self._error("mark the chat as done before drafting the thank-you", 400)
        if kind == "thankyou" and (person.get("thankyou_body") or "").strip():
            # Claude's thank-you, written from the chat notes.
            draft = {"subject": person.get("thankyou_subject") or "Thank you",
                     "body": person["thankyou_body"]}
        elif kind == "thankyou":
            # No template: the thank-you is always written by Claude from the
            # chat notes. Until it is, the box opens empty.
            draft = {"subject": "Thank you - Aashish Balivada", "body": ""}
        elif kind == "followup":
            draft = templates.followup(person, settings, lines or [])
        elif (person.get("draft_body") or "").strip():
            # Claude's researched draft. {{SLOTS}} / {{HORIZON}} take the
            # windows picked for this person, so the email and holds agree.
            tz_label = settings.get("tz_label") or "ET"
            body_text = person["draft_body"]
            body_text = body_text.replace("{{HORIZON}}", templates._horizon(lines or [])
                                          if lines else "in the next couple of weeks")
            body_text = body_text.replace("{{SLOTS}}", templates._slot_block(lines or [], tz_label)
                                          if lines else "[No windows picked yet — use Suggest slots]")
            draft = {"subject": person.get("draft_subject") or templates._subject(settings),
                     "body": body_text}
        else:
            draft = templates.outreach(person, settings, lines or [],
                                       my_profile(settings), their_profile(person))

        # An edited draft from the interface wins over the scaffold.
        subject = body.get("subject") or draft["subject"]
        text = body.get("body") or draft["body"]

        if body.get("save_only") and kind in ("thankyou", "outreach"):
            # Manual save: keep your edits so the draft reopens exactly as
            # you left it. Opening a draft never rewrites what is stored.
            prefix = "thankyou" if kind == "thankyou" else "draft"
            db.update_person(person["id"], {prefix + "_subject": subject,
                                            prefix + "_body": body.get("body", "")})
            return self._json({"ok": True, "saved": True})

        if not body.get("open_in_outlook"):
            return self._json({"ok": True, "subject": subject, "body": text,
                               "unfilled": templates.unfilled(text)})

        remaining = templates.unfilled(text)
        if remaining and not body.get("force"):
            return self._json({"ok": False, "needs_edit": True, "unfilled": remaining,
                               "subject": subject, "body": text})

        attachment = resume_attachment(settings) if kind != "thankyou" else ""
        result = macos.draft_email(person.get("email", ""), person.get("name", ""),
                                   subject, text, attachment)

        # Record what we just did so the follow-up clock starts ticking.
        stamp = dt.datetime.now(
            availability.get_tz(settings.get("timezone", "America/New_York"))
        ).isoformat()
        patch = {"last_outbound_at": stamp}
        if kind == "outreach" and person.get("status") in ("uninitiated", "tracking"):
            patch.update({"status": "outreach_sent", "first_contact_at": stamp})
        elif kind == "followup":
            patch["followups_sent"] = int(person.get("followups_sent") or 0) + 1
        elif kind == "thankyou":
            patch.update({"status": "thankyou_sent", "thankyou_sent_at": stamp})
        try:
            flags = json.loads(person.get("sent_flags") or "{}") or {}
        except ValueError:
            flags = {}
        flags[kind] = True
        patch["sent_flags"] = json.dumps(flags)
        db.update_person(person["id"], patch)
        db.add_sent_mail(person["id"], kind, subject, text, stamp)

        return self._json({"ok": True, "drafted": True, "subject": subject,
                           "body": text, **({"demo": True} if result.get("demo") else {})})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--print-url", action="store_true")
    parser.add_argument("--no-watchdog", action="store_true")
    args = parser.parse_args()

    db.init()
    try:
        research.write_snapshots()
    except OSError:
        pass

    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    _server[0] = httpd
    port = httpd.server_address[1]
    url = "http://127.0.0.1:%d/?t=%s" % (port, TOKEN)

    print("CCT_URL=%s" % url, flush=True)
    if args.print_url:
        return

    # Find out what Calendar and Outlook can do without being asked twice. In
    # the background: the first calendar read can sit behind a permission
    # prompt, and the window should be up and usable while that happens.
    threading.Thread(target=probe_connections, daemon=True).start()

    if not args.no_watchdog:
        _last_beat[0] = time.time()

        def watchdog():
            while True:
                time.sleep(5)
                if time.time() - _last_beat[0] > HEARTBEAT_GRACE:
                    httpd.shutdown()
                    return

        threading.Thread(target=watchdog, daemon=True).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
