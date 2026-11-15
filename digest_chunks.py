"""Bounded, resumable preparation of private digest evidence.

This module does not invoke a model or certify the truth of an AI sentence.
It keeps source text in memory and stores only content hashes and selections in
the caller's already-private SQLite database.
"""
import hashlib
import json
from datetime import datetime, timezone

MAX_SOURCE_BYTES = 1200
PROTOCOL_VERSION = "source-parts-v1"


def _utc(value):
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Čas podkladu nemá časové pásmo.")
    return parsed.astimezone(timezone.utc)


def split_text(text, limit=MAX_SOURCE_BYTES):
    """Split at whitespace where possible, without dropping any characters."""
    if not isinstance(text, str) or limit < 4:
        raise ValueError("Neplatný text nebo limit části.")
    start = 0
    while start < len(text):
        end = start
        size = 0
        last_boundary = None
        while end < len(text):
            width = len(text[end].encode("utf-8"))
            if size + width > limit:
                break
            size += width
            end += 1
            if text[end - 1].isspace() or text[end - 1] in ".!?;":
                last_boundary = end
        if end < len(text) and last_boundary and last_boundary > start:
            end = last_boundary
        if end == start:
            raise ValueError("Jeden znak přesahuje povolený limit.")
        yield text[start:end]
        start = end


def prepare(payload, limit=MAX_SOURCE_BYTES):
    """Return chronological bounded parts plus explicit snapshot warnings.

    Details are preserved as canonical JSON; they are not interpreted as proof
    that an issue was repaired or that a numeric status means closed.
    """
    if not isinstance(payload, dict) or payload.get("schema_version") != 1 or payload.get("purpose") != "local_henk_digest_input_only":
        raise ValueError("Neplatné podklady.")
    start, end = _utc(payload["period_start_utc"]), _utc(payload["period_end_utc"])
    if start > end or not isinstance(payload.get("issues"), list):
        raise ValueError("Neplatné období nebo seznam úkolů.")
    sources, warnings, seen = [], [], set()
    for issue in payload["issues"]:
        iid = issue.get("id") if isinstance(issue, dict) else None
        if type(iid) is not int or iid <= 0 or iid in seen:
            raise ValueError("Neplatné nebo duplicitní ID úkolu.")
        seen.add(iid)
        sid = "issue:" + str(iid)
        if _utc(issue["updated_on"]) <= end:
            author = issue.get("author") or {}
            project = issue.get("project") or {}
            status = issue.get("status") or {}
            if not all(isinstance(item, dict) for item in (author, project, status)):
                raise ValueError("Neplatná metadata úkolu.")
            metadata = {"source_id": sid, "author": author.get("name", ""),
                        "project_snapshot": project, "status_snapshot": status,
                        "time": issue.get("created_on"), "in_period": None}
            for field in ("subject", "description"):
                value = issue.get(field) or ""
                if not isinstance(value, str):
                    raise ValueError("Neplatný text úkolu.")
                if value:
                    sources.append({**metadata, "field": field, "text": value})
        else:
            warnings.append({"issue_id": iid, "reason": "Aktuální předmět a popis mohou být po uzávěrce; historické znění není ověřeno."})
        journals = issue.get("journals", [])
        if not isinstance(journals, list):
            raise ValueError("Neplatná historie úkolu.")
        journal_ids = set()
        ordered = sorted(journals, key=lambda j: (_utc(j["created_on"]), j["id"]))
        for journal in ordered:
            jid = journal.get("id")
            if type(jid) is not int or jid <= 0 or jid in journal_ids:
                raise ValueError("Neplatné nebo duplicitní ID journalu.")
            journal_ids.add(jid)
            stamp = _utc(journal["created_on"])
            if stamp > end:
                raise ValueError("Podklad obsahuje journal po uzávěrce.")
            jid_text = "journal:" + str(iid) + ":" + str(jid)
            author = journal.get("author") or {}
            if not isinstance(author, dict) or not isinstance(author.get("name", ""), str):
                raise ValueError("Neplatný autor journalu.")
            notes = journal.get("notes") or ""
            details = journal.get("details") or []
            if not isinstance(notes, str) or not isinstance(details, list):
                raise ValueError("Neplatný obsah journalu.")
            metadata = {"source_id": jid_text, "author": author.get("name", ""),
                        "time": journal["created_on"], "in_period": start <= stamp <= end}
            if notes:
                sources.append({**metadata, "field": "notes", "text": notes})
            for index, detail in enumerate(details):
                if not isinstance(detail, dict):
                    raise ValueError("Neplatná změna journalu.")
                sources.append({**metadata, "field": "detail:" + str(index),
                                "text": json.dumps(detail, ensure_ascii=False, sort_keys=True, separators=(",", ":"))})
    chunks = []
    for source in sources:
        parts = list(split_text(source["text"], limit))
        for index, text in enumerate(parts):
            chunks.append({**{k: v for k, v in source.items() if k != "text"},
                           "part": index + 1, "parts": len(parts), "text": text})
    return chunks, warnings


def cache_key(chunk, model_identity, prompt_identity):
    if not isinstance(model_identity, str) or not model_identity or not isinstance(prompt_identity, str) or not prompt_identity:
        raise ValueError("Chybí identita modelu nebo instrukce.")
    encoded = json.dumps([PROTOCOL_VERSION, model_identity, prompt_identity, chunk],
                         ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def process(chunks, connect, model_identity, prompt_identity, infer, validate):
    """Commit each validated part immediately; reruns reuse only exact inputs.

    Caller supplies validation and must independently enforce model locality.
    The returned values are proposals, not evidence of factual correctness.
    """
    with connect() as db:
        db.execute("CREATE TABLE IF NOT EXISTS digest_chunk_cache (cache_key TEXT PRIMARY KEY, result TEXT NOT NULL)")
    results = []
    for chunk in chunks:
        key = cache_key(chunk, model_identity, prompt_identity)
        with connect() as db:
            row = db.execute("SELECT result FROM digest_chunk_cache WHERE cache_key=?", (key,)).fetchone()
        if row:
            value = json.loads(row[0])
        else:
            value = infer(chunk)
        if not isinstance(value, list) or not value or any(type(index) is not int or index < 0 for index in value) or len(value) != len(set(value)):
            raise ValueError("Neplatný výběr částí podkladu.")
        validate(chunk, value)
        if not row:
            encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            with connect() as db:
                db.execute("INSERT OR IGNORE INTO digest_chunk_cache(cache_key,result) VALUES (?,?)", (key, encoded))
        results.append(value)
    return results
