#!/usr/bin/env python3
"""Migration 003 — labels on names (unifying primitive), hot_tags folds in.

Per Golda 2026-05-29 (after the view session's architectural input on
labels): labels attach to **names**, not bindings. The `hot_tags` table
becomes a special case — `labels` with `label='hot'`.

What this migration does (additive + one bridge trigger + one drop):

  1. CREATE TABLE labels(scope, name, label, added_by, added_at, expires_at)
     PRIMARY KEY (scope, name, label)
     The unifying language-label primitive.

  2. Copy existing hot_tags rows into labels as label='hot'
     (idempotent; ON CONFLICT DO NOTHING).

  3. Install bridge trigger on hot_tags so writes to it mirror to labels:
     INSERT/UPDATE on hot_tags → upsert (scope, name, 'hot') in labels
     with expires_at, added_by='urn:abra:hot-tag-bridge'
     DELETE on hot_tags → delete (scope, name, 'hot') from labels

     This keeps existing code (write_binding.set_hot, query.cmd_hot,
     `abra hot set/unset`) working while new label-aware code reads
     from labels. Later migration 00x can drop hot_tags + trigger
     once all callers are updated.

  4. DROP TABLE binding_labels — wrong unit (per labels rethink). It
     has zero rows from the prior migration 002 ship.

  5. GRANT on labels to abra_user.

Idempotent: re-running on already-migrated DB is a no-op.

Run:
    PG_USER=cobox PG_PASSWORD= ../../.venv/bin/python 003_labels_on_names.py
    PG_USER=cobox PG_PASSWORD= ../../.venv/bin/python 003_labels_on_names.py --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".." / ".." / ".env")

PG = dict(
    host=os.getenv("PG_HOST", "10.0.0.100"),
    port=os.getenv("PG_PORT", "5432"),
    user=os.getenv("PG_USER", "cobox"),
    password=os.getenv("PG_PASSWORD", ""),
    dbname=os.getenv("PG_DATABASE", "abra"),
)

HOT_TAG_BRIDGE_URI = "urn:abra:hot-tag-bridge"


def table_exists(cur, name: str) -> bool:
    cur.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_name = %s", (name,)
    )
    return cur.fetchone() is not None


def run(dry_run: bool = False) -> None:
    conn = psycopg2.connect(**PG)
    conn.autocommit = False
    cur = conn.cursor()

    print(f"connected to {PG['user']}@{PG['host']}:{PG['port']}/{PG['dbname']}")
    print(f"mode: {'DRY RUN (no changes will commit)' if dry_run else 'APPLY'}")
    print()

    steps = []

    steps.append(("create labels table", """
        CREATE TABLE IF NOT EXISTS labels (
            scope       VARCHAR(255) NOT NULL,
            name        VARCHAR(255) NOT NULL,
            label       TEXT         NOT NULL,
            added_by    TEXT         NOT NULL,
            added_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            expires_at  TIMESTAMPTZ,
            PRIMARY KEY (scope, name, label)
        )
    """))
    steps.append(("index labels (label)",
        "CREATE INDEX IF NOT EXISTS idx_labels_label ON labels (label)"))
    steps.append(("index labels (scope, name)",
        "CREATE INDEX IF NOT EXISTS idx_labels_scope_name ON labels (scope, name)"))

    steps.append(("backfill hot_tags into labels as label='hot'", f"""
        INSERT INTO labels (scope, name, label, added_by, added_at, expires_at)
        SELECT scope, name, 'hot', '{HOT_TAG_BRIDGE_URI}', added_at, expires_at
        FROM hot_tags
        ON CONFLICT (scope, name, label) DO NOTHING
    """))

    steps.append(("create hot_tags→labels bridge function", f"""
        CREATE OR REPLACE FUNCTION hot_tag_bridge() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                DELETE FROM labels
                WHERE scope = OLD.scope AND name = OLD.name AND label = 'hot';
                RETURN OLD;
            ELSE
                INSERT INTO labels (scope, name, label, added_by, added_at, expires_at)
                VALUES (NEW.scope, NEW.name, 'hot', '{HOT_TAG_BRIDGE_URI}', NEW.added_at, NEW.expires_at)
                ON CONFLICT (scope, name, label) DO UPDATE
                    SET added_at = EXCLUDED.added_at,
                        expires_at = EXCLUDED.expires_at;
                RETURN NEW;
            END IF;
        END;
        $$ LANGUAGE plpgsql
    """))
    steps.append(("drop hot_tag_bridge trigger if exists",
        "DROP TRIGGER IF EXISTS hot_tag_bridge_trigger ON hot_tags"))
    steps.append(("create hot_tag_bridge trigger", """
        CREATE TRIGGER hot_tag_bridge_trigger
        AFTER INSERT OR UPDATE OR DELETE ON hot_tags
        FOR EACH ROW EXECUTE FUNCTION hot_tag_bridge()
    """))

    if table_exists(cur, "binding_labels"):
        steps.append(("drop binding_labels (wrong unit, replaced by labels)",
            "DROP TABLE binding_labels"))
    else:
        print("  skip: binding_labels already absent")

    for label, sql in steps:
        print(f"  → {label}")
        if dry_run:
            continue
        cur.execute(sql)
        rc = cur.rowcount
        if rc > 0:
            print(f"    {rc} rows affected")

    if dry_run:
        print("\n  DRY RUN — rolling back")
        conn.rollback()
        cur.close()
        conn.close()
        return

    app_user = os.getenv("ABRA_APP_USER", "abra_user")
    cur.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON labels TO {app_user}")
    conn.commit()
    print(f"\n  committed; granted RW on labels to {app_user}")

    cur.execute("SELECT COUNT(*) FROM labels")
    n_labels = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM labels WHERE label = 'hot'")
    n_hot = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM hot_tags")
    n_hot_tags = cur.fetchone()[0]
    print(f"  labels: {n_labels} total ({n_hot} with label='hot')")
    print(f"  hot_tags: {n_hot_tags} (trigger keeps in sync with labels.label='hot')")

    cur.close()
    conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="Print what would change; don't commit.")
    args = ap.parse_args()
    try:
        run(dry_run=args.dry_run)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
