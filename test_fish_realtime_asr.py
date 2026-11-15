import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import msgpack
import fish_realtime_asr as asr


class Socket:
    def __init__(self, events):
        self.events = iter(events)
        self.sent = []
    def __enter__(self): return self
    def __exit__(self, *_): return False
    def send(self, value): self.sent.append(msgpack.unpackb(value, raw=False))
    def recv(self, timeout): return msgpack.packb(next(self.events), use_bin_type=True)


class FishRealtimeTest(unittest.TestCase):
    def run_case(self, event):
        socket = Socket([{'type':'session_started'}, event, {'type':'session_done'}])
        with tempfile.TemporaryDirectory() as folder:
            wav = Path(folder)/'test.wav'
            with wave.open(str(wav), 'wb') as file:
                file.setnchannels(1); file.setsampwidth(2); file.setframerate(16000)
                file.writeframes(b'\0\0' * 1600)
            with patch.object(asr, 'connect', return_value=socket):
                value = asr.transcribe(wav, 'synthetic-key')
        return value, socket.sent

    def test_czech_user_turn_with_expected_terms(self):
        value, sent = self.run_case({'type':'committed', 'user_turn':True,
                                     'language_code':'cs', 'text':'Hej Henku, co je nového?'})
        self.assertEqual(value, 'Hej Henku, co je nového?')
        self.assertEqual(sent[0]['context']['terms'], ['Henku', 'helpdesk'])
        self.assertEqual(sent[-1]['type'], 'audio_done')

    def test_unconfirmed_language_rejected(self):
        with self.assertRaises(ValueError):
            self.run_case({'type':'committed', 'user_turn':True, 'language_code':'pl', 'text':'Tak.'})

    def test_background_is_not_a_user_request(self):
        with self.assertRaises(ValueError):
            self.run_case({'type':'committed', 'user_turn':False, 'language_code':'cs', 'text':'Hej Henku.'})


if __name__ == '__main__':
    unittest.main()
