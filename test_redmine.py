import json
import os
import tempfile
import unittest
from unittest.mock import patch
import redmine

class DigestSourceBoundaryTests(unittest.TestCase):
    def test_digest_request_allows_only_text_endpoints_without_redirects(self):
        from io import BytesIO
        for path, params in [('/attachments/2', {}), ('/issues/1.json', {'include': 'attachments'}),
                             ('https://example.invalid/file', {}), ('/projects.json', {'include': 'attachments'})]:
            with self.subTest(path=path, params=params):
                with patch.object(redmine.urllib.request, 'build_opener') as opener:
                    with self.assertRaises(ValueError):
                        redmine.digest_request(path, params)
                    opener.assert_not_called()
        with patch.object(redmine.urllib.request, 'build_opener') as opener:
            opener.return_value.open.return_value = BytesIO(b'{"issue":{}}')
            self.assertEqual(redmine.digest_request('/issues/1.json', {'include': 'journals'}), {'issue': {}})
            handlers = opener.call_args.args
            self.assertTrue(any(isinstance(h, redmine._DigestNoRedirect) for h in handlers))
            req = opener.return_value.open.call_args.args[0]
            self.assertTrue(req.full_url.endswith('/issues/1.json?include=journals'))
        self.assertIsNone(redmine._DigestNoRedirect().redirect_request(None, None, 302, None, None, 'https://example.invalid/attachments/1'))


class CloseIssueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = patch.object(redmine, 'DB', os.path.join(self.tmp.name, 'test.db')); self.db.start(); self.addCleanup(self.db.stop)
        self.key = patch.object(redmine, 'KEY', 'test'); self.key.start(); self.addCleanup(self.key.stop)
        self.item = {'id': 22, 'updated_on': 'v1', 'status': {'id': 1}, 'allowed_statuses': [{'id': 2, 'name': 'Uzavřený'}]}
        with redmine.connect() as db:
            db.execute('INSERT INTO issues VALUES (?, ?, ?, ?)', (22, json.dumps(self.item), 'v1', 'v1'))
        self.statuses = {'issue_statuses': [{'id': 1, 'is_closed': False}, {'id': 2, 'is_closed': True}]}

    def test_closes_only_after_verified_and_removes_from_snapshot(self):
        responses = [{'issue': self.item}, self.statuses, {'issue': {'status': {'id': 2}}}]
        with patch.object(redmine, 'request', side_effect=responses), patch.object(redmine, 'redmine_write') as write:
            self.assertTrue(redmine.close_issue(22, 'v1')['ok'])
            write.assert_called_once_with('/issues/22.json', 'PUT', {'issue': {'status_id': 2}})
        with redmine.connect() as db:
            self.assertIsNone(db.execute('SELECT id FROM issues WHERE id=22').fetchone())

    def test_stale_or_ambiguous_status_never_writes(self):
        with patch.object(redmine, 'redmine_write') as write:
            with self.assertRaisesRegex(ValueError, 'změnil'):
                redmine.close_issue(22, 'old')
            with patch.object(redmine, 'request', side_effect=[{'issue': dict(self.item, updated_on='v2')}]):
                with self.assertRaisesRegex(ValueError, 'změnil'): redmine.close_issue(22, 'v1')
            with patch.object(redmine, 'request', side_effect=[{'issue': self.item}, {'issue_statuses': []}]):
                with self.assertRaisesRegex(ValueError, 'jednoznačně'): redmine.close_issue(22, 'v1')
            with patch.object(redmine, 'request', return_value={'issue': dict(self.item, allowed_statuses=None)}):
                with self.assertRaisesRegex(ValueError, 'neposkytl'): redmine.close_issue(22, 'v1')
            write.assert_not_called()

    def test_unconfirmed_write_keeps_item(self):
        with patch.object(redmine, 'request', side_effect=[{'issue': self.item}, self.statuses, OSError('offline')]), patch.object(redmine, 'redmine_write'):
            with self.assertRaisesRegex(RuntimeError, 'nelze ověřit'): redmine.close_issue(22, 'v1')
        with redmine.connect() as db:
            self.assertIsNotNone(db.execute('SELECT id FROM issues WHERE id=22').fetchone())


class SummaryTests(unittest.TestCase):
    def test_model_result_and_loopback(self):
        from io import BytesIO
        item = {'subject': 'Tisk', 'description': 'Tiskárna netiskne'}
        with patch.object(redmine, 'MODEL', 'test-model'), patch.object(redmine.urllib.request, 'urlopen', return_value=BytesIO(b'{"response":"  Hotovo  "}')) as urlopen:
            self.assertEqual(redmine.summary(item), 'Hotovo')
            req = urlopen.call_args.args[0]
            self.assertEqual(req.full_url, 'http://127.0.0.1:11434/api/generate')
            self.assertIn('Tiskárna netiskne', json.loads(req.data)['prompt'])
    def test_model_missing_offline_and_empty(self):
        from io import BytesIO
        with patch.object(redmine, 'MODEL', ''):
            with self.assertRaisesRegex(ValueError, 'není nastavený'): redmine.summary({})
        with patch.object(redmine, 'MODEL', 'test'), patch.object(redmine.urllib.request, 'urlopen', side_effect=redmine.urllib.error.URLError('offline')):
            with self.assertRaisesRegex(ValueError, 'není dostupná'): redmine.summary({})
        with patch.object(redmine, 'MODEL', 'test'), patch.object(redmine.urllib.request, 'urlopen', return_value=BytesIO(b'{"response":" "}')):
            with self.assertRaisesRegex(ValueError, 'žádné shrnutí'): redmine.summary({})

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
        customer = {'id': 123, 'subject': 'Provoz A', 'project': {'id': 1}, 'tracker': {'id': 4}}
        duplicate = dict(issue, relations=[{'issue_id': 22, 'issue_to_id': 123}])
        with patch.object(redmine, 'request', side_effect=[{'issue': duplicate}, {'issue': customer}]), patch.object(redmine, 'redmine_write') as write:
            with self.assertRaisesRegex(ValueError, 'již propojen'):
                redmine.apply_helpdesk_change(22, 'customer', 123, 'v1', redmine.helpdesk_state_token(duplicate))
            write.assert_not_called()
        with patch.object(redmine, 'request', side_effect=[{'issue': issue}, {'issue': customer}, {'issue': duplicate}]), patch.object(redmine, 'redmine_write') as write:
            self.assertTrue(redmine.apply_helpdesk_change(22, 'customer', 123, 'v1', redmine.helpdesk_state_token(issue))['ok'])
            write.assert_called_once_with('/issues/22/relations.json', 'POST', {'relation': {'issue_to_id': 123, 'relation_type': 'relates'}})
        with redmine.connect() as db:
            row = db.execute('SELECT payload FROM issue_customer_links WHERE issue_id=22').fetchone()
        self.assertEqual(json.loads(row[0]), [{'id': 123, 'name': 'Provoz A'}])

    def test_customer_link_unverified_does_not_create_cache(self):
        issue = {'id': 22, 'project': {'id': 12}, 'updated_on': 'v1', 'relations': []}
        customer = {'id': 123, 'subject': 'Provoz A', 'project': {'id': 1}, 'tracker': {'id': 4}}
        with patch.object(redmine, 'request', side_effect=[{'issue': issue}, {'issue': customer}, {'issue': issue}]), patch.object(redmine, 'redmine_write'):
            with self.assertRaisesRegex(RuntimeError, 'nepotvrdil'):
                redmine.apply_helpdesk_change(22, 'customer', 123, 'v1', redmine.helpdesk_state_token(issue))
        with redmine.connect() as db:
            self.assertIsNone(db.execute('SELECT payload FROM issue_customer_links WHERE issue_id=22').fetchone())

    def test_hw_assignee_is_honza_not_api_account(self):
        issue = {'id': 22, 'project': {'id': 12}, 'subject': 'Rozbitý terminál',
                 'updated_on': 'v1', 'relations': []}
        def advice(members, item=issue):
            with patch.object(redmine, 'request', return_value={'issue': item}), \
                 patch.object(redmine, 'matching_customers', return_value=[]), \
                 patch.object(redmine, 'helpdesk_members', return_value=members), \
                 patch.object(redmine, 'find_issue_customers', return_value=[]):
                return redmine.helpdesk_suggestions(22)
        members = [{'id': 7, 'name': 'servis'}, {'id': 9, 'name': 'honza'}]
        self.assertEqual(advice(members)['assignee_suggestion']['id'], 9)
        for invalid in ([{'id': 7, 'name': 'servis'}],
                        [{'id': 9, 'name': 'honza'}, {'id': 10, 'name': 'HONZA'}]):
            result = advice(invalid)
            self.assertIsNone(result['assignee_suggestion'])
            self.assertIn('nelze jednoznačně', result['assignee_unavailable_reason'])
        no_hw = dict(issue, subject='Faktura')
        self.assertIsNone(advice(members, no_hw)['assignee_suggestion'])

    def test_customer_match_is_local_and_explained(self):
        from suggestions import customer_suggestions
        candidates = [{'id': 4, 'name': 'ZŠ Nové Město'}, {'id': 5, 'name': 'Město'}]
        result = customer_suggestions('Potíže ZŠ Nové Město', '', candidates)
        self.assertEqual([c['id'] for c in result], [4, 5])
        self.assertEqual(customer_suggestions('Něco jiného', '', candidates), [])
        self.assertEqual(customer_suggestions('', 'Nefunguje mi aplikace e-jídelníček.', [{'id': 10, 'name': 'AAA Test E-jidelnicek'}]), [])
        partial = customer_suggestions('Oprava v Trebechovicich', '', [{'id': 9, 'name': 'Třebechovice škola', 'address': ''}])
        self.assertEqual(partial, [])
        partial = customer_suggestions('Oprava Třebechovice', '', [{'id': 9, 'name': 'Třebechovice škola', 'address': ''}])
        self.assertIn('zkontrolujte', partial[0]['reason'])

    def test_school_words_alone_do_not_suggest_a_customer(self):
        from suggestions import customer_suggestions
        candidates = [
            {'id': 1, 'name': 'U Nové školy MŠ'},
            {'id': 2, 'name': 'Škola'},
            {'id': 3, 'name': 'Základní škola'},
            {'id': 4, 'name': 'U Tyršovy školy'},
        ]
        for word in ('škola', 'školy', 'škole', 'školu', 'školou', 'školách', 'školami', 'základní škola'):
            with self.subTest(word=word):
                self.assertEqual(customer_suggestions('Potíže', word, candidates), [])
        result = customer_suggestions('Objednávka U Tyršovy školy', '', candidates)
        self.assertEqual([item['id'] for item in result], [4])
        self.assertIn('úplný název', result[0]['reason'])

    def test_contact_matching_and_ambiguity(self):
        from suggestions import customer_suggestions
        customers = [
            {'id': 7, 'name': 'ZŠ Lípa', 'contacts': ['Jana Novotná, +420 601 234 567', 'skola@example.cz']},
            {'id': 8, 'name': 'MŠ Lípa', 'contacts': ['601234567']},
        ]
        result = customer_suggestions('Oprava ZŠ Lípa', 'Novotná, tel. 601 234 567', customers)
        self.assertEqual([item['id'] for item in result], [7, 8])
        self.assertIn('telefon', result[0]['reason'])
        self.assertNotIn('jméno v podpisu', result[0]['reason'])
        self.assertNotIn('601', str(result))
        self.assertEqual(customer_suggestions('Oprava', 'kontakt na gmail.com', customers), [])
        self.assertIn('e-mail', customer_suggestions('Pomoc', 'skola@example.cz', customers)[0]['reason'])

    def test_customer_priority_contacts_signature_then_names(self):
        from suggestions import customer_suggestions
        candidates = [
            {'id': 1, 'name': 'ZŠ Na kopci', 'contacts': ['Jana Novotná', 'jana@example.cz']},
            {'id': 2, 'name': 'MŠ Na kopci', 'contacts': ['Petr Dvořák']},
            {'id': 3, 'name': 'Kopci servis'},
        ]
        description = 'Píšu za MŠ Na kopci. Jana je zmíněna v textu.\nS pozdravem\nPetr Dvořák'
        result = customer_suggestions('ZŠ Na kopci', description, candidates)
        self.assertEqual([c['id'] for c in result], [2, 1])
        self.assertIn('jméno v podpisu', result[0]['reason'])
        result = customer_suggestions('ZŠ Na kopci', description + '\nKontakt: jana@example.cz', candidates)
        self.assertEqual([c['id'] for c in result], [1, 2])
        self.assertIn('e-mail', result[0]['reason'])
        self.assertNotIn('jana@example.cz', str(result))
        self.assertEqual(customer_suggestions('', 'Jana Novotná je zmíněna v popisu.', candidates), [])
        result = customer_suggestions('ZŠ Na kopci', 'Telefon 601 234 567', [
            {'id': 1, 'name': 'ZŠ Na kopci'},
            {'id': 2, 'name': 'Jiná provozovna', 'contacts': ['+420 601 234 567']},
        ])
        self.assertEqual([c['id'] for c in result], [2, 1])

    def test_forwarded_messages_can_match_more_than_one_contact(self):
        from suggestions import customer_suggestions
        candidates = [
            {'id': 1, 'name': 'U Tyršovy školy', 'contacts': ['Renáta Řehořová', 'jidelna@example.cz']},
            {'id': 2, 'name': 'Dodavatel', 'contacts': ['technik@dodavatel.example']},
        ]
        message = ('Od jidelna@example.cz\nObjednávka\nPřeji krásný den.\n\n'
                   'Renáta Řehořová\n\nOd technik@dodavatel.example\nPředchozí odpověď')
        result = customer_suggestions('Objednávka U Tyršovy školy', message, candidates)
        self.assertEqual([c['id'] for c in result], [1, 2])
        self.assertIn('jméno v podpisu', result[0]['reason'])
        self.assertNotIn('jméno v podpisu', result[1]['reason'])

    def test_unambiguous_customer_requires_unique_signed_lead_phone_and_email(self):
        from suggestions import customer_suggestions
        lead = 'Jana Novotná, tel. 601 234 567, jana@example.cz'
        candidate = {'id': 1, 'name': 'Provoz A', 'lead_contact': lead,
                     'email_contact': 'jana@example.cz', 'contacts': [lead]}
        message = 'Kontakt 601 234 567, jana@example.cz\nS pozdravem\nJana Novotná'
        self.assertTrue(customer_suggestions('', message, [candidate])[0]['unambiguous'])
        for incomplete in ('jana@example.cz\nS pozdravem\nJana Novotná',
                           '601 234 567\nS pozdravem\nJana Novotná',
                           '601 234 567 jana@example.cz\nS pozdravem\nJana',
                           '601 234 567 jana@example.cz\nJana Novotná'):
            with self.subTest(message=incomplete):
                self.assertFalse(any(c['unambiguous'] for c in customer_suggestions('', incomplete, [candidate])))
        duplicate = dict(candidate, id=2, name='Provoz B')
        self.assertFalse(any(c['unambiguous'] for c in customer_suggestions('', message, [candidate, duplicate])))
        no_lead = dict(candidate, lead_contact='')
        self.assertFalse(any(c['unambiguous'] for c in customer_suggestions('', message, [no_lead])))
        phone_only_in_other_contact = dict(candidate, lead_contact='Jana Novotná', contacts=[lead])
        self.assertFalse(any(c['unambiguous'] for c in customer_suggestions('', message, [phone_only_in_other_contact])))
        self.assertNotIn('jana@example.cz', str(customer_suggestions('', message, [candidate])))

    def test_pagination(self):
        responses = [{'issues':[{'id':1}], 'total_count':2}, {'issues':[{'id':2}], 'total_count':2}]
        with patch.object(redmine, 'request', side_effect=responses):
            self.assertEqual([x['id'] for x in redmine.issues({})], [1,2])

if __name__ == '__main__': unittest.main()
