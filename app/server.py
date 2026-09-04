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
import templates  # noqa: E402

WEB_DIR = os.path.join(HERE, "web")
TOKEN = secrets.token_urlsafe(24)

# One id per run of the app. Items ticked off on Today are binned against it,
# which is what makes the bin empty itself when the app is next opened.
SESSION = secrets.token_urlsafe(12)

_outlook_status = {"checked": False}
_calendar_status = {"checked": False}
_lock = threading.Lock()

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
                "person_id": p["id"], "name": name, "firm": p.get("firm"),
                "kind": "thankyou",
                "key": action_key("thankyou", p, p.get("chat_at")),
                "urgency": "overdue" if hours > thankyou_hours else "today",
                "label": "Send thank-you note",
                "detail": ("%.0f hours since the chat — the window is %d"
                           % (hours, thankyou_hours)),
            })

        # 2. Silence after outreach
        elif status in ("outreach_sent", "awaiting_reply") and last_out:
            quiet = days_between(now, last_out)
            replied_since = last_in and last_in > last_out
            if not replied_since and quiet is not None and quiet >= followup_after:
                sent = int(p.get("followups_sent") or 0)
                if sent < max_followups:
                    actions.append({
                        "person_id": p["id"], "name": name, "firm": p.get("firm"),
                        "kind": "followup",
                        "key": action_key("followup", p, p.get("last_outbound_at"), sent),
                        "urgency": "overdue" if quiet >= followup_after * 2 else "today",
                        "label": "Follow up (nudge #%d)" % (sent + 1),
                        "detail": "%.0f days since your last email, no reply" % quiet,
                    })
                else:
                    actions.append({
                        "person_id": p["id"], "name": name, "firm": p.get("firm"),
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
                "person_id": p["id"], "name": name, "firm": p.get("firm"),
                "kind": "reply",
                "key": action_key("reply", p, p.get("last_inbound_at")),
                "urgency": "today",
                "label": "They replied — respond",
                "detail": "Reply received %s" % last_in.strftime("%b %d"),
            })

        # 4. Anything you scheduled yourself
        if p.get("next_action_date"):
            due = aware(iso_date(p["next_action_date"]))
            if due and due <= now + dt.timedelta(days=1):
                actions.append({
                    "person_id": p["id"], "name": name, "firm": p.get("firm"),
                    "kind": "custom",
                    "key": action_key("custom", p, p.get("next_action_date"),
                                      p.get("next_action")),
                    "urgency": "overdue" if due < now else "today",
                    "label": p.get("next_action") or "Follow up",
                    "detail": "Due %s" % due.strftime("%b %d"),
                })

    actions = [a for a in actions if a.get("key") not in resolved]
    order = {"overdue": 0, "today": 1, "low": 2}
    actions.sort(key=lambda a: order.get(a["urgency"], 3))
    return actions


def firm_coverage(people, settings):
    targets = [t.strip() for t in (settings.get("target_firms") or "").split(",") if t.strip()]
    buckets = {}
    for p in people:
        firm = (p.get("firm") or "Unassigned").strip()
        b = buckets.setdefault(firm, {"firm": firm, "total": 0, "chatted": 0,
                                      "scheduled": 0, "pending": 0})
        b["total"] += 1
        status = p.get("status")
        if status in ("chat_done", "thankyou_sent", "nurturing"):
            b["chatted"] += 1
        elif status == "scheduled":
            b["scheduled"] += 1
        elif status in ("outreach_sent", "awaiting_reply"):
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
    return parsed if parsed.get("ok") else {}


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
    """Split every dated chat into what is coming, what is happening, and what
    has been and gone."""
    tz = availability.get_tz(settings.get("timezone", "America/New_York"))
    now = dt.datetime.now(tz)
    lead = dt.timedelta(minutes=CHAT_LEAD_MINUTES)
    run = dt.timedelta(minutes=CHAT_RUN_MINUTES)

    buckets = {"current": [], "upcoming": [], "expired": []}
    for p in people:
        when = iso_date(p.get("chat_at"))
        if not when:
            continue
        when = when.replace(tzinfo=tz) if not when.tzinfo else when.astimezone(tz)
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
        elif now < when + run:
            buckets["current"].append(row)
        else:
            buckets["expired"].append(row)

    buckets["current"].sort(key=lambda r: r["when"])
    buckets["upcoming"].sort(key=lambda r: r["when"])
    buckets["expired"].sort(key=lambda r: r["when"], reverse=True)
    buckets["expired"] = buckets["expired"][:12]
    return buckets


def build_slots(settings, refresh_days=None, after=None):
    tz = availability.get_tz(settings.get("timezone", "America/New_York"))
    now = dt.datetime.now(tz)
    horizon = int(refresh_days or settings.get("horizon_days", 14))

    # Asking for more slots means looking past what has already been offered,
    # so the calendar read has to reach that far too.
    cutoff = None
    if after:
        parsed = availability.parse_iso(str(after))
        if parsed:
            cutoff = parsed.date()
    start_of_read = now
    if cutoff:
        from_day = dt.datetime(cutoff.year, cutoff.month, cutoff.day, tzinfo=tz)
        start_of_read = max(now, from_day)

    end = start_of_read + dt.timedelta(days=horizon + 1)
    payload = macos.read_calendar(now, end)
    days = availability.find_windows(payload.get("events", []), settings,
                                     now=now, after=cutoff)
    lines = availability.format_slot_lines(days, settings.get("tz_label", "ET"))
    return {
        "days": days,
        "lines": lines,
        "event_count": len(payload.get("events", [])),
        "demo": payload.get("demo", False),
        "note": payload.get("note", ""),
    }


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
        if status == "uninitiated" and last_out:
            db.update_person(p["id"], {"status": "outreach_sent",
                                       "first_contact_at": p["last_outbound_at"]})
            advanced.append("%s → outreach sent" % p["name"])
        elif status == "outreach_sent" and last_in and last_out and last_in > last_out:
            db.update_person(p["id"], {"status": "awaiting_reply"})
            advanced.append("%s → replied to you" % p["name"])
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


def state_payload():
    settings = db.get_settings()
    people = db.list_people()
    if roll_finished_chats(people, settings):
        people = db.list_people()   # re-read so everything below sees the move
    return {
        "settings": settings,
        "people": people,
        "statuses": [{"key": k, "label": l} for k, l in db.STATUSES],
        "actions": compute_actions(people, settings, db.resolved_keys(SESSION)),
        "coverage": firm_coverage(people, settings),
        "chats": chat_buckets(people, settings),
        "bin": db.bin_items(SESSION),
        "questions": templates.QUESTION_BANK,
        "outlook": _outlook_status,
        "calendar": _calendar_status,
        "platform": {"is_mac": macos.IS_MAC, "demo": macos.DEMO},
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
        return self._error("unknown endpoint", 404)

    def _api_post(self, path, body):
        settings = db.get_settings()

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
                    settings, body.get("days"), body.get("after"))})

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
            return self._file(text.encode("utf-8"),
                              "text/calendar; charset=utf-8",
                              "Coffee chat holds.ics")

        if path == "/api/action/resolve":
            key = (body.get("key") or "").strip()
            if not key:
                return self._error("missing action key", 400)
            db.resolve_action(
                key, body.get("person_id"), body.get("kind", ""),
                body.get("label", ""), body.get("detail", ""),
                body.get("name", ""), SESSION,
            )
            return self._json({"ok": True})

        if path == "/api/action/restore":
            key = (body.get("key") or "").strip()
            if not key:
                return self._error("missing action key", 400)
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

        if path == "/api/offered-slots":
            # What you picked for one person, kept so the draft you write
            # tomorrow offers the same times you offered today.
            person = db.get_person(int(body["person_id"]))
            if not person:
                return self._error("person not found", 404)
            if body.get("clear"):
                person = db.update_person(person["id"],
                                          {"offered_slots": "", "offered_slots_at": None})
                return self._json({"ok": True, "person": person})
            payload = json.dumps({
                "lines": body.get("lines") or [],
                "days": body.get("days") or [],
            })
            stamp = dt.datetime.now(
                availability.get_tz(settings.get("timezone"))).isoformat()
            person = db.update_person(person["id"], {
                "offered_slots": payload, "offered_slots_at": stamp})
            return self._json({"ok": True, "person": person})

        if path == "/api/prep":
            sheet = self._prep(body, settings)
            if sheet is None:
                return self._error("person not found", 404)
            return self._json({"ok": True, "prep": sheet})

        if path == "/api/prep.pdf":
            sheet = self._prep(body, settings)
            if sheet is None:
                return self._error("person not found", 404)
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
        person = db.get_person(int(body["person_id"]))
        if not person:
            return self._error("person not found", 404)

        kind = body.get("kind", "outreach")
        lines = body.get("slot_lines")
        if lines is None and kind in ("outreach", "followup"):
            # Times you actually picked for this person beat a fresh guess —
            # otherwise the email offers different slots than the calendar
            # holds you already put down for them.
            lines = stored_slot_lines(person)
            if lines is None:
                lines = build_slots(settings).get("lines", [])

        if kind == "thankyou":
            draft = templates.thankyou(person, settings, body.get("highlights", ""))
        elif kind == "followup":
            draft = templates.followup(person, settings, lines or [])
        else:
            draft = templates.outreach(person, settings, lines or [],
                                       my_profile(settings), their_profile(person))

        # An edited draft from the interface wins over the scaffold.
        subject = body.get("subject") or draft["subject"]
        text = body.get("body") or draft["body"]

        if not body.get("open_in_outlook"):
            return self._json({"ok": True, "subject": subject, "body": text,
                               "unfilled": templates.unfilled(text)})

        remaining = templates.unfilled(text)
        if remaining and not body.get("force"):
            return self._json({"ok": False, "needs_edit": True, "unfilled": remaining,
                               "subject": subject, "body": text})

        attachment = settings.get("resume_path", "") if kind != "thankyou" else ""
        result = macos.draft_email(person.get("email", ""), person.get("name", ""),
                                   subject, text, attachment)

        # Record what we just did so the follow-up clock starts ticking.
        stamp = dt.datetime.now(
            availability.get_tz(settings.get("timezone", "America/New_York"))
        ).isoformat()
        patch = {"last_outbound_at": stamp}
        if kind == "outreach" and person.get("status") == "uninitiated":
            patch.update({"status": "outreach_sent", "first_contact_at": stamp})
        elif kind == "followup":
            patch["followups_sent"] = int(person.get("followups_sent") or 0) + 1
        elif kind == "thankyou":
            patch.update({"status": "thankyou_sent", "thankyou_sent_at": stamp})
        db.update_person(person["id"], patch)

        return self._json({"ok": True, "drafted": True, "subject": subject,
                           "body": text, **({"demo": True} if result.get("demo") else {})})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--print-url", action="store_true")
    parser.add_argument("--no-watchdog", action="store_true")
    args = parser.parse_args()

    db.init()
    # Ticking something off lasts for one run of the app. Anything binned by an
    # earlier run is dropped now, so whatever is still outstanding comes back.
    db.purge_old_resolutions(SESSION)

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
