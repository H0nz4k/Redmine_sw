import os
import sqlite3
import stat
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import daily_digest as digest


class DigestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.database = os.path.join(self.tmp.name, "digest.sqlite")
        self.directory = patch.object(digest, "REPORT_DIR", Path(self.tmp.name) / "private-reports")
        self.directory.start()
        self.addCleanup(self.directory.stop)
        self.projects = [{"id": 1, "name": "Servis"}]
        self.items = []
        self.details = {}
        self.calls = []

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.database)
        try:
            with db:
                yield db
        finally:
            db.close()

    def issues(self, params):
        self.assertEqual(params["status_id"], "*")
        start = digest._utc(params["updated_on"][2:])
        return iter(i for i in self.items if digest._utc(i["updated_on"]) >= start)

    def request(self, path, params):
        self.calls.append((path, params))
        if path == "/projects.json":
            off = params["offset"]
            return {"projects": self.projects[off:off + 100], "total_count": len(self.projects)}
        return {"issue": self.details[int(path.split("/")[2].split(".")[0])]}

    def issue(self, iid, created, updated, journals=None, status="Nový", status_id=1):
        item = {"id": iid, "subject": "Servis tiskárny", "project": {"id": 1, "name": "Servis"},
                "author": {"name": "Eva"}, "created_on": created, "updated_on": updated,
                "status": {"id": status_id, "name": status}}
        self.items.append(item)
        self.details[iid] = dict(item, journals=journals or [])
        return item

    def generate(self, now):
        return digest.generate(self.connect, self.issues, self.request,
                               "https://redmine.example.test", datetime.fromisoformat(now))

    def test_daily_archive_and_manual_regeneration_are_idempotent(self):
        journal = [{"id": 11, "created_on": "2026-11-13T16:00:00Z",
                    "user": {"name": "Petr"},
                    "details": [{"name": "status_id", "new_value": "5"}], "notes": ""}]
        self.issue(42, "2026-11-13T13:00:00Z", "2026-11-13T16:00:00Z",
                   journals=journal, status="Vyřešený", status_id=5)
        result = self.generate("2026-11-13T16:30:00+00:00")
        self.assertEqual(result["event_count"], 2)
        text = digest.read_report(self.connect, "2026-11-13")
        self.assertIn("Eva", text)
        self.assertIn("Petr", text)
        self.assertIn("https://redmine.example.test/issues/42", text)
        self.assertNotIn("Nové projekty", text)  # first run creates baseline
        self.assertEqual(self.generate("2026-11-13T16:35:00+00:00")["event_count"], 2)
        self.assertEqual(len(digest.history(self.connect)), 1)
        self.assertEqual(len([line for line in digest.read_report(self.connect, "2026-11-13").splitlines()
                              if "/issues/42" in line]), 2)
        self.assertEqual(stat.S_IMODE((digest.REPORT_DIR / "2026-11-13.md").stat().st_mode), 0o600)
        with self.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM digest_event_ids").fetchone()[0], 2)

    def test_next_day_includes_changes_after_previous_report(self):
        self.issue(42, "2026-11-13T12:00:00Z", "2026-11-13T14:00:00Z")
        self.generate("2026-11-13T16:30:00+00:00")
        self.items.clear()
        self.issue(43, "2026-11-13T18:00:00Z", "2026-11-13T18:00:00Z")
        self.projects.append({"id": 2, "name": "Nový projekt"})
        later = self.generate("2026-11-14T16:30:00+00:00")
        self.assertEqual(later["event_count"], 2)
        report = digest.read_report(self.connect, "2026-11-14")
        self.assertIn("Nový projekt", report)
        self.assertIn("/issues/43", report)
        self.assertEqual(len(digest.history(self.connect)), 2)

    def test_missing_journals_fails_without_marking_completion(self):
        self.issue(42, "2026-11-13T12:00:00Z", "2026-11-13T14:00:00Z")
        self.details[42].pop("journals")
        with self.assertRaisesRegex(RuntimeError, "historii"):
            self.generate("2026-11-13T16:30:00+00:00")
        self.assertEqual(digest.history(self.connect), [])
        self.assertFalse((digest.REPORT_DIR / "2026-11-13.md").exists())

    def test_time_is_configurable_and_persistent(self):
        now = datetime(2026, 11, 13, 16, 45, tzinfo=timezone.utc)
        settings = digest.get_settings(self.connect, now)
        self.assertEqual(settings["time"], "17:30")
        self.assertFalse(digest.due(self.connect, datetime(2026, 11, 13, 15, 0, tzinfo=timezone.utc)))
        digest.set_time(self.connect, "18:15")
        self.assertEqual(digest.get_settings(self.connect, now)["time"], "18:15")
        self.assertTrue(digest.due(self.connect, datetime(2026, 11, 13, 17, 15, tzinfo=timezone.utc)))
        for invalid in ("24:00", "17:99", "17:30\n", "abc", None):
            with self.assertRaises(ValueError):
                digest.set_time(self.connect, invalid)

    def test_access_is_restricted_to_known_archive_dates(self):
        with self.assertRaisesRegex(ValueError, "Neplatné datum"):
            digest.read_report(self.connect, "../secrets")
        with self.assertRaisesRegex(ValueError, "není dostupný"):
            digest.read_report(self.connect, "2026-11-13")


if __name__ == "__main__":
    unittest.main()
