"""Text embeddings for content blobs and search queries.

Asks the local embed service (embed_server.py) first so callers never load the
model; falls back to loading sentence-transformers in-process when the service
is not running.
"""
from __future__ import annotations

import json
import os
import socket
from pathlib import Path

import instance  # noqa: F401  loads impl/.env

MODEL_NAME = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
SERVICE_TIMEOUT_S = 30

_model = None


def socket_path() -> Path:
    return Path(os.getenv("ABRA_EMBED_SOCKET", "~/.abra/embed.sock")).expanduser()


def local_model():
    """Lazy-load the sentence-transformers model in this process."""
    global _model
    if _model is None:
        os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
        os.environ.setdefault("HF_HUB_VERBOSITY", "error")
        os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def encode(text: str) -> list[float]:
    """Embedding vector for text, from the service when available."""
    vec = _from_service(text)
    if vec is None:
        vec = local_model().encode(text).tolist()
    return vec


def _from_service(text: str) -> list[float] | None:
    """None when the service is absent, unreachable, or serves another model."""
    path = socket_path()
    if not path.exists():
        return None
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(SERVICE_TIMEOUT_S)
            s.connect(str(path))
            s.sendall(json.dumps({"model": MODEL_NAME, "text": text}).encode() + b"\n")
            with s.makefile("rb") as f:
                reply = json.loads(f.readline())
    except (OSError, ValueError):
        return None
    vec = reply.get("vector") if isinstance(reply, dict) else None
    return vec if isinstance(vec, list) else None
