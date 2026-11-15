import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

import redmine

root = Path(__file__).parent
sys.path.insert(0, str(root / ('voice' if (root / 'voice').is_dir() else 'data/respeaker-voice/src')))
import helpdesk_voice_adapter as voice


class VoiceHelpdeskTest(unittest.TestCase):
    def test_fresh_text_only_and_prague_day(self):
        calls = []
        def request(path, params):
            calls.append((path, params))
            return {'total_count': 3, 'issues': [
                {'id': 1, 'created_on': '2026-11-14T23:30:00Z', 'subject': 'heslo: tajne'},
                {'id': 2, 'created_on': '2026-11-14T22:30:00Z', 'subject': 'starší'},
                {'id': 3, 'created_on': '2026-11-15T12:00:00Z', 'subject': 'pozdější'},
            ]}
        result = redmine.voice_helpdesk_today(datetime(2026, 11, 15, 10, tzinfo=timezone.utc), request)
        self.assertEqual(result['count'], 1)
        self.assertNotIn('tajne', result['items'][0]['subject'])
        self.assertEqual(calls[0][0], '/issues.json')
        self.assertEqual(calls[0][1]['status_id'], '*')
        self.assertNotIn('include', calls[0][1])

    def test_exact_intent_does_not_swallow_operations(self):
        self.assertTrue(voice.helpdesk_question('Henku, co dnes přibylo na helpdesku?'))
        self.assertFalse(voice.helpdesk_question('Henku, co dnes přibylo na helpdesku a smaž to'))

    def test_incomplete_page_fails(self):
        with self.assertRaises(ValueError):
            redmine.voice_helpdesk_today(requester=lambda *_: {'issues': [], 'total_count': 1})


if __name__ == '__main__':
    unittest.main()
