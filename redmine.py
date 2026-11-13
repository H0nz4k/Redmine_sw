import json
import hmac
from contextlib import contextmanager
import os
import sqlite3
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE = os.environ.get('REDMINE_URL', 'https://redmine.altisima.cz').rstrip('/')
KEY = os.environ.get('REDMINE_API_KEY', '')
DB = os.environ.get('REDMINE_DB', 'redmine.sqlite3')
INTERVAL = int(os.environ.get('SYNC_SECONDS', '300'))
MODEL = os.environ.get('OLLAMA_MODEL', '')
HENK_TOKEN = os.environ.get('HENK_API_TOKEN', '')
HELPDESK = os.environ.get('REDMINE_HELPDESK', 'helpdesk')
INTERESTS = tuple(w.strip().casefold() for w in os.environ.get('REDMINE_INTERESTS', '').split(',') if w.strip())
SYNC_LOCK = threading.Lock()
WORDS = ('terminál', 'terminal', 'snímač', 'snímac', 'čtečk', 'cteck', 'tiskárn', 'tiskarn', 'klávesnic', 'klavesnic', 'reproduktor', 'hardware', 'počítač', 'pocitac', ' pc ', 'pc box')

def request(path, params=None):
    url = BASE + path + ('?' + urllib.parse.urlencode(params) if params else '')
    req = urllib.request.Request(url, headers={'X-Redmine-API-Key': KEY, 'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)

def issues(params):
    offset = 0
    while True:
        data = request('/issues.json', {**params, 'limit': 100, 'offset': offset})
        batch = data['issues']
        yield from batch
        offset += len(batch)
        if not batch or offset >= data['total_count']:
            break

def classify(issue):
    content = ' ' + (issue.get('subject', '') + ' ' + (issue.get('description') or '')).lower() + ' '
    return [word.strip() for word in WORDS if word in content]

@contextmanager
def connect():
    db = sqlite3.connect(DB, timeout=30)
    db.execute('CREATE TABLE IF NOT EXISTS issues (id INTEGER PRIMARY KEY, payload TEXT NOT NULL, updated TEXT NOT NULL, first_seen TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, issue_id INTEGER NOT NULL, kind TEXT NOT NULL, seen_at TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS triage (issue_id INTEGER PRIMARY KEY, decision TEXT NOT NULL, reviewed_revision TEXT)')
    try:
        with db:
            yield db
    finally:
        db.close()

def sync():
    with SYNC_LOCK:
        return _sync()

def _sync():
    if not KEY:
        raise ValueError('Chybí REDMINE_API_KEY.')
    me = request('/users/current.json')['user']['id']
    collected = {}
    for params in ({'assigned_to_id': 'me', 'status_id': 'open'}, {'project_id': HELPDESK, 'status_id': 'open'}):
        for issue in issues(params):
            issue['helpdesk'] = bool(issue.get('helpdesk') or params.get('project_id') or collected.get(issue['id'], {}).get('helpdesk'))
            collected[issue['id']] = issue
    now = datetime.now(timezone.utc).isoformat()
    with connect() as db:
        initial = db.execute("SELECT value FROM meta WHERE key='last_sync'").fetchone() is None
        previous = {row[0]: row[1] for row in db.execute('SELECT id, updated FROM issues')}
        for issue in collected.values():
            iid = issue['id']
            if not initial and (iid not in previous or previous[iid] != issue['updated_on']):
                db.execute('INSERT INTO events(issue_id,kind,seen_at) VALUES (?,?,?)', (iid, 'new' if iid not in previous else 'updated', now))
            db.execute('INSERT INTO issues VALUES (?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, updated=excluded.updated', (iid, json.dumps(issue, ensure_ascii=False), issue['updated_on'], now))
        for (old_id,) in db.execute('SELECT id FROM issues').fetchall():
            if old_id not in collected:
                db.execute('DELETE FROM issues WHERE id=?', (old_id,))
        for k,v in [('last_sync', now), ('user_id', str(me)), ('error', '')]:
            db.execute('INSERT INTO meta VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (k,v))
    return len(collected)

def snapshot():
    with connect() as db:
        meta = dict(db.execute('SELECT key,value FROM meta'))
        decisions = {i: (d, r) for i,d,r in db.execute('SELECT issue_id,decision,reviewed_revision FROM triage')}
        data = [json.loads(row[0]) for row in db.execute('SELECT payload FROM issues ORDER BY updated DESC')]
        events = [{'issue_id': i, 'kind': k, 'seen_at': t} for i,k,t in db.execute('SELECT issue_id,kind,seen_at FROM events ORDER BY id DESC LIMIT 100')]
    for issue in data:
        issue['hardware_reasons'] = classify(issue)
        issue['mine'] = str(issue.get('assigned_to', {}).get('id', '')) == meta.get('user_id')
        decision, revision = decisions.get(issue['id'], ('auto', None))
        issue['triage'] = assess(issue, decision, revision)
    data.sort(key=lambda i: (i['triage']['score'], i.get('updated_on', '')), reverse=True)
    return {'henk_api_configured': bool(HENK_TOKEN), 'issues': data, 'events': events, 'last_sync': meta.get('last_sync'), 'error': meta.get('error'), 'configured': bool(KEY), 'ai_configured': bool(MODEL), 'base_url': BASE}

def assess(issue, decision='auto', revision=None):
    text = (issue.get('subject', '') + ' ' + (issue.get('description') or '')).casefold()
    matches = [w for w in INTERESTS if w in text]
    reasons = []
    if issue['mine']: reasons.append('Přiřazeno přímo tobě')
    if issue['hardware_reasons']: reasons.append('Hardware: ' + ', '.join(issue['hardware_reasons']))
    if matches: reasons.append('Tvoje témata: ' + ', '.join(matches))
    relevant = issue['mine'] or bool(matches or issue['hardware_reasons'])
    if decision == 'yes': relevant = True; reasons.insert(0, 'Ručně označeno pro tebe')
    if decision == 'no': relevant = False; reasons.insert(0, 'Ručně vyřazeno z doporučení')
    today = datetime.now(ZoneInfo('Europe/Prague')).date().isoformat()
    due = issue.get('due_date')
    overdue = bool(due and due < today)
    due_today = due == today
    if overdue: reasons.append('Po termínu')
    elif due_today: reasons.append('Termín dnes')
    reviewed = revision == issue.get('updated_on') and revision is not None
    return {'decision': decision, 'relevant': relevant, 'reviewed': reviewed,
            'overdue': overdue, 'due_today': due_today, 'reasons': reasons,
            'score': (100 if relevant else 0) + (40 if overdue else 20 if due_today else 0) + (10 if not reviewed else 0),
            'method': 'rules'}

def set_triage(iid, payload):
    if not isinstance(payload, dict): raise ValueError('Neplatná volba.')
    with connect() as db:
        row = db.execute('SELECT updated FROM issues WHERE id=?', (iid,)).fetchone()
        if not row: raise ValueError('Úkol nebyl nalezen.')
        old = db.execute('SELECT decision,reviewed_revision FROM triage WHERE issue_id=?', (iid,)).fetchone() or ('auto', None)
        decision = payload.get('decision', old[0])
        if decision not in ('auto', 'yes', 'no'): raise ValueError('Neplatné třídění.')
        revision = old[1]
        if 'reviewed' in payload:
            if not isinstance(payload['reviewed'], bool): raise ValueError('Neplatný stav přečtení.')
            if payload.get('revision') != row[0]: raise ValueError('Úkol se změnil. Obnov přehled.')
            revision = row[0] if payload['reviewed'] else None
        db.execute('INSERT INTO triage VALUES (?,?,?) ON CONFLICT(issue_id) DO UPDATE SET decision=excluded.decision, reviewed_revision=excluded.reviewed_revision', (iid, decision, revision))
    return {'ok': True}

def summary(issue):
    if not MODEL:
        raise ValueError('Lokální model není nastavený (OLLAMA_MODEL).')
    # Only loopback is permitted: issue content must stay on this host.
    body = json.dumps({'model': MODEL, 'stream': False, 'prompt': 'Stručně česky shrň požadavek. Nevymýšlej fakta. Uveď možný HW problém a nejistoty.\nPředmět: ' + issue.get('subject', '') + '\nPopis: ' + (issue.get('description') or '')[:12000]}).encode()
    req = urllib.request.Request('http://127.0.0.1:11434/api/generate', body, {'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=120) as response:
        return json.load(response)['response']

def worker():
    while True:
        try:
            sync()
        except Exception as exc:
            with connect() as db:
                db.execute("INSERT INTO meta VALUES ('error', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(exc)[:300],))
        time.sleep(max(60, INTERVAL))

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass
    def send(self, data, content_type='application/json; charset=utf-8', status=200):
        data = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status); self.send_header('Content-Type', content_type); self.send_header('Content-Length', str(len(data))); self.send_header('Cache-Control', 'no-store'); self.send_header('X-Content-Type-Options', 'nosniff'); self.end_headers(); self.wfile.write(data)
    def do_GET(self):
        if self.path == '/':
            self.send(Path(__file__).with_name('index.html').read_bytes(), 'text/html; charset=utf-8')
        elif self.path == '/api/henk/briefing':
            supplied = self.headers.get('Authorization', '')
            if not HENK_TOKEN or not hmac.compare_digest(supplied.encode(), ('Bearer ' + HENK_TOKEN).encode()):
                self.send({'error': 'Neautorizováno'}, status=401); return
            data = snapshot()
            self.send({'last_sync': data['last_sync'], 'error': data['error'], 'issues': [i for i in data['issues'] if i['triage']['relevant'] and not i['triage']['reviewed']], 'method': 'rules'})
        elif self.path == '/api/overview':
            self.send(snapshot())
        else:
            self.send({'error': 'Nenalezeno'}, status=404)
    def do_POST(self):
        if self.headers.get('Origin') not in (None, 'http://127.0.0.1:' + str(self.server.server_port), 'http://localhost:' + str(self.server.server_port)):
            self.send({'error':'Nepovolený původ'}, status=403); return
        try:
            if self.path == '/api/sync':
                self.send({'count': sync()})
            elif self.path.startswith('/api/triage/'):
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 4096: raise ValueError('Neplatná velikost požadavku.')
                self.send(set_triage(int(self.path.rsplit('/', 1)[1]), json.loads(self.rfile.read(size))))
            elif self.path.startswith('/api/summary/'):
                iid = int(self.path.rsplit('/', 1)[1])
                issue = next((i for i in snapshot()['issues'] if i['id'] == iid), None)
                if not issue: raise ValueError('Úkol nebyl nalezen.')
                self.send({'summary': summary(issue)})
            else:
                self.send({'error':'Nenalezeno'}, status=404)
        except Exception as exc:
            self.send({'error':str(exc)[:300]}, status=400)

if __name__ == '__main__':
    threading.Thread(target=worker, daemon=True).start()
    port = int(os.environ.get('PORT', '4091'))
    print(f'Redmine asistent: http://127.0.0.1:{port}', flush=True)
    ThreadingHTTPServer(('127.0.0.1', port), Handler).serve_forever()
