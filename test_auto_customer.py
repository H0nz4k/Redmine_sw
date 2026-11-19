import json
import os
import tempfile
import unittest
from unittest.mock import patch

from auto_customer import decide_customer, sender_metadata, signature_block
import redmine


class AutoCustomerMatchTests(unittest.TestCase):
    def setUp(self):
        self.catalog = [
            {'id': 1, 'name': 'Škola A', 'contacts': ['Vedoucí, +420 601 234 567, vedouci@skola.example']},
            {'id': 2, 'name': 'Škola B', 'contacts': ['IT, +420 608 123 456, it@skola.example']},
        ]

    def test_explicit_sender_email_matches_card(self):
        issue = {'custom_fields': [{'name': 'E-mail odesílatele', 'value': 'Vedouci@skola.example'}]}
        result = decide_customer(issue, self.catalog)
        self.assertEqual(result['status'], 'auto')
        self.assertEqual(result['customer_id'], 1)
        self.assertEqual(result['source'], 'sender')
        self.assertNotIn('vedouci@', str(result))

    def test_sender_phone_matches_after_czech_normalization(self):
        issue = {'sender_phone': '601 234 567'}
        self.assertEqual(decide_customer(issue, self.catalog)['customer_id'], 1)

    def test_signed_contact_without_mail_metadata(self):
        issue = {'description': 'Nefunguje tiskárna.\nS pozdravem,\nJana Novotná\n'
                                'tel. +420 608 123 456\nit@skola.example'}
        result = decide_customer(issue, self.catalog)
        self.assertEqual(result['status'], 'auto')
        self.assertEqual(result['source'], 'signature')
        self.assertEqual(result['customer_id'], 2)

    def test_only_body_contact_is_not_automatic(self):
        issue = {'subject': 'Pomoc', 'description': 'Kontaktujte 601 234 567 ohledně tiskárny.'}
        self.assertEqual(decide_customer(issue, self.catalog)['status'], 'none')

    def test_forwarded_content_is_ignored(self):
        issue = {'description': 'Problém.\n---- Original Message ----\n'
                                'S pozdravem\nJana\nvedouci@skola.example'}
        self.assertEqual(decide_customer(issue, self.catalog)['status'], 'none')

    def test_other_custom_field_is_not_sender(self):
        issue = {'custom_fields': [{'name': 'Kontakt na kolegu', 'value': 'vedouci@skola.example'}]}
        self.assertEqual(sender_metadata(issue), '')
        self.assertEqual(decide_customer(issue, self.catalog)['status'], 'none')

    def test_duplicate_contact_requires_review(self):
        catalog = self.catalog + [{'id': 3, 'name': 'Jiná škola', 'contacts': ['vedouci@skola.example']}]
        issue = {'sender_email': 'vedouci@skola.example'}
        self.assertEqual(decide_customer(issue, catalog)['status'], 'review')

    def test_disagreement_sender_and_signature_requires_review(self):
        issue = {'sender_email': 'vedouci@skola.example',
                 'description': 'S pozdravem\nIT\nit@skola.example'}
        self.assertEqual(decide_customer(issue, self.catalog)['status'], 'review')

    def test_unverified_sender_blocks_signature_only_match(self):
        issue = {'sender_email': 'jiny@firma.example',
                 'description': 'S pozdravem\nIT\nit@skola.example'}
        self.assertEqual(decide_customer(issue, self.catalog)['status'], 'review')

    def test_signature_split_at_quote(self):
        message = 'S pozdravem\nJana\n601 234 567\nFrom: old@sender.example\nit@skola.example'
        self.assertNotIn('it@skola.example', signature_block(message))


class AutoCustomerSyncTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p = patch.object(redmine, 'DB', os.path.join(tmp.name, 'redmine.sqlite3'))
        p.start()
        self.addCleanup(p.stop)
        self.issue = {'id': 22, 'project': {'id': 12}, 'updated_on': 'v1',
                      'description': 'S pozdravem\nPetr\nvedouci@skola.example',
                      'relations': [], 'custom_fields': []}
        self.catalog = [{'id': 1, 'name': 'Škola A', 'contacts': ['vedouci@skola.example']}]
        with redmine.connect() as db:
            db.execute('INSERT INTO issue_customer_links VALUES (?,?,?)',
                       (22, 'v1', json.dumps([])))

    def test_dry_run_has_no_remote_write(self):
        with patch.object(redmine, 'AUTO_CUSTOMER_MODE', 'dry-run'), \
             patch.object(redmine, 'request', return_value={'issue': self.issue}), \
             patch.object(redmine, '_apply_helpdesk_change') as write:
            redmine.auto_link_customers({22: self.issue}, self.catalog)
            write.assert_not_called()
        with redmine.connect() as db:
            outcome = db.execute('SELECT outcome FROM auto_customer_audit').fetchone()[0]
        self.assertEqual(outcome, 'dry-run')

    def test_write_only_once_after_dry_run(self):
        with patch.object(redmine, 'AUTO_CUSTOMER_MODE', 'dry-run'), \
             patch.object(redmine, 'request', return_value={'issue': self.issue}):
            redmine.auto_link_customers({22: self.issue}, self.catalog)
        with patch.object(redmine, 'AUTO_CUSTOMER_MODE', 'write'), \
             patch.object(redmine, 'request', return_value={'issue': self.issue}), \
             patch.object(redmine, 'find_issue_customers', return_value=[]), \
             patch.object(redmine, '_apply_helpdesk_change', return_value={'ok': True}) as write:
            redmine.auto_link_customers({22: self.issue}, self.catalog)
            redmine.auto_link_customers({22: self.issue}, self.catalog)
            write.assert_called_once()
        with redmine.connect() as db:
            outcomes = [row[0] for row in db.execute('SELECT outcome FROM auto_customer_audit ORDER BY id')]
        self.assertEqual(outcomes, ['dry-run', 'written'])

    def test_uncertain_remote_write_is_never_replayed(self):
        with patch.object(redmine, 'AUTO_CUSTOMER_MODE', 'write'), \
             patch.object(redmine, 'request', return_value={'issue': self.issue}), \
             patch.object(redmine, 'find_issue_customers', return_value=[]), \
             patch.object(redmine, '_apply_helpdesk_change', side_effect=RuntimeError('unknown')) as write:
            redmine.auto_link_customers({22: self.issue}, self.catalog)
            next_issue = dict(self.issue, updated_on='v2')
            redmine.auto_link_customers({22: next_issue}, self.catalog)
            write.assert_called_once()
        with redmine.connect() as db:
            self.assertEqual(db.execute('SELECT outcome FROM auto_customer_audit').fetchone()[0], 'uncertain')

    def test_existing_customer_is_untouched(self):
        with redmine.connect() as db:
            db.execute('UPDATE issue_customer_links SET payload=? WHERE issue_id=22',
                       (json.dumps([{'id': 1, 'name': 'Škola A'}]),))
        with patch.object(redmine, 'AUTO_CUSTOMER_MODE', 'write'), \
             patch.object(redmine, 'request') as req, \
             patch.object(redmine, '_apply_helpdesk_change') as write:
            redmine.auto_link_customers({22: self.issue}, self.catalog)
            req.assert_not_called()
            write.assert_not_called()


if __name__ == '__main__':
    unittest.main()
