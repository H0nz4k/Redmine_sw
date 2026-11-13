"""Private daily Redmine company digest (all visible projects, not only Helpdesk)."""
import json
import os
import re
import threading
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Prague")
DEFAULT_TIME = "17:30"
REPORT_DIR = Path(os.getenv("REDMINE_REPORT_DIR", "data/reports"))
_LOCK = threading.Lock()


def _utc(value):
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _stamp(value):
    return _utc(value).isoformat().replace("+00:00", "Z")


def _clock(value):
    if not isinstance(value, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
        raise ValueError("Čas musí mít formát HH:MM.")
    return tuple(map(int, value.split(":")))


def _schema(db):
    db.execute("CREATE TABLE IF NOT EXISTS digest_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS digest_reports (day TEXT PRIMARY KEY, start_utc TEXT NOT NULL, end_utc TEXT NOT NULL, path TEXT NOT NULL, event_count INTEGER NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS digest_projects (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS digest_event_ids (id TEXT PRIMARY KEY, occurred_utc TEXT NOT NULL)")


def get_settings(connect, now=None):
    now = _utc(now or datetime.now(timezone.utc))
    with connect() as db:
        _schema(db)
        row = db.execute("SELECT value FROM digest_settings WHERE key='time'").fetchone()
        clock = row[0] if row else DEFAULT_TIME
        latest = db.execute("SELECT day, end_utc FROM digest_reports ORDER BY end_utc DESC LIMIT 1").fetchone()
    hour, minute = _clock(clock)
    local = now.astimezone(TZ)
    next_run = datetime.combine(local.date(), time(hour, minute), tzinfo=TZ)
    if next_run <= local:
        next_run = datetime.combine(local.date() + timedelta(days=1), time(hour, minute), tzinfo=TZ)
    return {"time": clock, "timezone": "Europe/Prague",
            "next_run": next_run.isoformat(), "latest_day": latest[0] if latest else None}


def set_time(connect, value):
    _clock(value)
    with connect() as db:
        _schema(db)
        db.execute("INSERT INTO digest_settings(key,value) VALUES('time', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (value,))
    return get_settings(connect)


def _projects(request):
    offset = 0
    result = {}
    while True:
        data = request("/projects.json", {"limit": 100, "offset": offset})
        page = data["projects"]
        for item in page:
            result[int(item["id"])] = item.get("name", "")
        offset += len(page)
        if not page or offset >= data.get("total_count", offset):
            return result


def _clean(text):
    # Redmine text never becomes HTML; remove Markdown link-control characters.
    return re.sub(r"[\[\]<>\r\n]", " ", str(text or "")).replace("|", " ").strip()[:180]


def _event(key, kind, issue, who, when, base, message):
    return {"key": key, "kind": kind, "who": _clean(who) or "Neznámý autor",
            "project": _clean(issue.get("project", {}).get("name")) or "Neznámý projekt",
            "time": _stamp(when), "subject": _clean(issue.get("subject")) or "Bez předmětu",
            "message": message, "url": base.rstrip("/") + "/issues/" + str(int(issue["id"]))}


def _digest_excerpt(value, limit=340):
    """Conservative extractive summary: never claim actions absent from Redmine."""
    value = re.sub(r"\s+", " ", str(value or "")).strip()
    value = re.sub(r"[<>\[\]`*_#|~]", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) <= limit:
        return value
    cut = value[:limit].rsplit(" ", 1)[0]
    return (cut or value[:limit]).rstrip(" ,.;:") + "…"


def _stories(events, contexts):
    """One readable paragraph per changed issue; keep source links and detailed list."""
    groups = {}
    for event in events:
        if "/issues/" not in event["url"]:
            continue
        issue_id = int(event["url"].rsplit("/", 1)[1])
        groups.setdefault(issue_id, []).append(event)
    paragraphs = []
    for issue_id, changes in groups.items():
        context = contexts.get(issue_id, {})
        first = changes[0]
        project, subject = first["project"], first["subject"]
        link = "[#" + str(issue_id) + " – " + subject.replace("(", " ").replace(")", " ") + "](" + first["url"] + ")"
        author = context.get("author", "")
        if any(e["kind"] == "new" for e in changes):
            opening = ("V projektu " + project + " přibyl požadavek " + link +
                       (", který zadal(a) " + author if author else "") + ".")
        else:
            opening = "V projektu " + project + " se řešil požadavek " + link + "."
        sentences = [opening]
        description = _digest_excerpt(context.get("description"))
        if description:
            sentences.append("Zadání uvádí: " + description + ".")
        notes = context.get("notes", [])
        for note in notes[-3:]:
            excerpt = _digest_excerpt(note.get("text"), 260)
            if excerpt:
                sentences.append("V komentáři " + note["author"] + " uvedl(a): " + excerpt + ".")
        if len(notes) > 3:
            sentences.append("Další komentáře jsou v původním úkolu.")
        if any(e["kind"] == "done" for e in changes):
            sentences.append("V historii tohoto období je také zaznamenána změna na vyřešený nebo uzavřený stav.")
        elif any(e["kind"] == "change" for e in changes) and not notes:
            sentences.append("Během dne došlo k aktualizaci úkolu; podrobnosti jsou v odkazu.")
        if not description and not notes:
            sentences.append("Podrobnější popis ani komentáře pro toto období nejsou dostupné.")
        paragraphs.append(" ".join(sentences))
    return paragraphs


def _collect(start, end, issues, request, base, previous_projects):
    found = {}
    for item in issues({"status_id": "*", "updated_on": ">=" + _stamp(start)}):
        found[int(item["id"])] = item
    events = {}
    contexts = {}
    for item in found.values():
        created = item.get("created_on")
        if created and start <= _utc(created) <= end:
            event = _event("new:" + str(item["id"]), "new", item,
                           item.get("author", {}).get("name"), created, base, "založil(a) úkol")
            events[event["key"]] = event
        detail = request("/issues/" + str(int(item["id"])) + ".json", {"include": "journals"})["issue"]
        if "journals" not in detail:
            raise RuntimeError("Redmine nevrátil historii změn úkolu #" + str(item["id"]))
        contexts[int(item["id"])] = {
            "author": _clean(detail.get("author", item.get("author", {})).get("name")),
            "description": detail.get("description") or item.get("description") or "",
            "notes": [],
        }
        for journal in detail["journals"]:
            changed = journal.get("created_on")
            if not changed or not (start <= _utc(changed) <= end):
                continue
            details = journal.get("details") or []
            status_changes = [d for d in details if d.get("name") == "status_id"]
            significant = [d for d in details if d.get("name") in
                           ("status_id", "assigned_to_id", "priority_id", "due_date", "start_date", "subject", "description")]
            notes = (journal.get("notes") or "").strip()
            if notes:
                contexts[int(item["id"])]["notes"].append({
                    "author": _clean(journal.get("user", {}).get("name")) or "Neznámý autor",
                    "time": _stamp(changed),
                    "text": notes,
                })
            if not significant and not notes:
                continue
            done = any(str(d.get("new_value")) == str(item.get("status", {}).get("id"))
                       for d in status_changes) and bool(re.search(r"vyřeš|uzavřen|zavřen|resolved|closed", item.get("status", {}).get("name", ""), re.I))
            kind = "done" if done else "change"
            if done:
                message = "uzavřel(a) nebo vyřešil(a) úkol"
            elif status_changes:
                message = "změnil(a) stav úkolu"
            elif any(d.get("name") == "assigned_to_id" for d in significant):
                message = "předal(a) úkol jinému řešiteli"
            elif notes:
                message = "doplnil(a) komentář"
            else:
                message = "upravil(a) důležité údaje úkolu"
            key = "journal:" + str(item["id"]) + ":" + str(journal["id"])
            events[key] = _event(key, kind, item, journal.get("user", {}).get("name"), changed, base, message)
    current_projects = _projects(request)
    if previous_projects:
        for project_id, name in current_projects.items():
            if project_id not in previous_projects:
                key = "project:" + str(project_id)
                events[key] = {"key": key, "kind": "project", "who": "Redmine", "project": _clean(name),
                               "time": _stamp(end), "subject": _clean(name), "message": "objevil se nový projekt",
                               "url": base.rstrip("/") + "/projects/" + str(project_id)}
    return sorted(events.values(), key=lambda e: (e["time"], e["key"])), current_projects, contexts


def _markdown(events, start, end, contexts=None):
    local_start = start.astimezone(TZ).strftime("%d.%m.%Y %H:%M")
    local_end = end.astimezone(TZ).strftime("%d.%m.%Y %H:%M")
    groups = {"project": [], "new": [], "done": [], "change": []}
    for event in events:
        groups[event["kind"]].append(event)
    count = lambda key: len(groups[key])
    parts = ["# Dnes ve firmě — " + end.astimezone(TZ).strftime("%d.%m.%Y"),
             "", "Období: " + local_start + " až " + local_end + " (Europe/Prague).", "",
             "## Shrnutí", ""]
    if not events:
        parts.append("V dostupné historii Redminu nebyly v tomto období nalezeny významné změny.")
    else:
        parts.append("Přibylo " + str(count("project")) + " projektů a " + str(count("new")) +
                     " úkolů; dokončeno nebo uzavřeno " + str(count("done")) +
                     " úkolů; dalších důležitých změn " + str(count("change")) + ".")
    stories = _stories(events, contexts or {})
    if stories:
        parts.extend(["", "## Co se skutečně řešilo", ""])
        for story in stories:
            parts.extend([story, ""])
    headings = (("project", "Nové projekty"), ("new", "Co přibylo"),
                ("done", "Co se dokončilo"), ("change", "Důležité změny"))
    for category, heading in headings:
        if not groups[category]:
            continue
        parts.extend(["", "## " + heading, ""])
        for event in groups[category]:
            local_when = _utc(event["time"]).astimezone(TZ).strftime("%H:%M")
            parts.append("- " + local_when + " · " + event["who"] + " · " + event["project"] + ": " +
                         event["message"] + " [" + event["subject"].replace("(", " ").replace(")", " ") +
                         "](" + event["url"] + ")")
    parts.extend(["", "_Vychází pouze z událostí dostupných účtu Redmine API._", ""])
    return "\n".join(parts)


def generate(connect, issues, request, base, now=None):
    end = _utc(now or datetime.now(timezone.utc))
    day = end.astimezone(TZ).date().isoformat()
    if not _LOCK.acquire(blocking=False):
        raise RuntimeError("Denní souhrn se právě vytváří.")
    try:
        with connect() as db:
            _schema(db)
            previous = db.execute("SELECT start_utc FROM digest_reports WHERE day=?", (day,)).fetchone()
            last = db.execute("SELECT end_utc FROM digest_reports WHERE day<>? ORDER BY end_utc DESC LIMIT 1", (day,)).fetchone()
            projects = {int(pid): name for pid, name in db.execute("SELECT id,name FROM digest_projects")}
        if previous:
            start = _utc(previous[0])
        elif last:
            start = _utc(last[0])
        else:
            start = datetime.combine(end.astimezone(TZ).date(), time(0, 0), tzinfo=TZ).astimezone(timezone.utc)
        if start > end:
            raise RuntimeError("Čas uzávěrky je před začátkem intervalu.")
        events, current_projects, contexts = _collect(start, end, issues, request, base, projects)
        markdown = _markdown(events, start, end, contexts)
        REPORT_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = REPORT_DIR / (day + ".md")
        temp = REPORT_DIR / (day + ".tmp")
        with temp.open("w", encoding="utf-8") as stream:
            os.chmod(temp, 0o600)
            stream.write(markdown)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        with connect() as db:
            _schema(db)
            db.execute("INSERT INTO digest_reports(day,start_utc,end_utc,path,event_count) VALUES(?,?,?,?,?) "
                       "ON CONFLICT(day) DO UPDATE SET start_utc=excluded.start_utc,end_utc=excluded.end_utc,path=excluded.path,event_count=excluded.event_count",
                       (day, _stamp(start), _stamp(end), str(path), len(events)))
            for event in events:
                db.execute("INSERT OR IGNORE INTO digest_event_ids(id,occurred_utc) VALUES(?,?)",
                           (event["key"], event["time"]))
            db.execute("DELETE FROM digest_projects")
            db.executemany("INSERT INTO digest_projects(id,name) VALUES(?,?)", current_projects.items())
        return {"day": day, "event_count": len(events), "end": _stamp(end)}
    finally:
        _LOCK.release()


def history(connect, limit=60):
    with connect() as db:
        _schema(db)
        rows = db.execute("SELECT day,end_utc,event_count FROM digest_reports ORDER BY day DESC LIMIT ?",
                          (min(365, max(1, int(limit))),)).fetchall()
    return [{"day": day, "generated_at": end, "events": count} for day, end, count in rows]


def read_report(connect, day):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day or ""):
        raise ValueError("Neplatné datum reportu.")
    with connect() as db:
        _schema(db)
        row = db.execute("SELECT day FROM digest_reports WHERE day=?", (day,)).fetchone()
    if not row:
        raise ValueError("Report není dostupný.")
    return (REPORT_DIR / (day + ".md")).read_text(encoding="utf-8")


def due(connect, now=None):
    now = _utc(now or datetime.now(timezone.utc))
    local = now.astimezone(TZ)
    hour, minute = _clock(get_settings(connect, now)["time"])
    if (local.hour, local.minute) < (hour, minute):
        return False
    with connect() as db:
        _schema(db)
        return db.execute("SELECT 1 FROM digest_reports WHERE day=?", (local.date().isoformat(),)).fetchone() is None
