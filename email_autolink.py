"""One-shot, fail-closed linking for newly created Helpdesk issues."""
from datetime import datetime, timezone
import sqlite3
from suggestions import emails


def _utc(value):
    parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Timestamp requires timezone')
    return parsed.astimezone(timezone.utc)


def activate(connect, now=None):
    now = now or datetime.now(timezone.utc)
    with connect() as db:
        db.execute('CREATE TABLE IF NOT EXISTS email_autolink_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS email_autolink_attempts (issue_id INTEGER PRIMARY KEY, state TEXT NOT NULL, customer_id INTEGER, updated TEXT NOT NULL)')
        db.execute("INSERT OR IGNORE INTO email_autolink_settings VALUES ('activated_at', ?)", (now.isoformat(),))
        return _utc(db.execute("SELECT value FROM email_autolink_settings WHERE key='activated_at'").fetchone()[0])


def _state(connect, issue_id, state, customer_id=None):
    with connect() as db:
        db.execute('UPDATE email_autolink_attempts SET state=?, customer_id=?, updated=? WHERE issue_id=?',
                   (state, customer_id, datetime.now(timezone.utc).isoformat(), issue_id))


def statuses(connect):
    try:
        with connect() as db:
            return dict(db.execute('SELECT issue_id, state FROM email_autolink_attempts'))
    except sqlite3.OperationalError:
        return {}


def scan_start(connect, cutoff):
    with connect() as db:
        row = db.execute("SELECT value FROM email_autolink_settings WHERE key='scanned_at'").fetchone()
    return max(cutoff, _utc(row[0])) if row else cutoff


def mark_scanned(connect, value):
    with connect() as db:
        db.execute("INSERT INTO email_autolink_settings VALUES ('scanned_at', ?) "
                   "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (value.isoformat(),))


def process(connect, items, catalog, cutoff, sender, detail, relations, links, write, now=None):
    """Attempt each new Helpdesk issue once; uncertain writes are never retried."""
    now = now or datetime.now(timezone.utc)
    for issue in items:
        try:
            iid = int(issue['id'])
            created = _utc(issue['created_on'])
            if iid <= 0 or issue.get('project', {}).get('id') != 12 or not cutoff < created <= now:
                continue
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        with connect() as db:
            claimed = db.execute('INSERT OR IGNORE INTO email_autolink_attempts VALUES (?, ?, NULL, ?)',
                                 (iid, 'checking', now.isoformat())).rowcount
        if not claimed:
            continue
        try:
            sender_addresses = emails(sender(iid) or '')
            if len(sender_addresses) != 1:
                _state(connect, iid, 'review')
                continue
            matches = [c for c in catalog if sender_addresses & emails(' '.join(
                [str(v) for v in c.get('contacts', [])] +
                [str(c.get('email_contact') or ''), str(c.get('lead_contact') or '')]))]
            if len(matches) != 1 or type(matches[0].get('id')) is not int or matches[0]['id'] <= 0:
                _state(connect, iid, 'review')
                continue
            target = matches[0]['id']
            current = detail(iid)
            if (current.get('id') != iid or current.get('project', {}).get('id') != 12
                    or current.get('created_on') != issue.get('created_on')
                    or current.get('updated_on') != issue.get('updated_on')):
                _state(connect, iid, 'review')
                continue
            current_relations = relations(iid)
            if not isinstance(current_relations, list) or any(not isinstance(r, dict) for r in current_relations):
                _state(connect, iid, 'review')
                continue
            customer = detail(target)
            allowed = {'Email', 'Kontakt vedoucí stravování', 'Kontakt ředitel', 'Kontakt IT'}
            contact_text = ' '.join(str(field.get('value') or '') for field in customer.get('custom_fields', [])
                                    if field.get('name') in allowed)
            if (customer.get('id') != target or customer.get('project', {}).get('id') != 1
                    or customer.get('tracker', {}).get('id') != 4 or not sender_addresses & emails(contact_text)):
                _state(connect, iid, 'review')
                continue
            related = {r.get('issue_to_id') if r.get('issue_id') == iid else r.get('issue_id')
                       for r in current_relations}
            related.add(current.get('parent', {}).get('id'))
            known_customer_ids = {c.get('id') for c in catalog}
            if related & known_customer_ids:
                _state(connect, iid, 'already_linked')
                continue
            if links(iid, dict(current, relations=current_relations)):
                _state(connect, iid, 'already_linked')
                continue
            if emails(sender(iid) or '') != sender_addresses:
                _state(connect, iid, 'review')
                continue
            latest = detail(iid)
            if (latest.get('id') != iid or latest.get('project', {}).get('id') != 12
                    or latest.get('created_on') != issue.get('created_on')
                    or latest.get('updated_on') != issue.get('updated_on')
                    or relations(iid) != current_relations):
                _state(connect, iid, 'review')
                continue
            # Commit this state before the external write. A crash or uncertain
            # network result must never cause a second POST on a later sync.
            _state(connect, iid, 'sending', target)
        except Exception:
            _state(connect, iid, 'review')
            continue
        try:
            write(f'/issues/{iid}/relations.json', 'POST',
                  {'relation': {'issue_to_id': target, 'relation_type': 'relates'}})
            after = relations(iid)
            if not isinstance(after, list) or any(not isinstance(r, dict) for r in after):
                raise ValueError('Invalid relation list')
            related = {r.get('issue_to_id') if r.get('issue_id') == iid else r.get('issue_id')
                       for r in after}
            _state(connect, iid, 'linked' if target in related else 'unknown', target)
        except Exception:
            _state(connect, iid, 'unknown', target)
