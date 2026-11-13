import json
import re
from contextlib import contextmanager
import os
import sqlite3
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE = os.environ.get('REDMINE_URL', 'https://redmine.altisima.cz').rstrip('/')
KEY = os.environ.get('REDMINE_API_KEY', '')
DB = os.environ.get('REDMINE_DB', 'redmine.sqlite3')
INTERVAL = int(os.environ.get('SYNC_SECONDS', '300'))
MODEL = os.environ.get('OLLAMA_MODEL', '')
MAP_KEY = os.environ.get('MAPY_API_KEY', '')
CUSTOMERS = Path(os.environ.get('CUSTOMERS_FILE', 'data/customers.json'))
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
    db.execute('CREATE TABLE IF NOT EXISTS customer_locations (issue_id INTEGER PRIMARY KEY, lat REAL NOT NULL, lon REAL NOT NULL)')
    try:
        with db:
            yield db
    finally:
        db.close()

def sync():
    if not KEY:
        raise ValueError('Chybí REDMINE_API_KEY.')
    me = request('/users/current.json')['user']['id']
    collected = {}
    for params in ({'assigned_to_id': 'me', 'status_id': 'open'}, {'project_id': 'helpdesk', 'status_id': 'open'}):
        for issue in issues(params):
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
        data = [json.loads(row[0]) for row in db.execute('SELECT payload FROM issues ORDER BY updated DESC')]
        events = [{'issue_id': i, 'kind': k, 'seen_at': t} for i,k,t in db.execute('SELECT issue_id,kind,seen_at FROM events ORDER BY id DESC LIMIT 100')]
    for issue in data:
        issue['hardware_reasons'] = classify(issue)
        issue['mine'] = str(issue.get('assigned_to', {}).get('id', '')) == meta.get('user_id')
    return {'issues': data, 'events': events, 'last_sync': meta.get('last_sync'), 'error': meta.get('error'), 'configured': bool(KEY), 'ai_configured': bool(MODEL), 'base_url': BASE}

def customers():
    data = json.loads(CUSTOMERS.read_text(encoding='utf-8')) if CUSTOMERS.exists() else []
    with connect() as db:
        locations = {i: (lat, lon) for i, lat, lon in db.execute('SELECT issue_id, lat, lon FROM customer_locations')}
        issue_ids = {i for (i,) in db.execute('SELECT id FROM issues')}
    for customer in data:
        manual = locations.get(customer['issue_id'])
        customer['location'] = manual or customer.get('candidate_location')
        customer['location_source'] = 'Ručně potvrzeno' if manual else customer.get('candidate_source', '')
        customer['in_open_issues'] = customer['issue_id'] in issue_ids
    return {'customers': data, 'map_configured': bool(MAP_KEY), 'base_url': BASE}

def related_issues(customer_id):
    if customer_id not in {c['issue_id'] for c in customers()['customers']}:
        raise ValueError('Zákazník nebyl nalezen.')
    if not KEY:
        raise ValueError('Chybí REDMINE_API_KEY.')
    found = []
    for item in snapshot()['issues']:
        if item['id'] == customer_id:
            continue
        detail = request(f"/issues/{item['id']}.json", {'include': 'relations'})['issue']
        ids = {detail.get('parent', {}).get('id')}
        for relation in detail.get('relations', []):
            ids.update((relation.get('issue_id'), relation.get('issue_to_id')))
        if customer_id in ids:
            found.append({'id': item['id'], 'subject': item.get('subject', ''), 'status': item.get('status', {}).get('name', '')})
    return found


def save_location(iid, lat, lon):
    import math
    if iid not in {c['issue_id'] for c in customers()['customers']}:
        raise ValueError('Zákazník nebyl nalezen.')
    lat, lon = float(lat), float(lon)
    if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError('Neplatné souřadnice.')
    with connect() as db:
        db.execute('INSERT INTO customer_locations VALUES (?, ?, ?) ON CONFLICT(issue_id) DO UPDATE SET lat=excluded.lat, lon=excluded.lon', (iid, lat, lon))


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
        elif self.path == '/mapa':
            self.send(Path(__file__).with_name('mapa.html').read_bytes(), 'text/html; charset=utf-8')
        elif self.path in ('/vendor/leaflet/leaflet.js', '/vendor/leaflet/leaflet.css'):
            asset = Path(__file__).parent / self.path.lstrip('/')
            self.send(asset.read_bytes(), 'text/javascript; charset=utf-8' if self.path.endswith('.js') else 'text/css; charset=utf-8')
        elif self.path == '/api/customers':
            self.send(customers())
        elif self.path.startswith('/maptiles/'):
            match = re.fullmatch(r'/maptiles/(\d{1,2})/(\d{1,7})/(\d{1,7})', self.path)
            if not match or not MAP_KEY:
                self.send({'error': 'Mapový podklad není nastaven.'}, status=404); return
            z, x, y = map(int, match.groups())
            if z > 19 or x >= 2**z or y >= 2**z:
                self.send({'error': 'Neplatná dlaždice.'}, status=400); return
            try:
                url = f'https://api.mapy.com/v1/maptiles/basic/256/{z}/{x}/{y}?' + urllib.parse.urlencode({'apikey': MAP_KEY})
                with urllib.request.urlopen(url, timeout=15) as response:
                    self.send(response.read(), response.headers.get('Content-Type', 'image/png'))
            except Exception:
                self.send({'error': 'Mapový podklad není dostupný.'}, status=502)
        elif self.path == '/api/overview':
            self.send(snapshot())
        else:
            self.send({'error': 'Nenalezeno'}, status=404)
    def do_POST(self):
        if self.headers.get('Origin') not in (None, 'http://127.0.0.1:' + str(self.server.server_port), 'http://localhost:' + str(self.server.server_port)):
            self.send({'error':'Nepovolený původ'}, status=403); return
        try:
            if self.path.startswith('/api/customer-issues/'):
                iid = int(self.path.rsplit('/', 1)[1])
                self.send({'issues': related_issues(iid)})
            elif self.path.startswith('/api/location/'):
                iid = int(self.path.rsplit('/', 1)[1])
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 1024: raise ValueError('Neplatný požadavek.')
                body = json.loads(self.rfile.read(length))
                save_location(iid, body['lat'], body['lon'])
                self.send({'ok': True})
            elif self.path == '/api/sync':
                self.send({'count': sync()})
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
