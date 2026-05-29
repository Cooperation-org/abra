#!/usr/bin/env python3
"""Migration 002 — per-user config + per-user scoring + language labels on bindings.

Adds three additive tables (no impact on existing tables):

  user_config(user_uri, key, value JSONB, updated_at)
      Per-user view config. Tab names, column visibility, sort order,
      hot-portal catcode, etc. — all things the user can rename or
      rearrange. View reads on render, writes back per-key.

  user_signal(user_uri, scope, name, score_kind, value, updated_at)
      Per-user scoring. score_kind = 'now' (recency-weighted importance)
      or 'long' (persistent emotional pin). Drives reorder in views.

  binding_labels(binding_id, label, added_by, added_at)
      Free-language labels on bindings. User vocabulary: 'todo', 'goal',
      'urgent', 'for-jen', whatever. Drives view-side grouping, tabs,
      filters — without any hardcoded primitive for todo-ness or
      goal-ness. Labels emerge from use.

Per Golda 2026-05-29: "we can use language" — labels are pure strings,
not enums, not URIs, not catcodes. View can group, filter, render
however it wants; the data model just stores.

Run:
    PG_USER=cobox PG_PASSWORD= ../../.venv/bin/python 002_user_config_signals_labels.py
    PG_USER=cobox PG_PASSWORD= ../../.venv/bin/python 002_user_config_signals_labels.py --dry-run

(requires table-owner credentials — cobox — to ALTER. Daily app
connections use abra_user as before; no change there.)
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


def table_exists(cur, name: str) -> bool:
    cur.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_name = %s", (name,)
    )
    return cur.fetchone() is not None


STATEMENTS = [
    (
        "user_config",
        """
        CREATE TABLE IF NOT EXISTS user_config (
            user_uri    TEXT        NOT NULL,
            key         TEXT        NOT NULL,
            value       JSONB       NOT NULL,
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (user_uri, key)
        )
        """,
    ),
    (
        "user_signal",
        """
        CREATE TABLE IF NOT EXISTS user_signal (
            user_uri    TEXT         NOT NULL,
            scope       VARCHAR(255) NOT NULL,
            name        VARCHAR(255) NOT NULL,
            score_kind  VARCHAR(64)  NOT NULL,
            value       REAL         NOT NULL,
            updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            PRIMARY KEY (user_uri, scope, name, score_kind)
        )
        """,
    ),
    (
        "idx_user_signal_rank",
        """
        CREATE INDEX IF NOT EXISTS idx_user_signal_rank
            ON user_signal (user_uri, scope, score_kind, value DESC)
        """,
    ),
    (
        "binding_labels",
        """
        CREATE TABLE IF NOT EXISTS binding_labels (
            binding_id  BIGINT      NOT NULL REFERENCES bindings(id) ON DELETE CASCADE,
            label       TEXT        NOT NULL,
            added_by    TEXT        NOT NULL,
            added_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (binding_id, label)
        )
        """,
    ),
    (
        "idx_binding_labels_label",
        """
        CREATE INDEX IF NOT EXISTS idx_binding_labels_label
            ON binding_labels (label)
        """,
    ),
    (
        "idx_binding_labels_binding",
        """
        CREATE INDEX IF NOT EXISTS idx_binding_labels_binding
            ON binding_labels (binding_id)
        """,
    ),
]


def run(dry_run: bool = False) -> None:
    conn = psycopg2.connect(**PG)
    conn.autocommit = False
    cur = conn.cursor()

    print(f"connected to {PG['user']}@{PG['host']}:{PG['port']}/{PG['dbname']}")
    print(f"mode: {'DRY RUN (no changes will commit)' if dry_run else 'APPLY'}")
    print()

    for label, sql in STATEMENTS:
        print(f"  → {label}")
        if dry_run:
            continue
        cur.execute(sql)

    if dry_run:
        print("\n  DRY RUN — rolling back")
        conn.rollback()
        cur.close()
        conn.close()
        return

    conn.commit()
    print("\n  committed")

    # Grant the daily app user (abra_user) read/write on the new tables.
    # The tables are owned by cobox (the migration user); without this,
    # abra_user can't INSERT/SELECT against them.
    app_user = os.getenv("ABRA_APP_USER", "abra_user")
    for table in ("user_config", "user_signal", "binding_labels"):
        cur.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {app_user}"
        )
    conn.commit()
    print(f"  granted SELECT/INSERT/UPDATE/DELETE on new tables to {app_user}")

    # Summary
    for table in ("user_config", "user_signal", "binding_labels"):
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        print(f"  {table}: {cur.fetchone()[0]} rows")

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
