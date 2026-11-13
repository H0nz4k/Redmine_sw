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



class TriageTests(unittest.TestCase):
    setUp = SyncTests.setUp
    run_sync = SyncTests.run_sync
    def test_review_revision_and_decision_persist(self):
        self.run_sync([self.item])
        redmine.set_triage(1, {'decision': 'no', 'reviewed': True, 'revision': self.item['updated_on']})
        triage = redmine.snapshot()['issues'][0]['triage']
        self.assertFalse(triage['relevant'])
        self.assertTrue(triage['reviewed'])
        self.run_sync([dict(self.item, updated_on='2026-01-03T00:00:00Z')])
        triage = redmine.snapshot()['issues'][0]['triage']
        self.assertFalse(triage['reviewed'])
        self.assertEqual(triage['decision'], 'no')
        with self.assertRaises(ValueError):
            redmine.set_triage(1, {'reviewed': True, 'revision': self.item['updated_on']})
    def test_interest_and_no_match(self):
        item = dict(self.item, mine=False, subject='Databáze SQL', hardware_reasons=[])
        with patch.object(redmine, 'INTERESTS', ('sql',)):
            self.assertTrue(redmine.assess(item)['relevant'])
        with patch.object(redmine, 'INTERESTS', ()):
            self.assertFalse(redmine.assess(item)['relevant'])
    def test_helpdesk_membership_survives_merge(self):
        with patch.object(redmine, 'request', return_value={'user': {'id': 7}}), patch.object(redmine, 'issues', side_effect=[[dict(self.item)], [dict(self.item)]]):
            redmine.sync()
        self.assertTrue(redmine.snapshot()['issues'][0]['helpdesk'])
    def test_invalid_decision(self):
        self.run_sync([self.item])
        with self.assertRaises(ValueError): redmine.set_triage(1, {'decision': 'unknown'})

class HenkApiTests(unittest.TestCase):
    def test_token_required_and_briefing_filtered(self):
        from unittest.mock import Mock
        handler = object.__new__(redmine.Handler)
        handler.path = '/api/henk/briefing'
        handler.send = Mock()
        handler.headers = {}
        with patch.object(redmine, 'HENK_TOKEN', 'test-token'):
            handler.do_GET()
            self.assertEqual(handler.send.call_args.kwargs['status'], 401)
            handler.headers = {'Authorization': 'Bearer test-token'}
            data = {'last_sync': None, 'error': 'offline', 'issues': [
                {'id': 1, 'triage': {'relevant': True, 'reviewed': False}},
                {'id': 2, 'triage': {'relevant': False, 'reviewed': False}},
                {'id': 3, 'triage': {'relevant': True, 'reviewed': True}}]}
            with patch.object(redmine, 'snapshot', return_value=data): handler.do_GET()
            result = handler.send.call_args.args[0]
            self.assertEqual([i['id'] for i in result['issues']], [1])
            self.assertEqual(result['error'], 'offline')

if __name__ == '__main__': unittest.main()
