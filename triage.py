"""Conservative, explainable Helpdesk hardware triage; no API writes."""
import re
import unicodedata

DEVICES = {
    'terminál': r'\bterminal\w*',
    'tiskárna': r'\btiskarn\w*',
    'čtečka': r'\bcteck\w*',
    'snímač': r'\bsnimac\w*',
    'počítač': r'\bpocitac\w*|\bpc\b',
    'monitor': r'\bmonitor\w*|\bobrazovk\w*',
    'klávesnice': r'\bklavesnic\w*',
    'reproduktor': r'\breproduktor\w*',
    'hardware': r'\bhardwar\w*',
    'router': r'\brouter\w*',
}
FAULTS = {
    'nefunguje': r'\bnefunguj\w*',
    'nejde': r'\bnejd\w*',
    'porucha': r'\bporuch\w*',
    'rozbité': r'\brozbit\w*',
    'poškozené': r'\bposkozen\w*',
    'vadné': r'\bvadn\w*',
    'nereaguje': r'\bnereaguj\w*',
    'nelze zapnout': r'\b(?:nezapn\w*|nelze zapnout|nejde zapnout)\b',
    'nenabíhá': r'\bnenabih\w*',
    'výpadky': r'\bvypadav\w*',
    'oprava': r'\boprav\w*',
    'výměna': r'\bvymen\w*',
    'servis': r'\bservis\w*',
    'problém': r'\bproblem\w*',
    'závada': r'\bzavad\w*',
}
HEALTHY = re.compile(
    r'\b(?:funguje|funkcni|v poradku|bez problemu|zadna zavada|'
    r'neni problem|neni porucha|neni zavada|nepotrebuje opravu)\b')
SOFTWARE = re.compile(
    r'\b(?:ovladac\w*|driver\w*|instalac\w*|konfigurac\w*|'
    r'nastaven\w*|aplikac\w*|program\w*|software\w*|report\w*)\b')


def normalize(value):
    value = unicodedata.normalize('NFKD', str(value or '').casefold())
    return ''.join(char for char in value if not unicodedata.combining(char))


def matches(text, patterns):
    return [label for label, regex in patterns.items() if re.search(regex, text)]


def analyze_issue(issue):
    """Return an advisory classification. Never performs a Redmine mutation.

    'auto_candidate' means eligible for a *future* guarded worker, not assigned.
    """
    text = normalize((issue.get('subject') or '') + '\n' + (issue.get('description') or ''))
    clauses = re.split(r'[.!?;\n]+|\bale\b|\bavsak\b', text)
    devices, faults, uncertain = set(), set(), False
    for clause in clauses:
        found = matches(clause, DEVICES)
        if not found:
            continue
        devices.update(found)
        broken = matches(clause, FAULTS)
        if HEALTHY.search(clause):
            # A healthy device must not be treated as broken just because
            # unrelated failure words appear in the same clause.
            uncertain = True
            continue
        if SOFTWARE.search(clause):
            uncertain = True
            continue
        faults.update(broken)

    terms = sorted(devices)
    signals = sorted(faults)
    assigned = issue.get('assigned_to')
    helpdesk = issue.get('project', {}).get('id') == 12
    eligible = helpdesk and not assigned
    if signals:
        confidence = 'high'
        action = 'auto_candidate' if eligible else 'none'
        reason = 'Zařízení: ' + ', '.join(terms) + '; závada: ' + ', '.join(signals)
    elif terms:
        confidence = 'medium' if not uncertain else 'low'
        action = 'review' if eligible else 'none'
        reason = 'Zmíněný hardware: ' + ', '.join(terms) + '; závada není jednoznačná'
    else:
        confidence = 'low'
        action = 'none'
        reason = 'Nebyl rozpoznán konkrétní hardware'
    return {
        'category': 'hardware' if terms else 'other',
        'confidence': confidence,
        'action': action,
        'devices': terms,
        'faults': signals,
        'reason': reason,
    }
