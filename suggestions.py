"""Explainable local matching; contact details never leave the server."""
import re
import unicodedata
from collections import Counter


def normalize(value):
    text = unicodedata.normalize('NFKD', str(value).casefold())
    text = ''.join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r'[^a-z0-9]+', ' ', text).strip()


def phones(value):
    result = set()
    for match in re.findall(r'(?<!\d)(?:\+?420[\s.\-/]*)?(?:\d[\s.\-/]*){9}(?!\d)', str(value)):
        digits = re.sub(r'\D', '', match)
        if len(digits) == 12 and digits.startswith('420'):
            digits = digits[3:]
        if len(digits) == 9:
            result.add(digits)
    return result


def emails(value):
    return set(re.findall(r'[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}', str(value).lower()))


def customer_suggestions(subject, description, candidates):
    raw = (subject or '') + ' ' + (description or '')
    text = ' ' + normalize(raw) + ' '
    words = set(text.split())
    generic = {'zakladni', 'stredni', 'materska', 'skolni', 'jidelnicka', 'skolnich', 'organizace', 'prispevkova', 'nemocnice', 'gymnazium', 'pavilon', 'zakaznik', 'skola', 'jidelnа', 'praha', 'mesto'}
    contact_generic = generic | {'vedouci', 'stravovani', 'kontakt', 'telefon', 'email', 'reditel', 'reditelka', 'jidelna', 'skolа'}
    names, contacts = [], []
    for c in candidates:
        names.append({t for t in normalize(str(c.get('name') or '') + ' ' + str(c.get('address') or '')).split() if len(t) >= 4 and t.isalpha() and t not in generic})
        contact = ' '.join(str(v) for v in c.get('contacts', []) if v)
        contact = re.sub(r'[\w.+-]+@[\w.-]+', ' ', contact)
        contacts.append({t for t in normalize(contact).split() if len(t) >= 5 and t.isalpha() and t not in contact_generic})
    name_counts = Counter(t for group in names for t in group)
    contact_counts = Counter(t for group in contacts for t in group)
    found = []
    for candidate, group, people in zip(candidates, names, contacts):
        name = normalize(candidate.get('name', ''))
        exact = len(name) >= 5 and ' ' + name + ' ' in text
        overlap = group & words
        rare = [t for t in overlap if name_counts[t] <= 5]
        evidence = []
        score = 0
        if exact:
            evidence.append('úplný název provozovny'); score += 4
        elif rare:
            evidence.append('část názvu provozovny'); score += 1
        contact = ' '.join(str(v) for v in candidate.get('contacts', []) if v)
        if phones(raw) & phones(contact):
            evidence.append('telefon'); score += 5
        if emails(raw) & emails(contact):
            evidence.append('e-mail'); score += 5
        if any(contact_counts[t] <= 3 for t in people & words):
            evidence.append('jméno v textu'); score += 2
        if not evidence:
            continue
        strong = score >= 7 and len(evidence) >= 2
        reason = 'Shoda: ' + ', '.join(evidence) + '; zkontrolujte provozovnu.'
        found.append((-score, candidate['id'], {'id': candidate['id'], 'name': candidate['name'], 'reason': reason, 'strength': 'strong' if strong else 'possible'}))
    return [item for _, _, item in sorted(found)[:10]]
