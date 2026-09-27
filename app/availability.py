"""Turn a calendar's busy time into a short list of offerable coffee-chat windows.

The GCA deck asks for "at least 3 slots of an hour in length", with time zones,
and warns against double-booking yourself. This module does exactly that: it
subtracts busy time (plus a travel/breather buffer) from your working hours and
returns the widest remaining windows, grouped by day.
"""

import datetime as dt
import itertools

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
    """9:00 -> '9:00am'; 16:30 -> '4:30pm'. Always on the hour or half hour —
    never a quarter-past or quarter-to — so it reads cleanly at a glance."""
    hour = moment.hour % 12 or 12
    suffix = "am" if moment.hour < 12 else "pm"
    return "%d:%02d%s" % (hour, moment.minute, suffix)


def fmt_day(day):
    return "%s %d, %s" % (MONTH_NAMES[day.month - 1], day.day,
                          WEEKDAY_NAMES[day.weekday()])


def tidy_window(start, end, min_window, max_window):
    """Make a raw gap presentable: land on the hour or half hour — nothing
    like 2:15 or 3:45 — and don't offer a seven-hour stretch — "I'm free all
    Friday" reads as no plan at all."""
    spare = start.minute % 30
    if spare:
        start += dt.timedelta(minutes=30 - spare)
    start = start.replace(second=0, microsecond=0)
    end = (end - dt.timedelta(minutes=end.minute % 30)).replace(second=0, microsecond=0)
    if end - start > max_window:
        end = start + max_window
    if end - start < min_window:
        return None
    return (start, end)


# Offering the same hour three days running reads like a script, and if that
# hour happens to be bad for them every option fails at once. So the day is
# split into three named parts and the picks lean away from whichever parts
# have already been offered.
BUCKETS = ("morning", "midday", "afternoon")


def _bucket(moment):
    hour = moment.hour + moment.minute / 60.0
    if hour < 12:
        return "morning"
    if hour < 15:
        return "midday"
    return "afternoon"


STRIDE = dt.timedelta(hours=1)


def split_window(start, end, min_window, max_window):
    """Every offerable window inside one free gap, an hour apart.

    A free 9–6 is not one 9–12 with the rest thrown away; it is a morning, a
    midday and an afternoon to choose between. Sliding by the hour rather than
    tiling means two different days can offer genuinely different times out of
    identically empty calendars.
    """
    out = []
    cursor = start
    while cursor + min_window <= end:
        out.append((cursor, min(cursor + max_window, end)))
        cursor += STRIDE
    tail = max(start, end - max_window)
    if end - tail >= min_window and (tail, end) not in out:
        out.append((tail, end))
    return out


SEPARATION = dt.timedelta(hours=1)


def _gap_between(a, b):
    if a[1] <= b[0]:
        return b[0] - a[1]
    if b[1] <= a[0]:
        return a[0] - b[1]
    return None                 # they overlap


def pick_spread(candidates, max_per_day, spread):
    """Choose one day's windows. Candidates are (start, end, gap) triples.

    Judged as a set rather than one at a time, because the two best windows
    individually are usually two slices of the same long afternoon. Ranked by:

      1. no two windows out of the same stretch of free time. A free 12:45–6
         offered as "12:45–3:45 or 4:45–6" invents an hour of unavailability
         in the middle of an afternoon you are free for. Two offers are only
         a real choice when something of yours actually sits between them.
      2. no two touching, so a genuine pair reads as two options.
      3. lean away from whichever part of the day other days already used.
      4. prefer the longer window.

    Where a day cannot fill its quota without breaking (1) or (2), it offers
    fewer windows instead of pretending.
    """
    fallback = None
    for take in range(min(max_per_day, len(candidates)), 0, -1):
        best, best_key = None, None
        for combo in itertools.combinations(sorted(candidates), take):
            gaps = [_gap_between(a, b) for a, b in itertools.combinations(combo, 2)]
            if any(gap is None for gap in gaps):
                continue        # overlapping windows are not two offers
            touching = sum(1 for gap in gaps if gap < SEPARATION)
            shared = sum(1 for a, b in itertools.combinations(combo, 2)
                         if a[2] == b[2])

            local = {}
            bucket_cost = 0
            for window in combo:
                name = _bucket(window[0])
                bucket_cost += spread[name] + local.get(name, 0)
                local[name] = local.get(name, 0) + 1

            length = sum((w[1] - w[0]).total_seconds() for w in combo)
            key = (shared, touching, bucket_cost, -length,
                   tuple(w[0] for w in combo))
            if best_key is None or key < best_key:
                best, best_key = combo, key

        if best is None:
            continue
        if fallback is None:
            fallback = best
        if best_key[0] == 0 and best_key[1] == 0:
            fallback = best
            break

    if fallback is None:
        return []
    for window in fallback:
        spread[_bucket(window[0])] += 1

    # The spread rule chooses *which part* of a free stretch to lean on, but it
    # must never hide the start of that stretch: free from 2:30 and offered
    # "3:30–4:30" reads as busy until 3:30. Stretch each pick back to the
    # earliest offer out of the same gap that still reaches the same end.
    chosen = []
    for w in fallback:
        earlier = [c for c in candidates
                   if c[2] == w[2] and c[0] < w[0] and c[1] >= w[1]]
        alone = sum(1 for o in fallback if o[2] == w[2]) == 1
        if earlier and alone:
            best_c = min(earlier, key=lambda c: c[0])
            chosen.append((best_c[0], best_c[1]))
        else:
            chosen.append((w[0], w[1]))
    return sorted(chosen)


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
    """Normalise calendar events into merged busy (start, end) pairs in `tz`.

    The buffer only pushes the *end* of an event later, never the *start*
    earlier: a coffee chat can run right up until class starts, but needs a
    real gap after class ends before the next one begins."""
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
        raw.append((start.astimezone(tz),
                    end.astimezone(tz) + buffer_delta))
    return _merge(raw)


# Fixed two-hour blocks between 9am and 5pm. These are the only times ever
# suggested; the list is not shaped by the calendar at all.
FIXED_BLOCKS = ((9, 11), (11, 13), (13, 15), (15, 17))


def _overlaps(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def find_windows(taken, rules, now=None, after=None, days_wanted=3):
    """Every free fixed block for the next `days_wanted` weekdays.

    `taken` is a list of (start, end) windows already saved for other people;
    a block overlapping one of those is the only thing ever filtered out.
    `after` is the last date already shown: "Request 3 more days" continues
    from the weekday following it. Without it, the search starts tomorrow.
    """
    tz = get_tz(rules.get("timezone", "America/New_York"))
    now = now.astimezone(tz) if now else dt.datetime.now(tz)
    taken = [(s.astimezone(tz), e.astimezone(tz)) for s, e in (taken or [])]

    day = (after or now.date()) + dt.timedelta(days=1)
    days = []
    while len(days) < days_wanted:
        if day.weekday() < 5:
            windows = []
            for sh, eh in FIXED_BLOCKS:
                s = dt.datetime(day.year, day.month, day.day, sh, tzinfo=tz)
                e = dt.datetime(day.year, day.month, day.day, eh, tzinfo=tz)
                if any(_overlaps(s, e, ts, te) for ts, te in taken):
                    continue
                windows.append({
                    "start": s.isoformat(),
                    "end": e.isoformat(),
                    "text": "%s – %s" % (fmt_time(s), fmt_time(e)),
                    "minutes": 120,
                })
            # A weekday counts toward the three even if every block is taken,
            # so "next 3 weekdays" always means exactly that.
            days.append({"date": day.isoformat(), "label": fmt_day(day),
                         "windows": windows})
        day += dt.timedelta(days=1)
    return days


def format_slot_lines(days, tz_label="ET"):
    """Render the exact bullet style the deck's example email uses."""
    lines = []
    for day in days:
        joined = " or ".join(w["text"] for w in day["windows"])
        lines.append("%s: %s %s" % (day["label"], joined, tz_label))
    return lines
