import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from unittest.mock import patch

import henk_mcp


class HenkMcpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = os.path.join(self.temp.name, 'requests.sqlite')
        @contextmanager
        def connect():
            db = sqlite3.connect(self.path)
            try:
                with db:
                    yield db
            finally:
                db.close()
        self.connect = connect
        self.prompt = json.dumps({
            'issue_id': 1, 'issue_source_id': 'issue:1', 'snapshot_safe': True,
            'subject_snapshot': 'Test', 'description_snapshot': 'heslo: tajne',
            'status_snapshot': {}, 'journals_through_cutoff': [],
            'period_source_ids': [], 'attachments': [{'filename': 'secret.pdf'}],
        }, ensure_ascii=False)

    @patch.dict(os.environ, {'HENK_REDMINE_OPENAI_CONSENT': '1'})
    def test_correlated_answer_is_reused_and_redacted(self):
        calls = []
        def call(name, args):
            calls.append((name, args))
            ident = args['request_id']
            if name == 'send_henk_message':
                self.assertEqual(args['kind'], 'digest')
                self.assertNotIn('tajne', args['text'])
                self.assertNotIn('secret.pdf', args['text'])
                return {'id': ident, 'phase': 'DONE'}
            return {'result': [{'message_id': ident, 'kind': 'answer', 'body': '{}'},
                               {'message_id': ident, 'kind': 'done', 'body': 'done'}]}
        for _ in range(2):
            self.assertEqual(henk_mcp.infer(self.prompt, 'henk', self.connect,
                                            call=call, verify=lambda: None), '{}')
        sent = [args for name, args in calls if name == 'send_henk_message']
        self.assertEqual(sent[0], sent[1])

    @patch.dict(os.environ, {'HENK_REDMINE_OPENAI_CONSENT': '1'})
    def test_untrusted_runtime_blocks_before_send(self):
        def verify():
            raise henk_mcp.HenkUnavailable('untrusted')
        with self.assertRaises(henk_mcp.HenkUnavailable):
            henk_mcp.infer(self.prompt, 'henk', self.connect,
                           call=lambda *_: self.fail('sent'), verify=verify)

    @patch.dict(os.environ, {'HENK_REDMINE_OPENAI_CONSENT': '1'})
    def test_progress_or_wrong_correlation_is_rejected(self):
        def call(name, args):
            ident = args['request_id']
            if name == 'send_henk_message':
                return {'id': ident, 'phase': 'DONE'}
            return {'result': [{'message_id': ident, 'kind': 'progress', 'body': 'operation'}]}
        with self.assertRaises(henk_mcp.HenkUnavailable):
            henk_mcp.infer(self.prompt, 'henk', self.connect, call=call, verify=lambda: None)

    @patch.dict(os.environ, {'HENK_REDMINE_OPENAI_CONSENT': '1'})
    def test_confirmed_missing_key_can_retry_but_unknown_failure_keeps_uuid(self):
        for reason, fresh in [('digest_api_credential_unavailable', True), ('digest_openai_unavailable', False)]:
            sent = []
            def call(name, args):
                ident = args['request_id']
                if name == 'send_henk_message':
                    sent.append(ident)
                    return {'id': ident, 'phase': 'BLOCKED'}
                return {'result': [{'message_id': ident, 'kind': 'blocked', 'body': '[' + reason + ']'}]}
            prompt = self.prompt.replace('tajne', 'tajne-' + reason)
            for _ in range(2):
                with self.assertRaises(henk_mcp.HenkUnavailable):
                    henk_mcp.infer(prompt, 'henk', self.connect, call=call, verify=lambda: None)
            self.assertEqual(sent[0] != sent[1], fresh)


if __name__ == '__main__':
    unittest.main()
