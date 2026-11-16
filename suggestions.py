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


def signature_words(description):
    """Use the first recognizable sign-off, not arbitrary names in the message body."""
    lines = str(description or '').splitlines()
    signoff = re.compile(r'^(?:s pozdravem|s uctou|srdecne zdravim|zdravi|preji (?:hezky|krasny|prijemny) (?:den|vecer))\b')
    for index, line in enumerate(lines):
        normalized = normalize(line)
        match = signoff.match(normalized)
        if not match:
            continue
        signature = [normalized[match.end():]]
        for following in lines[index + 1:]:
            following = normalize(following)
            if not following:
                if any(signature):
                    break
                continue
            if signoff.match(following):
                continue
            signature.append(following)
            if len(signature) >= 4:
                break
        return set(' '.join(signature).split())
    return set()


def customer_suggestions(subject, description, candidates):
    raw = (subject or '') + ' ' + (description or '')
    text = ' ' + normalize(raw) + ' '
    words = set(text.split())
    signed = signature_words(description)
    raw_phones, raw_emails = phones(raw), emails(raw)
    school_words = {'skola', 'skoly', 'skole', 'skolu', 'skolou', 'skol', 'skolach', 'skolami'}
    generic = school_words | {'zakladni', 'stredni', 'materska', 'skolni', 'jidelnicka', 'jidelnicek', 'skolnich', 'organizace', 'prispevkova', 'nemocnice', 'gymnazium', 'pavilon', 'zakaznik', 'jidelnа', 'praha', 'mesto'}
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
        only_school = all(t in school_words | {'zs', 'ms', 'zakladni', 'materska', 'skolni'} for t in name.split())
        exact = len(name) >= 5 and not only_school and ' ' + name + ' ' in text
        overlap = group & words
        rare = [t for t in overlap if name_counts[t] <= 5]
        contact = ' '.join(str(v) for v in candidate.get('contacts', []) if v)
        phone_match = bool(raw_phones & phones(contact))
        email_match = bool(raw_emails & emails(contact))
        signed_match = any(contact_counts[t] <= 3 for t in people & signed)
        evidence = []
        if email_match: evidence.append('e-mail')
        if phone_match: evidence.append('telefon')
        if signed_match: evidence.append('jméno v podpisu')
        if exact: evidence.append('úplný název provozovny')
        elif rare: evidence.append('část názvu provozovny')
        if not evidence:
            continue
        contact_match = phone_match or email_match
        priority = 3 if contact_match else 2 if signed_match else 1 if exact else 0
        score = 2 * (int(phone_match) + int(email_match)) + int(signed_match) + int(exact)
        reason = 'Shoda: ' + ', '.join(evidence) + '; zkontrolujte provozovnu.'
        found.append((-priority, -score, candidate['id'], {'id': candidate['id'], 'name': candidate['name'], 'reason': reason, 'strength': 'strong' if contact_match and (signed_match or exact or (phone_match and email_match)) else 'possible'}))
    # Weak name fragments are useful only when no better evidence is available.
    if any(priority < 0 for priority, _, _, _ in found):
        found = [entry for entry in found if entry[0] < 0]
    return [item for _, _, _, item in sorted(found)[:10]]
