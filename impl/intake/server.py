#!/usr/bin/env python3
"""
abra intake: a write-only HTTP endpoint other VMs use to record notes into abra.

One operation: POST /store. There is no read, list, update or delete endpoint,
so a caller holding a token can add notes and learn nothing back but the new id.

Each token belongs to one VM and is accepted only from that VM's IP (the TCP
peer address, not a header). Writes land in the token's scope (default
`intake`) under category `intake/<vm>`, stamped created_by urn:abra:intake:<vm>,
so a compromised VM can neither read abra nor write as another VM.

Tokens: see tokens.py. Only sha256 hashes are stored, in tokens.json (600, gitignored).
"""
import hashlib
import json
import os
import re
import sys
import threading
import time
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'pgvector'))
from write_binding import AbraWriter, embed  # noqa: E402
from query import _resolve_cat_path  # noqa: E402

HOST = os.getenv("ABRA_INTAKE_HOST", "10.0.0.200")
PORT = int(os.getenv("ABRA_INTAKE_PORT", "8040"))
TOKENS_FILE = os.getenv("ABRA_INTAKE_TOKENS", os.path.join(HERE, "tokens.json"))

MAX_BODY = 100_000
MAX_CONTENT = 65_536
RATE_PER_MIN = 60
NAME_RE = re.compile(r'^[a-z0-9][a-z0-9-]{0,79}$')
DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')

_catcodes = {}
_catcode_lock = threading.Lock()
_hits = {}
_hits_lock = threading.Lock()


def load_tokens():
    """Re-read on every request so adding or revoking a token needs no restart."""
    try:
        with open(TOKENS_FILE) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def rate_ok(vm):
    now = time.time()
    with _hits_lock:
        recent = [t for t in _hits.get(vm, []) if now - t < 60]
        if len(recent) >= RATE_PER_MIN:
            _hits[vm] = recent
            return False
        recent.append(now)
        _hits[vm] = recent
        return True


def catcode_for(writer, vm):
    with _catcode_lock:
        if vm not in _catcodes:
            _catcodes[vm] = _resolve_cat_path(writer, f"intake/{vm}")
            writer.conn.commit()
        return _catcodes[vm]


def validate(body):
    name = body.get("name")
    content = body.get("content")
    qualifier = body.get("qualifier")
    note_date = body.get("date")
    if not isinstance(name, str) or not NAME_RE.match(name):
        return "name: lowercase letters, digits, hyphens, max 80"
    if not isinstance(content, str) or not content.strip() or len(content) > MAX_CONTENT:
        return f"content: non-empty string, max {MAX_CONTENT} chars"
    if qualifier is not None and (not isinstance(qualifier, str) or len(qualifier) > 200):
        return "qualifier: string, max 200 chars"
    if note_date is not None:
        if note_date == "today":
            body["date"] = date.today().isoformat()
        elif not isinstance(note_date, str) or not DATE_RE.match(note_date):
            return "date: YYYY-MM-DD or 'today'"
    return None


class Handler(BaseHTTPRequestHandler):
    server_version = "abra-intake"
    sys_version = ""

    def reply(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            return self.reply(200, {"ok": True})
        self.reply(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/store":
            return self.reply(404, {"error": "not found"})

        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return self.reply(401, {"error": "missing bearer token"})
        entry = load_tokens().get(hashlib.sha256(auth[7:].strip().encode()).hexdigest())
        if not entry or entry.get("ip") != self.client_address[0]:
            return self.reply(403, {"error": "token not valid from this address"})
        vm = entry["vm"]
        if not rate_ok(vm):
            return self.reply(429, {"error": f"max {RATE_PER_MIN} writes per minute"})

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self.reply(400, {"error": "bad Content-Length"})
        if length <= 0 or length > MAX_BODY:
            return self.reply(413, {"error": f"body must be 1..{MAX_BODY} bytes"})
        try:
            body = json.loads(self.rfile.read(length))
        except (ValueError, UnicodeDecodeError):
            return self.reply(400, {"error": "body must be JSON"})
        if not isinstance(body, dict):
            return self.reply(400, {"error": "body must be a JSON object"})
        err = validate(body)
        if err:
            return self.reply(400, {"error": err})

        writer = AbraWriter(writer_uri=f"urn:abra:intake:{vm}")
        try:
            catcode = catcode_for(writer, vm)
            content_id = writer.store_content(
                f"intake-{vm}-{body['name']}", body["content"], catcode=catcode)
            writer.write_binding(
                entry.get("scope", "intake"), body["name"], "ABOUT", "content",
                str(content_id), qualifier=body.get("qualifier") or f"from {vm}",
                source_date=body.get("date"), catcode=catcode)
        except Exception as e:
            self.log_error("store failed for %s: %s", vm, e)
            return self.reply(500, {"error": "store failed"})
        finally:
            writer.close()
        self.reply(201, {"id": content_id})

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.client_address[0], fmt % args))


def main():
    embed("warm up")  # load the embedding model once, before the first request
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
