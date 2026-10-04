"""Inbox files that Locked In sends back: person status and follow-up ticks.

Run from the repo root:  python3 -m unittest discover app/tests
Uses a throwaway HOME, so the real database is never touched.
"""

import datetime as dt
import json
import os
import sys
import tempfile
import unittest

HOME = tempfile.mkdtemp()
os.environ["HOME"] = HOME
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db  # noqa: E402
import research  # noqa: E402
import server  # noqa: E402  (registers the research hooks)


class ImportTest(unittest.TestCase):

    def setUp(self):
        if os.path.exists(db.db_path()):
            os.remove(db.db_path())
        db.init()
        self.root = tempfile.mkdtemp(dir=HOME)
        research.ROOT = self.root
        research.INBOX = os.path.join(self.root, "inbox")
        research.DONE = os.path.join(self.root, "imported")
        os.makedirs(research.INBOX)

    def drop(self, name, payload):
        with open(os.path.join(research.INBOX, name), "w", encoding="utf-8") as fh:
            json.dump(payload, fh)

    def run_import(self):
        report = research.import_inbox()
        self.assertEqual(len(report), 1)
        return report[0]

    # ------------------------------------------------------------ status

    def test_status_thankyou_sets_timestamp(self):
        pid = db.create_person({"name": "Jane Doe", "status": "chat_done"})
        self.drop("jane.json", {"name": "Jane Doe", "require_existing": True,
                                "person": {"status": "thankyou_sent"}})
        result = self.run_import()
        self.assertNotIn("error", result)
        person = db.get_person(pid)
        self.assertEqual(person["status"], "thankyou_sent")
        self.assertTrue(person["thankyou_sent_at"])

    def test_status_thankyou_keeps_existing_timestamp(self):
        pid = db.create_person({"name": "Jane Doe", "status": "thankyou_sent",
                                "thankyou_sent_at": "2026-09-01T10:00:00-04:00"})
        self.drop("jane.json", {"name": "Jane Doe", "require_existing": True,
                                "person": {"status": "thankyou_sent"}})
        self.run_import()
        self.assertEqual(db.get_person(pid)["thankyou_sent_at"],
                         "2026-09-01T10:00:00-04:00")

    def test_other_status_leaves_thankyou_alone(self):
        pid = db.create_person({"name": "Jane Doe", "status": "outreach_sent"})
        self.drop("jane.json", {"name": "Jane Doe", "require_existing": True,
                                "person": {"status": "scheduled"}})
        self.run_import()
        person = db.get_person(pid)
        self.assertEqual(person["status"], "scheduled")
        self.assertFalse(person["thankyou_sent_at"])

    def test_unknown_status_rejected(self):
        pid = db.create_person({"name": "Jane Doe", "status": "chat_done"})
        self.drop("jane.json", {"name": "Jane Doe", "require_existing": True,
                                "person": {"status": "offer"}})
        result = self.run_import()
        self.assertIn("unknown status", result["error"])
        self.assertEqual(db.get_person(pid)["status"], "chat_done")
        self.assertTrue(os.path.exists(os.path.join(research.INBOX, "jane.json")))

    def test_unknown_status_creates_no_one(self):
        self.drop("new.json", {"name": "New Person",
                               "person": {"status": "offer"}})
        self.assertIn("unknown status", self.run_import()["error"])
        self.assertEqual(db.list_people(include_archived=True), [])

    # --------------------------------------------------------- follow-ups

    def thankyou_owed(self):
        chat = (dt.datetime.now().astimezone() - dt.timedelta(hours=3)).isoformat()
        pid = db.create_person({"name": "Jane Doe", "status": "chat_done",
                                "chat_at": chat})
        [action] = [a for a in server.open_actions() if a["person_id"] == pid]
        return pid, action

    def test_followup_done_ticks_without_changing_text(self):
        pid, action = self.thankyou_owed()
        self.drop("f.json", {"type": "followups",
                             "items": [{"key": action["key"], "done": True,
                                        "label": "something else"}]})
        result = self.run_import()
        self.assertEqual(result["done"], [action["key"]])
        self.assertIn(action["key"], db.resolved_keys())
        conn = db.connect()
        try:
            row = conn.execute("SELECT label, detail FROM resolved_action "
                               "WHERE key=?", (action["key"],)).fetchone()
        finally:
            conn.close()
        self.assertEqual(row["label"], action["label"])
        self.assertEqual(row["detail"], action["detail"])
        # Same as ticking it off in the app: the thank-you went out.
        self.assertEqual(db.get_person(pid)["status"], "thankyou_sent")

    def test_followup_reimport_is_unchanged(self):
        _, action = self.thankyou_owed()
        for _ in range(2):
            self.drop("f.json", {"type": "followups",
                                 "items": [{"key": action["key"]}]})
            result = self.run_import()
        self.assertEqual(result["done"], [])
        self.assertEqual(result["unchanged"], [action["key"]])

    def test_followup_undone_restores(self):
        pid, action = self.thankyou_owed()
        server.tick_action(action)
        self.drop("f.json", {"type": "followups",
                             "items": [{"key": action["key"], "done": False}]})
        result = self.run_import()
        self.assertEqual(result["reopened"], [action["key"]])
        self.assertNotIn(action["key"], db.resolved_keys())
        self.assertEqual(db.get_person(pid)["status"], "chat_done")

    def test_followup_unknown_key_reported(self):
        self.drop("f.json", {"type": "followups",
                             "items": [{"key": "thankyou:999:nope"}]})
        result = self.run_import()
        self.assertEqual(result["not_found"], ["thankyou:999:nope"])

    def test_followup_missing_key_is_an_error(self):
        self.drop("f.json", {"type": "followups", "items": [{"done": True}]})
        self.assertIn("needs a key", self.run_import()["error"])

    def test_followup_ticked_by_its_own_key(self):
        db.upsert_followup("mck-apply", "Apply to McKinsey", None, "McKinsey", "")
        self.drop("f.json", {"type": "followups", "items": [{"key": "mck-apply"}]})
        result = self.run_import()
        self.assertEqual(result["done"], ["mck-apply"])
        self.assertIn("todo:mck-apply", db.resolved_keys())
        research.write_snapshots()
        with open(os.path.join(self.root, "followups.json"), encoding="utf-8") as fh:
            [item] = json.load(fh)["followups"]
        self.assertTrue(item["done"])
        self.assertEqual(item["text"], "Apply to McKinsey")

    def test_people_snapshot_carries_nudge_fields(self):
        db.create_person({"name": "Jane Doe", "status": "outreach_sent",
                          "last_outbound_at": "2026-09-20T09:00:00-04:00",
                          "followups_sent": 1})
        research.write_snapshot()
        with open(os.path.join(self.root, "people.json"), encoding="utf-8") as fh:
            [row] = json.load(fh)["people"]
        self.assertEqual(row["last_outbound_at"], "2026-09-20T09:00:00-04:00")
        self.assertEqual(row["followups_sent"], 1)
        self.assertIn("last_inbound_at", row)

    def test_actions_snapshot_written(self):
        _, action = self.thankyou_owed()
        research.write_snapshots()
        with open(os.path.join(self.root, "actions.json"), encoding="utf-8") as fh:
            keys = [a["key"] for a in json.load(fh)["actions"]]
        self.assertIn(action["key"], keys)


if __name__ == "__main__":
    unittest.main()
