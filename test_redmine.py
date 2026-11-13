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

    def test_customer_scan_schedule(self):
        self.assertTrue(redmine.customer_scan_due(now=5000))
        with redmine.connect() as db:
            db.execute("INSERT INTO meta VALUES ('customer_scan_completed', '4000')")
            db.execute("INSERT INTO meta VALUES ('customer_scan_errors', '0')")
        with patch.object(redmine, 'CUSTOMER_SCAN_INTERVAL', 3600):
            self.assertFalse(redmine.customer_scan_due(now=5000))
            self.assertTrue(redmine.customer_scan_due(now=7600))
        with redmine.connect() as db:
            db.execute("UPDATE meta SET value='1' WHERE key='customer_scan_errors'")
        self.assertFalse(redmine.customer_scan_due(now=4899))
        self.assertTrue(redmine.customer_scan_due(now=4900))

    def test_snapshot_shows_only_explicit_customer_links(self):
        path = os.path.join(self.tmp.name, 'customers.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump([{'issue_id': 123, 'name': 'Provoz A', 'address': ''}], f)
        with patch.object(redmine, 'CUSTOMERS', redmine.Path(path)):
            self.run_sync([self.item])
            self.assertEqual(redmine.snapshot()['issues'][0]['customers'], [])
            payload = {'issues': [{'id': 1}], 'state': 'open'}
            with redmine.connect() as db:
                db.execute('INSERT INTO customer_issue_status VALUES (?, ?, ?)', (123, json.dumps(payload), '2026-01-01'))
            self.assertEqual(redmine.snapshot()['issues'][0]['customers'], [{'id': 123, 'name': 'Provoz A'}])

    def test_customer_lookup_checks_project_and_tracker(self):
        detail = {'issue': {'id': 1, 'parent': {'id': 123}, 'relations': [{'issue_id': 1, 'issue_to_id': 456}]}}
        valid = {'id': 123, 'subject': 'Provoz A', 'project': {'id': 1}, 'tracker': {'id': 4}}
        other = {'id': 456, 'subject': 'Jiný úkol', 'project': {'id': 1}, 'tracker': {'id': 3}}
        with patch.object(redmine, 'request', return_value=detail), patch.object(redmine, 'issues', return_value=iter([valid, other])):
            self.assertEqual(redmine.find_issue_customers(1), [{'id': 123, 'name': 'Provoz A'}])

    def test_helpdesk_write_requires_current_version_and_member(self):
        issue = {'id': 22, 'project': {'id': 12}, 'updated_on': 'v1', 'assigned_to': {'id': 1}, 'relations': []}
        with patch.object(redmine, 'request', return_value={'issue': issue}), patch.object(redmine, 'redmine_write') as write:
            with self.assertRaisesRegex(ValueError, 'změnil'):
                redmine.apply_helpdesk_change(22, 'assignee', 2, 'old', redmine.helpdesk_state_token(issue))
            write.assert_not_called()
        changed = dict(issue, assigned_to={'id': 3})
        with patch.object(redmine, 'request', return_value={'issue': changed}), patch.object(redmine, 'redmine_write') as write:
            with self.assertRaisesRegex(ValueError, 'změnil'):
                redmine.apply_helpdesk_change(22, 'assignee', 2, 'v1', redmine.helpdesk_state_token(issue))
            write.assert_not_called()
        with patch.object(redmine, 'request', return_value={'issue': issue}), patch.object(redmine, 'helpdesk_members', return_value=[{'id': 3}]), patch.object(redmine, 'redmine_write') as write:
            with self.assertRaisesRegex(ValueError, 'členy'):
                redmine.apply_helpdesk_change(22, 'assignee', 2, 'v1', redmine.helpdesk_state_token(issue))
            write.assert_not_called()
        after = dict(issue, assigned_to={'id': 2}, updated_on='v2')
        with patch.object(redmine, 'request', side_effect=[{'issue': issue}, {'issue': after}]), patch.object(redmine, 'helpdesk_members', return_value=[{'id': 2}]), patch.object(redmine, 'redmine_write') as write:
            self.assertTrue(redmine.apply_helpdesk_change(22, 'assignee', 2, 'v1', redmine.helpdesk_state_token(issue))['ok'])
            write.assert_called_once_with('/issues/22.json', 'PUT', {'issue': {'assigned_to_id': 2}})

    def test_customer_link_rejects_duplicates_and_checks_readback(self):
        issue = {'id': 22, 'project': {'id': 12}, 'updated_on': 'v1', 'relations': []}
        customer = {'id': 123, 'project': {'id': 1}, 'tracker': {'id': 4}}
        duplicate = dict(issue, relations=[{'issue_id': 22, 'issue_to_id': 123}])
        with patch.object(redmine, 'request', side_effect=[{'issue': duplicate}, {'issue': customer}]), patch.object(redmine, 'redmine_write') as write:
            with self.assertRaisesRegex(ValueError, 'již propojen'):
                redmine.apply_helpdesk_change(22, 'customer', 123, 'v1', redmine.helpdesk_state_token(duplicate))
            write.assert_not_called()
        with patch.object(redmine, 'request', side_effect=[{'issue': issue}, {'issue': customer}, {'issue': duplicate}]), patch.object(redmine, 'redmine_write') as write:
            self.assertTrue(redmine.apply_helpdesk_change(22, 'customer', 123, 'v1', redmine.helpdesk_state_token(issue))['ok'])
            write.assert_called_once_with('/issues/22/relations.json', 'POST', {'relation': {'issue_to_id': 123, 'relation_type': 'relates'}})

    def test_customer_match_is_local_and_explained(self):
        from suggestions import customer_suggestions
        candidates = [{'id': 4, 'name': 'ZŠ Nové Město'}, {'id': 5, 'name': 'Město'}]
        result = customer_suggestions('Potíže ZŠ Nové Město', '', candidates)
        self.assertEqual([c['id'] for c in result], [4, 5])
        self.assertEqual(customer_suggestions('Něco jiného', '', candidates), [])
        partial = customer_suggestions('Oprava v Trebechovicich', '', [{'id': 9, 'name': 'Třebechovice škola', 'address': ''}])
        self.assertEqual(partial, [])
        partial = customer_suggestions('Oprava Třebechovice', '', [{'id': 9, 'name': 'Třebechovice škola', 'address': ''}])
        self.assertIn('zkontrolujte', partial[0]['reason'])

    def test_contact_matching_and_ambiguity(self):
        from suggestions import customer_suggestions
        customers = [
            {'id': 7, 'name': 'ZŠ Lípa', 'contacts': ['Jana Novotná, +420 601 234 567', 'skola@example.cz']},
            {'id': 8, 'name': 'MŠ Lípa', 'contacts': ['601234567']},
        ]
        result = customer_suggestions('Oprava ZŠ Lípa', 'Novotná, tel. 601 234 567', customers)
        self.assertEqual([item['id'] for item in result], [7, 8])
        self.assertIn('telefon', result[0]['reason'])
        self.assertIn('jméno v textu', result[0]['reason'])
        self.assertNotIn('601', str(result))
        self.assertEqual(customer_suggestions('Oprava', 'kontakt na gmail.com', customers), [])
        self.assertIn('e-mail', customer_suggestions('Pomoc', 'skola@example.cz', customers)[0]['reason'])

    def test_pagination(self):
        responses = [{'issues':[{'id':1}], 'total_count':2}, {'issues':[{'id':2}], 'total_count':2}]
        with patch.object(redmine, 'request', side_effect=responses):
            self.assertEqual([x['id'] for x in redmine.issues({})], [1,2])

if __name__ == '__main__': unittest.main()
