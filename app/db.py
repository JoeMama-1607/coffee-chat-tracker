"""SQLite storage for Coffee Chat Tracker.

Pure standard library. Compatible with Python 3.9+ (the python3 that ships
with Xcode Command Line Tools) through 3.13.
"""

import json
import os
import sqlite3
import time

APP_NAME = "CoffeeChatTracker"


def data_dir():
    base = os.path.expanduser("~/Library/Application Support")
    if not os.path.isdir(base):  # non-mac fallback (used for testing)
        base = os.path.expanduser("~/.local/share")
    path = os.path.join(base, APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def db_path():
    return os.path.join(data_dir(), "tracker.sqlite3")


SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS person (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    email         TEXT DEFAULT '',
    firm          TEXT DEFAULT '',
    role          TEXT DEFAULT '',
    office        TEXT DEFAULT '',
    linkedin      TEXT DEFAULT '',
    grad_year     TEXT DEFAULT '',
    is_alum       INTEGER DEFAULT 0,
    tier          TEXT DEFAULT 'B',
    source        TEXT DEFAULT '',
    status        TEXT DEFAULT 'uninitiated',
    priority_note TEXT DEFAULT '',
    referred_by   INTEGER REFERENCES person(id) ON DELETE SET NULL,
    first_contact_at   TEXT,
    last_outbound_at   TEXT,
    last_inbound_at    TEXT,
    chat_at            TEXT,
    thankyou_sent_at   TEXT,
    followups_sent     INTEGER DEFAULT 0,
    next_action        TEXT DEFAULT '',
    next_action_date   TEXT,
    linkedin_raw       TEXT DEFAULT '',
    profile_updated_at TEXT,
    archived      INTEGER DEFAULT 0,
    created_at    TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at    TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS note (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id  INTEGER NOT NULL REFERENCES person(id) ON DELETE CASCADE,
    kind       TEXT DEFAULT 'note',      -- note | question | takeaway | prep
    body       TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS mail_event (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id   INTEGER REFERENCES person(id) ON DELETE CASCADE,
    direction   TEXT NOT NULL,           -- in | out
    subject     TEXT DEFAULT '',
    counterpart TEXT DEFAULT '',
    occurred_at TEXT NOT NULL,
    message_id  TEXT DEFAULT '',
    snippet     TEXT DEFAULT '',
    UNIQUE(person_id, direction, occurred_at, subject)
);

CREATE TABLE IF NOT EXISTS setting (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_person_status ON person(status);
CREATE INDEX IF NOT EXISTS idx_note_person  ON note(person_id);
CREATE INDEX IF NOT EXISTS idx_mail_person  ON mail_event(person_id);
"""

# Pipeline stages, in the order the GCA deck describes the process.
STATUSES = [
    ("uninitiated", "Uninitiated"),
    ("outreach_sent", "Outreach sent"),
    ("awaiting_reply", "Awaiting reply"),
    ("scheduled", "Chat scheduled"),
    ("chat_done", "Chat done"),
    ("thankyou_sent", "Thank-you sent"),
    ("nurturing", "Nurturing"),
    ("no_response", "No response"),
]

DEFAULT_SETTINGS = {
    "user_name": "",
    "user_email": "",
    "user_program": "Class of 2028 | Master of Business Administration (M.B.A.)",
    "user_school": "Goizueta Business School | Emory University",
    "user_phone": "",
    "user_linkedin": "",
    "resume_path": "",
    "timezone": "America/New_York",
    "tz_label": "ET",
    # availability rules
    "work_days": "1,2,3,4,5",          # Mon=1 .. Sun=7
    "work_start": "09:00",
    "work_end": "18:00",
    "min_window_minutes": "60",
    "max_window_minutes": "180",
    "outlook_lookback_days": "30",
    "buffer_minutes": "15",
    "lead_days": "2",
    "horizon_days": "14",
    "slots_wanted": "3",
    "max_per_day": "2",
    "ignore_all_day": "1",
    "ignore_tentative": "1",
    "excluded_calendars": "",
    "hold_prefix": "Coffee chat hold",
    # follow-up policy, straight from the deck
    "followup_after_days": "7",
    "max_followups": "3",
    "thankyou_within_hours": "24",
    "target_firms": "McKinsey, Bain, BCG, Deloitte, EY, Kearney, Strategy&, Accenture, PwC, Simon-Kucher",
}

# Firms get written down half a dozen ways ("Bain", "Bain & Company", "Bain and
# Company") and each spelling used to open its own row in Firm coverage, which
# split one firm's progress across two bars. One short name per firm wins.
FIRM_ALIASES = {
    "bain & company": "Bain",
    "bain and company": "Bain",
    "bain & co": "Bain",
    "bain & co.": "Bain",
    "mckinsey & company": "McKinsey",
    "mckinsey and company": "McKinsey",
    "mckinsey & co": "McKinsey",
    "mckinsey & co.": "McKinsey",
    "ey-parthenon": "EY",
    "ey parthenon": "EY",
    "ernst & young": "EY",
    "ernst and young": "EY",
    "boston consulting group": "BCG",
    "the boston consulting group": "BCG",
}


def canonical_firm(name):
    return FIRM_ALIASES.get((name or "").strip().lower(), (name or "").strip())


def connect():
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init():
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        migrate(conn)
        for k, v in DEFAULT_SETTINGS.items():
            conn.execute(
                "INSERT OR IGNORE INTO setting(key, value) VALUES (?,?)", (k, v)
            )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------- settings

def get_settings():
    conn = connect()
    try:
        rows = conn.execute("SELECT key, value FROM setting").fetchall()
    finally:
        conn.close()
    out = dict(DEFAULT_SETTINGS)
    for r in rows:
        out[r["key"]] = r["value"]
    return out


def save_settings(patch):
    conn = connect()
    try:
        for k, v in patch.items():
            conn.execute(
                "INSERT INTO setting(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(k), "" if v is None else str(v)),
            )
        conn.commit()
    finally:
        conn.close()
    return get_settings()


# ------------------------------------------------------------------ people

PERSON_FIELDS = [
    "name", "email", "firm", "role", "office", "linkedin", "grad_year",
    "is_alum", "tier", "source", "status", "priority_note", "referred_by",
    "first_contact_at", "last_outbound_at", "last_inbound_at", "chat_at",
    "thankyou_sent_at", "followups_sent", "next_action", "next_action_date",
    "linkedin_raw", "profile_updated_at", "archived",
]

# Columns added after the first release. Existing databases are upgraded in
# place on startup so nobody loses the people they have already entered.
MIGRATIONS = [
    ("person", "linkedin_raw", "TEXT DEFAULT ''"),
    ("person", "profile_updated_at", "TEXT"),
]


OLD_TARGET_FIRMS = ("McKinsey & Company, Bain & Company, BCG, Deloitte, "
                    "EY-Parthenon, Kearney, Strategy&, Accenture, PwC, Simon-Kucher")


def migrate(conn):
    for table, column, decl in MIGRATIONS:
        existing = {r["name"] for r in conn.execute(
            "PRAGMA table_info(%s)" % table).fetchall()}
        if column not in existing:
            conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, column, decl))

    # Fold the long firm spellings into the short ones, once, in place.
    for row in conn.execute(
            "SELECT DISTINCT firm FROM person WHERE firm <> ''").fetchall():
        short = canonical_firm(row["firm"])
        if short != row["firm"]:
            conn.execute("UPDATE person SET firm=? WHERE firm=?", (short, row["firm"]))

    # An untouched target list follows the rename; an edited one is left alone.
    current = conn.execute(
        "SELECT value FROM setting WHERE key='target_firms'").fetchone()
    if current and current["value"].strip() == OLD_TARGET_FIRMS:
        conn.execute("UPDATE setting SET value=? WHERE key='target_firms'",
                     (DEFAULT_SETTINGS["target_firms"],))


def list_people(include_archived=False):
    conn = connect()
    try:
        sql = (
            "SELECT p.*, r.name AS referred_by_name "
            "FROM person p LEFT JOIN person r ON r.id = p.referred_by "
        )
        if not include_archived:
            sql += "WHERE p.archived = 0 "
        sql += "ORDER BY p.firm COLLATE NOCASE, p.name COLLATE NOCASE"
        return [dict(r) for r in conn.execute(sql).fetchall()]
    finally:
        conn.close()


def get_person(pid):
    conn = connect()
    try:
        row = conn.execute(
            "SELECT p.*, r.name AS referred_by_name "
            "FROM person p LEFT JOIN person r ON r.id = p.referred_by "
            "WHERE p.id = ?",
            (pid,),
        ).fetchone()
        if row is None:
            return None
        person = dict(row)
        person["notes"] = [
            dict(x)
            for x in conn.execute(
                "SELECT * FROM note WHERE person_id=? ORDER BY created_at DESC, id DESC",
                (pid,),
            ).fetchall()
        ]
        person["mail"] = [
            dict(x)
            for x in conn.execute(
                "SELECT * FROM mail_event WHERE person_id=? "
                "ORDER BY occurred_at DESC LIMIT 50",
                (pid,),
            ).fetchall()
        ]
        person["referrals"] = [
            dict(x)
            for x in conn.execute(
                "SELECT id, name, firm, status FROM person WHERE referred_by=? "
                "ORDER BY name",
                (pid,),
            ).fetchall()
        ]
        return person
    finally:
        conn.close()


def create_person(data):
    data = dict(data)
    if data.get("firm"):
        data["firm"] = canonical_firm(data["firm"])
    fields = [f for f in PERSON_FIELDS if f in data]
    if "name" not in fields:
        raise ValueError("name is required")
    conn = connect()
    try:
        cols = ", ".join(fields)
        marks = ", ".join("?" for _ in fields)
        cur = conn.execute(
            "INSERT INTO person (%s) VALUES (%s)" % (cols, marks),
            [data[f] for f in fields],
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def update_person(pid, data):
    data = dict(data)
    if data.get("firm"):
        data["firm"] = canonical_firm(data["firm"])
    fields = [f for f in PERSON_FIELDS if f in data]
    if not fields:
        return get_person(pid)
    conn = connect()
    try:
        sets = ", ".join("%s=?" % f for f in fields)
        conn.execute(
            "UPDATE person SET %s, updated_at=CURRENT_TIMESTAMP WHERE id=?" % sets,
            [data[f] for f in fields] + [pid],
        )
        conn.commit()
    finally:
        conn.close()
    return get_person(pid)


def delete_person(pid):
    conn = connect()
    try:
        conn.execute("DELETE FROM person WHERE id=?", (pid,))
        conn.commit()
    finally:
        conn.close()


def add_note(pid, body, kind="note"):
    conn = connect()
    try:
        cur = conn.execute(
            "INSERT INTO note(person_id, kind, body) VALUES (?,?,?)",
            (pid, kind, body),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def delete_note(nid):
    conn = connect()
    try:
        conn.execute("DELETE FROM note WHERE id=?", (nid,))
        conn.commit()
    finally:
        conn.close()


def record_mail(person_id, direction, subject, counterpart, occurred_at,
                message_id="", snippet=""):
    conn = connect()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO mail_event"
            "(person_id, direction, subject, counterpart, occurred_at, message_id, snippet)"
            " VALUES (?,?,?,?,?,?,?)",
            (person_id, direction, subject, counterpart, occurred_at, message_id, snippet),
        )
        col = "last_outbound_at" if direction == "out" else "last_inbound_at"
        conn.execute(
            "UPDATE person SET %s = MAX(COALESCE(%s,''), ?) WHERE id=?" % (col, col),
            (occurred_at, person_id),
        )
        conn.commit()
    finally:
        conn.close()


def people_by_email():
    """Map lowercase email -> person id, for matching Outlook messages."""
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT id, email FROM person WHERE email <> '' AND archived = 0"
        ).fetchall()
    finally:
        conn.close()
    return {r["email"].strip().lower(): r["id"] for r in rows}
