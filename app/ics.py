"""Turn proposed coffee-chat windows into an .ics file Apple Calendar can import.

Once you have offered someone a slot, that time is spoken for: if they accept,
you have to be free. So every event is written as a **busy** hold that really
does block the calendar. Nothing else can be booked over it, and the slot finder
sees it as a genuine conflict — which is what stops the same window being
offered to the next person and double-booking you.

The cost of that is holds outliving their purpose. If someone declines or never
replies, the hold is still sitting there blocking good time, so delete it. Every
event carries the same title prefix and a "Coffee chats" category, which makes
them easy to find and clear out in bulk.

Standard library only. Output follows RFC 5545, including the 75-octet line
folding that trips up most hand-rolled calendar files.
"""

import datetime as dt
import hashlib

PRODID = "-//Coffee Chat Tracker//Coffee Chat Tracker 1.0//EN"


def _escape(text):
    """RFC 5545 TEXT escaping."""
    return (str(text or "")
            .replace("\\", "\\\\")
            .replace(";", "\\;")
            .replace(",", "\\,")
            .replace("\r\n", "\\n")
            .replace("\n", "\\n"))


def _fold(line):
    """Wrap at 75 octets, continuing with a leading space.

    Counted in encoded bytes rather than characters, and never split through
    the middle of a multi-byte character.
    """
    out = []
    current = ""
    length = 0
    for ch in line:
        size = len(ch.encode("utf-8"))
        if length + size > 75:
            out.append(current)
            current = " " + ch
            length = 1 + size
        else:
            current += ch
            length += size
    out.append(current)
    return "\r\n".join(out)


def _utc(moment):
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    return moment.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _uid(start, end, label):
    seed = "%s|%s|%s" % (_utc(start), _utc(end), label)
    return hashlib.sha1(seed.encode("utf-8")).hexdigest() + "@coffeechattracker"


def build_slots_ics(windows, label, settings, now=None):
    """`windows` is a list of (start, end) aware datetimes.

    Returns (text, count).
    """
    prefix = (settings or {}).get("hold_prefix") or "Coffee chat hold"
    label = (label or "").strip()
    summary = "%s — %s" % (prefix, label) if label else prefix
    tz_label = (settings or {}).get("tz_label", "")

    description = (
        "Time offered for a coffee chat%s.\n\n"
        "Held deliberately: if they accept, you need to be free, so this blocks "
        "the slot and Coffee Chat Tracker will not offer it to anyone else.\n\n"
        "When the chat is confirmed, replace this with the real meeting. If they "
        "decline or go quiet, delete it so the time goes back into circulation."
        % ((" with " + label) if label else "")
    )

    stamp = _utc(now or dt.datetime.now(dt.timezone.utc))
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:" + PRODID,
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:" + _escape(summary),
    ]

    count = 0
    for start, end in windows:
        if not start or not end or end <= start:
            continue
        local_note = ""
        if tz_label:
            local_note = " (%s–%s %s)" % (
                start.strftime("%-I:%M%p").lower().replace(":00", ""),
                end.strftime("%-I:%M%p").lower().replace(":00", ""),
                tz_label,
            )
        lines += [
            "BEGIN:VEVENT",
            "UID:" + _uid(start, end, summary),
            "DTSTAMP:" + stamp,
            "DTSTART:" + _utc(start),
            "DTEND:" + _utc(end),
            "SUMMARY:" + _escape(summary + local_note),
            "DESCRIPTION:" + _escape(description),
            "STATUS:CONFIRMED",
            "TRANSP:OPAQUE",                    # blocks the time
            "X-MICROSOFT-CDO-BUSYSTATUS:BUSY",  # ditto, for Outlook
            "CATEGORIES:Coffee chats",
            "END:VEVENT",
        ]
        count += 1

    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n", count


def build_confirm_ics(chosen, cancelled, label, settings, now=None):
    """One CONFIRMED event for the window that was actually accepted, and a
    CANCELLED event for every other window that had been offered and held.

    Each reuses the exact UID its hold was given when it was first downloaded
    (same label, same start/end) — a calendar that kept that identity around
    can update those entries in place instead of gaining a duplicate. Whether
    a plain file import actually does that depends on the calendar app; if
    the stale holds are still sitting there afterwards, they're found and
    removed the same way as always — by searching the hold's title.
    """
    prefix = (settings or {}).get("hold_prefix") or "Coffee chat hold"
    hold_summary = "%s — %s" % (prefix, label) if label else prefix
    stamp = _utc(now or dt.datetime.now(dt.timezone.utc))

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:" + PRODID,
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:" + _escape("Coffee chat — %s" % label if label else "Coffee chat"),
    ]

    start, end = chosen
    if start and end and end > start:
        summary = "Coffee chat — %s" % label if label else "Coffee chat"
        lines += [
            "BEGIN:VEVENT",
            "UID:" + _uid(start, end, hold_summary),   # same identity as the original hold
            "SEQUENCE:1",
            "DTSTAMP:" + stamp,
            "DTSTART:" + _utc(start),
            "DTEND:" + _utc(end),
            "SUMMARY:" + _escape(summary),
            "DESCRIPTION:" + _escape("Confirmed by Coffee Chat Tracker."),
            "STATUS:CONFIRMED",
            "TRANSP:OPAQUE",
            "X-MICROSOFT-CDO-BUSYSTATUS:BUSY",
            "CATEGORIES:Coffee chats",
            "END:VEVENT",
        ]

    for c_start, c_end in cancelled or []:
        if not c_start or not c_end or c_end <= c_start:
            continue
        lines += [
            "BEGIN:VEVENT",
            "UID:" + _uid(c_start, c_end, hold_summary),
            "SEQUENCE:1",
            "DTSTAMP:" + stamp,
            "DTSTART:" + _utc(c_start),
            "DTEND:" + _utc(c_end),
            "SUMMARY:" + _escape(hold_summary),
            "DESCRIPTION:" + _escape("Not the slot that was picked — safe to delete."),
            "STATUS:CANCELLED",
            "TRANSP:TRANSPARENT",
            "CATEGORIES:Coffee chats",
            "END:VEVENT",
        ]

    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"


def windows_from_days(days, parse_iso):
    """Flatten the slot finder's day/window structure into datetime pairs."""
    out = []
    for day in days or []:
        for window in day.get("windows", []):
            start = parse_iso(window.get("start"))
            end = parse_iso(window.get("end"))
            if start and end:
                out.append((start, end))
    return out
