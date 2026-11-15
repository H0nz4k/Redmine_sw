"""Bounded Fish streaming transcription for one locally captured utterance."""
import time
import wave

import msgpack
from websockets.sync.client import connect
from websockets.exceptions import WebSocketException

from voice_bridge import validate_czech_transcript

URL = 'wss://api.fish.audio/v1/asr/realtime'
TERMS = ['Henku', 'helpdesk']


def transcribe(path, api_key):
    with wave.open(str(path), 'rb') as audio:
        if (audio.getnchannels() != 1 or audio.getsampwidth() != 2 or
                audio.getframerate() != 16000 or audio.getcomptype() != 'NONE' or
                not 0 < audio.getnframes() <= 12 * 16000):
            raise ValueError('Neplatný zvuk pro přepis.')
        pcm = audio.readframes(audio.getnframes())
    config = {'type': 'config', 'audio': {'format': 'pcm_s16le', 'sample_rate': 16000, 'channels': 1},
              'turn_detection': {'mode': 'auto'}, 'results': {'diarize': False, 'tag_audio_events': False},
              'context': {'terms': TERMS}}
    deadline = time.monotonic() + 45
    texts = []
    try:
        with connect(URL, additional_headers={'Authorization': 'Bearer ' + api_key,
                                             'model': 'transcribe-stream-1'},
                     open_timeout=12, close_timeout=5, max_size=262144) as ws:
            ws.send(msgpack.packb(config, use_bin_type=True))
            first = msgpack.unpackb(ws.recv(timeout=12), raw=False)
            if not isinstance(first, dict) or first.get('type') != 'session_started':
                raise ValueError('Fish nepřijal nastavení přepisu.')
            for i in range(0, len(pcm), 1280):
                ws.send(msgpack.packb({'type': 'audio', 'data': pcm[i:i+1280]}, use_bin_type=True))
            ws.send(msgpack.packb({'type': 'audio_done'}, use_bin_type=True))
            while time.monotonic() < deadline:
                event = msgpack.unpackb(ws.recv(timeout=min(12, deadline-time.monotonic())), raw=False)
                if not isinstance(event, dict):
                    raise ValueError('Neplatná odpověď Fish.')
                if event.get('type') == 'committed' and event.get('user_turn') is True:
                    if event.get('degraded') or event.get('language_code') not in ('cs', 'sk'):
                        raise ValueError('Řeč není spolehlivě označena jako česká.')
                    texts.append(validate_czech_transcript({'text': event.get('text', ''),
                                                            'language_code': event['language_code']}))
                elif event.get('type') == 'error':
                    raise ValueError('Fish nepřepsal řeč.')
                elif event.get('type') == 'session_done':
                    break
            else:
                raise ValueError('Přepis vypršel.')
    except (OSError, TimeoutError, EOFError, WebSocketException, msgpack.UnpackException) as error:
        raise ValueError('Spojení s Fish není dostupné.') from error
    result = ' '.join(texts).strip()
    if not result or len(result) > 2000:
        raise ValueError('Fish nerozpoznal otázku.')
    return result
