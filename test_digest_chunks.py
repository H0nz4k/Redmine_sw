"""Offline regression tests for private evidence chunking and resumption."""
import json
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

import digest_chunks


class EvidenceChunksTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = str(Path(self.tmp.name) / "private.sqlite")
        self.payload = {
            "schema_version": 1, "purpose": "local_henk_digest_input_only",
            "period_start_utc": "2026-11-13T00:00:00Z", "period_end_utc": "2026-11-13T16:30:00Z",
            "issues": [{"id": 5, "updated_on": "2026-11-13T15:00:00Z",
                        "created_on": "2026-11-12T10:00:00Z", "subject": "Tiskárna",
                        "author": {"name": "Jana"}, "project": {"id": 4, "name": "Servis"},
                        "status": {"id": 5, "name": "Vyřešený"},
                        "description": "Žlutý kůň. " * 300,
                        "journals": [
                            {"id": 2, "created_on": "2026-11-13T14:00:00Z", "author": {"name": "Eva"},
                             "notes": "Tisk se podařil.", "details": [{"name": "status_id", "old_value": "1", "new_value": "5"}]},
                            {"id": 1, "created_on": "2026-11-13T12:00:00Z", "author": {"name": "Petr"},
                             "notes": "Vyměnil jsem kabel.", "details": []}]}]}

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.db)
        try:
            with db:
                yield db
        finally:
            db.close()

    def test_long_utf8_sources_are_split_without_silent_loss(self):
        chunks, warnings = digest_chunks.prepare(self.payload, limit=80)
        descriptions = [c for c in chunks if c["field"] == "description"]
        self.assertGreater(len(descriptions), 2)
        self.assertEqual("".join(c["text"] for c in descriptions), self.payload["issues"][0]["description"])
        self.assertTrue(all(len(c["text"].encode("utf-8")) <= 80 for c in chunks))
        self.assertEqual([c["part"] for c in descriptions], list(range(1, len(descriptions) + 1)))
        self.assertEqual(warnings, [])

    def test_authors_timeline_and_raw_status_details_are_retained(self):
        chunks, _ = digest_chunks.prepare(self.payload)
        self.assertEqual(chunks[0]["author"], "Jana")
        self.assertEqual(chunks[0]["status_snapshot"]["name"], "Vyřešený")
        journals = [c for c in chunks if c["source_id"].startswith("journal:")]
        self.assertEqual([c["source_id"] for c in journals], ["journal:5:1", "journal:5:2", "journal:5:2"])
        self.assertEqual([c["author"] for c in journals], ["Petr", "Eva", "Eva"])
        self.assertEqual(json.loads(journals[-1]["text"])["new_value"], "5")
        self.assertTrue(all(c["in_period"] for c in journals))

    def test_future_snapshot_is_explicitly_omitted_and_future_journal_rejected(self):
        self.payload["issues"][0]["updated_on"] = "2026-11-14T08:00:00Z"
        chunks, warnings = digest_chunks.prepare(self.payload)
        self.assertFalse(any(c["source_id"] == "issue:5" for c in chunks))
        self.assertEqual(warnings[0]["issue_id"], 5)
        self.payload["issues"][0]["journals"][0]["created_on"] = "2026-11-14T08:00:00Z"
        with self.assertRaisesRegex(ValueError, "po uzávěrce"):
            digest_chunks.prepare(self.payload)

    def test_retry_reuses_completed_parts_and_invalidates_changed_inputs(self):
        chunks, _ = digest_chunks.prepare(self.payload)
        chunks = chunks[:3]
        calls = []
        def infer(chunk):
            calls.append(chunk["text"])
            if len(calls) == 3:
                raise OSError("synthetic outage")
            return [0]
        def validate(chunk, selection):
            self.assertEqual(selection, [0])
        with self.assertRaises(OSError):
            digest_chunks.process(chunks, self.connect, "model-sha", "prompt-v1", infer, validate)
        self.assertEqual(len(calls), 3)
        resumed = []
        results = digest_chunks.process(chunks, self.connect, "model-sha", "prompt-v1",
                                        lambda chunk: resumed.append(chunk["text"]) or [0], validate)
        self.assertEqual(results, [[0], [0], [0]])
        self.assertEqual(resumed, [chunks[2]["text"]])
        changed = [dict(item) for item in chunks]
        changed[1]["text"] += " Změna zdroje."
        digest_chunks.process(changed, self.connect, "model-sha", "prompt-v1",
                              lambda chunk: resumed.append(chunk["text"]) or [0], validate)
        self.assertEqual(resumed[-1], changed[1]["text"])
        self.assertEqual(len(resumed), 2)
        digest_chunks.process(chunks, self.connect, "changed-model", "prompt-v1",
                              lambda chunk: resumed.append(chunk["text"]) or [0], validate)
        self.assertEqual(len(resumed), 5)

    def test_unvalidated_or_text_results_are_never_cached(self):
        chunk = {"source_id": "issue:5", "text": "Synthetic", "part": 1, "parts": 1}
        with self.assertRaises(ValueError):
            digest_chunks.process([chunk], self.connect, "model", "prompt", lambda _: ["synthetic text"], lambda *_: None)
        with self.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM digest_chunk_cache").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
