"""Database connection and SQL dialect for the abra binding store.

Backend selection:
  - ABRA_DATABASE_URL=sqlite:///<path>   SQLite file (`~` expands; four slashes for an absolute path)
  - ABRA_DATABASE_URL=postgresql://...   PostgreSQL + pgvector
  - unset                                PostgreSQL from PG_* vars (default)

SQL in callers uses the psycopg2 `%s` paramstyle on both backends. The few
fragments that differ (case-insensitive match, time arithmetic, arrays,
vectors) come from the `Dialect` returned by `dialect()`.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import date, datetime
from pathlib import Path

import instance  # noqa: F401  loads impl/.env

SQLITE_PREFIX = "sqlite://"


def database_url() -> str:
    """The configured connection URL, or '' for the PG_* default."""
    return os.getenv("ABRA_DATABASE_URL", "")


def pg_params(default_user: str = "cobox") -> dict:
    """psycopg2 connect kwargs from PG_* vars."""
    return dict(
        host=os.getenv("PG_HOST", "10.0.0.100"),
        port=os.getenv("PG_PORT", "5432"),
        user=os.getenv("PG_USER", default_user),
        password=os.getenv("PG_PASSWORD", ""),
        dbname=os.getenv("PG_DATABASE", "abra"),
    )


def is_sqlite(url: str | None = None) -> bool:
    return (database_url() if url is None else url).startswith(SQLITE_PREFIX)


def sqlite_path(url: str | None = None) -> Path:
    """Filesystem path from a sqlite:/// URL (SQLAlchemy convention)."""
    url = database_url() if url is None else url
    rest = url[len(SQLITE_PREFIX):]
    if not rest.startswith("/"):
        raise ValueError(f"expected sqlite:///<path>, got {url!r}")
    return Path(rest[1:]).expanduser()


def connect(url: str | None = None, create: bool = False):
    """Open a DB-API connection to the configured store.

    create: SQLite only; allow creating a new database file (schema setup)."""
    url = database_url() if url is None else url
    if is_sqlite(url):
        return _connect_sqlite(sqlite_path(url), create=create)
    import psycopg2
    if url:
        return psycopg2.connect(url)
    return psycopg2.connect(**pg_params())


def dialect(url: str | None = None) -> "Dialect":
    return SQLITE if is_sqlite(url) else POSTGRES


# ── SQLite connection: psycopg2 paramstyle + PG-compatible types ─────────

_PYFORMAT = re.compile(r"%([%s])")


def _to_qmark(sql: str) -> str:
    """Translate psycopg2 `%s` / `%%` to sqlite3 `?` / `%`."""
    return _PYFORMAT.sub(lambda m: "?" if m.group(1) == "s" else "%", sql)


class _PyformatCursor(sqlite3.Cursor):
    def execute(self, sql, params=None):
        if params is None:
            return super().execute(sql)
        return super().execute(_to_qmark(sql), params)

    def executemany(self, sql, seq_of_params):
        return super().executemany(_to_qmark(sql), seq_of_params)


class _PyformatConnection(sqlite3.Connection):
    def cursor(self, factory=_PyformatCursor):
        return super().cursor(factory)


sqlite3.register_adapter(date, date.isoformat)
sqlite3.register_adapter(datetime, lambda d: d.isoformat(" "))
sqlite3.register_converter("DATE", lambda b: date.fromisoformat(b.decode()))
sqlite3.register_converter("TIMESTAMP", lambda b: datetime.fromisoformat(b.decode()))


def _connect_sqlite(path: Path, create: bool) -> sqlite3.Connection:
    if not create and not path.exists():
        raise FileNotFoundError(
            f"abra database not found at {path}. "
            f"Create it: .venv/bin/python pgvector/setup_db.py")
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, factory=_PyformatConnection,
                           detect_types=sqlite3.PARSE_DECLTYPES)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


# ── Dialect ──────────────────────────────────────────────────────────────

class Dialect:
    """SQL fragments and value encodings that differ between backends."""

    name: str
    now: str  # current local timestamp expression

    def ilike(self, expr: str) -> str:
        """Case-insensitive LIKE against one `%s` parameter."""
        raise NotImplementedError

    def now_plus_days(self) -> str:
        """Timestamp `%s` days from now (one integer parameter)."""
        raise NotImplementedError

    def array(self, values: list[str]):
        """Encode a text-array column value."""
        raise NotImplementedError

    def vector(self, values):
        """Encode an embedding column value; None passes through."""
        raise NotImplementedError

    def nearest_content(self, cur, query_vec, limit: int) -> list[tuple]:
        """Content rows nearest to query_vec by cosine similarity.
        Returns (id, source_file, note_date, content, similarity), best first."""
        raise NotImplementedError


class _Postgres(Dialect):
    name = "postgres"
    now = "NOW()"

    def ilike(self, expr):
        return f"{expr} ILIKE %s"

    def now_plus_days(self):
        return "NOW() + make_interval(days => %s)"

    def array(self, values):
        return list(values)

    def vector(self, values):
        return None if values is None else str(list(values))

    def nearest_content(self, cur, query_vec, limit):
        vec = self.vector(query_vec)
        cur.execute("""
            SELECT c.id, c.source_file, c.note_date, c.content,
                   1 - (c.embedding <=> %s::vector) AS similarity
            FROM content c
            WHERE c.embedding IS NOT NULL
            ORDER BY c.embedding <=> %s::vector
            LIMIT %s
        """, (vec, vec, limit))
        return cur.fetchall()


class _Sqlite(Dialect):
    """Timestamps are local-time text, matching PG TIMESTAMP in the session zone.
    Arrays are JSON text. Embeddings are float32 blobs searched in Python."""
    name = "sqlite"
    now = "datetime('now', 'localtime')"

    def ilike(self, expr):
        # SQLite LIKE is case-insensitive for ASCII.
        return f"{expr} LIKE %s"

    def now_plus_days(self):
        return "datetime('now', 'localtime', '+' || %s || ' days')"

    def array(self, values):
        return json.dumps(list(values))

    def vector(self, values):
        if values is None:
            return None
        import numpy as np
        return np.asarray(values, dtype=np.float32).tobytes()

    def nearest_content(self, cur, query_vec, limit):
        import numpy as np
        cur.execute("SELECT id, embedding FROM content WHERE embedding IS NOT NULL")
        rows = cur.fetchall()
        if not rows:
            return []
        ids = [r[0] for r in rows]
        matrix = np.stack([np.frombuffer(r[1], dtype=np.float32) for r in rows])
        query = np.asarray(query_vec, dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1) * np.linalg.norm(query)
        sims = (matrix @ query) / np.where(norms == 0, 1, norms)
        top = np.argsort(-sims)[:limit]
        top_ids = [ids[i] for i in top]
        placeholders = ", ".join(["%s"] * len(top_ids))
        cur.execute(
            f"SELECT id, source_file, note_date, content FROM content WHERE id IN ({placeholders})",
            top_ids)
        by_id = {r[0]: r for r in cur.fetchall()}
        return [(*by_id[ids[i]], float(sims[i])) for i in top]


POSTGRES = _Postgres()
SQLITE = _Sqlite()
