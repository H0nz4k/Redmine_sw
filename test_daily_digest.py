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
                              if "/issues/42" in line]), 3)
        self.assertEqual(stat.S_IMODE((digest.REPORT_DIR / "2026-11-13.md").stat().st_mode), 0o600)
        with self.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM digest_event_ids").fetchone()[0], 2)

    def test_narrative_reads_description_and_journal_notes(self):
        journal = [
            {"id": 10, "created_on": "2026-11-13T14:00:00Z",
             "user": {"name": "Jarda"}, "details": [],
             "notes": "Terminál přestal načítat čipy strávníků."},
            {"id": 11, "created_on": "2026-11-13T15:00:00Z",
             "user": {"name": "Petr"}, "details": [],
             "notes": "Zkontroloval kabel a připojení; oprava pokračuje."},
            {"id": 12, "created_on": "2026-11-14T15:00:00Z",
             "user": {"name": "Petr"}, "details": [],
             "notes": "Vyměněna vadná deska, dokončeno až další den."},
        ]
        item = self.issue(44, "2026-11-13T12:00:00Z",
                          "2026-11-14T15:00:00Z", journals=journal)
        self.details[44]["description"] = (
            "Na škole nelze načíst čipy při výdeji obědů. "
            "Terminál zobrazuje chybu spojení."
        )
        result = self.generate("2026-11-13T16:30:00+00:00")
        self.assertEqual(result["event_count"], 3)
        report = digest.read_report(self.connect, "2026-11-13")
        story = report.split("## Co se skutečně řešilo")[1].split("## Co přibylo")[0]
        self.assertIn("Na škole nelze načíst čipy", story)
        self.assertIn("Terminál přestal načítat čipy", story)
        self.assertIn("Jarda", story)
        self.assertIn("Zkontroloval kabel", story)
        self.assertIn("Petr", story)
        self.assertIn("/issues/44", story)
        self.assertNotIn("Vyměněna vadná deska", story)
        self.assertNotIn("hotovo", story.lower())

    def test_repeated_changes_same_issue_have_single_narrative_paragraph(self):
        changes = [
            {"id": 21, "created_on": "2026-11-13T14:00:00Z",
             "user": {"name": "Jarda"}, "details": [], "notes": "Ověřujeme spojení."},
            {"id": 22, "created_on": "2026-11-13T15:00:00Z",
             "user": {"name": "Petr"}, "details": [], "notes": "Zatím otevřeno."},
        ]
        self.issue(45, "2026-11-13T10:00:00Z", "2026-11-13T15:00:00Z", journals=changes)
        report = digest.read_report(self.connect, self.generate("2026-11-13T16:30:00+00:00")["day"])
        story = report.split("## Co se skutečně řešilo")[1].split("## Co přibylo")[0]
        self.assertEqual(story.count("/issues/45"), 1)
        self.assertIn("Zatím otevřeno", story)

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

    def test_missed_days_are_generated_separately_without_duplicates(self):
        # Start with a successful report at 17:30 Prague on Friday.
        self.issue(40, "2026-11-13T12:00:00Z", "2026-11-13T14:00:00Z")
        self.generate("2026-11-13T16:30:00+00:00")
        self.items.clear()
        self.issue(41, "2026-11-14T10:00:00Z", "2026-11-14T10:00:00Z")
        self.issue(42, "2026-11-15T10:00:00Z", "2026-11-15T10:00:00Z")
        self.issue(43, "2026-11-16T10:00:00Z", "2026-11-16T10:00:00Z")
        after_outage = datetime(2026, 11, 16, 17, 0, tzinfo=timezone.utc)
        planned = digest.pending_cutoffs(self.connect, after_outage)
        self.assertEqual([x.date().isoformat() for x in planned],
                         ["2026-11-14", "2026-11-15", "2026-11-16"])
        results = digest.generate_missed_reports(
            self.connect, self.issues, self.request,
            "https://redmine.example.test", now=after_outage)
        self.assertEqual([x["day"] for x in results],
                         ["2026-11-14", "2026-11-15", "2026-11-16"])
        for day, iid in (("2026-11-14", 41), ("2026-11-15", 42), ("2026-11-16", 43)):
            report = digest.read_report(self.connect, day)
            self.assertIn(f"/issues/{iid}", report)
            for other in ({41, 42, 43} - {iid}):
                self.assertNotIn(f"/issues/{other}", report)
        self.assertEqual(digest.generate_missed_reports(
            self.connect, self.issues, self.request,
            "https://redmine.example.test", now=after_outage), [])
        self.assertEqual(len(digest.history(self.connect)), 4)

    def test_dst_transition_preserves_local_schedule(self):
        # Prague ends daylight saving on 25 October 2026.
        with self.connect() as db:
            digest._schema(db)
            db.execute(
                "INSERT INTO digest_reports VALUES (?,?,?,?,?)",
                ("2026-10-24", "2026-10-23T15:30:00Z",
                 "2026-10-24T15:30:00Z", "unused", 0))
        cutoffs = digest.pending_cutoffs(
            self.connect, datetime(2026, 10, 25, 17, 0, tzinfo=timezone.utc))
        self.assertEqual(len(cutoffs), 1)
        self.assertEqual(cutoffs[0].isoformat(), "2026-10-25T16:30:00+00:00")
        with self.connect() as db:
            last = db.execute("SELECT end_utc FROM digest_reports").fetchone()[0]
        self.assertEqual((cutoffs[0] - digest._utc(last)).total_seconds(), 25 * 3600)

    def test_manual_report_is_asynchronous_and_single_flight(self):
        from threading import Event
        started, released, completed = Event(), Event(), Event()

        def slow_generate(*args, **kwargs):
            started.set()
            try:
                self.assertTrue(released.wait(3))
                return {"day": "2026-11-13", "event_count": 3}
            finally:
                completed.set()

        with patch.object(digest, "generate", side_effect=slow_generate):
            first = digest.launch_manual_report(
                self.connect, self.issues, self.request, "https://redmine.example.test")
            self.assertTrue(first["accepted"])
            self.assertTrue(started.wait(2))
            self.assertEqual(digest.manual_job_status()["state"], "running")
            again = digest.launch_manual_report(
                self.connect, self.issues, self.request, "https://redmine.example.test")
            self.assertFalse(again["accepted"])
            released.set()
            self.assertTrue(completed.wait(2))
        # Thread updates its status immediately after returning from slow_generate.
        from time import sleep
        for _ in range(100):
            if digest.manual_job_status()["state"] == "done":
                break
            sleep(0.01)
        self.assertEqual(digest.manual_job_status()["state"], "done")
        self.assertEqual(digest.manual_job_status()["result"]["event_count"], 3)

    def test_henk_json_keeps_full_discussion_private_and_separate(self):
        import json

        long_description = "Chyba na terminálu. " + ("Podrobnosti výpadku čtečky. " * 36) + "POSLEDNI_VETA_ZADANI"
        old_comment = "Starší kontext: první pokus před dneškem."
        today_comment = "Dnes Jarda zjistil potíže s ověřením DKIM. " + ("Detaily diagnostiky. " * 32) + "POSLEDNI_VETA_KOMENTARE"
        tomorrow_comment = "Zítřejší zpráva, která do dnešního exportu nepatří."
        journal = [
            {"id": 8, "created_on": "2026-11-12T11:00:00Z",
             "user": {"name": "Jarda"}, "details": [],
             "notes": old_comment},
            {"id": 9, "created_on": "2026-11-13T14:00:00Z",
             "user": {"name": "Jarda"}, "details": [],
             "notes": today_comment},
            {"id": 10, "created_on": "2026-11-14T09:00:00Z",
             "user": {"name": "Petr"}, "details": [],
             "notes": tomorrow_comment},
        ]
        self.issue(91, "2026-11-12T10:00:00Z", "2026-11-14T09:00:00Z", journals=journal)
        self.details[91]["description"] = long_description
        self.generate("2026-11-13T16:30:00+00:00")

        source_dir = digest.REPORT_DIR / "henk-input"
        path = source_dir / "2026-11-13.json"
        self.assertTrue(path.is_file())
        self.assertEqual(stat.S_IMODE(source_dir.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        source = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(source["purpose"], "local_henk_digest_input_only")
        self.assertEqual(source["issues"][0]["description"], long_description)
        self.assertEqual(
            [j["notes"] for j in source["issues"][0]["journals"]],
            [old_comment, today_comment],
        )
        self.assertEqual(source["report_day"], "2026-11-13")
        report = digest.read_report(self.connect, "2026-11-13")
        self.assertNotIn("POSLEDNI_VETA_ZADANI", report)
        self.assertNotIn("POSLEDNI_VETA_KOMENTARE", report)
        self.assertNotIn(tomorrow_comment, report)
        self.assertNotIn("henk-input", report)

    def test_access_is_restricted_to_known_archive_dates(self):
        with self.assertRaisesRegex(ValueError, "Neplatné datum"):
            digest.read_report(self.connect, "../secrets")
        with self.assertRaisesRegex(ValueError, "není dostupný"):
            digest.read_report(self.connect, "2026-11-13")


if __name__ == "__main__":
    unittest.main()
