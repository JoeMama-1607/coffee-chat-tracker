# Coffee Chat Tracker

A small macOS app for running consulting coffee chats: who you're talking to,
what stage each conversation is at, when the calendar actually has room, and
what you owe people today.

Everything runs on your Mac. There is no account, no server, no sync. Your data
lives in one SQLite file at
`~/Library/Application Support/CoffeeChatTracker/tracker.sqlite3`.

---

## Install

1. **Put this folder in your home folder** — for example `~/CoffeeChatTracker`.
   Not Desktop, Documents, Downloads or iCloud Drive: macOS silently blocks
   the app from reading files there and it will not start. The installer
   checks this, and offers to move the folder for you if it's in the wrong place.
2. Double-click **`install.command`**.
   - The first time, macOS may say it can't be opened because it's from an
     unidentified developer. Open **System Settings → Privacy & Security**,
     scroll down, click **Open Anyway** next to the message about
     install.command, and confirm.
   - It downloads the app's own copy of Python (about 25 MB, verified by
     checksum) into a `runtime/` folder here. You do not need Python installed,
     and it never touches any Python already on your Mac. Running the installer
     again later updates that copy if a newer one is pinned.
   - It builds **Coffee Chat Tracker.app** inside this folder.
3. Open the app from this folder, or search for it in Spotlight.
4. Go to **Settings**: fill in your name and email, upload your resume under
   **You**, and under **Your background** upload your own LinkedIn PDF (on
   LinkedIn: your profile → More → Save to PDF).

Running `install.command` again is safe: if the app is already set up it just
says so. Type `reinstall` at its prompt to rebuild it anyway — for instance
after replacing the app's files with a newer version.

If the app ever seems not to open, double-click **`Run in Terminal.command`**:
it runs the app with its log on screen, so you can see what went wrong.

### Permissions you'll be asked for

| Prompt | Why | If you decline |
|---|---|---|
| Calendar access | Reading busy time to propose conflict-free slots | Slots tab stops working; everything else is fine |
| Control "Microsoft Outlook" | Opening drafts, checking who replied | Draft and mail-scan buttons stop working; you can still copy text |

Both can be changed later in **System Settings → Privacy & Security**, under
**Calendars** and **Automation**.

---

## How it works

**Today** is the only screen you need most days. It applies the rules from the
GCA networking deck:

- a thank-you note is owed within 24 hours of a chat,
- a nudge is due after a week of silence,
- after three nudges it tells you to stop and ask a summer intern instead.

**Pipeline** is the log — the deck's spreadsheet, but it updates itself. Each
person moves through: uninitiated → outreach sent → awaiting reply → scheduled →
chat done → thank-you sent.

**Slots** reads Apple Calendar and hands you three conflict-free days formatted
exactly like the deck's example email, with your time zone attached:

```
• October 20, Monday: 12pm – 2pm or 4pm – 6pm ET
```

Rules you control: working hours, which days, a buffer around existing events so
you're not sprinting out of class, how far ahead to look, and how long a window
can be. Windows are capped at three hours by default — "I'm free all Friday"
reads as no plan at all.

**Download .ics** saves those same windows as calendar holds you can open
straight into Apple Calendar, optionally labelled with who you offered them to.

They are written as **busy** holds. Once you have offered a slot you have to be
free if it is accepted, so the time is genuinely blocked: nothing else can be
booked over it, and the slot finder counts it as a real conflict, which is what
stops the same window being offered to the next person.

The trade is that holds outlive their purpose. If someone declines or goes
quiet, the hold is still blocking good time — delete it. Every event shares the
same title prefix (`hold_prefix` in the database, default "Coffee chat hold")
and a "Coffee chats" category, so searching either one finds them all.

When a chat is confirmed, replace the hold with the real meeting.

**Applications** is every role you have applied to or mean to, soonest
deadline first. Overdue deadlines are red, the next week is gold, and each one
opens a panel with the role, the job description, where you stand, the key
dates, and buttons that open the tailored resume and cover letter from wherever
you keep them. Anything inside a week also shows up on Today.

Nothing about a deadline is ever emailed or notified. Today and the
Applications screen are the only places recruiting is allowed to nag from.

**Firms** covers the six you are actually recruiting for — McKinsey, Bain, BCG,
EY, PwC and Kearney. Each card opens with a fixed line or two on what the firm
is, then everything you have learned about it grouped by what it is about, then
everyone you know there (live from the pipeline, clickable through to the
person), then the applications you have in. Every
piece of knowledge carries where it came from: a chat, with who and when, or
research, with the page it came off. In an interview that difference matters.

**Review** is where changes wait for you. When you paste a coffee-chat
transcript to Claude it does not write anything into the tracker; it proposes.
Each proposal shows what it would change — a line-by-line before and after for
the resume walk — why, and Accept, Edit-then-accept or Reject. Accepting takes
exactly the same path as typing it in yourself.

**Prep** holds the call structure and a question bank split into good and great.
The great ones carry your own context, which is what makes them great.

### Prep sheets

The **Prep** button next to an upcoming chat (and in the person panel) builds a
briefing for that specific person.

LinkedIn requires a login and blocks automated access, so the app cannot fetch a
profile for you. Open their profile, select all, copy, and paste it into the box
on the prep sheet. Everything after that is local — the paste is stored in your
own database and never leaves the Mac.

From the paste it reads their actual career — roles, employers, how long each
lasted, education — and works out what is worth asking about:

- a pivot into consulting from another industry,
- a promotion, and how long it took,
- unusual tenure, or being brand new,
- more than one consulting firm on the CV,
- an MBA, and whether it was Goizueta.

Each of those earns a question that could only be asked of this person. Below
them sit three questions on company culture (growth, team dynamics, inclusion)
and three on their journey, then the thirty minutes laid out as a schedule.

If the paste can't be read, you still get the culture and journey questions and
the call structure — just not the tailored ones.

At the bottom of every prep sheet, **Download prep notes (PDF)** saves the whole
briefing to your Downloads folder: summary, career timeline, all the questions,
the thirty-minute schedule, and a page of ruled lines to write on during the
call. The PDF is composed from the underlying data rather than from the screen,
so the on-screen Copy buttons never appear in it.

### Your resume walk

**Settings → Resume walk** holds the two minutes you open every interview with,
the coaching points people have given you on it, and every version it has been
through. Saving never overwrites: the previous script stays in the history with
the date and who prompted the change, so you can see how the story moved.

---

## Working with Claude

Claude cannot open the database — it is in `~/Library`, where a separate app has
no business reaching. The hand-off is files, in the `research/` folder next to
this README.

**Claude writes into `research/inbox/`.** The app imports everything there the
next time the page refreshes, moves each file into `research/imported/` with a
timestamp, and writes `research/last_import.json` saying what each file did,
including anything that failed and why.

A top-level `"type"` says what a file is. A file with no `type` is person
research, which is what the folder started out doing:

| `type` | What it does |
|---|---|
| *(none)* | Research, prep and drafts for one person |
| `application` | Creates or updates one role, matched on `match_id` or company + role |
| `firm_knowledge` | Adds notes to one of the six firm pages, applied straight away |
| `proposals` | Everything read out of a transcript, waiting for you in Review |

Only the keys present in a file are written, so a file can update one field and
leave the rest alone. Imports are safe to repeat: a duplicate knowledge entry is
skipped, and re-importing a proposal batch adds nothing and never resurrects
something you already decided.

Nothing read out of a transcript is ever applied on import. It lands in Review
as a pending proposal and waits.

**Claude reads the snapshots**, which the app rewrites after every import and
after anything you change in the app:

| File | What's in it |
|---|---|
| `research/people.json` | Everyone in the tracker |
| `research/applications.json` | Every application, with days to the deadline |
| `research/firms.json` | Per firm: people, knowledge, applications |
| `research/resume_walk.json` | The current script, feedback, version count |
| `research/proposals.json` | Pending, plus the last 50 decided |
| `research/calendar.json` | Free time, written when Claude asks for it |

The exact shape of every inbox file is documented at the top of
`app/research.py`, which is the file that reads them.

### Backfill

`app/scripts/backfill_firms.py` reads everything already in
`research/imported/` and lifts the firm-level statements out of it onto the
firm pages. It is deliberately timid — a line has to name the firm, carry a
firm-level word and not read as somebody's own story — because a firm page full
of one person's career history is worse than an empty one. Run it as often as
you like; it never adds the same line twice.

```
python3 app/scripts/backfill_firms.py --dry-run          # show, write nothing
python3 app/scripts/backfill_firms.py
python3 app/scripts/backfill_firms.py --seed-applications
```

`--seed-applications` is off by default and asks before it writes: it guesses
one application per PDF in your Recruiting/Applications folder, and a guess is
not something to do quietly.

---

## About the drafts

The app never sends anything. It composes the email, opens it in Outlook, and
stops. You read it, fix it, and hit send yourself.

Drafts arrive with `[bracketed prompts]` where the personal content goes, and
the app counts how many are left before you open it. That friction is
deliberate — the deck's warning is that everybody can tell when they've received
a template, and a draft where only the name changed is exactly that.

Upload your resume once in **Settings → You** (PDF or Word). The app keeps its
own copy next to its data — not a link to wherever the file lives — because
macOS silently stops the app reading Documents, Desktop and Downloads, which is
where most resumes sit. Outreach and nudge drafts opened in Outlook attach that
copy, and the email only says "I've attached my resume" when the copy is
actually there to attach.

---

## Outlook: classic vs new

Mail tracking needs the **classic** Outlook for Mac. Microsoft's "new Outlook"
ships without AppleScript support, so nothing can read it locally.

Check which you have with **Settings → Test Outlook**. If it reports
`unscriptable`, open Outlook and turn off the **New Outlook** toggle at the top
right of the window.

Without it you lose only the automatic "who replied" detection. Drafting still
works, and you can move people through the pipeline by hand.

---

## If something goes wrong

Run **`Run in Terminal.command`**. It starts the app in the foreground and
prints the actual error instead of failing silently. The app also writes to
`~/Library/Logs/CoffeeChatTracker.log`.

Common ones:

- **Nothing happens when I open the app.** Most often the folder has ended up
  inside Desktop, Documents, Downloads or iCloud Drive, where macOS silently
  blocks it — move it to your home folder. Otherwise the app's Python may be
  missing: double-click `install.command` again. `Run in Terminal.command`
  shows the exact reason.
- **"Calendar access denied".** System Settings → Privacy & Security →
  Calendars → enable Coffee Chat Tracker.
- **Slots tab finds nothing.** Your rules are too tight. Widen working hours,
  drop the minimum window, or extend the look-ahead.
- **A red bar says "Lost contact with the app".** The server behind the window
  stopped. Nothing you type is being saved while that bar is up. Click Reload;
  if that fails, quit and reopen the app. Anything saved before the bar appeared
  is safe on disk.
- **I moved this folder.** That's fine as long as the app stays inside it and
  the folder isn't in one of the blocked places above. macOS may ask for
  Calendar access once more.

Edits in the person panel save themselves as you leave each field — there is no
Save button to forget. The line at the bottom of the panel confirms each save,
and turns red if one fails.

Closing the app window shuts the server down within a couple of minutes. Nothing
keeps running in the background.

---

## Backing up

Copy the whole folder:

```
~/Library/Application Support/CoffeeChatTracker/
```

That's your entire history — people, notes, questions asked, mail timestamps.

---

## Layout

```
CoffeeChatTracker/
├── install.command            build the .app, check the environment
├── Run in Terminal.command    foreground launch, for debugging
├── launcher.sh                what the .app actually runs
├── Info.plist                 bundle metadata + permission strings
└── app/
    ├── server.py              local HTTP server and JSON API
    ├── db.py                  SQLite schema and queries
    ├── availability.py        busy time → offerable windows
    ├── templates.py           email scaffolds, question bank
    ├── profile.py             LinkedIn paste → summary, signals, questions
    ├── pdfwriter.py           hand-rolled PDF output for prep notes
    ├── ics.py                 calendar holds for offered slots
    ├── macos.py               osascript bridge
    ├── research.py            the JSON hand-off with Claude
    ├── scripts/               the AppleScript and JXA it calls, and backfill_firms.py
    └── web/                   the interface
```

Standard library only. Nothing to install, nothing to update.
