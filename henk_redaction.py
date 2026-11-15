"""Minimize Redmine text before sending it to Henk's model transport.

No network access, attachment loading, or logging. The recognizers cover
obvious credentials; they do not guarantee detection of every possible secret.
"""
import re

REMOVED = "[citlivý údaj odstraněn]"
LINK_REMOVED = "[odkaz odstraněn]"

_PEM = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)", re.I)
_MARKDOWN_IMAGE = re.compile(r"!\[[^\]\r\n]*\]\([^\r\n)]*\)")
_TEXTILE_IMAGE = re.compile(r"![^!\r\n]{1,500}!")
_URL = re.compile(r"(?i)\b(?:https?|ftp)://[^\s<>\"']+")
_MAILTO = re.compile(r"(?i)\b(?:mailto:|file://)[^\s<>\"']+")
_BEARER = re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{6,}")
_TOKEN = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]{12,}|github_pat_[A-Za-z0-9_]{12,}|eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,})\b")
_ASSIGNMENT = re.compile(
    r"(?i)(\b(?:[a-z0-9_-]*[_-])?(?:password|passwd|pwd|heslo|heslo\s+je|token|api[_ -]?key|access[_ -]?key|"
    r"secret|client[_ -]?secret|authorization|přístupový[_ -]?klíč)\b\s*(?:[:=]|\s+je\s+)\s*)"
    r"(?!\[citlivý údaj odstraněn\])(?:\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\s,;]+)"
)
_ATTACHMENT = re.compile(r"(?i)(?:!\s*)?(?:attachment|příloha|priloha):[^\s\]\)<>]+")
_ATTACHMENT_PATH = re.compile(r"(?i)/(?:attachments|uploads)/[^\s\]\)<>]+")


def text(value):
    if not isinstance(value, str):
        raise ValueError("Text podkladu není řetězec.")
    value = _PEM.sub(REMOVED, value)
    value = _MARKDOWN_IMAGE.sub("[příloha vynechána]", value)
    value = _TEXTILE_IMAGE.sub("[příloha vynechána]", value)
    value = _URL.sub(LINK_REMOVED, value)
    value = _MAILTO.sub(LINK_REMOVED, value)
    value = _ATTACHMENT.sub("[příloha vynechána]", value)
    value = _ATTACHMENT_PATH.sub("[příloha vynechána]", value)
    value = _BEARER.sub(REMOVED, value)
    value = _TOKEN.sub(REMOVED, value)
    return _ASSIGNMENT.sub(lambda match: match.group(1) + REMOVED, value)


def detail(value):
    """Exclude attachment details entirely; redact known secret field values."""
    if not isinstance(value, dict):
        raise ValueError("Neplatná položka historie.")
    prop = str(value.get("property", "")).lower()
    name = str(value.get("name", "")).lower()
    if prop in ("attachment", "attachments") or name in ("attachment", "attachments"):
        return None
    secret = re.search(r"(?i)(password|passwd|heslo|token|secret|api.?key|authorization|credential)", name)
    result = {}
    for key in ("property", "name", "old_value", "new_value"):
        item = value.get(key)
        if isinstance(item, str):
            result[key] = REMOVED if secret and key in ("old_value", "new_value") else text(item)
        elif item is None or type(item) in (int, float, bool):
            result[key] = item
        else:
            raise ValueError("Neplatná hodnota změny.")
    return result


def context(value):
    """Whitelist only text-bearing issue fields required for summarization."""
    if not isinstance(value, dict):
        raise ValueError("Neplatný kontext podkladů.")
    status = value.get("status_snapshot") or {}
    if not isinstance(status, dict):
        raise ValueError("Neplatný stav úkolu.")
    result = {
        "issue_id": value["issue_id"], "issue_source_id": value["issue_source_id"],
        "snapshot_safe": value["snapshot_safe"],
        "subject_snapshot": text(value.get("subject_snapshot") or ""),
        "description_snapshot": text(value.get("description_snapshot") or ""),
        "status_snapshot": {"id": status.get("id"), "name": text(status.get("name") or "")},
        "journals_through_cutoff": [],
    }
    for entry in value.get("journals_through_cutoff", []):
        if not isinstance(entry, dict):
            raise ValueError("Neplatná historie.")
        details = []
        for item in entry.get("details", []):
            cleaned = detail(item)
            if cleaned is not None:
                details.append(cleaned)
        result["journals_through_cutoff"].append({
            "source_id": entry["source_id"], "created_on": entry["created_on"],
            "author": text(entry.get("author") or ""), "notes": text(entry.get("notes") or ""),
            "details": details,
        })
    return result
