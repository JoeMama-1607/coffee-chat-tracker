"""SQLite storage for Coffee Chat Tracker.

Pure standard library. Compatible with Python 3.9+ (the python3 that ships
with Xcode Command Line Tools) through 3.13.
"""

import datetime as dt
import json
import os
import re
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


def resume_dir():
    """Where the uploaded resume copy lives, alongside the database.

    Keeping our own copy matters: most people keep their resume in Documents or
    Downloads, which macOS silently stops this app from reading. A copy here is
    always readable, so it can always be attached."""
    path = os.path.join(data_dir(), "resume")
    os.makedirs(path, exist_ok=True)
    return path


def profiles_dir():
    """Where uploaded LinkedIn PDFs are kept, alongside the database. They stay
    so a profile can be re-read later without asking for the file again."""
    path = os.path.join(data_dir(), "profiles")
    os.makedirs(path, exist_ok=True)
    return path


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
    contact_channel TEXT DEFAULT '',   -- how you first reached them: email | linkedin
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
    offered_slots      TEXT DEFAULT '',
    offered_slots_at   TEXT,
    profile_pdf        TEXT DEFAULT '',
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

-- Items ticked off on the Today page. Nothing on that page is stored — every
-- action is worked out fresh from the people table — so ticking one off means
-- remembering the exact situation that produced it. If that situation changes
-- (they reply, you email again, a new chat is booked) the key changes with it
-- and the action comes back on its own.
--
-- Resolutions last for one run of the app and no longer. `session` records
-- which run binned the item; while it matches, the item sits in the bin and
-- can be put back. On the next launch every older row is deleted outright, so
-- anything genuinely still outstanding is back on the list where it belongs.
-- Ticking something off is for clearing today's noise, not for burying it.
CREATE TABLE IF NOT EXISTS resolved_action (
    key         TEXT PRIMARY KEY,
    person_id   INTEGER REFERENCES person(id) ON DELETE CASCADE,
    kind        TEXT DEFAULT '',
    label       TEXT DEFAULT '',
    detail      TEXT DEFAULT '',
    person_name TEXT DEFAULT '',
    resolved_at TEXT DEFAULT CURRENT_TIMESTAMP,
    session     TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_person_status ON person(status);
CREATE INDEX IF NOT EXISTS idx_note_person  ON note(person_id);
CREATE INDEX IF NOT EXISTS idx_mail_person  ON mail_event(person_id);

-- Exactly what went to Outlook when "Open in Outlook" was clicked, so the
-- person panel can show the email that was sent. The app never sends: "sent"
-- here means handed to Outlook as a draft.
CREATE TABLE IF NOT EXISTS sent_mail (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id  INTEGER NOT NULL REFERENCES person(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,            -- outreach | followup | thankyou
    subject    TEXT DEFAULT '',
    body       TEXT DEFAULT '',
    sent_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sent_person ON sent_mail(person_id);

-- ------------------------------------------------------------ recruiting
-- Everything from here down is the application side of recruiting: the roles
-- applied to, what has been learned about the six target firms, the resume
-- walk, and the changes Claude proposes from a coffee-chat transcript.

CREATE TABLE IF NOT EXISTS application (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    company           TEXT NOT NULL,
    role              TEXT DEFAULT '',
    office            TEXT DEFAULT '',
    job_url           TEXT DEFAULT '',
    jd_text           TEXT DEFAULT '',
    status            TEXT DEFAULT 'researching',
    deadline          TEXT,             -- YYYY-MM-DD
    applied_at        TEXT,
    interview_r1_at   TEXT,
    interview_r2_at   TEXT,
    resume_file       TEXT DEFAULT '',  -- absolute path, usually in iCloud
    cover_letter_file TEXT DEFAULT '',
    notes             TEXT DEFAULT '',
    archived          INTEGER DEFAULT 0,
    created_at        TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at        TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_application_deadline ON application(deadline);

-- Every move through the pipeline, kept rather than overwritten: "when did
-- this become an interview" is the question you actually ask later.
CREATE TABLE IF NOT EXISTS application_status (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER NOT NULL REFERENCES application(id) ON DELETE CASCADE,
    status         TEXT NOT NULL,
    note           TEXT DEFAULT '',
    created_at     TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_appstatus_app ON application_status(application_id);

-- What you know about a firm, whoever it came from. A line from a chat and a
-- line from the careers page sit side by side, each carrying its own source,
-- because in an interview the difference matters.
CREATE TABLE IF NOT EXISTS firm_knowledge (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    firm             TEXT NOT NULL,
    category         TEXT DEFAULT 'other',
    body             TEXT NOT NULL,
    source_type      TEXT DEFAULT 'research',   -- chat | research
    source_person_id INTEGER REFERENCES person(id) ON DELETE SET NULL,
    source_label     TEXT DEFAULT '',
    source_url       TEXT DEFAULT '',
    created_at       TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_knowledge_firm ON firm_knowledge(firm);

-- The resume walk is one script that keeps being rewritten. Every version is
-- kept: the newest row is the current script, the rest are the history, and
-- nothing is ever edited in place.
CREATE TABLE IF NOT EXISTS resume_walk_version (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    body       TEXT NOT NULL,
    source     TEXT DEFAULT 'you',        -- you | chat with … | research
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS resume_walk_feedback (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    body       TEXT NOT NULL,
    source     TEXT DEFAULT '',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Changes Claude proposes after reading a transcript. Nothing here has
-- touched the tracker yet — a proposal is applied only when it is accepted
-- in the Review screen, through the same code the manual UI uses.
CREATE TABLE IF NOT EXISTS proposal (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id     TEXT NOT NULL,
    item_key     TEXT DEFAULT '',        -- batch-stable id, so re-import can't duplicate
    source_label TEXT DEFAULT '',
    person_id    INTEGER REFERENCES person(id) ON DELETE SET NULL,
    kind         TEXT NOT NULL,          -- firm_knowledge | resume_walk | person_update | application_update
    payload      TEXT NOT NULL,          -- JSON
    rationale    TEXT DEFAULT '',
    status       TEXT DEFAULT 'pending', -- pending | accepted | rejected
    decided_at   TEXT,
    created_at   TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(batch_id, item_key)
);
CREATE INDEX IF NOT EXISTS idx_proposal_batch ON proposal(batch_id);

-- The transcript a batch came from, kept once per batch so Review can show
-- what a proposal was actually read out of.
CREATE TABLE IF NOT EXISTS proposal_batch (
    batch_id     TEXT PRIMARY KEY,
    source_label TEXT DEFAULT '',
    person_id    INTEGER REFERENCES person(id) ON DELETE SET NULL,
    transcript   TEXT DEFAULT '',
    created_at   TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

# Pipeline stages, in the order the GCA deck describes the process.
STATUSES = [
    ("uninitiated", "Uninitiated"),
    ("tracking", "Tracking"),          # to research and reach out to
    ("outreach_sent", "Outreach sent"),
    ("scheduled", "Chat scheduled"),
    ("chat_done", "Chat done"),
    ("thankyou_sent", "Thank-you sent"),
    ("no_response", "No response"),
]

# Where an application stands. One list, in the order it actually happens.
APPLICATION_STATUSES = [
    ("researching", "Researching"),
    ("networking", "Networking"),
    ("applying", "Applying"),
    ("applied", "Applied"),
    ("interview_r1", "Interview R1"),
    ("interview_r2", "Interview R2"),
    ("offer", "Offer"),
    ("rejected", "Rejected"),
    ("withdrawn", "Withdrawn"),
]

# The six firms this recruiting cycle is actually aimed at. Firm pages exist
# for these and no others, so the list lives here once and everything else
# asks for it. (`target_firms` in settings is the wider coverage chart.)
TARGET_FIRMS = ["McKinsey", "Bain", "BCG", "EY", "PwC", "Kearney"]

# How a firm gets written on a LinkedIn profile, matched to which of the six
# it is. Kept apart from FIRM_ALIASES, which rewrites what is stored on a
# person: nothing here changes a single row, it only answers "is this Bain?".
TARGET_FIRM_ALIASES = {
    "mckinsey": "McKinsey", "mckinsey & company": "McKinsey",
    "mckinsey and company": "McKinsey", "mckinsey & co": "McKinsey",
    "mckinsey & co.": "McKinsey",
    "bain": "Bain", "bain & company": "Bain", "bain and company": "Bain",
    "bain & co": "Bain", "bain & co.": "Bain", "bain capability network": "Bain",
    "bcg": "BCG", "boston consulting group": "BCG",
    "the boston consulting group": "BCG", "bcg x": "BCG",
    "ey": "EY", "ey-parthenon": "EY", "ey parthenon": "EY",
    "ernst & young": "EY", "ernst and young": "EY", "ey strategy and transactions": "EY",
    "pwc": "PwC", "pricewaterhousecoopers": "PwC", "pwc strategy&": "PwC",
    "pwc strategy and": "PwC", "strategy&": "PwC", "strategy& (pwc)": "PwC",
    "kearney": "Kearney", "a.t. kearney": "Kearney", "at kearney": "Kearney",
    "a t kearney": "Kearney",
}

# A fixed line or two on each firm, so a firm page opens with something on it
# on day one. Deliberately the uncontroversial shape of the place — what it is
# and what it is known for — and deliberately not recruiting specifics, which
# change every cycle and belong in knowledge entries with a source on them.
FIRM_BRIEFS = {
    "McKinsey": "Founded 1926 by James O. McKinsey; employee-owned, ~38,000 people and "
                "~$16B revenue (2023 est.). The largest and oldest of MBB: generalist "
                "staffing with deep practice/industry knowledge, strict up-or-out, and the "
                "strongest CEO and alumni network in the industry. Tops prestige rankings but "
                "has sat out Vault's Consulting 50 for three years; carries reputational "
                "baggage (e.g. the $600M+ opioid settlements). CaseCoach #1.",
    "BCG": "Founded 1963 by Bruce Henderson; inventor of the growth-share matrix. $14.4B "
           "revenue in 2025 (+7%, 22nd straight year of growth), 33,500 people, 100+ cities. "
           "Now close to McKinsey in size and growing faster, with the heaviest push into "
           "AI and tech delivery through BCG X (AI work grew ~25% in 2025). Known for "
           "creative, bespoke problem-solving. Vault 2026 #2; CaseCoach #2.",
    "Bain": "Founded 1973 in Boston by Bill Bain and ex-BCG partners (separate from Bain "
            "Capital). ~19,000 people in 67 cities, the smallest of MBB. Differentiators: "
            "results focus and implementation, the leading private equity / due diligence "
            "practice, Net Promoter Score, and an office-centred, famously supportive "
            "culture. Vault 2026 #1 and Glassdoor #1 Best Place to Work a record seven "
            "times. CaseCoach #3.",
    "Kearney": "Shares its 1926 Chicago origin with McKinsey; independent and partner-owned "
               "again since a 2006 buyback from EDS. $2B+ revenue, 5,300+ people, 60+ "
               "offices in 40+ countries. Best known for operations, procurement and supply "
               "chain, plus strategy work; runs the Global Business Policy Council think tank "
               "(FDI Confidence Index). Smaller classes, collegial and entrepreneurial feel. "
               "CaseCoach #4.",
    "EY": "EY-Parthenon is EY's strategy brand: Parthenon (a Boston boutique founded 1991, "
          "strong in private equity, M&A and education) was bought in 2014. In 2025 EY "
          "folded its whole Strategy & Transactions line into it, making ~25,000 people in "
          "150 countries covering strategy, deals, value creation and turnaround. Pitch: "
          "MBB-style strategy backed by Big Four scale and execution; the work you get "
          "depends heavily on the team you join. CaseCoach #9.",
    "PwC": "Strategy& is PwC's strategy arm: the former Booz & Company (roots in Edwin "
           "Booz's 1914 firm), acquired in 2014 and the largest strategy firm bought by a "
           "Big Four. ~4,500 consultants, 80+ offices in 41 countries; known for "
           "capabilities-driven strategy and Fit for Growth cost transformation. Most MBA "
           "hiring sits across PwC advisory, deals and transformation (PwC Advisory $24.3B "
           "in FY2025), split by practice. CaseCoach #8.",
}

# What a piece of firm knowledge is about. `other` is the honest home for
# anything that doesn't fit rather than a category invented on the spot.
KNOWLEDGE_CATEGORIES = [
    ("culture", "Culture"),
    ("practice_areas", "Practice areas"),
    ("recruiting_process", "Recruiting process"),
    ("office", "Office"),
    ("why_this_firm", "Why this firm"),
    ("people_insights", "People insights"),
    ("other", "Other"),
]

PROPOSAL_KINDS = ["firm_knowledge", "resume_walk", "person_update", "application_update"]


def match_target_firm(name):
    """Which of the six this firm name is, or "" if it is none of them."""
    raw = (name or "").strip()
    if not raw:
        return ""
    key = raw.casefold()
    if key in TARGET_FIRM_ALIASES:
        return TARGET_FIRM_ALIASES[key]
    # "Bain & Company | Atlanta", "EY-Parthenon (Strategy Consulting)" — the
    # office or practice after a separator is dropped and the name in front of
    # it is looked up whole. Deliberately not a prefix match: "Bain Capital"
    # is not Bain, and guessing costs more here than missing.
    head = re.split(r"[|(/,\u2013\u2014]|\s[-\u2022]\s", key)[0].strip()
    return TARGET_FIRM_ALIASES.get(head, "")


DEFAULT_SETTINGS = {
    "user_name": "",
    # Put in the chat invite (location + body) and the confirmation email.
    "zoom_link": "",
    "user_email": "",
    "user_program": "Class of 2028 | Master of Business Administration (M.B.A.)",
    "user_school": "Goizueta Business School | Emory University",
    # Your own profile, so the app can work out what you and the person you
    # are writing to actually have in common.
    "user_profile_raw": "",
    "user_profile_pdf": "",
    "user_pitch": "",
    "resume_path": "",
    "timezone": "America/New_York",
    "tz_label": "ET",
    # availability rules
    "work_days": "1,2,3,4,5",          # Mon=1 .. Sun=7
    "work_start": "09:00",
    "work_end": "18:00",
    "min_window_minutes": "60",
    "max_window_minutes": "120",
    "outlook_lookback_days": "30",
    "buffer_minutes": "15",
    "lead_days": "0",
    "horizon_days": "14",
    "slots_wanted": "3",
    "max_per_day": "2",
    "ignore_all_day": "1",
    "ignore_tentative": "1",
    "excluded_calendars": "",
    "hold_prefix": "Coffee chat hold",
    # Apple Calendar calendars (by name) for holds and confirmed chats. Empty
    # = your default calendar; a name that doesn't exist falls back to it.
    "hold_calendar": "",
    "chat_calendar": "",
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


def backup_once(tag):
    """Copy the database aside before a release that changes its shape.

    One copy per tag, never overwritten, kept next to the database itself. It
    costs a few megabytes and it is the only thing standing between a bad
    migration and a rebuilt pipeline."""
    src = db_path()
    if not os.path.isfile(src):
        return None
    marker = os.path.join(data_dir(), "backups", ".%s" % tag)
    if os.path.exists(marker):
        return None
    folder = os.path.dirname(marker)
    os.makedirs(folder, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = os.path.join(folder, "tracker-%s-%s.sqlite3" % (tag, stamp))
    conn = connect()
    try:                            # the sqlite way: consistent even in WAL
        out = sqlite3.connect(dest)
        with out:
            conn.backup(out)
        out.close()
    except (AttributeError, sqlite3.Error):
        import shutil
        shutil.copy2(src, dest)
    finally:
        conn.close()
    with open(marker, "w", encoding="utf-8") as fh:
        fh.write(dest)
    return dest


def init():
    backup_once("pre-applications")
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
    "is_alum", "tier", "source", "contact_channel", "status", "priority_note", "referred_by",
    "first_contact_at", "last_outbound_at", "last_inbound_at", "chat_at",
    "thankyou_sent_at", "followups_sent", "next_action", "next_action_date",
    "linkedin_raw", "profile_updated_at", "offered_slots", "offered_slots_at",
    "profile_pdf", "archived",
    "research_md", "research_sources", "prep_md", "draft_subject", "draft_body",
    "researched_at", "invite_drafted_at", "confirm_drafted_at",
]

# Columns added after the first release. Existing databases are upgraded in
# place on startup so nobody loses the people they have already entered.
MIGRATIONS = [
    ("person", "linkedin_raw", "TEXT DEFAULT ''"),
    ("person", "profile_updated_at", "TEXT"),
    ("person", "offered_slots", "TEXT DEFAULT ''"),
    ("person", "offered_slots_at", "TEXT"),
    ("person", "profile_pdf", "TEXT DEFAULT ''"),
    ("person", "contact_channel", "TEXT DEFAULT ''"),
    # Research Claude writes and the app imports (research.py).
    ("person", "research_md", "TEXT DEFAULT ''"),
    ("person", "research_sources", "TEXT DEFAULT ''"),
    ("person", "prep_md", "TEXT DEFAULT ''"),
    ("person", "draft_subject", "TEXT DEFAULT ''"),
    ("person", "draft_body", "TEXT DEFAULT ''"),
    ("person", "researched_at", "TEXT"),
    # After a slot is confirmed: the Outlook invite and the confirmation reply.
    ("person", "invite_drafted_at", "TEXT"),
    ("person", "confirm_drafted_at", "TEXT"),
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

    # Slots used to start two days out. They now start today, on the same
    # "only if you never changed it yourself" terms.
    lead = conn.execute("SELECT value FROM setting WHERE key='lead_days'").fetchone()
    if lead and lead["value"].strip() == "2":
        conn.execute("UPDATE setting SET value='0' WHERE key='lead_days'")

    # A day's longest offered window shrank from 3 hours to 2, on the same
    # "only if you never changed it yourself" terms.
    max_window = conn.execute(
        "SELECT value FROM setting WHERE key='max_window_minutes'").fetchone()
    if max_window and max_window["value"].strip() == "180":
        conn.execute("UPDATE setting SET value='120' WHERE key='max_window_minutes'")

    # "Nurturing" is gone as a stage — it always meant "thank-you already
    # sent, ongoing", which thankyou_sent already covers.
    conn.execute("UPDATE person SET status='thankyou_sent' WHERE status='nurturing'")

    # "Awaiting reply" is gone too — it was "Outreach sent" by another name.
    conn.execute("UPDATE person SET status='outreach_sent' WHERE status='awaiting_reply'")


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


def add_sent_mail(pid, kind, subject, body, sent_at):
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO sent_mail(person_id, kind, subject, body, sent_at) "
            "VALUES (?,?,?,?,?)", (pid, kind, subject, body, sent_at))
        conn.commit()
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
        person["sent_mail"] = [
            dict(x)
            for x in conn.execute(
                "SELECT id, kind, subject, body, sent_at FROM sent_mail "
                "WHERE person_id=? ORDER BY sent_at, id",
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
    # Most people you're chatting with are Goizueta alumni — imports and any
    # other path that doesn't set this explicitly should assume that rather
    # than the exception.
    if "is_alum" not in data:
        data["is_alum"] = 1
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


# ------------------------------------------------------- resolved actions

def resolve_action(key, person_id, kind, label, detail, person_name, session):
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO resolved_action"
            "(key, person_id, kind, label, detail, person_name, session) "
            "VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET session=excluded.session, "
            "resolved_at=CURRENT_TIMESTAMP",
            (key, person_id, kind, label, detail, person_name, session),
        )
        conn.commit()
    finally:
        conn.close()


def restore_action(key):
    """Put it back on the Today list."""
    conn = connect()
    try:
        conn.execute("DELETE FROM resolved_action WHERE key=?", (key,))
        conn.commit()
    finally:
        conn.close()


def resolved_keys():
    """Every action ever ticked off, across every run. A resolution is keyed
    to the exact situation that produced it (`action_key()` folds in the
    outbound timestamp, the reply timestamp, the due date — whatever makes
    the situation what it is), so a genuinely new situation always mints a
    new key on its own. Nothing here needs to expire for that to work; it
    only needs to stay resolved until the facts underneath it change."""
    conn = connect()
    try:
        return {r["key"] for r in conn.execute("SELECT key FROM resolved_action")}
    finally:
        conn.close()


def bin_items(session):
    """What is still recoverable with one click — just this run's ticks, so
    the bin reads as 'what I did just now' rather than a growing history.
    Anything ticked off in an earlier run is still resolved (see
    `resolved_keys`), it just no longer shows up here to undo."""
    if not session:
        return []
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT * FROM resolved_action WHERE session=? "
            "ORDER BY resolved_at DESC, rowid DESC", (session,)).fetchall()
        return [dict(r) for r in rows]
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


# ------------------------------------------------------------ applications

APPLICATION_FIELDS = [
    "company", "role", "office", "job_url", "jd_text", "status", "deadline",
    "applied_at", "interview_r1_at", "interview_r2_at", "resume_file",
    "cover_letter_file", "notes", "archived",
]


def _days_to(deadline):
    """Whole days from today to a YYYY-MM-DD date; negative once it's past."""
    text = (deadline or "")[:10]
    if not text:
        return None
    try:
        day = dt.date(*[int(x) for x in text.split("-")])
    except (TypeError, ValueError):
        return None
    return (day - dt.date.today()).days


def _application_row(row):
    app = dict(row)
    app["days_to_deadline"] = _days_to(app.get("deadline"))
    # Derived, never stored: the six are a constant, so a row can't drift out
    # of step with the list the way a saved flag would.
    app["target_firm"] = match_target_firm(app.get("company"))
    app["is_target_firm"] = bool(app["target_firm"])
    return app


def list_applications(include_archived=False):
    conn = connect()
    try:
        sql = "SELECT * FROM application "
        if not include_archived:
            sql += "WHERE archived = 0 "
        # No deadline means nothing to be late for, so those sort last.
        sql += ("ORDER BY CASE WHEN COALESCE(deadline,'') = '' THEN 1 ELSE 0 END, "
                "deadline, company COLLATE NOCASE")
        return [_application_row(r) for r in conn.execute(sql).fetchall()]
    finally:
        conn.close()


def get_application(aid):
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM application WHERE id=?", (aid,)).fetchone()
        if row is None:
            return None
        app = _application_row(row)
        app["status_history"] = [dict(r) for r in conn.execute(
            "SELECT * FROM application_status WHERE application_id=? "
            "ORDER BY created_at, id", (aid,)).fetchall()]
        return app
    finally:
        conn.close()


def create_application(data):
    data = dict(data)
    if not (data.get("company") or "").strip():
        raise ValueError("company is required")
    fields = [f for f in APPLICATION_FIELDS if f in data]
    conn = connect()
    try:
        cols = ", ".join(fields)
        marks = ", ".join("?" for _ in fields)
        cur = conn.execute("INSERT INTO application (%s) VALUES (%s)" % (cols, marks),
                           [data[f] for f in fields])
        aid = cur.lastrowid
        conn.execute(
            "INSERT INTO application_status(application_id, status, note) VALUES (?,?,?)",
            (aid, data.get("status") or "researching", "added"))
        conn.commit()
        return aid
    finally:
        conn.close()


def update_application(aid, data):
    """Partial update. A status that actually changes is logged as history."""
    data = dict(data)
    fields = [f for f in APPLICATION_FIELDS if f in data]
    if not fields:
        return get_application(aid)
    conn = connect()
    try:
        before = conn.execute("SELECT status FROM application WHERE id=?",
                              (aid,)).fetchone()
        sets = ", ".join("%s=?" % f for f in fields)
        conn.execute(
            "UPDATE application SET %s, updated_at=CURRENT_TIMESTAMP WHERE id=?" % sets,
            [data[f] for f in fields] + [aid])
        if before and "status" in data and data["status"] != before["status"]:
            conn.execute(
                "INSERT INTO application_status(application_id, status, note) "
                "VALUES (?,?,?)", (aid, data["status"], data.get("status_note", "")))
        conn.commit()
    finally:
        conn.close()
    return get_application(aid)


def delete_application(aid):
    conn = connect()
    try:
        conn.execute("DELETE FROM application WHERE id=?", (aid,))
        conn.commit()
    finally:
        conn.close()


def find_application(match_id=None, company="", role=""):
    """How an inbox file points at an application: by id, else by company and
    role together. Company alone is not enough — two roles at one firm is the
    normal case, not the exception."""
    conn = connect()
    try:
        if match_id:
            row = conn.execute("SELECT * FROM application WHERE id=?",
                               (int(match_id),)).fetchone()
            return _application_row(row) if row else None
        if not (company or "").strip():
            return None
        rows = conn.execute(
            "SELECT * FROM application WHERE lower(trim(company))=? "
            "AND lower(trim(role))=?",
            (company.strip().lower(), (role or "").strip().lower())).fetchall()
        return _application_row(rows[0]) if len(rows) == 1 else None
    finally:
        conn.close()


# --------------------------------------------------------- firm knowledge

def list_knowledge(firm=None):
    conn = connect()
    try:
        if firm:
            rows = conn.execute(
                "SELECT k.*, p.name AS source_person_name FROM firm_knowledge k "
                "LEFT JOIN person p ON p.id = k.source_person_id "
                "WHERE k.firm=? ORDER BY k.category, k.created_at DESC, k.id DESC",
                (firm,)).fetchall()
        else:
            rows = conn.execute(
                "SELECT k.*, p.name AS source_person_name FROM firm_knowledge k "
                "LEFT JOIN person p ON p.id = k.source_person_id "
                "ORDER BY k.firm, k.category, k.created_at DESC, k.id DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def add_knowledge(firm, category, body, source_type="research",
                  source_person_id=None, source_label="", source_url=""):
    """Returns the new id, or None when that exact body is already on file for
    the firm — imports and the backfill both re-run, and a second copy of a
    sentence is noise rather than knowledge."""
    firm = match_target_firm(firm) or canonical_firm(firm)
    body = (body or "").strip()
    if not firm or not body:
        raise ValueError("firm and body are required")
    conn = connect()
    try:
        dup = conn.execute(
            "SELECT id FROM firm_knowledge WHERE firm=? AND trim(body)=?",
            (firm, body)).fetchone()
        if dup:
            return None
        cur = conn.execute(
            "INSERT INTO firm_knowledge(firm, category, body, source_type, "
            "source_person_id, source_label, source_url) VALUES (?,?,?,?,?,?,?)",
            (firm, category or "other", body, source_type or "research",
             source_person_id, source_label or "", source_url or ""))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


KNOWLEDGE_FIELDS = ["firm", "category", "body", "source_type", "source_label",
                    "source_url", "source_person_id"]


def update_knowledge(kid, data):
    fields = [f for f in KNOWLEDGE_FIELDS if f in data]
    if not fields:
        return None
    conn = connect()
    try:
        sets = ", ".join("%s=?" % f for f in fields)
        conn.execute("UPDATE firm_knowledge SET %s WHERE id=?" % sets,
                     [data[f] for f in fields] + [kid])
        conn.commit()
    finally:
        conn.close()
    return kid


def delete_knowledge(kid):
    conn = connect()
    try:
        conn.execute("DELETE FROM firm_knowledge WHERE id=?", (kid,))
        conn.commit()
    finally:
        conn.close()


# ------------------------------------------------------------ resume walk

def resume_walk():
    """The current script, its history, and the coaching points against it.
    The newest version is the script; the rest is how it got there."""
    conn = connect()
    try:
        versions = [dict(r) for r in conn.execute(
            "SELECT * FROM resume_walk_version ORDER BY created_at DESC, id DESC"
        ).fetchall()]
        feedback = [dict(r) for r in conn.execute(
            "SELECT * FROM resume_walk_feedback ORDER BY created_at DESC, id DESC"
        ).fetchall()]
    finally:
        conn.close()
    return {
        "body": versions[0]["body"] if versions else "",
        "updated_at": versions[0]["created_at"] if versions else None,
        "source": versions[0]["source"] if versions else "",
        "versions": versions,
        "feedback": feedback,
    }


def set_resume_walk(body, source="you"):
    """Writes a new version and keeps the old one. Identical text is not a
    change, so it does not earn a version — otherwise a tab-out on an
    untouched field would bury the real history."""
    body = body or ""
    current = resume_walk()
    if body.strip() == (current["body"] or "").strip():
        return current
    conn = connect()
    try:
        conn.execute("INSERT INTO resume_walk_version(body, source) VALUES (?,?)",
                     (body, source or "you"))
        conn.commit()
    finally:
        conn.close()
    return resume_walk()


def add_resume_feedback(body, source=""):
    body = (body or "").strip()
    if not body:
        raise ValueError("feedback is required")
    conn = connect()
    try:
        cur = conn.execute(
            "INSERT INTO resume_walk_feedback(body, source) VALUES (?,?)",
            (body, source or ""))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def delete_resume_feedback(fid):
    conn = connect()
    try:
        conn.execute("DELETE FROM resume_walk_feedback WHERE id=?", (fid,))
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------- proposals

def add_proposal_batch(batch_id, source_label="", person_id=None, transcript=""):
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO proposal_batch(batch_id, source_label, person_id, transcript) "
            "VALUES (?,?,?,?) ON CONFLICT(batch_id) DO UPDATE SET "
            "source_label=excluded.source_label, person_id=excluded.person_id, "
            "transcript=CASE WHEN excluded.transcript <> '' "
            "THEN excluded.transcript ELSE proposal_batch.transcript END",
            (batch_id, source_label or "", person_id, transcript or ""))
        conn.commit()
    finally:
        conn.close()


def add_proposal(batch_id, item_key, kind, payload, rationale="",
                 source_label="", person_id=None):
    """Returns the new id, or None if this batch already carries that item.
    The agent re-writes a batch file whenever it revises it, so re-import has
    to be a no-op for anything already decided or waiting."""
    if kind not in PROPOSAL_KINDS:
        raise ValueError("unknown proposal kind %r" % kind)
    conn = connect()
    try:
        cur = conn.execute(
            "INSERT OR IGNORE INTO proposal(batch_id, item_key, source_label, "
            "person_id, kind, payload, rationale) VALUES (?,?,?,?,?,?,?)",
            (batch_id, item_key, source_label or "", person_id, kind,
             json.dumps(payload or {}), rationale or ""))
        conn.commit()
        return cur.lastrowid if cur.rowcount else None
    finally:
        conn.close()


def _proposal_row(row):
    item = dict(row)
    try:
        item["payload"] = json.loads(item.get("payload") or "{}")
    except ValueError:
        item["payload"] = {}
    return item


def list_proposals(status=None, decided_limit=50):
    """Everything pending, plus the last few decisions so the agent can see
    what was taken up and what was not."""
    conn = connect()
    try:
        if status:
            rows = conn.execute(
                "SELECT p.*, pe.name AS person_name FROM proposal p "
                "LEFT JOIN person pe ON pe.id = p.person_id WHERE p.status=? "
                "ORDER BY p.created_at DESC, p.id DESC", (status,)).fetchall()
            return [_proposal_row(r) for r in rows]
        pending = conn.execute(
            "SELECT p.*, pe.name AS person_name FROM proposal p "
            "LEFT JOIN person pe ON pe.id = p.person_id WHERE p.status='pending' "
            "ORDER BY p.created_at DESC, p.id DESC").fetchall()
        decided = conn.execute(
            "SELECT p.*, pe.name AS person_name FROM proposal p "
            "LEFT JOIN person pe ON pe.id = p.person_id WHERE p.status<>'pending' "
            "ORDER BY p.decided_at DESC, p.id DESC LIMIT ?",
            (decided_limit,)).fetchall()
        return [_proposal_row(r) for r in list(pending) + list(decided)]
    finally:
        conn.close()


def get_proposal(pid):
    conn = connect()
    try:
        row = conn.execute(
            "SELECT p.*, pe.name AS person_name FROM proposal p "
            "LEFT JOIN person pe ON pe.id = p.person_id WHERE p.id=?",
            (pid,)).fetchone()
        return _proposal_row(row) if row else None
    finally:
        conn.close()


def set_proposal(pid, status, payload=None):
    """Mark a proposal decided. An edited-then-accepted proposal stores what
    was actually applied, so Review shows the change that really happened."""
    conn = connect()
    try:
        if payload is not None:
            conn.execute("UPDATE proposal SET payload=? WHERE id=?",
                         (json.dumps(payload), pid))
        conn.execute("UPDATE proposal SET status=?, decided_at=CURRENT_TIMESTAMP "
                     "WHERE id=?", (status, pid))
        conn.commit()
    finally:
        conn.close()
    return get_proposal(pid)


def proposal_batches():
    conn = connect()
    try:
        return {r["batch_id"]: dict(r) for r in conn.execute(
            "SELECT * FROM proposal_batch").fetchall()}
    finally:
        conn.close()
