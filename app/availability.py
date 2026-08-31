"""Turn a calendar's busy time into a short list of offerable coffee-chat windows.

The GCA deck asks for "at least 3 slots of an hour in length", with time zones,
and warns against double-booking yourself. This module does exactly that: it
subtracts busy time (plus a travel/breather buffer) from your working hours and
returns the widest remaining windows, grouped by day.
"""

import datetime as dt

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python < 3.9
    ZoneInfo = None

WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday",
                 "Friday", "Saturday", "Sunday"]
MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December"]


def get_tz(name):
    if ZoneInfo is not None:
        try:
            return ZoneInfo(name)
        except Exception:
            pass
    return dt.timezone.utc


def parse_iso(value):
    """Parse ISO-8601 including a trailing Z, which older Pythons reject."""
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return dt.datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S%z",
                    "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return dt.datetime.strptime(text, fmt)
            except ValueError:
                continue
    return None


def parse_hhmm(value, fallback):
    try:
        h, m = value.split(":")
        return int(h), int(m)
    except Exception:
        return fallback


def fmt_time(moment):
    """9:00 -> '9am'; 16:30 -> '4:30pm'. Matches the deck's email examples."""
    hour = moment.hour % 12 or 12
    suffix = "am" if moment.hour < 12 else "pm"
    if moment.minute:
        return "%d:%02d%s" % (hour, moment.minute, suffix)
    return "%d%s" % (hour, suffix)


def fmt_day(day):
    return "%s %d, %s" % (MONTH_NAMES[day.month - 1], day.day,
                          WEEKDAY_NAMES[day.weekday()])


def tidy_window(start, end, min_window, max_window):
    """Make a raw gap presentable: land on quarter hours, and don't offer a
    seven-hour stretch — "I'm free all Friday" reads as no plan at all."""
    spare = start.minute % 15
    if spare:
        start += dt.timedelta(minutes=15 - spare)
    start = start.replace(second=0, microsecond=0)
    end = (end - dt.timedelta(minutes=end.minute % 15)).replace(second=0, microsecond=0)
    if end - start > max_window:
        end = start + max_window
    if end - start < min_window:
        return None
    return (start, end)


def _merge(intervals):
    """Merge overlapping (start, end) pairs."""
    merged = []
    for start, end in sorted(intervals, key=lambda x: x[0]):
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            if end > merged[-1][1]:
                merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return merged


def busy_intervals(events, tz, rules):
    """Normalise calendar events into merged busy (start, end) pairs in `tz`."""
    ignore_all_day = rules.get("ignore_all_day", True)
    ignore_tentative = rules.get("ignore_tentative", True)
    excluded = {c.strip().lower()
                for c in rules.get("excluded_calendars", "").split(",")
                if c.strip()}
    buffer_delta = dt.timedelta(minutes=int(rules.get("buffer_minutes", 0)))

    raw = []
    for ev in events:
        if ignore_all_day and ev.get("all_day"):
            continue
        status = (ev.get("status") or "").lower()
        if ignore_tentative and status in ("tentative", "pending"):
            continue
        if (ev.get("calendar") or "").strip().lower() in excluded:
            continue
        if (ev.get("availability") or "").lower() == "free":
            continue
        start = parse_iso(ev.get("start"))
        end = parse_iso(ev.get("end"))
        if start is None or end is None:
            continue
        if start.tzinfo is None:
            start = start.replace(tzinfo=tz)
        if end.tzinfo is None:
            end = end.replace(tzinfo=tz)
        raw.append((start.astimezone(tz) - buffer_delta,
                    end.astimezone(tz) + buffer_delta))
    return _merge(raw)


def find_windows(events, rules, now=None):
    """Return offerable windows grouped by day.

    rules keys: timezone, tz_label, work_days, work_start, work_end,
    min_window_minutes, buffer_minutes, lead_days, horizon_days,
    slots_wanted, max_per_day, ignore_all_day, ignore_tentative,
    excluded_calendars.
    """
    tz = get_tz(rules.get("timezone", "America/New_York"))
    now = now.astimezone(tz) if now else dt.datetime.now(tz)

    work_days = {int(d) for d in str(rules.get("work_days", "1,2,3,4,5")).split(",")
                 if d.strip().isdigit()}
    sh, sm = parse_hhmm(str(rules.get("work_start", "09:00")), (9, 0))
    eh, em = parse_hhmm(str(rules.get("work_end", "18:00")), (18, 0))
    min_window = dt.timedelta(minutes=int(rules.get("min_window_minutes", 60)))
    lead_days = int(rules.get("lead_days", 2))
    horizon = int(rules.get("horizon_days", 14))
    wanted_days = int(rules.get("slots_wanted", 3))
    max_per_day = int(rules.get("max_per_day", 2))
    max_window = dt.timedelta(minutes=int(rules.get("max_window_minutes", 180)))

    busy = busy_intervals(events, tz, rules)
    earliest = now + dt.timedelta(days=lead_days)

    days = []
    cursor = now.date()
    for offset in range(horizon + 1):
        day = cursor + dt.timedelta(days=offset)
        if (day.weekday() + 1) not in work_days:
            continue

        day_start = dt.datetime(day.year, day.month, day.day, sh, sm, tzinfo=tz)
        day_end = dt.datetime(day.year, day.month, day.day, eh, em, tzinfo=tz)
        if day_start < earliest:
            day_start = earliest.replace(second=0, microsecond=0)
            # round up to the next quarter hour so slots read cleanly
            spare = day_start.minute % 15
            if spare:
                day_start += dt.timedelta(minutes=15 - spare)
        if day_end - day_start < min_window:
            continue

        free = [(day_start, day_end)]
        for b_start, b_end in busy:
            if b_end <= day_start or b_start >= day_end:
                continue
            carved = []
            for f_start, f_end in free:
                if b_end <= f_start or b_start >= f_end:
                    carved.append((f_start, f_end))
                    continue
                if b_start > f_start:
                    carved.append((f_start, min(b_start, f_end)))
                if b_end < f_end:
                    carved.append((max(b_end, f_start), f_end))
            free = carved

        windows = [(s, e) for s, e in free if e - s >= min_window]
        if not windows:
            continue
        # Prefer the longest windows, then present them in time order.
        windows.sort(key=lambda w: (w[1] - w[0]), reverse=True)
        windows = sorted(windows[:max_per_day])
        windows = [w for w in (tidy_window(s, e, min_window, max_window)
                               for s, e in windows) if w]
        if not windows:
            continue

        days.append({
            "date": day.isoformat(),
            "label": fmt_day(day),
            "windows": [{
                "start": s.isoformat(),
                "end": e.isoformat(),
                "text": "%s – %s" % (fmt_time(s), fmt_time(e)),
                "minutes": int((e - s).total_seconds() // 60),
            } for s, e in windows],
        })
        if len(days) >= wanted_days:
            break

    return days


def format_slot_lines(days, tz_label="ET"):
    """Render the exact bullet style the deck's example email uses."""
    lines = []
    for day in days:
        joined = " or ".join(w["text"] for w in day["windows"])
        lines.append("%s: %s %s" % (day["label"], joined, tz_label))
    return lines
