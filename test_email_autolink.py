import os
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import Mock

import email_autolink as auto


class EmailAutolinkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, 'test.sqlite')
        self.cutoff = auto.activate(self.connect, datetime(2026, 11, 18, 10, tzinfo=timezone.utc))
        self.now = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)
        self.issue = {'id': 21, 'created_on': '2026-11-18T10:05:00Z',
                      'updated_on': '2026-11-18T10:05:00Z', 'project': {'id': 12}}
        self.customer = {'id': 55, 'project': {'id': 1}, 'tracker': {'id': 4},
                         'custom_fields': [{'name': 'Email', 'value': 'jidelna@example.test'}]}
        self.catalog = [{'id': 55, 'name': 'Škola', 'contacts': ['jidelna@example.test']}]
        self.relations = []
        self.sender = Mock(return_value='jidelna@example.test')
        self.detail = Mock(side_effect=lambda iid: dict(self.issue) if iid == 21 else dict(self.customer))
        self.list_relations = Mock(side_effect=lambda iid: list(self.relations))
        self.links = Mock(return_value=[])
        self.write = Mock(side_effect=self._write)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        try:
            with db:
                yield db
        finally:
            db.close()

    def _write(self, path, method, payload):
        self.relations.append({'issue_id': 21, 'issue_to_id': payload['relation']['issue_to_id']})

    def run_process(self, issues=None):
        auto.process(self.connect, [self.issue] if issues is None else issues, self.catalog, self.cutoff,
                     self.sender, self.detail, self.list_relations, self.links, self.write, self.now)

    def test_single_exact_email_links_once_and_verifies_relation(self):
        self.run_process()
        self.run_process()
        self.write.assert_called_once_with('/issues/21/relations.json', 'POST',
                                           {'relation': {'issue_to_id': 55, 'relation_type': 'relates'}})
        self.assertEqual(auto.statuses(self.connect)[21], 'linked')
        self.assertEqual(auto.activate(self.connect, self.now), self.cutoff)

    def test_existing_and_future_or_non_helpdesk_requests_are_never_processed(self):
        old = dict(self.issue, id=1, created_on='2026-11-18T09:00:00Z')
        future = dict(self.issue, id=2, created_on='2026-11-18T13:00:00Z')
        other = dict(self.issue, id=3, project={'id': 90})
        self.run_process([old, future, other])
        self.write.assert_not_called()
        self.assertEqual(auto.statuses(self.connect), {})

    def test_ambiguous_or_missing_sender_never_links(self):
        self.catalog.append({'id': 56, 'name': 'Jiná škola', 'contacts': ['jidelna@example.test']})
        self.run_process()
        self.assertEqual(auto.statuses(self.connect)[21], 'review')
        self.write.assert_not_called()

    def test_sender_with_multiple_addresses_never_links(self):
        self.sender.return_value = 'jidelna@example.test, other@example.test'
        self.run_process()
        self.assertEqual(auto.statuses(self.connect)[21], 'review')
        self.write.assert_not_called()

    def test_existing_customer_relation_is_not_changed(self):
        self.relations.append({'issue_id': 21, 'issue_to_id': 55})
        self.run_process()
        self.assertEqual(auto.statuses(self.connect)[21], 'already_linked')
        self.write.assert_not_called()

    def test_changed_issue_or_stale_customer_email_prevents_write(self):
        self.detail.side_effect = lambda iid: dict(self.issue, updated_on='2026-11-18T10:06:00Z') if iid == 21 else self.customer
        self.run_process()
        self.assertEqual(auto.statuses(self.connect)[21], 'review')
        self.write.assert_not_called()

    def test_stale_customer_email_prevents_write(self):
        self.customer['custom_fields'][0]['value'] = 'other@example.test'
        self.run_process()
        self.assertEqual(auto.statuses(self.connect)[21], 'review')
        self.write.assert_not_called()

    def test_changed_sender_or_missing_relations_prevents_write(self):
        self.sender.side_effect = ['jidelna@example.test', 'other@example.test']
        self.run_process()
        self.assertEqual(auto.statuses(self.connect)[21], 'review')
        self.write.assert_not_called()

    def test_unavailable_relation_list_prevents_write(self):
        self.list_relations.return_value = None
        self.list_relations.side_effect = None
        self.run_process()
        self.assertEqual(auto.statuses(self.connect)[21], 'review')
        self.write.assert_not_called()

    def test_unconfirmed_write_is_unknown_and_not_repeated(self):
        self.write.side_effect = None
        self.run_process()
        self.run_process()
        self.assertEqual(auto.statuses(self.connect)[21], 'unknown')
        self.write.assert_called_once()

    def test_scan_cursor_persists_without_changing_activation(self):
        self.assertEqual(auto.scan_start(self.connect, self.cutoff), self.cutoff)
        auto.mark_scanned(self.connect, self.now)
        self.assertEqual(auto.scan_start(self.connect, self.cutoff), self.now)
        self.assertEqual(auto.activate(self.connect, self.now), self.cutoff)

    def test_uncertain_write_is_not_retried(self):
        self.write.side_effect = OSError('network outcome unknown')
        self.run_process()
        self.run_process()
        self.assertEqual(auto.statuses(self.connect)[21], 'unknown')
        self.write.assert_called_once()

    def test_crash_after_claim_is_not_retried(self):
        with self.connect() as db:
            db.execute('INSERT INTO email_autolink_attempts VALUES (?,?,?,?)', (21, 'sending', 55, self.now.isoformat()))
        self.run_process()
        self.assertEqual(auto.statuses(self.connect)[21], 'sending')
        self.write.assert_not_called()


if __name__ == '__main__':
    unittest.main()
