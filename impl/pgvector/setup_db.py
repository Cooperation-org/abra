#!/usr/bin/env python3
"""
Initialize abra database with bindings + content tables.
Schema matches binding-format-v0.1.md spec.

Backend follows db.py: ABRA_DATABASE_URL=sqlite:///<path> creates the full
current schema in a SQLite file; otherwise PostgreSQL from PG_* vars, then
run migrations/ in order.
"""
import os
import sys

import db

EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "384"))

# SQLite equivalent of setup_postgres() plus migrations 001-003. Timestamps are
# local-time text; catcodes are JSON arrays; embeddings are float32 blobs.
SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS catcode_registry (
    catcode TEXT PRIMARY KEY CHECK (length(catcode) <= 64),
    parent_catcode TEXT REFERENCES catcode_registry(catcode) ON DELETE CASCADE,
    label TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_catcode_parent ON catcode_registry (parent_catcode);

CREATE TABLE IF NOT EXISTS content (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file TEXT,
    content TEXT NOT NULL,
    embedding BLOB,
    note_date DATE,
    catcode TEXT,
    catcodes TEXT,
    created_by TEXT,
    created_at TIMESTAMP DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_content_note_date ON content (note_date);
CREATE INDEX IF NOT EXISTS idx_content_catcode ON content (catcode);

CREATE TABLE IF NOT EXISTS bindings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope TEXT NOT NULL,
    name TEXT NOT NULL,
    relationship TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_ref TEXT NOT NULL,
    qualifier TEXT,
    permanence TEXT DEFAULT 'CURRENT',
    source_date DATE,
    catcode TEXT,
    catcodes TEXT,
    created_by TEXT,
    created_at TIMESTAMP DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_bindings_scope_name ON bindings (scope, name);
CREATE INDEX IF NOT EXISTS idx_bindings_relationship ON bindings (relationship);
CREATE INDEX IF NOT EXISTS idx_bindings_target ON bindings (target_type, target_ref);
CREATE INDEX IF NOT EXISTS idx_bindings_source_date ON bindings (source_date);
CREATE INDEX IF NOT EXISTS idx_bindings_catcode ON bindings (catcode);

CREATE TABLE IF NOT EXISTS hot_tags (
    scope TEXT NOT NULL,
    name TEXT NOT NULL,
    priority INTEGER DEFAULT 0,
    added_at TIMESTAMP DEFAULT (datetime('now', 'localtime')),
    expires_at TIMESTAMP,
    PRIMARY KEY (scope, name)
);

CREATE TABLE IF NOT EXISTS user_config (
    user_uri TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT (datetime('now', 'localtime')),
    PRIMARY KEY (user_uri, key)
);

CREATE TABLE IF NOT EXISTS user_signal (
    user_uri TEXT NOT NULL,
    scope TEXT NOT NULL,
    name TEXT NOT NULL,
    score_kind TEXT NOT NULL,
    value REAL NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT (datetime('now', 'localtime')),
    PRIMARY KEY (user_uri, scope, name, score_kind)
);
CREATE INDEX IF NOT EXISTS idx_user_signal_rank
    ON user_signal (user_uri, scope, score_kind, value DESC);

CREATE TABLE IF NOT EXISTS labels (
    scope TEXT NOT NULL,
    name TEXT NOT NULL,
    label TEXT NOT NULL,
    added_by TEXT NOT NULL,
    added_at TIMESTAMP NOT NULL DEFAULT (datetime('now', 'localtime')),
    expires_at TIMESTAMP,
    PRIMARY KEY (scope, name, label)
);
CREATE INDEX IF NOT EXISTS idx_labels_label ON labels (label);
CREATE INDEX IF NOT EXISTS idx_labels_scope_name ON labels (scope, name);

-- hot_tags mirrors into labels as label='hot' (migration 003 bridge)
CREATE TRIGGER IF NOT EXISTS hot_tag_bridge_insert AFTER INSERT ON hot_tags
BEGIN
    INSERT INTO labels (scope, name, label, added_by, added_at, expires_at)
    VALUES (NEW.scope, NEW.name, 'hot', 'urn:abra:hot-tag-bridge', NEW.added_at, NEW.expires_at)
    ON CONFLICT (scope, name, label) DO UPDATE
        SET added_at = excluded.added_at, expires_at = excluded.expires_at;
END;
CREATE TRIGGER IF NOT EXISTS hot_tag_bridge_update AFTER UPDATE ON hot_tags
BEGIN
    INSERT INTO labels (scope, name, label, added_by, added_at, expires_at)
    VALUES (NEW.scope, NEW.name, 'hot', 'urn:abra:hot-tag-bridge', NEW.added_at, NEW.expires_at)
    ON CONFLICT (scope, name, label) DO UPDATE
        SET added_at = excluded.added_at, expires_at = excluded.expires_at;
END;
CREATE TRIGGER IF NOT EXISTS hot_tag_bridge_delete AFTER DELETE ON hot_tags
BEGIN
    DELETE FROM labels WHERE scope = OLD.scope AND name = OLD.name AND label = 'hot';
END;
"""


def setup():
    if db.is_sqlite():
        setup_sqlite()
    else:
        setup_postgres()


def setup_sqlite():
    path = db.sqlite_path()
    print(f"Opening SQLite database at {path}...")
    conn = db.connect(create=True)
    conn.executescript(SQLITE_SCHEMA)
    conn.commit()
    conn.close()
    print(f"\nDatabase ready: {path}")


def setup_postgres():
    import psycopg2
    pg = db.pg_params()
    PG_HOST, PG_PORT, PG_USER = pg["host"], pg["port"], pg["user"]
    PG_PASSWORD, PG_DATABASE = pg["password"], pg["dbname"]

    # Connect to postgres to create database if needed
    print(f"Connecting to PostgreSQL at {PG_HOST}...")
    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, user=PG_USER,
        password=PG_PASSWORD, dbname="postgres"
    )
    conn.autocommit = True
    cur = conn.cursor()

    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (PG_DATABASE,))
    if not cur.fetchone():
        cur.execute(f"CREATE DATABASE {PG_DATABASE}")
        print(f"Created database: {PG_DATABASE}")
    else:
        print(f"Database {PG_DATABASE} already exists")

    cur.close()
    conn.close()

    # Connect to abra database
    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, user=PG_USER,
        password=PG_PASSWORD, dbname=PG_DATABASE
    )
    conn.autocommit = True
    cur = conn.cursor()

    cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
    print("pgvector extension enabled")

    # Catcode registry — the fundamental structure
    # Defines positions in the shared information space.
    # Prefix search on catcode returns subtrees. Cascading deletes.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS catcode_registry (
            catcode VARCHAR(64) PRIMARY KEY,
            parent_catcode VARCHAR(64) REFERENCES catcode_registry(catcode) ON DELETE CASCADE,
            label TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    # text_pattern_ops enables prefix search: WHERE catcode LIKE 'a00101%'
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_catcode_prefix
        ON catcode_registry (catcode varchar_pattern_ops)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_catcode_parent
        ON catcode_registry (parent_catcode)
    """)
    print("Table: catcode_registry")

    # Content table — where blobs live.
    # catcode (singular, legacy) is kept; catcodes (array, spec-current) is the
    # one new code should read. Migration 001 adds catcodes + created_by to
    # existing DBs; fresh installs include them here.
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS content (
            id SERIAL PRIMARY KEY,
            source_file VARCHAR(512),
            content TEXT NOT NULL,
            embedding vector({EMBEDDING_DIM}),
            note_date DATE,
            catcode VARCHAR(64),
            catcodes TEXT[],
            created_by TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    print("Table: content")

    # Bindings table — the core of abra.
    # See note above on catcode vs catcodes.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bindings (
            id SERIAL PRIMARY KEY,
            scope VARCHAR(255) NOT NULL,
            name VARCHAR(255) NOT NULL,
            relationship VARCHAR(100) NOT NULL,
            target_type VARCHAR(50) NOT NULL,
            target_ref TEXT NOT NULL,
            qualifier VARCHAR(255),
            permanence VARCHAR(20) DEFAULT 'CURRENT',
            source_date DATE,
            catcode VARCHAR(64),
            catcodes TEXT[],
            created_by TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    print("Table: bindings")

    # Hot tags — lightweight flag marking names as "warm context"
    # Not part of the binding format (runtime/agent concern).
    # A name in a scope that should be loaded first when referenced.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS hot_tags (
            scope VARCHAR(255) NOT NULL,
            name VARCHAR(255) NOT NULL,
            priority INTEGER DEFAULT 0,
            added_at TIMESTAMP DEFAULT NOW(),
            expires_at TIMESTAMP,
            PRIMARY KEY (scope, name)
        )
    """)
    print("Table: hot_tags")

    # Indexes
    cur.execute("CREATE INDEX IF NOT EXISTS idx_content_note_date ON content(note_date)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_content_catcode ON content(catcode)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_bindings_scope_name ON bindings(scope, name)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_bindings_relationship ON bindings(relationship)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_bindings_target ON bindings(target_type, target_ref)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_bindings_source_date ON bindings(source_date)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_bindings_catcode ON bindings(catcode)")
    # GIN indexes for fast array-membership lookups on the multi-catcode column
    cur.execute("CREATE INDEX IF NOT EXISTS idx_content_catcodes_gin ON content USING gin (catcodes)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_bindings_catcodes_gin ON bindings USING gin (catcodes)")
    print("Indexes created")

    cur.close()
    conn.close()
    print(f"\nDatabase ready: {PG_DATABASE} on {PG_HOST}")


if __name__ == "__main__":
    try:
        setup()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
