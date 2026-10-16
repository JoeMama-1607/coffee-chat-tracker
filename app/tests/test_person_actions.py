"""Actions queued from Locked In: confirm / reschedule / cancel, status, notes,
add person with a LinkedIn PDF, and the richer people.json.

Run from the repo root:  python3 -B -m unittest discover app/tests
"""
import datetime as dt
import json
import os
import sys
import tempfile
import unittest

from test_sync_slots import (FakeCalendar, NAME, TZ, HOLD, HOME, db, macos,
                             research, server, win, near)


class ActionCalendar(FakeCalendar):
    """FakeCalendar plus the chat-event upsert the real calendar does."""

    def sync(self, delete=None, upsert=None, ensure=None):
        res = FakeCalendar.sync(self, delete, upsert, ensure)
        if upsert:
            old = upsert.get("match")
            created = updated = 0
            if old and old[0]:
                for i, ev in enumerate(self.events):
                    if ev[0].startswith(upsert["prefix"]) and near(ev[1], old[0]):
                        self.events[i] = (upsert["title"], upsert["start"], upsert["end"])
                        updated = 1
                        break
            if not updated:
                self.events.append((upsert["title"], upsert["start"], upsert["end"]))
                created = 1
            res = dict(res, created=created, updated=updated)
        return res

    def chats(self):
        return [ev for ev in self.events if ev[0].startswith("Coffee chat — ")]


class ActionTest(unittest.TestCase):
    def setUp(self):
        self._saved = (macos.read_calendar, macos.calendar_sync, server.pdfreader.extract_text)
        if os.path.exists(db.db_path()):
            os.remove(db.db_path())
        db.init()
        self.root = tempfile.mkdtemp(dir=HOME)
        research.ROOT = self.root
        research.INBOX = os.path.join(self.root, "inbox")
        research.DONE = os.path.join(self.root, "imported")
        os.makedirs(research.INBOX)
        self.cal = ActionCalendar()
        macos.read_calendar = self.cal.read
        macos.calendar_sync = self.cal.sync
        self.n = 0
        self.pid = db.create_person({"name": NAME, "firm": "McKinsey", "email": "t@x.com",
                                     "status": "outreach_sent"})

    def tearDown(self):
        macos.read_calendar, macos.calendar_sync, server.pdfreader.extract_text = self._saved

    def drop(self, data):
        self.n += 1
        with open(os.path.join(research.INBOX, "a%d.json" % self.n), "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        return research.import_inbox()

    def act(self, action, **kw):
        rep = self.drop(dict({"type": "person_action", "action": action,
                              "person_id": self.pid}, **kw))
        self.assertFalse([r for r in rep if r.get("error")], rep)
        return rep[0]

    def person(self):
        return db.get_person(self.pid)

    def test_confirm_slot_replaces_holds_and_schedules(self):
        a, b, c = win(2, 10), win(3, 11), win(4, 14)
        db.update_person(self.pid, {"offered_slots": json.dumps(
            {"days": server._days_from_windows([(*a, True), (*b, True), (*c, True)], TZ)})})
        self.cal.replace_holds([a, b, c])
        self.act("confirm_slot", start=b[0].isoformat(), end=b[1].isoformat())
        self.assertEqual(self.cal.holds(), [])                  # all three holds removed
        chats = self.cal.chats()
        self.assertEqual(len(chats), 1)
        self.assertTrue(near(chats[0][1], b[0]))
        p = self.person()
        self.assertEqual(p["status"], "scheduled")
        self.assertTrue(p["chat_at"].startswith(b[0].astimezone(TZ).strftime("%Y-%m-%dT%H:%M")))
        self.assertFalse(p["offered_slots"])

    def test_reschedule_moves_the_chat_and_cancel_removes_it(self):
        a, b = win(2, 10), win(3, 15)
        self.act("confirm_slot", start=a[0].isoformat(), end=a[1].isoformat())
        self.act("reschedule", start=b[0].isoformat(), end=b[1].isoformat())
        chats = self.cal.chats()
        self.assertEqual(len(chats), 1)
        self.assertTrue(near(chats[0][1], b[0]))
        self.act("cancel_chat")
        self.assertEqual(self.cal.chats(), [])
        p = self.person()
        self.assertFalse(p["chat_at"])
        self.assertEqual(p["status"], "outreach_sent")

    def test_calendar_failure_changes_nothing_and_keeps_the_file(self):
        macos.calendar_sync = lambda **k: {"ok": False, "error": "calendar locked"}
        a = win(2, 10)
        rep = self.drop({"type": "person_action", "action": "confirm_slot",
                         "person_id": self.pid, "start": a[0].isoformat(),
                         "end": a[1].isoformat()})
        self.assertTrue(rep[0].get("error"))
        self.assertEqual(self.person()["status"], "outreach_sent")
        self.assertEqual(os.listdir(research.INBOX), ["a1.json"])   # retries next time

    def test_status_note_archive_and_errors(self):
        self.act("set_status", status="thankyou_sent")
        p = self.person()
        self.assertEqual(p["status"], "thankyou_sent")
        self.assertTrue(p["thankyou_sent_at"])
        self.act("note", body="Met at the info session", kind="note")
        self.assertEqual(self.person()["notes"][0]["body"], "Met at the info session")
        rep = self.drop({"type": "person_action", "action": "set_status",
                         "person_id": self.pid, "status": "nonsense"})
        self.assertIn("unknown status", rep[0]["error"])
        os.remove(os.path.join(research.INBOX, "a3.json"))
        self.act("archive")
        self.assertTrue(self.person()["archived"])
        before = len(db.list_people(include_archived=True))
        rep = self.drop({"type": "person_action", "action": "note",
                         "name": "Nobody Here", "body": "x"})
        self.assertIn("no single person", rep[0]["error"])
        os.remove(os.path.join(research.INBOX, "a5.json"))
        self.assertEqual(len(db.list_people(include_archived=True)), before)

    def test_add_person_with_pdf_and_snapshot(self):
        pdf = os.path.join(self.root, "profiles")
        os.makedirs(pdf)
        with open(os.path.join(pdf, "jane-doe.pdf"), "wb") as fh:
            fh.write(b"%PDF-1.4 fake")
        # the text extractor is its own module; stub it so this tests the plumbing
        server.pdfreader.extract_text = lambda blob: "Jane Doe\nAssociate at Bain"
        rep = self.drop({"name": "Jane Doe", "person": {"firm": "Bain", "role": "Associate",
                                                        "status": "tracking"},
                         "profile_pdf_file": "profiles/jane-doe.pdf"})
        self.assertFalse([r for r in rep if r.get("error")], rep)
        jane = [p for p in db.list_people() if p["name"] == "Jane Doe"][0]
        self.assertEqual(jane["status"], "tracking")
        self.assertTrue(jane["profile_pdf"] and os.path.isfile(jane["profile_pdf"]))
        rep = self.drop({"name": "Jane Doe", "profile_pdf_file": "../../etc/passwd"})
        self.assertTrue(rep[0].get("error"))
        os.remove(os.path.join(research.INBOX, "a2.json"))
        with open(os.path.join(self.root, "people.json")) as fh:
            snap = json.load(fh)["people"]
        row = [p for p in snap if p["name"] == "Jane Doe"][0]
        for key in ("slots_state", "saved_windows", "has_thankyou", "notes", "first_contact_at"):
            self.assertIn(key, row)


if __name__ == "__main__":
    unittest.main()
