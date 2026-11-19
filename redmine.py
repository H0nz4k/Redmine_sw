import json
import hashlib
import re
from contextlib import contextmanager
from functools import lru_cache
import os
import sqlite3
import socketserver
import socket
import struct
import stat
import threading
import time
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timezone
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from suggestions import customer_suggestions
from auto_customer import decide_customer
from triage import analyze_issue
import daily_digest
import henk_redaction
import realization_create

BASE = os.environ.get('REDMINE_URL', 'https://redmine.altisima.cz').rstrip('/')
KEY = os.environ.get('REDMINE_API_KEY', '')
DB = os.environ.get('REDMINE_DB', 'redmine.sqlite3')
INTERVAL = int(os.environ.get('SYNC_SECONDS', '300'))
CUSTOMER_SCAN_INTERVAL = max(900, int(os.environ.get('CUSTOMER_SCAN_SECONDS', '3600')))
MODEL = os.environ.get('OLLAMA_MODEL', '')
MAP_KEY = os.environ.get('MAPY_API_KEY', '')
CUSTOMERS = Path(os.environ.get('CUSTOMERS_FILE', 'data/customers.json'))
UNIX_SOCKET = os.environ.get('REDMINE_UNIX_SOCKET', '')
VOICE_SOCKET = os.environ.get('REDMINE_VOICE_SOCKET', '')
ALLOWED_ORIGINS = {value.strip() for value in os.environ.get('REDMINE_ALLOWED_ORIGINS', '').split(',') if value.strip()}
AUTO_CUSTOMER_MODE = os.environ.get('REDMINE_AUTO_CUSTOMER_LINK', 'dry-run').strip().lower()

@lru_cache(maxsize=1)
def app_version():
    """Identify the actual running code, including deployments without a .git directory."""
    root = Path(__file__).resolve().parent
    name = (root / 'VERSION').read_text(encoding='utf-8').strip() if (root / 'VERSION').exists() else 'unversioned'
    fingerprint = hashlib.sha256()
    for filename in ('VERSION', 'redmine.py', 'index.html', 'mapa.html', 'triage.py', 'daily_digest.py', 'denni-prehled.html', 'henk_digest.py', 'henk_mcp.py', 'henk_redaction.py', 'appearance.css', 'appearance.js', 'realizace.js', 'realization_create.py', 'auto_customer.py'):
        path = root / filename
        if path.exists():
            fingerprint.update(filename.encode('utf-8') + b'\0' + path.read_bytes())
    return {'number': name, 'build': fingerprint.hexdigest()[:10]}

WORDS = ('terminál', 'terminal', 'snímač', 'snímac', 'čtečk', 'cteck', 'tiskárn', 'tiskarn', 'klávesnic', 'klavesnic', 'reproduktor', 'hardware', 'počítač', 'pocitac', ' pc ', 'pc box')

def request(path, params=None):
    url = BASE + path + ('?' + urllib.parse.urlencode(params) if params else '')
    req = urllib.request.Request(url, headers={'X-Redmine-API-Key': KEY, 'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


class _DigestNoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def digest_request(path, params=None):
    """Only Redmine issue, project and status endpoints; never follow redirects."""
    params = params or {}
    if path == '/issues.json':
        allowed = {'status_id', 'updated_on', 'created_on', 'project_id', 'limit', 'offset'}
        if 'project_id' in params and params['project_id'] != 'helpdesk':
            raise ValueError('Nepovolený projekt hlasového přehledu.')
    elif path == '/projects.json':
        allowed = {'limit', 'offset'}
    elif path == '/issue_statuses.json':
        allowed = set()
    elif re.fullmatch(r'/issues/[1-9][0-9]*\.json', path):
        if params != {'include': 'journals'}:
            raise ValueError('Nepovolené parametry historie Redmine.')
        allowed = {'include'}
    else:
        raise ValueError('Nepovolený zdroj podkladů Redmine.')
    if set(params) - allowed:
        raise ValueError('Nepovolené parametry podkladů Redmine.')
    url = BASE + path + ('?' + urllib.parse.urlencode(params) if params else '')
    req = urllib.request.Request(url, headers={'X-Redmine-API-Key': KEY, 'Accept': 'application/json'})
    opener = urllib.request.build_opener(_DigestNoRedirect())
    with opener.open(req, timeout=30) as response:
        return json.load(response)


def _issues_with(requester, params):
    offset = 0
    while True:
        data = requester('/issues.json', {**params, 'limit': 100, 'offset': offset})
        batch = data['issues']
        yield from batch
        offset += len(batch)
        if not batch or offset >= data['total_count']:
            break


def issues(params):
    yield from _issues_with(request, params)


def digest_issues(params):
    yield from _issues_with(digest_request, params)


def voice_helpdesk_today(now=None, requester=digest_request):
    """Fetch only new Helpdesk issues, without attachments or issue links."""
    now = daily_digest._utc(now or datetime.now(timezone.utc))
    today = now.astimezone(daily_digest.TZ).date()
    query_day = (today - timedelta(days=1)).isoformat()
    rows = []
    for offset in range(0, 500, 100):
        page = requester('/issues.json', {'project_id': 'helpdesk', 'status_id': '*',
                         'created_on': '>=' + query_day, 'limit': 100, 'offset': offset})
        items, total = page['issues'], page['total_count']
        if not isinstance(items, list) or type(total) is not int or total < 0:
            raise ValueError('Redmine vrátil neplatný seznam.')
        for issue in items:
            iid = issue.get('id')
            if type(iid) is not int or iid <= 0:
                raise ValueError('Redmine vrátil neplatné ID.')
            created = daily_digest._utc(issue['created_on'])
            if created <= now and created.astimezone(daily_digest.TZ).date() == today:
                title = henk_redaction.text(issue.get('subject') or '')
                title = re.sub(r'\s+', ' ', title).strip()
                if len(title) > 120:
                    title = title[:117] + '...'
                rows.append({'id': iid, 'subject': title})
        if offset + len(items) >= total:
            break
        if not items:
            raise ValueError('Redmine vrátil neúplný seznam.')
    else:
        raise ValueError('Příliš mnoho výsledků pro úplný hlasový přehled.')
    if len({row['id'] for row in rows}) != len(rows):
        raise ValueError('Redmine vrátil duplicitní požadavek.')
    return {'day': today.isoformat(), 'count': len(rows), 'items': rows[:5],
            'remaining': max(0, len(rows)-5)}

def classify(issue):
    content = ' ' + (issue.get('subject', '') + ' ' + (issue.get('description') or '')).lower() + ' '
    return [word.strip() for word in WORDS if word in content]

@contextmanager
def connect():
    db = sqlite3.connect(DB, timeout=30)
    db.execute('CREATE TABLE IF NOT EXISTS issues (id INTEGER PRIMARY KEY, payload TEXT NOT NULL, updated TEXT NOT NULL, first_seen TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, issue_id INTEGER NOT NULL, kind TEXT NOT NULL, seen_at TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS issue_customer_suggestions (issue_id INTEGER PRIMARY KEY, updated TEXT NOT NULL, payload TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS issue_customer_links (issue_id INTEGER PRIMARY KEY, updated TEXT NOT NULL, payload TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS auto_customer_audit (id INTEGER PRIMARY KEY AUTOINCREMENT, issue_id INTEGER NOT NULL, updated TEXT NOT NULL, outcome TEXT NOT NULL, customer_id INTEGER, reason TEXT NOT NULL, checked_at TEXT NOT NULL)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_auto_customer_issue ON auto_customer_audit(issue_id, id)')
    db.execute('CREATE TABLE IF NOT EXISTS customer_issue_status (issue_id INTEGER PRIMARY KEY, payload TEXT NOT NULL, checked_at TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS added_customers (issue_id INTEGER PRIMARY KEY, name TEXT NOT NULL, address TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS customer_locations (issue_id INTEGER PRIMARY KEY, lat REAL NOT NULL, lon REAL NOT NULL)')
    try:
        with db:
            yield db
    finally:
        db.close()

def find_issue_customers(issue_id):
    detail = request(f'/issues/{issue_id}.json', {'include': 'relations'})['issue']
    ids = {detail.get('parent', {}).get('id')}
    for rel in detail.get('relations', []):
        ids.add(rel.get('issue_to_id') if rel.get('issue_id') == issue_id else rel.get('issue_id'))
    ids.discard(None); ids.discard(issue_id)
    found = []
    ordered = sorted(ids)
    for n in range(0, len(ordered), 100):
        for item in issues({'issue_id': ','.join(map(str, ordered[n:n+100])), 'project_id': 'zakaznici', 'tracker_id': 4, 'status_id': '*'}):
            if item['id'] in ids and item.get('project', {}).get('id') == 1 and item.get('tracker', {}).get('id') == 4:
                found.append({'id': item['id'], 'name': item.get('subject', '')})
    return found


sync_close_lock = threading.RLock()

def sync():
    with sync_close_lock:
        return _sync()

def _sync():
    if not KEY:
        raise ValueError('Chybí REDMINE_API_KEY.')
    me = request('/users/current.json')['user']['id']
    collected = {}
    for params in ({'assigned_to_id': 'me', 'status_id': 'open'}, {'project_id': 'helpdesk', 'status_id': 'open'}):
        for issue in issues(params):
            collected[issue['id']] = issue
    with connect() as db:
        previous_links = dict(db.execute('SELECT issue_id, updated FROM issue_customer_links'))
    link_updates = {}
    for issue in collected.values():
        if previous_links.get(issue['id']) != issue['updated_on']:
            try:
                link_updates[issue['id']] = find_issue_customers(issue['id'])
            except Exception:
                link_updates[issue['id']] = None
    catalog = None
    try:
        catalog = matching_customers()
        proposals = {i['id']: customer_suggestions(i.get('subject', ''), i.get('description', ''), catalog)
                     for i in collected.values() if i.get('project', {}).get('id') == 12}
    except Exception:
        proposals = None
    now = datetime.now(timezone.utc).isoformat()
    with connect() as db:
        initial = db.execute("SELECT value FROM meta WHERE key='last_sync'").fetchone() is None
        previous = {row[0]: row[1] for row in db.execute('SELECT id, updated FROM issues')}
        for issue in collected.values():
            iid = issue['id']
            if proposals is not None and iid in proposals:
                db.execute('INSERT INTO issue_customer_suggestions VALUES (?, ?, ?) ON CONFLICT(issue_id) DO UPDATE SET updated=excluded.updated, payload=excluded.payload', (iid, issue['updated_on'], json.dumps(proposals[iid], ensure_ascii=False)))
            if iid in link_updates:
                links = link_updates[iid]
                if links is None:
                    db.execute('DELETE FROM issue_customer_links WHERE issue_id=?', (iid,))
                else:
                    db.execute('INSERT INTO issue_customer_links VALUES (?, ?, ?) ON CONFLICT(issue_id) DO UPDATE SET updated=excluded.updated, payload=excluded.payload', (iid, issue['updated_on'], json.dumps(links, ensure_ascii=False)))
            if not initial and (iid not in previous or previous[iid] != issue['updated_on']):
                db.execute('INSERT INTO events(issue_id,kind,seen_at) VALUES (?,?,?)', (iid, 'new' if iid not in previous else 'updated', now))
            db.execute('INSERT INTO issues VALUES (?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, updated=excluded.updated', (iid, json.dumps(issue, ensure_ascii=False), issue['updated_on'], now))
        for (old_id,) in db.execute('SELECT id FROM issues').fetchall():
            if old_id not in collected:
                db.execute('DELETE FROM issues WHERE id=?', (old_id,))
                db.execute('DELETE FROM issue_customer_suggestions WHERE issue_id=?', (old_id,))
        for k,v in [('last_sync', now), ('user_id', str(me)), ('error', '')]:
            db.execute('INSERT INTO meta VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (k,v))
    if catalog is not None and AUTO_CUSTOMER_MODE in ('dry-run', 'write'):
        auto_link_customers(collected, catalog)
    return len(collected)

def _auto_customer_audit(iid, updated, outcome, customer_id, reason):
    with connect() as db:
        db.execute(
            'INSERT INTO auto_customer_audit(issue_id,updated,outcome,customer_id,reason,checked_at) VALUES (?,?,?,?,?,?)',
            (iid, updated, outcome, customer_id, reason, datetime.now(timezone.utc).isoformat())
        )


def auto_link_customers(collected, catalog):
    """Match against Redmine customer cards; only write with explicit opt-in.

    Called under sync_close_lock. Avoid repeating any uncertain remote write,
    including after a subsequent update to the Helpdesk issue.
    """
    if AUTO_CUSTOMER_MODE not in ('dry-run', 'write'):
        return
    with connect() as db:
        existing = {
            iid: json.loads(payload)
            for iid, payload in db.execute('SELECT issue_id,payload FROM issue_customer_links')
        }
        history = {}
        for iid, updated, outcome in db.execute(
            'SELECT issue_id,updated,outcome FROM auto_customer_audit ORDER BY id'
        ):
            history.setdefault(iid, []).append((updated, outcome))
    for issue in collected.values():
        if issue.get('project', {}).get('id') != 12:
            continue
        iid, updated = issue['id'], issue['updated_on']
        if iid not in existing or existing[iid]:
            # Missing cache can mean an API failure: fail closed.
            continue
        past = history.get(iid, [])
        if any(outcome in ('written', 'uncertain') for _, outcome in past):
            continue
        if any(version == updated and (
            outcome in ('review', 'none', 'existing', 'changed') or
            (outcome == 'dry-run' and AUTO_CUSTOMER_MODE == 'dry-run')
        ) for version, outcome in past):
            continue
        try:
            detail = request(f'/issues/{iid}.json', {'include': 'relations'})['issue']
            if detail.get('project', {}).get('id') != 12 or detail.get('updated_on') != updated:
                _auto_customer_audit(iid, updated, 'changed', None, 'Požadavek se během kontroly změnil.')
                continue
            decision = decide_customer(detail, catalog)
            if decision['status'] != 'auto':
                _auto_customer_audit(iid, updated, decision['status'], None, decision['reason'])
                continue
            target = decision['customer_id']
            if AUTO_CUSTOMER_MODE == 'dry-run':
                _auto_customer_audit(iid, updated, 'dry-run', target, decision['reason'])
                continue
            # Fresh check before writing; do not override a hand-linked customer.
            if find_issue_customers(iid):
                _auto_customer_audit(iid, updated, 'existing', None, 'Požadavek už má zákazníka.')
                continue
            _apply_helpdesk_change(iid, 'customer', target, updated, helpdesk_state_token(detail))
            _auto_customer_audit(iid, updated, 'written', target, decision['reason'])
        except ValueError:
            _auto_customer_audit(iid, updated, 'changed', None, 'Propojení vyžaduje novou kontrolu.')
        except Exception:
            # Some remote writes can succeed despite network errors. Never
            # replay until a human checks the actual Redmine issue.
            _auto_customer_audit(iid, updated, 'uncertain', None, 'Výsledek kontroly či zápisu není potvrzen; ověřte Redmine.')


def snapshot():
    with connect() as db:
        meta = dict(db.execute('SELECT key,value FROM meta'))
        data = [json.loads(row[0]) for row in db.execute('SELECT payload FROM issues ORDER BY updated DESC')]
        proposals = {i: (updated, json.loads(payload)) for i, updated, payload in db.execute('SELECT issue_id, updated, payload FROM issue_customer_suggestions')}
        direct_links = {i: json.loads(payload) for i, payload in db.execute('SELECT issue_id, payload FROM issue_customer_links')}
        events = [{'issue_id': i, 'kind': k, 'seen_at': t} for i,k,t in db.execute('SELECT issue_id,kind,seen_at FROM events ORDER BY id DESC LIMIT 100')]
    customer_links = {}
    for customer in customers()['customers']:
        for related in (customer.get('related_status') or {}).get('issues', []):
            customer_links.setdefault(related['id'], []).append({'id': customer['issue_id'], 'name': customer['name']})
    for issue in data:
        links = direct_links.get(issue['id'], customer_links.get(issue['id'], []))
        issue['customers'] = list({c['id']: c for c in links}.values())
        cached = proposals.get(issue['id'])
        issue['customer_suggestions'] = cached[1] if cached and cached[0] == issue.get('updated_on') and not issue['customers'] else []
        issue['hardware_reasons'] = classify(issue)
        issue['triage'] = analyze_issue(issue)
        issue['mine'] = str(issue.get('assigned_to', {}).get('id', '')) == meta.get('user_id')
    return {'issues': data, 'events': events, 'last_sync': meta.get('last_sync'), 'error': meta.get('error'), 'configured': bool(KEY), 'ai_configured': bool(MODEL), 'base_url': BASE, 'version': app_version()}

def customers():
    data = json.loads(CUSTOMERS.read_text(encoding='utf-8')) if CUSTOMERS.exists() else []
    with connect() as db:
        stored_ids = {c['issue_id'] for c in data}
        data.extend({'issue_id': i, 'name': n, 'address': a, 'poe': '', 'origin': 'Redmine'} for i, n, a in db.execute('SELECT issue_id, name, address FROM added_customers') if i not in stored_ids)
        locations = {i: (lat, lon) for i, lat, lon in db.execute('SELECT issue_id, lat, lon FROM customer_locations')}
        issue_ids = {i for (i,) in db.execute('SELECT id FROM issues')}
        states = {i: json.loads(payload) for i, payload in db.execute('SELECT issue_id, payload FROM customer_issue_status')}
    for customer in data:
        manual = locations.get(customer['issue_id'])
        customer['location'] = manual or customer.get('candidate_location')
        customer['location_source'] = 'Ručně potvrzeno' if manual else customer.get('candidate_source', '')
        customer['in_open_issues'] = customer['issue_id'] in issue_ids
        customer['related_status'] = states.get(customer['issue_id'])
    return {'customers': data, 'map_configured': bool(MAP_KEY), 'base_url': BASE}

def matching_customers():
    # Only explicitly relevant contact fields are used, in memory and never returned to clients.
    allowed = {'Email', 'Kontakt vedoucí stravování', 'Kontakt ředitel', 'Kontakt IT'}
    result = []
    for item in issues({'project_id': 'zakaznici', 'tracker_id': 4, 'status_id': '*' }):
        if item.get('project', {}).get('id') != 1 or item.get('tracker', {}).get('id') != 4:
            continue
        fields = {f.get('name'): f.get('value') for f in item.get('custom_fields', []) if f.get('name') in allowed | {'Adresa'}}
        result.append({'id': item['id'], 'name': item.get('subject', ''), 'address': fields.get('Adresa') or '',
                       'contacts': [value for key, value in fields.items() if key in allowed and isinstance(value, str)],
                       'lead_contact': fields.get('Kontakt vedoucí stravování') or '',
                       'email_contact': fields.get('Email') or ''})
    return result


def redmine_customers():
    if not KEY:
        raise ValueError('Chybí REDMINE_API_KEY.')
    present = {c['issue_id'] for c in customers()['customers']}
    result = []
    for item in issues({'project_id': 'zakaznici', 'tracker_id': 4, 'status_id': '*'}):
        fields = {f.get('name'): f.get('value') for f in item.get('custom_fields', [])}
        result.append({'id': item['id'], 'name': item.get('subject', ''),
                       'address': fields.get('Adresa') or '', 'gps': fields.get('GPS') or '',
                       'status': item.get('status', {}).get('name', ''), 'in_map': item['id'] in present})
    return result

def customer_details(iid):
    if iid not in {c['issue_id'] for c in customers()['customers']}:
        raise ValueError('Zákazník nebyl nalezen.')
    if not KEY:
        raise ValueError('Chybí REDMINE_API_KEY.')
    item = request(f'/issues/{iid}.json')['issue']
    if item.get('project', {}).get('id') != 1 or item.get('tracker', {}).get('id') != 4:
        raise ValueError('Záznam není zákazník v projektu Zákazníci.')
    fields = {f.get('name'): f.get('value') for f in item.get('custom_fields', [])}
    return {'name': item.get('subject', ''), 'address': fields.get('Adresa') or '', 'gps': fields.get('GPS') or ''}


def add_redmine_customer(iid):
    if not KEY:
        raise ValueError('Chybí REDMINE_API_KEY.')
    item = request(f'/issues/{iid}.json')['issue']
    if item.get('project', {}).get('id') != 1 or item.get('tracker', {}).get('id') != 4:
        raise ValueError('Záznam není zákazník v projektu Zákazníci.')
    fields = {f.get('name'): f.get('value') for f in item.get('custom_fields', [])}
    address = fields.get('Adresa') or ''
    if not isinstance(address, str): address = ''
    with connect() as db:
        db.execute('INSERT INTO added_customers VALUES (?, ?, ?) ON CONFLICT(issue_id) DO NOTHING',
                   (iid, item.get('subject', ''), address))


def helpdesk_members():
    members = []
    offset = 0
    while True:
        data = request('/projects/helpdesk/memberships.json', {'limit': 100, 'offset': offset})
        batch = data['memberships']
        members.extend(m['user'] for m in batch if m.get('user'))
        offset += len(batch)
        if not batch or offset >= data.get('total_count', len(batch)):
            break
    return list({m['id']: m for m in members}.values())

def helpdesk_state_token(issue):
    relations = sorted((r.get('issue_id', 0), r.get('issue_to_id', 0), r.get('relation_type', '')) for r in issue.get('relations', []))
    state = {'updated_on': issue.get('updated_on'), 'subject': issue.get('subject'), 'description': issue.get('description'),
             'assignee': issue.get('assigned_to', {}).get('id'), 'status': issue.get('status', {}).get('id'),
             'parent': issue.get('parent', {}).get('id'), 'relations': relations}
    return hashlib.sha256(json.dumps(state, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()


def helpdesk_suggestions(iid):
    issue = request(f'/issues/{iid}.json', {'include': 'relations'})['issue']
    if issue.get('project', {}).get('id') != 12:
        raise ValueError('Nejde o požadavek projektu Helpdesk.')
    all_customers = matching_customers()
    members = helpdesk_members()
    reasons = classify(issue)
    matches = [m for m in members if str(m.get('name', '')).strip().casefold() == 'honza']
    person = matches[0] if reasons and len(matches) == 1 else None
    return {'issue_id': iid, 'updated_on': issue['updated_on'], 'state_token': helpdesk_state_token(issue), 'subject': issue.get('subject', ''),
            'assigned_to': issue.get('assigned_to'), 'linked_customers': find_issue_customers(iid),
            'customer_candidates': customer_suggestions(issue.get('subject', ''), issue.get('description', ''), all_customers),
            'assignee_suggestion': {'id': person['id'], 'name': person['name'],
                                    'reason': 'Možný hardware: ' + ', '.join(reasons)} if person else None,
            'assignee_unavailable_reason': ('Účet honza nelze jednoznačně ověřit mezi členy Helpdesku.' if reasons and len(matches) != 1 else ''),
            'members': members}


def redmine_write(path, method, payload):
    body = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(BASE + path, data=body, method=method,
                                 headers={'X-Redmine-API-Key': KEY, 'Content-Type': 'application/json', 'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            response.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f'Redmine změnu odmítl (HTTP {exc.code}).') from None
    except (OSError, TimeoutError):
        raise RuntimeError('Výsledek zápisu není znám. Před opakováním zkontrolujte Redmine.') from None

def _apply_helpdesk_change(iid, action, target, expected_updated, expected_token):
    if not KEY or not isinstance(target, int) or isinstance(target, bool) or target <= 0 or not isinstance(expected_updated, str):
        raise ValueError('Neplatné údaje požadavku.')
    current = request(f'/issues/{iid}.json', {'include': 'relations'})['issue']
    if current.get('project', {}).get('id') != 12:
        raise ValueError('Nejde o požadavek projektu Helpdesk.')
    if current.get('updated_on') != expected_updated or helpdesk_state_token(current) != expected_token:
        raise ValueError('Požadavek se mezitím změnil. Načtěte návrhy znovu.')
    if action == 'assignee':
        if target not in {m['id'] for m in helpdesk_members()}:
            raise ValueError('Řešitel není mezi členy projektu Helpdesk.')
        if current.get('assigned_to', {}).get('id') == target:
            raise ValueError('Řešitel je již přiřazen.')
        redmine_write(f'/issues/{iid}.json', 'PUT', {'issue': {'assigned_to_id': target}})
    elif action == 'customer':
        customer = request(f'/issues/{target}.json')['issue']
        if customer.get('project', {}).get('id') != 1 or customer.get('tracker', {}).get('id') != 4:
            raise ValueError('Cílový záznam není zákazník v projektu Zákazníci.')
        related = {r.get('issue_to_id') if r.get('issue_id') == iid else r.get('issue_id') for r in current.get('relations', [])}
        if target in related or current.get('parent', {}).get('id') == target:
            raise ValueError('Zákazník je již propojen.')
        redmine_write(f'/issues/{iid}/relations.json', 'POST', {'relation': {'issue_to_id': target, 'relation_type': 'relates'}})
    else:
        raise ValueError('Neznámý typ změny.')
    with connect() as db:
        cached_row = db.execute('SELECT payload FROM issue_customer_links WHERE issue_id=?', (iid,)).fetchone()
        cached_links = json.loads(cached_row[0]) if cached_row else []
        db.execute('DELETE FROM issue_customer_links WHERE issue_id=?', (iid,))
    try:
        result = request(f'/issues/{iid}.json', {'include': 'relations'})['issue']
    except Exception:
        raise RuntimeError('Změna byla odeslána, ale její výsledek nelze ověřit. Před opakováním zkontrolujte Redmine.')
    if action == 'assignee' and result.get('assigned_to', {}).get('id') != target:
        raise RuntimeError('Redmine nepotvrdil zvolené přiřazení. Zkontrolujte úkol.')
    if action == 'customer':
        linked_ids = {r.get('issue_to_id') if r.get('issue_id') == iid else r.get('issue_id') for r in result.get('relations', [])}
        if target not in linked_ids:
            raise RuntimeError('Redmine nepotvrdil novou vazbu. Zkontrolujte úkol.')
        linked_ids.add(result.get('parent', {}).get('id'))
        links = [c for c in cached_links if c.get('id') in linked_ids and c.get('id') != target]
        links.append({'id': target, 'name': customer.get('subject', '')})
        with connect() as db:
            db.execute('INSERT INTO issue_customer_links VALUES (?, ?, ?) ON CONFLICT(issue_id) DO UPDATE SET updated=excluded.updated, payload=excluded.payload',
                       (iid, result.get('updated_on') or expected_updated, json.dumps(links, ensure_ascii=False)))
    return {'ok': True}


helpdesk_write_lock = threading.Lock()

def apply_helpdesk_change(iid, action, target, expected_updated, expected_token):
    with helpdesk_write_lock, sync_close_lock:
        return _apply_helpdesk_change(iid, action, target, expected_updated, expected_token)



def map_link_prepare(iid):
    if not KEY:
        raise ValueError('Chybí REDMINE_API_KEY.')
    matches = list(issues({'issue_id': str(iid), 'assigned_to_id': 'me', 'status_id': 'open'}))
    if not any(i.get('id') == iid for i in matches):
        raise ValueError('Úkol není otevřený nebo není přiřazen přihlášenému uživateli.')
    current = request(f'/issues/{iid}.json', {'include': 'relations'})['issue']
    return {'issue_id': iid, 'subject': current.get('subject', ''), 'updated_on': current.get('updated_on'),
            'state_token': helpdesk_state_token(current), 'linked_customers': find_issue_customers(iid)}


def map_link_customer(iid, target, expected_updated, expected_token):
    if not isinstance(target, int) or isinstance(target, bool) or target <= 0:
        raise ValueError('Neplatný zákazník.')
    with helpdesk_write_lock, sync_close_lock:
        prepared = map_link_prepare(iid)
        if prepared['updated_on'] != expected_updated or prepared['state_token'] != expected_token:
            raise ValueError('Úkol se mezitím změnil. Načtěte jej znovu.')
        if prepared['linked_customers']:
            raise ValueError('Úkol už má propojenou provozovnu. Zkontrolujte ji v Redmine.')
        customer = request(f'/issues/{target}.json')['issue']
        if customer.get('project', {}).get('id') != 1 or customer.get('tracker', {}).get('id') != 4:
            raise ValueError('Cílový záznam není zákazník v projektu Zákazníci.')
        if target not in {c['issue_id'] for c in customers()['customers']}:
            raise ValueError('Zákazník není v mapovém seznamu.')
        redmine_write(f'/issues/{iid}/relations.json', 'POST', {'relation': {'issue_to_id': target, 'relation_type': 'relates'}})
        with connect() as db:
            db.execute('DELETE FROM issue_customer_links WHERE issue_id=?', (iid,))
        try:
            result = request(f'/issues/{iid}.json', {'include': 'relations'})['issue']
        except Exception:
            raise RuntimeError('Vazba byla odeslána, ale výsledek nelze ověřit. Před opakováním zkontrolujte Redmine.') from None
        ids = {r.get('issue_to_id') if r.get('issue_id') == iid else r.get('issue_id') for r in result.get('relations', [])}
        if target not in ids:
            raise RuntimeError('Redmine nepotvrdil novou vazbu. Zkontrolujte úkol.')
        links = [{'id': target, 'name': customer.get('subject', '')}]
        with connect() as db:
            db.execute('INSERT INTO issue_customer_links VALUES (?, ?, ?) ON CONFLICT(issue_id) DO UPDATE SET updated=excluded.updated, payload=excluded.payload',
                       (iid, result.get('updated_on') or expected_updated, json.dumps(links, ensure_ascii=False)))
        return {'ok': True}


def close_issue(iid, expected_updated):
    if not KEY or not isinstance(expected_updated, str) or not expected_updated:
        raise ValueError('Neplatné údaje požadavku.')
    with sync_close_lock:
        with connect() as db:
            row = db.execute('SELECT updated FROM issues WHERE id=?', (iid,)).fetchone()
        if not row or row[0] != expected_updated:
            raise ValueError('Požadavek již není v přehledu nebo se změnil. Načtěte přehled znovu.')
        current = request(f'/issues/{iid}.json', {'include': 'allowed_statuses'})['issue']
        if current.get('updated_on') != expected_updated:
            raise ValueError('Požadavek se mezitím změnil. Načtěte přehled znovu.')
        allowed = current.get('allowed_statuses')
        if not isinstance(allowed, list):
            raise ValueError('Redmine neposkytl povolené stavy. Uzavřete požadavek přímo v Redmine.')
        statuses = request('/issue_statuses.json')['issue_statuses']
        closed_ids = {s['id'] for s in statuses if s.get('is_closed') is True}
        choices = [s for s in allowed if s.get('id') in closed_ids]
        if len(choices) != 1:
            raise ValueError('Nelze jednoznačně určit povolený uzavřený stav. Uzavřete požadavek přímo v Redmine.')
        target = choices[0]['id']
        redmine_write(f'/issues/{iid}.json', 'PUT', {'issue': {'status_id': target}})
        try:
            result = request(f'/issues/{iid}.json')['issue']
        except Exception:
            raise RuntimeError('Změna byla odeslána, ale výsledek nelze ověřit. Před opakováním zkontrolujte Redmine.') from None
        if result.get('status', {}).get('id') != target:
            raise RuntimeError('Redmine nepotvrdil uzavření. Zkontrolujte požadavek v Redmine.')
        with connect() as db:
            db.execute('DELETE FROM issues WHERE id=?', (iid,))
            db.execute('DELETE FROM issue_customer_suggestions WHERE issue_id=?', (iid,))
        return {'ok': True}


def related_issues(customer_id):
    if customer_id not in {c['issue_id'] for c in customers()['customers']}:
        raise ValueError('Zákazník nebyl nalezen.')
    if not KEY:
        raise ValueError('Chybí REDMINE_API_KEY.')
    item = request(f'/issues/{customer_id}.json', {'include': 'relations,children'})['issue']
    ids = {r.get('issue_to_id') if r.get('issue_id') == customer_id else r.get('issue_id') for r in item.get('relations', [])}
    ids.update(c.get('id') for c in item.get('children', []))
    ids.discard(None); ids.discard(customer_id)
    results = []
    sorted_ids = sorted(ids)
    for i in range(0, len(sorted_ids), 100):
        batch = sorted_ids[i:i+100]
        for status in ('open', 'closed'):
            for issue in issues({'issue_id': ','.join(map(str, batch)), 'status_id': status}):
                if issue['id'] in ids:
                    results.append({'id': issue['id'], 'subject': issue.get('subject', ''),
                                    'status': issue.get('status', {}).get('name', ''), 'open': status == 'open'})
    known = {i['id'] for i in results}
    missing = len(ids - known)
    state = 'open' if any(i['open'] for i in results) else 'unknown' if missing else 'closed' if results else 'none'
    result = {'state': state, 'issues': results, 'inaccessible': missing,
              'checked_at': datetime.now(timezone.utc).isoformat()}
    with connect() as db:
        db.execute('INSERT INTO customer_issue_status VALUES (?, ?, ?) ON CONFLICT(issue_id) DO UPDATE SET payload=excluded.payload, checked_at=excluded.checked_at', (customer_id, json.dumps(result, ensure_ascii=False), result['checked_at']))
    return result

scan_lock = threading.Lock()
scan_state = {'running': False, 'done': 0, 'total': 0, 'errors': 0}

def scan_customer_issues():
    with scan_lock:
        if scan_state['running']:
            return
        ids = [c['issue_id'] for c in customers()['customers']]
        scan_state.update(running=True, done=0, total=len(ids), errors=0)
    def run():
        try:
            for iid in ids:
                try:
                    related_issues(iid)
                except Exception:
                    with connect() as db:
                        db.execute('DELETE FROM customer_issue_status WHERE issue_id=?', (iid,))
                    scan_state['errors'] += 1
                scan_state['done'] += 1
                time.sleep(0.1)
        finally:
            try:
                with connect() as db:
                    db.execute("INSERT INTO meta VALUES ('customer_scan_completed', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(time.time()),))
                    db.execute("INSERT INTO meta VALUES ('customer_scan_errors', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(scan_state['errors']),))
            finally:
                scan_state['running'] = False
    threading.Thread(target=run, daemon=True).start()


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
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            result = json.load(response).get('response')
    except urllib.error.HTTPError as exc:
        raise ValueError('Lokální model odmítl požadavek; ověřte, zda je model v Ollamě dostupný.') from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ValueError('Lokální AI není dostupná nebo neodpověděla včas.') from exc
    except (ValueError, AttributeError) as exc:
        raise ValueError('Lokální AI vrátila neplatnou odpověď.') from exc
    if not isinstance(result, str) or not result.strip():
        raise ValueError('Lokální AI nevrátila žádné shrnutí.')
    return result.strip()

def customer_scan_due(now=None):
    with connect() as db:
        meta = dict(db.execute("SELECT key, value FROM meta WHERE key IN ('customer_scan_completed', 'customer_scan_errors')"))
    try:
        completed = float(meta.get('customer_scan_completed', '0'))
        errors = int(meta.get('customer_scan_errors', '0'))
    except ValueError:
        return True
    interval = 900 if errors else CUSTOMER_SCAN_INTERVAL
    return (time.time() if now is None else now) - completed >= interval

def customer_scan_worker():
    while True:
        try:
            if KEY and customer_scan_due():
                scan_customer_issues()
        except Exception:
            pass
        time.sleep(60)


def digest_worker():
    """Local scheduled generation; missed runs catch up from last successful cutoff."""
    while True:
        try:
            if KEY and daily_digest.due(connect):
                daily_digest.generate_missed_reports(connect, digest_issues, digest_request, BASE)
                with connect() as db:
                    db.execute("INSERT INTO meta(key,value) VALUES('digest_error','') ON CONFLICT(key) DO UPDATE SET value=excluded.value")
        except Exception as exc:
            with connect() as db:
                db.execute("INSERT INTO meta(key,value) VALUES('digest_error',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(exc)[:300],))
        time.sleep(60)


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
        elif self.path == '/denni-prehled':
            self.send(Path(__file__).with_name('denni-prehled.html').read_bytes(), 'text/html; charset=utf-8')
        elif self.path in ('/appearance.css', '/appearance.js', '/realizace.js'):
            asset = Path(__file__).parent / self.path.lstrip('/')
            self.send(asset.read_bytes(), 'text/css; charset=utf-8' if self.path.endswith('.css') else 'text/javascript; charset=utf-8')
        elif self.path in ('/vendor/leaflet/leaflet.js', '/vendor/leaflet/leaflet.css'):
            asset = Path(__file__).parent / self.path.lstrip('/')
            self.send(asset.read_bytes(), 'text/javascript; charset=utf-8' if self.path.endswith('.js') else 'text/css; charset=utf-8')
        elif self.path.startswith('/api/realization-search?'):
            try:
                if not KEY: raise ValueError('Chybí REDMINE_API_KEY.')
                query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get('q', [''])[0]
                self.send(realization_create.search(query, lambda path, params=None: realization_create.api_request(BASE, KEY, path, params)))
            except ValueError as exc:
                self.send({'error':str(exc)[:200]}, status=400)
            except Exception:
                self.send({'error':'Hledání realizací se nezdařilo.'}, status=502)
        elif re.fullmatch(r'/api/realization-job/[0-9a-f]{32}', self.path):
            try:
                with connect() as db:
                    db.execute('CREATE TABLE IF NOT EXISTS realization_jobs (id TEXT PRIMARY KEY, plan_hash TEXT NOT NULL, result TEXT NOT NULL)')
                    row = db.execute('SELECT result FROM realization_jobs WHERE id=?', (self.path.rsplit('/', 1)[1],)).fetchone()
                self.send(json.loads(row[0]) if row else {'error':'Záznam o odeslání není k dispozici; ověřte Redmine.'}, status=200 if row else 404)
            except Exception:
                self.send({'error':'Stav nelze načíst.'}, status=500)
        elif re.fullmatch(r'/api/realization-prepare/[1-9][0-9]{0,11}', self.path):
            try:
                if not KEY: raise ValueError('Chybí REDMINE_API_KEY.')
                self.send(realization_create.prepare(int(self.path.rsplit('/', 1)[1]), lambda path, params=None: realization_create.api_request(BASE, KEY, path, params)))
            except Exception as exc:
                self.send({'error': str(exc)[:300]}, status=400)
        elif self.path == '/api/scan-status':
            self.send(dict(scan_state))
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
        elif self.path == '/api/version':
            self.send(app_version())
        elif self.path == '/api/digest/settings':
            value = daily_digest.get_settings(connect)
            with connect() as db:
                value['error'] = db.execute("SELECT value FROM meta WHERE key='digest_error'").fetchone()
            value['error'] = value['error'][0] if value['error'] else ''
            self.send(value)
        elif self.path == '/api/digest/history':
            self.send({'reports': daily_digest.history(connect)})
        elif self.path == '/api/digest/job':
            self.send(daily_digest.manual_job_status())
        elif self.path.startswith('/api/digest/excerpts?'):
            params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            try:
                self.send(daily_digest.read_source_excerpts(connect, params.get('day', [''])[0], BASE))
            except (ValueError, OSError):
                self.send({'error': 'Výňatky nejsou dostupné.'}, status=404)
        elif self.path.startswith('/api/digest/report?'):
            params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            day = params.get('day', [''])[0]
            try:
                self.send({'day': day, 'markdown': daily_digest.read_report(connect, day)})
            except (ValueError, FileNotFoundError) as exc:
                self.send({'error': str(exc)}, status=404)
        else:
            self.send({'error': 'Nenalezeno'}, status=404)
    def do_POST(self):
        allowed = {None, 'http://127.0.0.1:' + str(self.server.server_port), 'http://localhost:' + str(self.server.server_port)} | ALLOWED_ORIGINS
        if self.headers.get('Origin') not in allowed:
            self.send({'error':'Nepovolený původ'}, status=403); return
        try:
            if self.path == '/api/realization-create':
                if self.headers.get('Origin') is None or self.headers.get_content_type() != 'application/json':
                    self.send({'error': 'Nepovolený požadavek.'}, status=403); return
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 16384: raise ValueError('Neplatný požadavek.')
                if not KEY: raise ValueError('Chybí REDMINE_API_KEY.')
                body = json.loads(self.rfile.read(length))
                self.send(realization_create.create_batch(body, lambda path, params=None: realization_create.api_request(BASE, KEY, path, params), connect,
                    lambda issue: realization_create.create_http(BASE, KEY, issue)))
            elif self.path.startswith('/api/map-link-prepare/'):
                if self.headers.get('Origin') is None:
                    self.send({'error': 'Nepovolený požadavek.'}, status=403); return
                self.send(map_link_prepare(int(self.path.rsplit('/', 1)[1])))
            elif self.path.startswith('/api/map-link/'):
                if self.headers.get('Origin') is None or self.headers.get_content_type() != 'application/json':
                    self.send({'error': 'Nepovolený požadavek.'}, status=403); return
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 2048: raise ValueError('Neplatný požadavek.')
                body = json.loads(self.rfile.read(length))
                self.send(map_link_customer(int(self.path.rsplit('/', 1)[1]), body.get('target'), body.get('updated_on'), body.get('state_token')))
            elif self.path.startswith('/api/close-issue/'):
                if self.headers.get('Origin') is None or self.headers.get_content_type() != 'application/json':
                    self.send({'error': 'Nepovolený požadavek.'}, status=403); return
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 2048: raise ValueError('Neplatný požadavek.')
                body = json.loads(self.rfile.read(length))
                iid = int(self.path.rsplit('/', 1)[1])
                self.send(close_issue(iid, body.get('updated_on')))
            elif self.path.startswith('/api/helpdesk-apply/'):
                origin = self.headers.get('Origin')
                if origin not in allowed or origin is None or self.headers.get_content_type() != 'application/json':
                    self.send({'error': 'Nepovolený požadavek.'}, status=403); return
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 2048: raise ValueError('Neplatný požadavek.')
                body = json.loads(self.rfile.read(length))
                iid = int(self.path.rsplit('/', 1)[1])
                self.send(apply_helpdesk_change(iid, body.get('action'), body.get('target'), body.get('updated_on'), body.get('state_token')))
            elif self.path.startswith('/api/helpdesk-suggestions/'):
                iid = int(self.path.rsplit('/', 1)[1])
                self.send(helpdesk_suggestions(iid))
            elif self.path == '/api/scan-status':
                scan_customer_issues()
                self.send(dict(scan_state))
            elif self.path == '/api/redmine-customers':
                self.send({'customers': redmine_customers()})
            elif self.path.startswith('/api/customer-details/'):
                self.send(customer_details(int(self.path.rsplit('/', 1)[1])))
            elif self.path.startswith('/api/add-customer/'):
                add_redmine_customer(int(self.path.rsplit('/', 1)[1]))
                self.send({'ok': True})
            elif self.path.startswith('/api/customer-issues/'):
                iid = int(self.path.rsplit('/', 1)[1])
                self.send(related_issues(iid))
            elif self.path.startswith('/api/location/'):
                iid = int(self.path.rsplit('/', 1)[1])
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 1024: raise ValueError('Neplatný požadavek.')
                body = json.loads(self.rfile.read(length))
                save_location(iid, body['lat'], body['lon'])
                self.send({'ok': True})
            elif self.path == '/api/sync':
                self.send({'count': sync()})
            elif self.path in ('/api/digest/settings', '/api/digest/generate'):
                # Browser POST is a privileged local action; require the trusted Origin.
                if self.headers.get('Origin') is None or self.headers.get('Origin') not in allowed:
                    self.send({'error': 'Nepovolený původ.'}, status=403); return
                if self.path == '/api/digest/settings':
                    if self.headers.get_content_type() != 'application/json':
                        raise ValueError('Očekáván JSON.')
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= 256:
                        raise ValueError('Neplatná délka nastavení.')
                    body = json.loads(self.rfile.read(length))
                    self.send(daily_digest.set_time(connect, body.get('time')))
                else:
                    if not KEY:
                        raise ValueError('Chybí REDMINE_API_KEY.')
                    result = daily_digest.launch_manual_report(connect, digest_issues, digest_request, BASE)
                    self.send(result, status=202 if result.get('accepted') else 409)
            elif self.path.startswith('/api/summary/'):
                iid = int(self.path.rsplit('/', 1)[1])
                issue = next((i for i in snapshot()['issues'] if i['id'] == iid), None)
                if not issue: raise ValueError('Úkol nebyl nalezen.')
                self.send({'summary': summary(issue)})
            else:
                self.send({'error':'Nenalezeno'}, status=404)
        except Exception as exc:
            self.send({'error':str(exc)[:300]}, status=400)

if hasattr(socketserver, 'UnixStreamServer'):
    class VoiceHandler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            try:
                _, uid, _ = struct.unpack('3i', self.connection.getsockopt(
                    socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i')))
                if uid != os.getuid() or self.path != '/helpdesk/today':
                    self.send_error(403)
                    return
                payload = json.dumps(voice_helpdesk_today(), ensure_ascii=False).encode('utf-8')
                self.send_response(200)
            except Exception:
                payload = b'{"error":"helpdesk_unavailable"}'
                self.send_response(503)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    class VoiceUnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
        daemon_threads = True

        def __init__(self, path):
            self.server_name = 'localhost'
            self.server_port = 0
            parent = Path(path).parent
            info = parent.stat()
            if info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise RuntimeError('Nezabezpečený adresář hlasového socketu.')
            if os.path.lexists(path):
                existing = os.lstat(path)
                if existing.st_uid != os.getuid() or not stat.S_ISSOCK(existing.st_mode):
                    raise RuntimeError('Cesta hlasového socketu není vlastní socket.')
                os.unlink(path)
            super().__init__(path, VoiceHandler)
            os.chmod(path, 0o600)

    class UnixHTTPServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
        daemon_threads = True
        def __init__(self, path, port):
            self.server_port = port
            super().__init__(path, Handler)
            os.chmod(path, 0o666)

if __name__ == '__main__':
    threading.Thread(target=worker, daemon=True).start()
    threading.Thread(target=customer_scan_worker, daemon=True).start()
    threading.Thread(target=digest_worker, daemon=True).start()
    port = int(os.environ.get('PORT', '4091'))
    if UNIX_SOCKET:
        socket_path = Path(UNIX_SOCKET)
        if socket_path.exists():
            if not socket_path.is_socket():
                raise RuntimeError('Cesta pro socket není socket.')
            socket_path.unlink()
        local_socket = UnixHTTPServer(UNIX_SOCKET, port)
        threading.Thread(target=local_socket.serve_forever, daemon=True).start()
    if VOICE_SOCKET:
        voice_socket = VoiceUnixServer(VOICE_SOCKET)
        threading.Thread(target=voice_socket.serve_forever, daemon=True).start()
    print(f'Redmine asistent: http://127.0.0.1:{port}', flush=True)
    ThreadingHTTPServer(('127.0.0.1', port), Handler).serve_forever()
