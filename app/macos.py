"""Bridge between the Python app and macOS, via osascript.

Everything that touches Apple Calendar or Outlook goes through here. No third
party packages: each call shells out to `osascript`, which is part of macOS.

When the module is imported somewhere that is not a Mac (or with CCT_DEMO=1),
it serves fixture data instead so the interface and scheduling logic stay
testable.
"""

import datetime as dt
import json
import os
import platform
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "scripts")

IS_MAC = platform.system() == "Darwin"
DEMO = os.environ.get("CCT_DEMO") == "1" or not IS_MAC

# Outlook scans can be slow on a large mailbox; calendar reads are quick.
CALENDAR_TIMEOUT = 90
OUTLOOK_TIMEOUT = 180
DETECT_TIMEOUT = 30


class BridgeError(Exception):
    pass


def _run(args, timeout):
    try:
        proc = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except FileNotFoundError:
        raise BridgeError("osascript is not available — this feature needs macOS.")
    except subprocess.TimeoutExpired:
        raise BridgeError(
            "Timed out after %ds. If Outlook is indexing a large mailbox, try a "
            "smaller lookback window in Settings." % timeout
        )
    out = proc.stdout.decode("utf-8", "replace").strip()
    err = proc.stderr.decode("utf-8", "replace").strip()
    if proc.returncode != 0:
        raise BridgeError(err or out or "osascript exited with %d" % proc.returncode)
    return out


def _script(name):
    return os.path.join(SCRIPTS, name)


# ------------------------------------------------------------ Apple Calendar

def _demo_events(start, end):
    """A plausible week for a first-year MBA, used when macOS isn't reachable."""
    tz = start.tzinfo
    events = []
    day = start.date()
    blocks = {
        0: [("09:00", "12:15", "Strategy"), ("13:00", "14:30", "Finance")],
        1: [("10:00", "11:30", "Data & Decisions"), ("16:00", "17:30", "GCA session")],
        2: [("09:00", "12:15", "Strategy"), ("14:00", "15:00", "Career coach")],
        3: [("11:00", "12:30", "Marketing"), ("15:00", "16:00", "Case practice")],
        4: [("09:30", "10:30", "Team meeting")],
    }
    for offset in range(0, (end.date() - day).days + 1):
        current = day + dt.timedelta(days=offset)
        for start_s, end_s, title in blocks.get(current.weekday(), []):
            sh, sm = [int(x) for x in start_s.split(":")]
            eh, em = [int(x) for x in end_s.split(":")]
            events.append({
                "title": title,
                "calendar": "Emory",
                "start": dt.datetime(current.year, current.month, current.day,
                                     sh, sm, tzinfo=tz).isoformat(),
                "end": dt.datetime(current.year, current.month, current.day,
                                   eh, em, tzinfo=tz).isoformat(),
                "all_day": False,
                "status": "confirmed",
                "availability": "busy",
                "source": "demo",
            })
    return events


def read_calendar(start, end):
    """Return busy events between two aware datetimes."""
    if DEMO:
        return {"ok": True, "events": _demo_events(start, end), "demo": True}

    start_utc = start.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    end_utc = end.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    raw = _run(
        ["osascript", "-l", "JavaScript", _script("calendar_events.js"),
         start_utc, end_utc],
        CALENDAR_TIMEOUT,
    )
    try:
        payload = json.loads(raw)
    except ValueError:
        raise BridgeError("Unexpected reply from the calendar script: %s" % raw[:400])
    if not payload.get("ok"):
        detail = payload.get("error", "unknown error")
        if "denied" in detail:
            raise BridgeError(
                "macOS has not granted calendar access yet. Open System Settings > "
                "Privacy & Security > Calendars and enable Coffee Chat Tracker "
                "(or Terminal, if you launched it from there)."
            )
        raise BridgeError(detail)
    return payload


def create_calendar_event(title, start_iso, end_iso, notes="", calendar_name=""):
    if DEMO:
        return {"ok": True, "calendar": "Demo", "demo": True}
    raw = _run(
        ["osascript", "-l", "JavaScript", _script("calendar_create.js"),
         title, start_iso, end_iso, notes, calendar_name],
        CALENDAR_TIMEOUT,
    )
    try:
        return json.loads(raw)
    except ValueError:
        raise BridgeError("Unexpected reply while creating the event: %s" % raw[:400])


# ------------------------------------------------------------------- Outlook

def detect_outlook():
    """Figure out whether this Mac's Outlook can be scripted."""
    if DEMO:
        return {"flavor": "demo", "detail": "Running outside macOS; Outlook features simulated."}
    try:
        raw = _run(["osascript", _script("outlook_detect.applescript")], DETECT_TIMEOUT)
    except BridgeError as exc:
        return {"flavor": "error", "detail": str(exc)}
    parts = raw.split("\t")
    flavor = parts[0] if parts else "error"
    detail = parts[1] if len(parts) > 1 else ""
    result = {"flavor": flavor, "detail": detail}
    if flavor == "classic":
        result["version"] = detail
        result["folders"] = parts[2] if len(parts) > 2 else ""
        result["detail"] = "Classic Outlook %s — mail tracking available." % detail
    return result


def scan_outlook(days_back=30, max_messages=400):
    """Return (messages, diagnostics). Each message: direction, when, address, subject."""
    if DEMO:
        now = dt.datetime.now(dt.timezone.utc)
        return ([
            {"direction": "out", "when": now - dt.timedelta(days=9),
             "address": "demo.consultant@example.com",
             "subject": "Goizueta Student Coffee Chat Request"},
        ], ["# demo mode"])

    raw = _run(
        ["osascript", _script("outlook_scan.applescript"),
         str(int(days_back)), str(int(max_messages))],
        OUTLOOK_TIMEOUT,
    )
    now = dt.datetime.now(dt.timezone.utc)
    messages = []
    diagnostics = []
    for line in raw.splitlines():
        line = line.rstrip()
        if not line:
            continue
        if line.startswith("#"):
            diagnostics.append(line)
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        direction, delta, address = parts[0], parts[1], parts[2]
        subject = parts[3] if len(parts) > 3 else ""
        try:
            when = now + dt.timedelta(seconds=int(delta))
        except ValueError:
            continue
        messages.append({
            "direction": direction,
            "when": when,
            "address": address.strip().lower(),
            "subject": subject,
        })
    return messages, diagnostics


# ------------------------------------------------------------------- Browser

def read_browser_profile():
    """Read the LinkedIn profile in whichever open tab (Safari or Chrome)
    already has one, in the user's own logged-in session. Reads only, never
    searches or navigates."""
    if DEMO:
        return {
            "ok": True, "browser": "Demo", "demo": True,
            "url": "https://www.linkedin.com/in/demo-consultant/",
            "text": "Jordan Rivera\nSenior Associate at Bain & Company\n"
                    "Atlanta, Georgia, United States\n\nExperience\n"
                    "Bain & Company\n2 yrs 3 mos\nSenior Associate\nJan 2024 - Present\n"
                    "Associate Consultant\nJun 2022 - Dec 2023\n\n"
                    "Deloitte\nBusiness Analyst\nJul 2020 - May 2022\n\n"
                    "Education\nEmory University, Goizueta Business School\nMBA\n2020 - 2022",
        }
    raw = _run(["osascript", "-l", "JavaScript", _script("browser_read.js")], DETECT_TIMEOUT)
    try:
        payload = json.loads(raw)
    except ValueError:
        raise BridgeError("Unexpected reply from the browser script: %s" % raw[:400])
    if not payload.get("ok"):
        raise BridgeError(payload.get("error", "Could not read the browser tab."))
    return payload


def draft_email(to_address, to_name, subject, body, attachment=""):
    """Open a pre-filled draft in Outlook. Never sends."""
    if DEMO:
        return {"ok": True, "demo": True,
                "preview": {"to": to_address, "subject": subject, "body": body}}

    attachment = attachment or ""
    if attachment and not os.path.isfile(os.path.expanduser(attachment)):
        attachment = ""
    args = [to_address, to_name, subject, body, os.path.expanduser(attachment) if attachment else ""]

    errors = []
    for script in ("outlook_draft_plain.applescript", "outlook_draft.applescript"):
        try:
            _run(["osascript", _script(script)] + args, DETECT_TIMEOUT)
            return {"ok": True, "script": script}
        except BridgeError as exc:
            errors.append("%s: %s" % (script, exc))
    raise BridgeError(
        "Could not create the draft in Outlook. " + " | ".join(errors)
    )
