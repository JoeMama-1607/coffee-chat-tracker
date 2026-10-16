"""Sync with calendar, proposed-vs-held slots, the master resume, and backups.

Run from the repo root:  python3 -B -m unittest discover app/tests
Throwaway HOME, a fake calendar and a fake Outlook: the real database,
Calendar and Outlook are never touched.
"""

import datetime as dt
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

HOME = tempfile.mkdtemp()
os.environ["HOME"] = HOME
os.environ["CCT_DEMO"] = "1"
os.environ["CCT_BACKUP_ROOT"] = os.path.join(HOME, "backups")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import availability  # noqa: E402
import db  # noqa: E402
import macos  # noqa: E402
import research  # noqa: E402
import server  # noqa: E402
from http.server import ThreadingHTTPServer  # noqa: E402

TZ = availability.get_tz("America/New_York")
NAME = "Test Person"
HOLD = "Coffee chat hold — " + NAME


def win(day_offset, hour, minutes=60):
    start = dt.datetime.now(TZ).replace(hour=hour, minute=0, second=0, microsecond=0)
    start += dt.timedelta(days=day_offset)
    return start, start + dt.timedelta(minutes=minutes)


def near(a, b):
    return abs((a - b).total_seconds()) < 60


class FakeCalendar:
    def __init__(self):
        s, e = win(2, 15)
        self.events = [("Strategy class", s, e)]    # something unrelated is always there
        self.writes = 0

    def read(self, start, end):
        return {"ok": True, "events": [
            {"title": t, "start": s.isoformat(), "end": e.isoformat(), "all_day": False}
            for t, s, e in self.events]}

    def sync(self, delete=None, upsert=None, ensure=None):
        for prefix, s, e in delete or []:
            self.events = [ev for ev in self.events
                           if not (ev[0].startswith(prefix) and near(ev[1], s))]
        for x in ensure or []:
            if not any(ev[0].startswith(x["prefix"]) and near(ev[1], x["start"])
                       and near(ev[2], x["end"]) for ev in self.events):
                self.events.append((x["title"], x["start"], x["end"]))
                self.writes += 1
        return {"ok": True, "deleted": 0, "created": 0, "errors": []}

    def holds(self, name=NAME):
        return sorted((s, e) for t, s, e in self.events if t == "Coffee chat hold — " + name)

    def replace_holds(self, windows, name=NAME):
        self.events = [ev for ev in self.events if ev[0] != "Coffee chat hold — " + name]
        for s, e in windows:
            self.events.append(("Coffee chat hold — " + name, s, e))


class SyncTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.port = cls.httpd.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def setUp(self):
        if os.path.exists(db.db_path()):
            os.remove(db.db_path())
        db.init()
        self.root = tempfile.mkdtemp(dir=HOME)
        research.ROOT = self.root
        research.INBOX = os.path.join(self.root, "inbox")
        research.DONE = os.path.join(self.root, "imported")
        os.makedirs(research.INBOX)
        self.cal = FakeCalendar()
        macos.read_calendar = self.cal.read
        macos.calendar_sync = self.cal.sync
        self.drafts = []
        macos.draft_email = lambda *a, **k: (self.drafts.append(a) or {"ok": True})
        server.MASTER_RESUME_DIR = tempfile.mkdtemp(dir=HOME)
        with open(os.path.join(server.MASTER_RESUME_DIR, "Aashish_Balivada_Resume.pdf"), "wb") as fh:
            fh.write(b"%PDF-1.4 test")
        self.n = 0

    # -- helpers -------------------------------------------------------------
    def drop(self, slots, name=NAME):
        self.n += 1
        data = {"name": name,
                "person": {"firm": "McKinsey", "email": "t@example.com", "status": "tracking"},
                "draft_subject": "Coffee chat?",
                "draft_body": "Hi,\n\nCould we talk {{HORIZON}}? Times that work:\n{{SLOTS}}\n\nThanks,\nAashish\n",
                "offered_slots": [{"start": s.isoformat(), "end": e.isoformat()} for s, e in slots]}
        with open(os.path.join(research.INBOX, "f%d.json" % self.n), "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        report = research.import_inbox()
        self.assertFalse([r for r in report if r.get("error")], report)

    def person(self, name=NAME):
        return [p for p in db.list_people() if p["name"] == name][0]

    def sync(self, person_id=None):
        return server.pull_from_calendar(db.get_settings(), person_id)

    def saved(self, name=NAME):
        return sorted((s, e, h) for s, e, h in server._offered_slots(self.person(name)))

    def call(self, path, body=None):
        req = urllib.request.Request(
            "http://127.0.0.1:%d%s" % (self.port, path),
            data=json.dumps(body if body is not None else {}).encode(),
            headers={"X-CCT-Token": server.TOKEN, "Content-Type": "application/json"},
            method="POST")
        try:
            with urllib.request.urlopen(req) as res:
                return res.status, json.loads(res.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    # -- tests ---------------------------------------------------------------
    def test_import_only_proposes_and_email_cannot_open_yet(self):
        slots = [win(2, 10), win(3, 11), win(4, 14)]
        self.drop(slots)
        self.assertEqual(self.cal.holds(), [])                 # nothing written yet
        self.assertEqual([h for _, _, h in self.saved()], [False] * 3)
        pid = self.person()["id"]
        code, res = self.call("/api/draft", {"person_id": pid, "kind": "outreach",
                                             "open_in_outlook": True,
                                             "subject": "x", "body": "y"})
        self.assertEqual(code, 409)
        self.assertEqual(self.drafts, [])

    def test_first_sync_writes_holds_and_is_idempotent(self):
        slots = [win(2, 10), win(3, 11), win(4, 14)]
        self.drop(slots)
        res = self.sync(self.person()["id"])
        kinds = [c["kind"] for c in res["changes"]]
        self.assertIn("slots_added", kinds)
        held = self.cal.holds()
        self.assertEqual(len(held), 3)
        for (s, e), (ws, we) in zip(held, sorted(slots)):
            self.assertTrue(near(s, ws) and near(e, we))
        self.assertTrue(all(h for _, _, h in self.saved()))
        writes = self.cal.writes
        self.assertEqual(self.sync()["changes"], [])            # second click: nothing to do
        self.assertEqual(self.cal.writes, writes)

    def test_edits_in_calendar_flow_back_into_the_email(self):
        a, b, c = win(2, 10), win(3, 11), win(4, 14)
        self.drop([a, b, c])
        self.sync()
        b2, d = win(3, 16), win(5, 9)
        self.cal.replace_holds([c, b2, d])                       # delete A, move B, add D
        res = self.sync()
        self.assertIn("slots", [x["kind"] for x in res["changes"]])
        got = [(s, e) for s, e, h in self.saved()]
        want = sorted([c, b2, d])
        self.assertEqual(len(got), 3)
        for (s, e), (ws, we) in zip(got, want):
            self.assertTrue(near(s, ws) and near(e, we))
        self.assertTrue(all(h for _, _, h in self.saved()))
        pid = self.person()["id"]
        code, draft = self.call("/api/draft", {"person_id": pid, "kind": "outreach"})
        self.assertEqual(code, 200)
        lines = server.stored_slot_lines(self.person())
        self.assertEqual(len(lines), 3)
        for line in lines:
            self.assertIn(line, draft["body"])
        old_a = availability.format_slot_lines(server._days_from_windows([a], TZ), "ET")[0]
        self.assertNotIn(old_a, draft["body"])

    def test_open_in_outlook_marks_sent_and_attaches_master_resume(self):
        self.drop([win(2, 10), win(3, 11), win(4, 14)])
        pid = self.person()["id"]
        self.sync(pid)
        code, draft = self.call("/api/draft", {"person_id": pid, "kind": "outreach"})
        self.assertEqual(draft["unfilled"], [])
        code, res = self.call("/api/draft", {"person_id": pid, "kind": "outreach",
                                             "subject": draft["subject"], "body": draft["body"],
                                             "open_in_outlook": True})
        self.assertEqual(code, 200, res)
        self.assertTrue(res["drafted"])
        self.assertEqual(len(self.drafts), 1)
        attachment = self.drafts[0][4]
        self.assertEqual(os.path.basename(attachment), "Aashish_Balivada_Resume.pdf")
        self.assertTrue(attachment.startswith(server.MASTER_RESUME_DIR))
        self.assertEqual(self.person()["status"], "outreach_sent")
        self.assertEqual(len(db.get_person(pid)["sent_mail"]), 1)

    def test_a_hold_deleted_after_it_was_written_stays_dropped(self):
        a, b, c = win(2, 10), win(3, 11), win(4, 14)
        self.drop([a, b, c])
        self.sync()
        self.cal.replace_holds([a, c])                           # you deleted B
        self.sync()
        self.assertEqual(len(self.cal.holds()), 2)               # not re-created
        self.assertEqual(len(self.saved()), 2)

    def test_slots_saved_before_this_change_count_as_held(self):
        a, b, c = win(2, 10), win(3, 11), win(4, 14)
        days = server._days_from_windows([(s, e) for s, e in (a, b, c)], TZ)   # no held flag
        lines = availability.format_slot_lines(days, "ET")
        pid = db.create_person({"name": NAME, "firm": "McKinsey", "status": "tracking",
                                "offered_slots": json.dumps({"lines": lines, "days": days})})
        self.cal.replace_holds([a, c])                           # B was deleted long ago
        self.sync()
        self.assertEqual(len(self.cal.holds()), 2)               # B is not resurrected
        self.assertEqual(len(self.saved()), 2)

    def test_a_failed_calendar_read_never_wipes_slots(self):
        self.drop([win(2, 10), win(3, 11), win(4, 14)])
        self.sync()
        self.cal.events = []                                     # a read that returns nothing at all
        self.assertEqual(self.sync()["changes"], [])
        self.assertEqual(len(self.saved()), 3)

    def test_deleting_every_hold_clears_the_slots(self):
        self.drop([win(2, 10), win(3, 11), win(4, 14)])
        self.sync()
        self.cal.replace_holds([])
        res = self.sync()
        self.assertIn("slots_cleared", [c["kind"] for c in res["changes"]])
        self.assertEqual(self.saved(), [])

    def test_a_new_batch_replaces_slots_and_removes_stale_holds(self):
        a, b, c = win(2, 10), win(3, 11), win(4, 14)
        self.drop([a, b, c])
        self.sync()
        e = win(6, 13)
        self.drop([c, e])                                        # Claude re-picks: keep C, add E
        holds = self.cal.holds()
        self.assertEqual(len(holds), 1)                          # A and B removed, C kept
        self.assertTrue(near(holds[0][0], c[0]))
        flags = {(s.date(), h) for s, _, h in self.saved()}
        self.assertEqual(flags, {(c[0].date(), True), (e[0].date(), False)})

    def test_sync_for_one_person_leaves_others_alone(self):
        self.drop([win(2, 10), win(3, 11), win(4, 14)], name="Other Person")
        self.drop([win(5, 10), win(6, 11), win(7, 14)], name=NAME)
        self.sync(self.person()["id"])
        self.assertEqual(len(self.cal.holds()), 3)
        self.assertEqual(self.cal.holds("Other Person"), [])
        self.assertEqual([h for _, _, h in self.saved("Other Person")], [False] * 3)

    def test_state_and_sync_endpoint(self):
        self.drop([win(2, 10), win(3, 11), win(4, 14)])
        pid = self.person()["id"]
        req = urllib.request.Request("http://127.0.0.1:%d/api/state" % self.port,
                                     headers={"X-CCT-Token": server.TOKEN})
        with urllib.request.urlopen(req) as res:
            state = json.loads(res.read())
        p = [x for x in state["people"] if x["id"] == pid][0]
        self.assertEqual(p["slots_pending"], 3)
        self.assertEqual(len(p["slots_lines"]), 3)
        self.assertTrue(state["resume"]["ok"])
        self.assertEqual(state["resume"]["name"], "Aashish_Balivada_Resume.pdf")
        self.assertIn("simple", state)
        code, res = self.call("/api/calendar/sync", {"person_id": pid})
        self.assertEqual(code, 200)
        self.assertTrue(res["ok"])
        self.assertEqual(len(self.cal.holds()), 3)

    def test_snapshot_copies_the_database_and_counts_every_table(self):
        self.drop([win(2, 10), win(3, 11), win(4, 14)])
        folder = db.snapshot_visible("unit")
        self.assertTrue(folder and os.path.isfile(os.path.join(folder, "tracker.sqlite3")))
        with open(os.path.join(folder, "counts.json")) as fh:
            counts = json.load(fh)["counts"]
        self.assertEqual(counts, db.table_counts())
        self.assertEqual(counts["person"], 1)
        self.assertIsNone(db.snapshot_visible("unit"))           # once per tag


if __name__ == "__main__":
    unittest.main()
