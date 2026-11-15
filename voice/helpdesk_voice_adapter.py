#!/usr/bin/env python3
"""Read-only helpdesk answer; retain the normal Henk inbox for other speech."""
import http.client
import difflib
import json
import os
import re
import socket
import stat
import struct
import sys
import unicodedata
import uuid

import henk_local_adapter

SOCKET = os.environ.get('REDMINE_VOICE_SOCKET', '/run/user/1000/redmine-voice.sock')


def helpdesk_question(text):
    text = unicodedata.normalize('NFKD', text.casefold())
    text = ''.join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r'[^a-z0-9]+', ' ', text).strip()
    match = re.fullmatch(r'(?:hej |(?:ahoj |cau |hej )?(?:henku|henk|hanku|hejku|henry) )?'
                         r'(?:co|kolik) ([a-z]+) ([a-z]+)(?: na| v)? ([a-z]+(?: [a-z]+)?)', text)
    if not match:
        return False
    day, verb, target = match.groups()
    def similar(word, expected, minimum):
        return any(difflib.SequenceMatcher(None, word, value).ratio() >= minimum for value in expected)
    if ' ' in target and target not in ('help desk', 'help desku'):
        return False
    target = target.replace(' ', '')
    return (similar(day, ('dnes', 'dneska'), .75)
            and similar(verb, ('pribylo', 'pribyly', 'pribyva'), .75)
            and target.startswith('h') and 6 <= len(target) <= 14
            and similar(target, ('helpdesku', 'helpdesk'), .65))


class LocalConnection(http.client.HTTPConnection):
    def connect(self):
        info = os.lstat(SOCKET)
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('unsafe_socket')
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(15)
        self.sock.connect(SOCKET)
        _, uid, _ = struct.unpack('3i', self.sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        if uid != os.getuid():
            raise ValueError('unsafe_peer')


def helpdesk():
    conn = LocalConnection('localhost', timeout=15)
    try:
        conn.request('GET', '/helpdesk/today')
        response = conn.getresponse()
        raw = response.read(65537)
        if response.status != 200 or len(raw) > 65536:
            raise ValueError('unavailable')
        data = json.loads(raw)
        n, items, remaining = data['count'], data['items'], data['remaining']
        if type(n) is not int or n < 0 or not isinstance(items, list) or remaining != n - len(items):
            raise ValueError('invalid_response')
        if n == 0:
            return 'Dnes na helpdesku zatím nepřibyl žádný požadavek.'
        reply = f'Dnes na helpdesku přibylo {n} požadavků. '
        for item in items:
            if type(item['id']) is not int or not isinstance(item['subject'], str):
                raise ValueError('invalid_issue')
            reply += f"Číslo {item['id']}: {item['subject']}. "
        if remaining:
            reply += f'Dalších {remaining} požadavků najdeš v přehledu.'
        return reply.strip()
    finally:
        conn.close()


def run(data):
    if (set(data) != {'schema_version', 'session_id', 'request_id', 'text', 'source'}
            or data['schema_version'] != 1 or data['source'] != 'respeaker'
            or not isinstance(data['text'], str) or len(data['text']) > 2000
            or str(uuid.UUID(data['request_id'])) != data['request_id']
            or str(uuid.UUID(data['session_id'])) != data['session_id']):
        raise ValueError('invalid_request')
    if not helpdesk_question(data['text']):
        try:
            return henk_local_adapter.run(data)
        except (OSError, ValueError, KeyError, TypeError):
            return {'status': 'error', 'reply': 'Spojení s Henkem není dostupné. Požadavek automaticky neopakuji.'}
    try:
        return {'status': 'completed', 'reply': helpdesk()}
    except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException):
        return {'status': 'error', 'reply': 'Aktuální helpdesk teď není dostupný. Zkus to prosím později.'}


if __name__ == '__main__':
    try:
        print(json.dumps(run(json.load(sys.stdin)), ensure_ascii=False))
    except (ValueError, TypeError, KeyError):
        print(json.dumps({'status': 'error', 'reply': 'Požadavek se nepodařilo zpracovat.'}, ensure_ascii=False))
