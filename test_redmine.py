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
    def test_customer_locations_and_relations(self):
        path = os.path.join(self.tmp.name, 'customers.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump([{'issue_id': 123, 'name': 'Test', 'address': 'Test', 'poe': ''}], f)
        with patch.object(redmine, 'CUSTOMERS', redmine.Path(path)):
            redmine.save_location(123, 50, 15)
            self.assertEqual(redmine.customers()['customers'][0]['location'], (50, 15))
            with self.assertRaises(ValueError): redmine.save_location(123, 'NaN', 15)
            with self.assertRaises(ValueError): redmine.save_location(456, 50, 15)
            self.run_sync([self.item])
            detail = {'issue': {'id': 1, 'relations': [{'issue_id': 1, 'issue_to_id': 123}]}}
            with patch.object(redmine, 'request', return_value=detail), patch.object(redmine, 'issues', side_effect=lambda params: iter([self.item] if params['status_id'] == 'open' else [])):
                result = redmine.related_issues(123)
                self.assertEqual(result['issues'][0]['id'], 1)
                self.assertEqual(result['state'], 'open')
            with patch.object(redmine, 'request', return_value=detail), patch.object(redmine, 'issues', return_value=iter([])):
                self.assertEqual(redmine.related_issues(123)['state'], 'unknown')
            with patch.object(redmine, 'request', return_value=detail), patch.object(redmine, 'issues', side_effect=lambda params: iter([self.item] if params['status_id'] == 'closed' else [])):
                self.assertEqual(redmine.related_issues(123)['state'], 'closed')
            with patch.object(redmine, 'request', return_value={'issue': {'id': 123}}):
                self.assertEqual(redmine.related_issues(123)['state'], 'none')

    def test_compare_and_add_redmine_customer(self):
        data = [{'issue_id': 123, 'name': 'A', 'address': '', 'poe': ''}]
        path = os.path.join(self.tmp.name, 'customers.json')
        with open(path, 'w', encoding='utf-8') as f: json.dump(data, f)
        customer = {'id': 456, 'subject': 'B', 'project': {'id': 1}, 'tracker': {'id': 4}, 'custom_fields': [{'name': 'Adresa', 'value': 'Test 1'}]}
        with patch.object(redmine, 'CUSTOMERS', redmine.Path(path)), patch.object(redmine, 'issues', return_value=iter([customer])):
            self.assertFalse(redmine.redmine_customers()[0]['in_map'])
            with patch.object(redmine, 'request', return_value={'issue': customer}):
                redmine.add_redmine_customer(456)
                self.assertEqual(redmine.customer_details(456)['address'], 'Test 1')
                redmine.add_redmine_customer(456)
            self.assertEqual(len(redmine.customers()['customers']), 2)
            bad = dict(customer, project={'id': 99})
            with patch.object(redmine, 'request', return_value={'issue': bad}):
                with self.assertRaises(ValueError): redmine.add_redmine_customer(456)

    def test_pagination(self):
        responses = [{'issues':[{'id':1}], 'total_count':2}, {'issues':[{'id':2}], 'total_count':2}]
        with patch.object(redmine, 'request', side_effect=responses):
            self.assertEqual([x['id'] for x in redmine.issues({})], [1,2])

if __name__ == '__main__': unittest.main()
