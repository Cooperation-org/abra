#!/usr/bin/env python3
"""Local embed service: holds the embedding model in memory for the abra CLI.

Listens on a user-only Unix socket ($ABRA_EMBED_SOCKET, default
~/.abra/embed.sock). One request per connection, newline-delimited JSON:
  → {"model": "<name>", "text": "<text>"}
  ← {"vector": [...]}  or  {"error": "<reason>"}

Run:  ../.venv/bin/python embed_server.py
macOS login agent: ../install-embed-service.sh
"""
from __future__ import annotations

import json
import os
import socketserver
import sys
import threading

import embedding

MAX_REQUEST_BYTES = 1_000_000

_encode_lock = threading.Lock()


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        line = self.rfile.readline(MAX_REQUEST_BYTES + 1)
        try:
            reply = self._reply(line)
        except Exception as e:  # never let one request take the service down
            reply = {"error": f"encode failed: {e}"}
        self.wfile.write(json.dumps(reply).encode() + b"\n")

    def _reply(self, line: bytes) -> dict:
        if len(line) > MAX_REQUEST_BYTES:
            return {"error": f"request over {MAX_REQUEST_BYTES} bytes"}
        try:
            req = json.loads(line)
        except ValueError:
            return {"error": "request must be JSON"}
        if not isinstance(req, dict) or not isinstance(req.get("text"), str):
            return {"error": "request needs a text string"}
        if req.get("model") != embedding.MODEL_NAME:
            return {"error": f"service model is {embedding.MODEL_NAME}"}
        with _encode_lock:
            return {"vector": embedding.local_model().encode(req["text"]).tolist()}


class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True


def main():
    path = embedding.socket_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    embedding.local_model().encode("warm up")
    if path.exists():
        path.unlink()
    old_umask = os.umask(0o177)
    try:
        server = Server(str(path), Handler)
    finally:
        os.umask(old_umask)
    print(f"abra embed service: {embedding.MODEL_NAME} on {path}", file=sys.stderr, flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        if path.exists():
            path.unlink()


if __name__ == "__main__":
    main()
