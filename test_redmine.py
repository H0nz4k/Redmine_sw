import json
import os
import tempfile
import unittest
from unittest.mock import patch
import redmine

class SyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = patch.object(redmine, 'DB', os.path.join(self.tmp.name, 'test.db')); self.db.start(); self.addCleanup(self.db.stop)
        self.key = patch.object(redmine, 'KEY', 'test'); self.key.start(); self.addCleanup(self.key.stop)
        self.item = {'id': 1, 'subject': 'Výdejní terminál', 'description': '', 'updated_on': '2026-01-01T00:00:00Z', 'assigned_to': {'id': 7}, 'project': {'name':'Helpdesk'}}
    def run_sync(self, items):
        with patch.object(redmine, 'request', return_value={'user': {'id': 7}}), patch.object(redmine, 'issues', return_value=iter(items)):
            redmine.sync()
    def test_initial_and_changed(self):
        self.run_sync([self.item])
        self.assertEqual(redmine.snapshot()['events'], [])
        self.assertTrue(redmine.snapshot()['issues'][0]['mine'])
        changed = dict(self.item, updated_on='2026-01-02T00:00:00Z')
        self.run_sync([changed])
        self.assertEqual(redmine.snapshot()['events'][0]['kind'], 'updated')
        self.assertIn('terminál', redmine.classify(changed))
    def test_failed_sync_keeps_snapshot(self):
        self.run_sync([self.item])
        with patch.object(redmine, 'request', side_effect=OSError('offline')):
            with self.assertRaises(OSError): redmine.sync()
        self.assertEqual(len(redmine.snapshot()['issues']), 1)
    def test_pagination(self):
        responses = [{'issues':[{'id':1}], 'total_count':2}, {'issues':[{'id':2}], 'total_count':2}]
        with patch.object(redmine, 'request', side_effect=responses):
            self.assertEqual([x['id'] for x in redmine.issues({})], [1,2])

if __name__ == '__main__': unittest.main()
