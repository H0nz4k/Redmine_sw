#!/usr/bin/env python3
"""Owner-only local HENK voice inbox.

Runs as existing unprivileged 'henkmcp' service identity. SO_PEERCRED restricts
access to the explicitly designated local human operator ('hanz'). The *only*
operations are send_message, message_status, and list_message_events of the
existing Queue. It does not expose queue files or tool execution to clients.

This is an opt-in local transport, not a replacement for public Cloudflare
Access auth. It reuses the existing durable message admission and approval flow.
"""
import argparse
import json
import os
from pathlib import Path
import pwd
import signal
import socket
import stat
import struct
import sys
import time
import uuid

MAX_REQUEST = 8192
MAX_REPLY = 65536
ALLOWED = {"send", "status", "events"}


def validate(req):
    if not isinstance(req, dict) or req.get("method") not in ALLOWED:
        raise ValueError("unsupported_method")
    method = req["method"]
    if method == "send":
        if set(req) not in ({"method", "id", "kind", "text", "expires"},
                            {"method", "id", "kind", "text", "expires", "thread"}):
            raise ValueError("invalid_fields")
        if req["kind"] not in ("message", "task"):
            raise ValueError("invalid_kind")
        if "thread" in req and req["kind"] != "message":
            raise ValueError("conversation_only_message")
        if not isinstance(req["text"], str) or not 1 <= len(req["text"].strip()) <= 2000:
            raise ValueError("invalid_text")
        if type(req["expires"]) is not int or not time.time() < req["expires"] <= time.time() + 3600:
            raise ValueError("invalid_expiry")
    elif method == "status" and set(req) != {"method", "id"}:
        raise ValueError("invalid_fields")
    elif method == "events" and set(req) != {"method", "id", "after"}:
        raise ValueError("invalid_fields")
    ident = req["id"]
    if not isinstance(ident, str):
        raise ValueError("invalid_id")
    try:
        if str(uuid.UUID(ident)) != ident:
            raise ValueError("invalid_id")
    except (ValueError, AttributeError):
        raise ValueError("invalid_id") from None
    if method == "send" and "thread" in req:
        try:
            if str(uuid.UUID(req["thread"])) != req["thread"]:
                raise ValueError("invalid_thread")
        except (ValueError, TypeError, AttributeError):
            raise ValueError("invalid_thread") from None
    if method == "events" and (type(req["after"]) is not int or req["after"] < 0):
        raise ValueError("invalid_cursor")
    return req


def dispatch(queue, req):
    req = validate(req)
    method = req["method"]
    if method == "send":
        if "thread" in req:
            return queue.conversation_send(req["id"], req["thread"], req["kind"],
                                           req["text"], req["expires"])
        return queue.send_message(req["id"], req["kind"], req["text"], req["expires"])
    if method == "status":
        return queue.message_status(req["id"])
    return queue.list_message_events(req["after"], 50, req["id"])


def serve(queue, path, uid):
    sock_path = Path(path)
    parent = sock_path.parent
    info = parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o022:
        raise ValueError("untrusted_socket_directory")
    if sock_path.is_symlink():
        raise ValueError("socket_symlink_refused")
    if sock_path.exists():
        st = sock_path.lstat()
        if not stat.S_ISSOCK(st.st_mode) or st.st_uid != os.geteuid():
            raise ValueError("occupied_socket")
        sock_path.unlink()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(str(sock_path))
        os.chmod(sock_path, 0o660)
        listener.listen(4)
        listener.settimeout(1)
        print("Voice inbox listening locally", flush=True)
        while True:
            try:
                conn, _ = listener.accept()
            except socket.timeout:
                continue
            with conn:
                conn.settimeout(4)
                try:
                    pid, peer_uid, peer_gid = struct.unpack("3i", conn.getsockopt(
                        socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")))
                    if peer_uid != uid:
                        continue
                    raw = bytearray()
                    while b"\n" not in raw and len(raw) <= MAX_REQUEST:
                        data = conn.recv(4096)
                        if not data:
                            break
                        raw.extend(data)
                    if len(raw) > MAX_REQUEST or not raw.endswith(b"\n"):
                        raise ValueError("invalid_frame")
                    req = json.loads(raw[:-1])
                    result = dispatch(queue, req)
                    response = json.dumps({"result": result}, ensure_ascii=False,
                                          separators=(",", ":")).encode() + b"\n"
                    if len(response) > MAX_REPLY:
                        raise ValueError("reply_too_large")
                except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError):
                    response = b'{"error":"request_refused"}\n'
                conn.sendall(response)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", default="/var/lib/hanzhub-mcp-channel")
    parser.add_argument("--socket", default="/run/respeaker-henk/voice.sock")
    parser.add_argument("--owner", default="hanz")
    args = parser.parse_args()
    if os.geteuid() == 0 or pwd.getpwuid(os.geteuid()).pw_name != "henkmcp":
        raise SystemExit("Run only as henkmcp; never as root.")
    if os.path.realpath(args.queue) != args.queue:
        raise SystemExit("Noncanonical queue path.")
    here = Path("/opt/hanzhub-project-control/mcp-channel")
    sys.path.insert(0, str(here))
    from channel import Queue
    queue = Queue(args.queue)
    serve(queue, args.socket, pwd.getpwnam(args.owner).pw_uid)


if __name__ == "__main__":
    main()
