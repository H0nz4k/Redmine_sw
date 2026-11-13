"""Local, explainable helpdesk suggestions; no external model calls."""
import re
import unicodedata
from collections import Counter


def normalize(value):
    text = unicodedata.normalize('NFKD', value.casefold())
    text = ''.join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r'[^a-z0-9]+', ' ', text).strip()


def customer_suggestions(subject, description, candidates):
    text = ' ' + normalize((subject or '') + ' ' + (description or '')) + ' '
    words = set(text.split())
    generic = {'zakladni', 'stredni', 'materska', 'skolni', 'jidelnicka', 'skolnich', 'organizace', 'prispevkova', 'nemocnice', 'gymnazium', 'pavilon', 'zakaznik'}
    terms = []
    for c in candidates:
        tokens = set(normalize(str(c.get('name') or '') + ' ' + str(c.get('address') or '')).split())
        terms.append({t for t in tokens if len(t) >= 6 and t.isalpha() and t not in generic})
    counts = Counter(t for group in terms for t in group)
    found = []
    for candidate, group in zip(candidates, terms):
        name = normalize(candidate.get('name', ''))
        exact = len(name) >= 5 and ' ' + name + ' ' in text
        overlap = sorted((t for t in group & words if counts[t] <= 5), key=lambda t: (counts[t], -len(t), t))
        if exact:
            reason = 'Úplný název zákazníka je uveden v předmětu nebo popisu.'
        elif overlap:
            reason = f'V textu je výraz „{overlap[0]}“; zkontrolujte provozovnu.'
        else:
            continue
        found.append((0 if exact else 1, counts[overlap[0]] if overlap else 0,
                      {'id': candidate['id'], 'name': candidate['name'], 'reason': reason}))
    return [item for _, _, item in sorted(found, key=lambda x: (x[0], x[1], x[2]['id']))[:10]]
