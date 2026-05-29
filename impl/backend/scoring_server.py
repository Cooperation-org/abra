#!/usr/bin/env python3
"""Abra scoring + labels HTTP service.

Small stdlib http.server exposing the per-user scoring and binding-label
endpoints backed by impl/pgvector/signals.py. JSON in, JSON out. View
sessions (or any other client) can call these to reorder rows by
updating per-user scores, and to tag bindings with free-language labels.

Run:
    cd /opt/shared/repos/abra
    ABRA_SCORING_PORT=8090 impl/.venv/bin/python impl/backend/scoring_server.py

Default port: 8090 (next to view's 8089). Listens on 127.0.0.1.

Endpoints
─────────

  POST   /signals                          set/update a score
         body: {user_uri, scope, name, kind, value}  → 200 {ok: true}
         kind: 'now' | 'long'

  DELETE /signals                          remove a score
         body: {user_uri, scope, name, kind}         → 200 {removed: bool}

  GET    /signals/ranked                   ranked names for a user+scope
         query: user_uri, scope, kind, limit (default 50)
         → 200 [{name, value, updated_at}, ...]

  POST   /labels                           attach a language label to a name
         body: {scope, name, label, added_by, expires_at?}  → 200 {ok: true}

  DELETE /labels                           remove a label
         body: {scope, name, label}                  → 200 {removed: bool}

  GET    /labels                           labels on a (scope, name)
         query: scope, name
         → 200 [{label, added_by, added_at, expires_at}, ...]

  GET    /labels/distinct                  all labels currently used in a scope
         query: scope
         → 200 [label, ...]

  GET    /labels/names                     names in scope carrying a label
         query: scope, label, limit (default 500)
         → 200 [{name, added_by, added_at, expires_at}, ...]

Labels attach to **names**, not bindings (per migration 003 / labels rethink).
`hot_tags` is now a bridge alias for `labels.label='hot'` — writes to the
hot_tags table mirror into labels automatically via a database trigger.

  GET    /healthz                          → 200 "ok"

All endpoints return JSON unless otherwise noted. Errors return JSON
{error: "..."} with the appropriate status code.

No authentication. Bind to 127.0.0.1; mount behind nginx if exposing
beyond the host. Real auth lands with the auth session.
"""
from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pgvector"))

import signals  # noqa: E402  (must come after sys.path mutation)

PORT = int(os.getenv("ABRA_SCORING_PORT", "8090"))
HOST = os.getenv("ABRA_SCORING_HOST", "127.0.0.1")


class BadRequest(Exception):
    """User-fixable validation problem; renders as 400."""


def _require(form: dict, *names: str) -> tuple:
    missing = [n for n in names if n not in form or form[n] in (None, "")]
    if missing:
        raise BadRequest(f"missing required field(s): {', '.join(missing)}")
    return tuple(form[n] for n in names)


class Handler(BaseHTTPRequestHandler):
    server_version = "AbraScoring/0.1"

    def log_message(self, fmt, *args):
        sys.stderr.write(f"[{self.log_date_time_string()}] {fmt % args}\n")

    def do_GET(self):    self._dispatch("GET")
    def do_POST(self):   self._dispatch("POST")
    def do_DELETE(self): self._dispatch("DELETE")

    # ── dispatch ─────────────────────────────────────────────────────

    def _dispatch(self, method: str) -> None:
        try:
            url = urlsplit(self.path)
            handler = self._route(method, url.path)
            if handler is None:
                return self._json(404, {"error": "not found"})
            qs = {k: v[0] for k, v in parse_qs(url.query).items()}
            body = self._read_json() if method in ("POST", "DELETE") else None
            status, payload = handler(qs, body)
            self._json(status, payload)
        except BadRequest as e:
            self._json(400, {"error": str(e)})
        except ValueError as e:
            self._json(400, {"error": str(e)})
        except Exception as e:  # genuine 500
            import traceback
            traceback.print_exc()
            self._json(500, {"error": str(e)})

    def _route(self, method: str, path: str):
        path = path.rstrip("/") or "/"
        table = {
            ("GET", "/healthz"):           self._healthz,
            ("POST", "/signals"):           self._post_signals,
            ("DELETE", "/signals"):         self._delete_signals,
            ("GET", "/signals/ranked"):     self._get_ranked,
            ("POST", "/labels"):            self._post_labels,
            ("DELETE", "/labels"):          self._delete_labels,
            ("GET", "/labels"):             self._get_labels,
            ("GET", "/labels/distinct"):    self._get_distinct_labels,
            ("GET", "/labels/names"):       self._get_names_by_label,
        }
        return table.get((method, path))

    # ── helpers ──────────────────────────────────────────────────────

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as e:
            raise BadRequest(f"invalid JSON body: {e}")
        if not isinstance(data, dict):
            raise BadRequest("body must be a JSON object")
        return data

    def _json(self, status: int, payload) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    # ── handlers ─────────────────────────────────────────────────────

    def _healthz(self, qs, body):
        return 200, "ok"

    def _post_signals(self, qs, body):
        user_uri, scope, name, kind, value = _require(
            body or {}, "user_uri", "scope", "name", "kind", "value"
        )
        signals.set_score(user_uri, scope, name, kind, float(value))
        return 200, {"ok": True}

    def _delete_signals(self, qs, body):
        user_uri, scope, name, kind = _require(
            body or {}, "user_uri", "scope", "name", "kind"
        )
        removed = signals.delete_score(user_uri, scope, name, kind)
        return 200, {"removed": removed}

    def _get_ranked(self, qs, body):
        user_uri, scope, kind = _require(qs, "user_uri", "scope", "kind")
        limit = int(qs.get("limit", 50))
        rows = signals.ranked(user_uri, scope, kind, limit)
        return 200, [{"name": n, "value": v, "updated_at": t} for n, v, t in rows]

    def _post_labels(self, qs, body):
        scope, name, label, added_by = _require(
            body or {}, "scope", "name", "label", "added_by"
        )
        expires_at = (body or {}).get("expires_at")  # optional
        signals.set_label(scope, name, label, added_by, expires_at)
        return 200, {"ok": True}

    def _delete_labels(self, qs, body):
        scope, name, label = _require(body or {}, "scope", "name", "label")
        removed = signals.remove_label(scope, name, label)
        return 200, {"removed": removed}

    def _get_labels(self, qs, body):
        scope, name = _require(qs, "scope", "name")
        return 200, signals.labels_for_name(scope, name)

    def _get_distinct_labels(self, qs, body):
        (scope,) = _require(qs, "scope")
        return 200, signals.distinct_labels_in_scope(scope)

    def _get_names_by_label(self, qs, body):
        scope, label = _require(qs, "scope", "label")
        limit = int(qs.get("limit", 500))
        return 200, signals.names_by_label(scope, label, limit)


def main() -> None:
    print(f"abra scoring service → http://{HOST}:{PORT}/")
    print(f"  endpoints: POST /signals · GET /signals/ranked · POST/DELETE/GET /labels · GET /labels/distinct")
    print("  stop with Ctrl-C")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
