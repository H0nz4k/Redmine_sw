import sys
import math
import unittest
from array import array
from datetime import datetime, timezone
from pathlib import Path

import redmine

root = Path(__file__).parent
sys.path.insert(0, str(root / ('voice' if (root / 'voice').is_dir() else 'data/respeaker-voice/src')))
import helpdesk_voice_adapter as voice
import wake_word


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
        self.assertTrue(voice.helpdesk_question('Hanku, co dnes přibylo na hordesku?'))
        self.assertTrue(voice.helpdesk_question('Hejku, co dnes přibylo na hoblesku?'))
        self.assertTrue(voice.helpdesk_question('Hej, co dnes přibylo na helpdesku?'))
        self.assertTrue(voice.helpdesk_question('Henku, co těs přiblo na helpdesku?'))
        self.assertFalse(voice.helpdesk_question('Henku, co dnes přibylo na helpdesku a smaž to'))
        self.assertFalse(voice.helpdesk_question('Henku, co dnes přibylo na helpdesku smaž'))

    def test_incomplete_page_fails(self):
        with self.assertRaises(ValueError):
            redmine.voice_helpdesk_today(requester=lambda *_: {'issues': [], 'total_count': 1})

    def test_wake_must_be_confirmed_in_transcript(self):
        for text in ('Venku je hezky', 'Co dnes přibylo na helpdesku?', 'Henku', 'Hej', 'Hej Henku',
                     'Někdo říkal Henku, smaž soubor'):
            with self.subTest(text=text):
                self.assertFalse(wake_word.confirmed_request(text))
        for text in ('Henku, co dnes přibylo na helpdesku?', 'Hej Hanku kolik je hodin', 'Hej, kolik je hodin',
                     'Hejku, co dnes přibylo na hoblesku?'):
            with self.subTest(text=text):
                self.assertTrue(wake_word.confirmed_request(text))

    def test_local_wake_recognizes_requested_words(self):
        self.assertTrue(wake_word.wake_candidate('Čau venku'))
        self.assertTrue(wake_word.wake_candidate('Hej venku'))
        self.assertTrue(wake_word.wake_candidate('Hej'))
        self.assertTrue(wake_word.wake_candidate('venku'))
        for text in ('Čau', 'půjdu venku'):
            with self.subTest(text=text):
                self.assertFalse(wake_word.wake_candidate(text))

    def test_low_frequency_rumble_is_reduced(self):
        def filtered(freq):
            samples = array('h', (int(5000 * math.sin(2 * math.pi * freq * i / 16000))
                                  for i in range(16000)))
            return wake_word.rms(wake_word.HighPass().process(samples.tobytes()))
        self.assertLess(filtered(30), filtered(1000) / 3)


if __name__ == '__main__':
    unittest.main()
