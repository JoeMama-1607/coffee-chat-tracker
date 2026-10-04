# Pending tasks

Backlog for future sessions on Coffee Chat Tracker. Nothing here is scheduled —
pick up whichever is next. Current focus is coffee chats specifically, not a
general job/company/application tracker (that's handled elsewhere), so keep
these scoped to what a coffee chat converts into, not compensation data,
office/practice tagging, or anything that duplicates that other tool.

## 1. Interview-stage pipeline (extend past "nurturing")

`db.STATUSES` (`app/db.py`) tops out at `nurturing` / `no_response` — a chat that
actually converts into something has nowhere to go. Add stages that pick up
where a chat leaves off:

- referral_asked
- referred
- interview (first round)
- case_round
- superday
- offer
- declined / closed (didn't convert)

Keep it a flat status list like today (one person, one current stage), not a
separate table. Touches: `db.py` `STATUSES`, the status dropdown in
`app.js`/`index.html` (Pipeline table + drawer), and probably `firm_coverage()`
in `server.py` for a "converted" bucket. `compute_actions()` likely doesn't
need new SLA rules for these — the deck's rules stop at thank-you.

## 2. Funnel / analytics dashboard

A new view (or Today section) showing conversion through the funnel above:
how many people are at each stage, response rate, median days-to-reply,
chats → referrals → interviews by firm/tier. This is what would show you're
under-networked at a firm before it's too late to fix.

Reference for **visual style only** — this is a separate job-application
tracker for a different purpose, don't pull in its data model (compensation,
sponsorship stats, job postings) or scope:
https://claude.ai/artifact/1oKw8caNa4QMQzU8wmuspe

Worth reusing from it:
- a row of stat tiles at the top (big number + label, a couple flagged red
  when something needs attention)
- status shown as small colored pills instead of plain text
- a horizontal "steps" indicator (segments lighting up as someone advances
  through the funnel)
- small dependency-free inline SVG charts: a bar-list for percentage
  breakdowns (label — track — filled bar — %), and a donut for a categorical
  split (e.g. tier mix, or contact_channel once #4 below has real data)

Keep it read-only and derived from existing tables, same philosophy as
`firm_coverage()` and `compute_actions()` today — no new state to maintain.

## 3. CSV import with labels

Bulk-add people from a CSV that carries labels (event name, firm, tag, etc.),
as an alternative to the one-line-per-person paste in `openImport()`
(`app.js`). **Blocked on the user providing a sample CSV** — don't guess the
column mapping without seeing the actual file shape.

## 4. CSV/Excel export of the pipeline

Export `db.list_people()` to CSV (stdlib `csv` module, no new dependency) —
for backup in a portable format, or to hand to a career coach. Not urgent as
of 2026-09-19: no coach ask yet, and copying
`~/Library/Application Support/CoffeeChatTracker/` already covers backup.
Revisit if either changes.

## 5. Locked In: only the owner can read contacts and reviews

Locked In's database rule is `read: view` at the root, so anyone the page is
shared with can read every contact's name, email and research (`persons/*`,
`snapshot/people`), the chat reviews (`chats/*`), prep (`prep/*`) and firm
cards. The page is private today, but the Case Log tab has a "Share my case
history" button that invites sharing. Make every collection owner-read except
`cases` (and `caseIndex`), so a shared link shows the case history and nothing
about people. Republish with the `db` rules declared explicitly, then check a
read at the `view` level comes back empty for `persons`.

## 6. Locked In: flag firms that are under-networked

A strip on Today listing target firms with few or no chats, next to their
application deadline. As of 2026-10-04 EY has 31 people in the tracker and
no chat done yet (two scheduled), Kearney none at all. Derived from
`snapshot/people` and `applications`, no new state. Overlaps with #2 above,
which is the fuller version in the Mac app.

## 7. Locked In: fill the readiness checklist from what it already knows

In an application, "Coffee chats done" and "Referral named" are manual
ticks, but the page already counts chats at the firm and stores
`referralPersonId`. Tick them automatically (show the count), and keep
"Cases in their style" tied to the graded cases it already lists.

## 8. Index more casebooks for the partner-case search

Only Wharton 2025 (18 cases) is in `caseIndex`, while "Log partner case"
offers seven books, so most partner cases don't match and get saved as
"located manually". Index the rest (Darden 2024–25 stays excluded) through
the case-coach routine.
