"""Bounded client for the installed Henk MCP inbox, with durable request IDs.

The Henk worker must have the reviewed no-operations digest mode installed.
This client does not use shell commands, send attachments, or log prompts.
"""
import hashlib
import json
import os
import re
import stat
import subprocess
import time
import uuid
from pathlib import Path

import henk_redaction

PREFIX = "REDMINE_DIGEST_V1:"
MAX_MESSAGE_CHARS = 4000
MAX_OUTPUT_BYTES = 131072
REQUEST_LIFETIME = 1800
WAIT_SECONDS = 120
POLL_SECONDS = 3
MCP_DIR = "/opt/hanzhub-project-control/mcp-channel"
MCP_COMMAND = (
    "/usr/bin/sudo", "-n", "-u", "henkmcp", "/usr/bin/env",
    "HENK_MCP_QUEUE=/var/lib/hanzhub-mcp-channel",
    "/var/lib/henkmcp-runtime/venv/bin/python", "-I", "-B",
    "/opt/hanzhub-project-control/mcp-channel/server.py",
)
# Exact candidate sources; the installed process must also be newer than them.
TRUSTED_RUNTIME = {
    MCP_DIR + '/agent_worker.py': 'ea21e90994111075ac88cb01e457f3208d8d759b780e12f46168c08b50c30cad',
    MCP_DIR + '/channel.py': '9207b6effd4174852a1f136f16bbc91750a219b0da28a3b8872096d30765da8a',
    MCP_DIR + '/henk_openai.py': 'ab7a9558518751c38c57defec2a238ce8fe774d68522f4f6276a53c1a4e5b18e',
    MCP_DIR + '/henk_redaction.py': '033f8e177b293be03f0981a8cd37bbf45a99a9e064402979fde2e9fdb55de892',
}


class HenkUnavailable(RuntimeError):
    pass


def verify_runtime():
    """Fail closed unless exact root-controlled sources were loaded after install."""
    if os.name != "posix" or len(TRUSTED_RUNTIME) != 4:
        raise HenkUnavailable("Ověřený režim Henka bez operací není nainstalován.")
    newest_ns = 0
    for filename, expected in TRUSTED_RUNTIME.items():
        path = Path(filename)
        try:
            if path.resolve(strict=True) != path:
                raise HenkUnavailable("Cesta runtime není důvěryhodná.")
            for parent in (path, *path.parents):
                info = parent.lstat()
                if info.st_uid != 0 or info.st_mode & 0o022:
                    raise HenkUnavailable("Oprávnění runtime nejsou důvěryhodná.")
            if not stat.S_ISREG(path.stat().st_mode):
                raise HenkUnavailable("Zdroj runtime není soubor.")
            with path.open("rb") as stream:
                actual = hashlib.file_digest(stream, "sha256").hexdigest()
            if actual != expected:
                raise HenkUnavailable("Běžící zdroj Henka neodpovídá ověřenému režimu.")
            newest_ns = max(newest_ns, path.stat().st_mtime_ns)
        except OSError as error:
            raise HenkUnavailable("Ověřený zdroj Henka není dostupný.") from error
    try:
        result = subprocess.run(['/usr/bin/systemctl', 'show', 'hanzhub-mcp-agent.service',
                                 '-p', 'MainPID', '-p', 'ActiveState'], capture_output=True,
                                text=True, timeout=5, check=True)
        props = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
        pid = int(props['MainPID'])
        if props['ActiveState'] != 'active' or pid <= 0:
            raise ValueError('inactive')
        proc = Path('/proc') / str(pid)
        argv = (proc / 'cmdline').read_bytes().split(b'\0')
        if os.fsencode(MCP_DIR + '/agent_worker.py') not in argv:
            raise ValueError('unexpected process')
        proc_stat = (proc / 'stat').read_text(encoding='ascii')
        ticks = int(proc_stat.rsplit(')', 1)[1].split()[19])
        boot = next(int(line.split()[1]) for line in Path('/proc/stat').read_text().splitlines() if line.startswith('btime '))
        started_ns = boot * 1_000_000_000 + ticks * 1_000_000_000 // os.sysconf('SC_CLK_TCK')
        if newest_ns >= started_ns - 1_000_000_000:
            raise ValueError('stale process')
    except (OSError, ValueError, KeyError, StopIteration, IndexError, subprocess.SubprocessError) as error:
        raise HenkUnavailable("Ověřený worker Henka ještě nenačetl novou verzi.") from error


def _call(name, arguments):
    if name not in {"send_henk_message", "get_henk_message_status", "list_henk_events"}:
        raise HenkUnavailable("Nepovolená operace MCP.")
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "redmine-digest", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": name, "arguments": arguments}},
    ]
    payload = ("\n".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in messages) + "\n").encode("utf-8")
    try:
        proc = subprocess.run(MCP_COMMAND, cwd=MCP_DIR, input=payload, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, timeout=20, check=False,
                              env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"})
    except (OSError, subprocess.TimeoutExpired) as error:
        raise HenkUnavailable("Spojení s Henkem není dostupné; stav ověřte opakováním.") from error
    if proc.returncode or len(proc.stdout) > MAX_OUTPUT_BYTES:
        raise HenkUnavailable("MCP spojení Henka selhalo.")
    try:
        rows = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
        matches = [row for row in rows if isinstance(row, dict) and row.get("id") == 2]
        if len(matches) != 1 or "error" in matches[0]:
            raise ValueError("invalid response")
        result = matches[0]["result"]
        if result.get("isError"):
            raise ValueError("tool error")
        if "structuredContent" in result:
            return result["structuredContent"]
        blocks = result.get("content", [])
        parsed = [json.loads(block["text"]) for block in blocks if block.get("type") == "text"]
        return parsed[0] if len(parsed) == 1 else parsed
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise HenkUnavailable("Henk vrátil neplatnou nebo odmítnutou odpověď.") from error


def infer(prompt, model, connect, *, call=_call, verify=verify_runtime,
          clock=time.time, monotonic=time.monotonic, sleep=time.sleep):
    """Send one redacted context with stable UUID and await a confirmed answer."""
    if os.getenv("HENK_REDMINE_OPENAI_CONSENT") != "1":
        raise HenkUnavailable("Zpracování textů v Henkově OpenAI transportu není aktivováno.")
    if not isinstance(prompt, str) or not isinstance(model, str):
        raise HenkUnavailable("Neplatný vstup shrnutí.")
    try:
        value = json.loads(prompt)
    except json.JSONDecodeError as error:
        raise HenkUnavailable("Neplatný vstup shrnutí.") from error
    try:
        safe = henk_redaction.context(value)
        period_ids = value.get("period_source_ids", [])
        if not isinstance(period_ids, list) or any(not isinstance(x, str) or not re.fullmatch(r"journal:\d+:\d+", x) for x in period_ids):
            raise ValueError("invalid sources")
        safe["period_source_ids"] = period_ids
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise HenkUnavailable("Neplatný vstup shrnutí.") from error
    body = PREFIX + json.dumps({"context": safe, "model": model}, ensure_ascii=False, separators=(",", ":"))
    if len(body) > MAX_MESSAGE_CHARS or len(body.encode("utf-8")) > 16000:
        raise HenkUnavailable("Podklady přesahují limit jedné zprávy Henka.")
    verify()  # Never send to an older worker that might invoke operations.
    fingerprint = hashlib.sha256((model + "\0" + body).encode("utf-8")).hexdigest()
    with connect() as db:
        db.execute("CREATE TABLE IF NOT EXISTS digest_henk_requests (fingerprint TEXT PRIMARY KEY, request_id TEXT NOT NULL, expires INTEGER NOT NULL)")
        db.execute("INSERT OR IGNORE INTO digest_henk_requests VALUES (?,?,?)",
                   (fingerprint, str(uuid.uuid4()), int(clock()) + REQUEST_LIFETIME))
        ident, expires = db.execute("SELECT request_id,expires FROM digest_henk_requests WHERE fingerprint=?", (fingerprint,)).fetchone()
    state = call("send_henk_message", {"request_id": ident, "kind": "digest", "text": body, "expires": expires})
    if not isinstance(state, dict) or state.get("id") != ident:
        raise HenkUnavailable("Henk nepotvrdil totožnost požadavku.")
    deadline = monotonic() + WAIT_SECONDS
    while state.get("phase") in ("QUEUED", "RECEIVED") and monotonic() < deadline:
        sleep(POLL_SECONDS)
        state = call("get_henk_message_status", {"request_id": ident})
        if not isinstance(state, dict) or state.get("id") != ident:
            raise HenkUnavailable("Stav Henka neodpovídá požadavku.")
    phase = state.get("phase")
    if phase == "EXPIRED":
        # Only confirmed unclaimed expiry permits a fresh UUID on the next run.
        with connect() as db:
            db.execute("DELETE FROM digest_henk_requests WHERE fingerprint=? AND request_id=?", (fingerprint, ident))
        raise HenkUnavailable("Zpráva vypršela před převzetím; lze ji znovu spustit.")
    if phase == "BLOCKED":
        events = call("list_henk_events", {"request_id": ident, "after_cursor": 0, "limit": 50})
        events = events.get("result") if isinstance(events, dict) else events
        before_send = ("[digest_api_credential_unavailable]", "[digest_openai_not_enabled]",
                       "[digest_api_auth_rejected]")
        if (isinstance(events, list) and all(isinstance(e, dict) and e.get("message_id") == ident for e in events)
                and any(e.get("kind") == "blocked" and isinstance(e.get("body"), str)
                        and e["body"].endswith(before_send) for e in events)):
            # Credential/config rejection is definitive; the next invocation may
            # create a new ID. Never do this for a timeout or unknown outcome.
            with connect() as db:
                db.execute("DELETE FROM digest_henk_requests WHERE fingerprint=? AND request_id=?", (fingerprint, ident))
        raise HenkUnavailable("Henk požadavek odmítl; zůstává poslední úspěšné shrnutí.")
    if phase != "DONE":
        raise HenkUnavailable("Henk výsledek nepotvrdil; nový požadavek se nevytváří.")
    events = call("list_henk_events", {"request_id": ident, "after_cursor": 0, "limit": 50})
    events = events.get("result") if isinstance(events, dict) else events
    if not isinstance(events, list) or any(not isinstance(event, dict) or event.get("message_id") != ident for event in events):
        raise HenkUnavailable("Odpověď nemá správnou korelaci.")
    if any(event.get("kind") not in ("received", "answer", "done") and not
           (event.get("kind") == "progress" and event.get("body") == "Čekám na dokončení předchozí úlohy.")
           for event in events):
        raise HenkUnavailable("Henk oznámil nepovolenou událost.")
    answers = [event.get("body") for event in events if event.get("kind") == "answer"]
    done = [event for event in events if event.get("kind") == "done"]
    if len(answers) != 1 or len(done) != 1 or not isinstance(answers[0], str):
        raise HenkUnavailable("Henk nevrátil jedinou dokončenou odpověď.")
    return answers[0]
