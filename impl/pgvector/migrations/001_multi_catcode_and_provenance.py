#!/usr/bin/env python3
"""Migration 001 — multi-catcode arrays + provenance.

Adds (additively, no drops):

  bindings.catcodes      TEXT[]              -- array (spec already says multi)
  bindings.created_by    TEXT                -- writer URI (provenance)
  content.catcodes       TEXT[]
  content.created_by     TEXT

  GIN indexes on the new array columns.

Backfill rules (per Golda 2026-05-29):

  - catcodes  = ARRAY[catcode]  WHERE catcode IS NOT NULL  ELSE '{}'
  - created_by = 'urn:abra:legacy-import'  for all existing rows

The old singular `catcode` column is **kept** for now. Writers still
populate it; new code can read either. Drop it in a later migration once
nothing reads it.

This script is idempotent: re-running on an already-migrated database is
a no-op (each ALTER uses IF NOT EXISTS where supported; backfills are
guarded by checking column population).

Run:

    ../../.venv/bin/python 001_multi_catcode_and_provenance.py
    ../../.venv/bin/python 001_multi_catcode_and_provenance.py --dry-run
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

LEGACY_WRITER_URI = "urn:abra:legacy-import"


def column_exists(cur, table: str, column: str) -> bool:
    cur.execute(
        """
        SELECT 1 FROM information_schema.columns
        WHERE table_name = %s AND column_name = %s
        """,
        (table, column),
    )
    return cur.fetchone() is not None


def run(dry_run: bool = False) -> None:
    conn = psycopg2.connect(**PG)
    conn.autocommit = False
    cur = conn.cursor()

    print(f"connected to {PG['user']}@{PG['host']}:{PG['port']}/{PG['dbname']}")
    print(f"mode: {'DRY RUN (no changes will commit)' if dry_run else 'APPLY'}")
    print()

    plan: list[tuple[str, str]] = []  # (label, sql)

    # 1. Add new columns (idempotent — IF NOT EXISTS)
    for table in ("bindings", "content"):
        if not column_exists(cur, table, "catcodes"):
            plan.append((f"add {table}.catcodes TEXT[]",
                         f"ALTER TABLE {table} ADD COLUMN catcodes TEXT[]"))
        else:
            print(f"  skip: {table}.catcodes already exists")

        if not column_exists(cur, table, "created_by"):
            plan.append((f"add {table}.created_by TEXT",
                         f"ALTER TABLE {table} ADD COLUMN created_by TEXT"))
        else:
            print(f"  skip: {table}.created_by already exists")

    # 2. Backfill: catcodes <- ARRAY[catcode] for rows where catcodes is NULL.
    #    Use {} (empty array) when catcode itself is NULL.
    for table in ("bindings", "content"):
        plan.append((
            f"backfill {table}.catcodes from catcode",
            f"""
            UPDATE {table}
            SET catcodes = CASE
                WHEN catcode IS NULL THEN '{{}}'::text[]
                ELSE ARRAY[catcode]
            END
            WHERE catcodes IS NULL
            """,
        ))

    # 3. Backfill: created_by = 'urn:abra:legacy-import' where NULL
    for table in ("bindings", "content"):
        plan.append((
            f"backfill {table}.created_by = {LEGACY_WRITER_URI}",
            f"UPDATE {table} SET created_by = %s WHERE created_by IS NULL",
        ))

    # 4. GIN indexes on the array columns (fast `catcodes @> ARRAY[...]` lookups)
    for table in ("bindings", "content"):
        plan.append((
            f"index {table}.catcodes (GIN)",
            f"CREATE INDEX IF NOT EXISTS idx_{table}_catcodes_gin ON {table} USING gin (catcodes)",
        ))

    # Execute
    for label, sql in plan:
        print(f"  → {label}")
        if dry_run:
            continue
        # Pass param tuple only for the created_by backfills (use %s)
        if "created_by = " in label and "backfill" in label:
            cur.execute(sql, (LEGACY_WRITER_URI,))
        else:
            cur.execute(sql)
        print(f"    {cur.rowcount if cur.rowcount >= 0 else ''} rows affected"
              if cur.rowcount > 0 else "    (no-op)")

    if dry_run:
        print("\n  DRY RUN — rolling back")
        conn.rollback()
        cur.close()
        conn.close()
        return

    conn.commit()
    print("\n  committed")

    # Summary (only after a real commit — columns won't exist after a dry-run rollback)
    cur.execute("SELECT COUNT(*) FROM bindings WHERE created_by IS NULL")
    null_by = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM bindings WHERE catcodes IS NULL")
    null_cc = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM bindings")
    total = cur.fetchone()[0]
    print(f"\n  bindings: {total} total, {null_by} missing created_by, {null_cc} missing catcodes")

    cur.execute("SELECT COUNT(*) FROM content WHERE created_by IS NULL")
    null_by = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM content WHERE catcodes IS NULL")
    null_cc = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM content")
    total = cur.fetchone()[0]
    print(f"  content:  {total} total, {null_by} missing created_by, {null_cc} missing catcodes")

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
