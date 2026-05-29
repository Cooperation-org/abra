#!/usr/bin/env python3
"""Per-user signals — scoring and labels.

Read/write helpers for the user_signal and binding_labels tables added in
migration 002. Importable by any backend or script; usable as a small CLI
for spot checks.

Pure data layer. No HTTP. The HTTP service is in impl/backend/scoring_server.py.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

PG = dict(
    host=os.getenv("PG_HOST", "10.0.0.100"),
    port=os.getenv("PG_PORT", "5432"),
    user=os.getenv("PG_USER", "abra_user"),
    password=os.getenv("PG_PASSWORD", ""),
    dbname=os.getenv("PG_DATABASE", "abra"),
)

VALID_SCORE_KINDS = frozenset({"now", "long"})


@contextmanager
def conn():
    c = psycopg2.connect(**PG)
    try:
        yield c
    finally:
        c.close()


# ── user_signal: per-user scoring ────────────────────────────────────────

def set_score(user_uri: str, scope: str, name: str, score_kind: str, value: float) -> None:
    """Upsert a score. score_kind must be 'now' or 'long'."""
    if score_kind not in VALID_SCORE_KINDS:
        raise ValueError(f"score_kind must be one of {sorted(VALID_SCORE_KINDS)}; got {score_kind!r}")
    with conn() as c, c.cursor() as cur:
        cur.execute(
            """
            INSERT INTO user_signal (user_uri, scope, name, score_kind, value)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (user_uri, scope, name, score_kind)
            DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
            """,
            (user_uri, scope, name, score_kind, value),
        )
        c.commit()


def get_score(user_uri: str, scope: str, name: str, score_kind: str):
    if score_kind not in VALID_SCORE_KINDS:
        raise ValueError(f"score_kind must be one of {sorted(VALID_SCORE_KINDS)}; got {score_kind!r}")
    with conn() as c, c.cursor() as cur:
        cur.execute(
            "SELECT value FROM user_signal WHERE user_uri=%s AND scope=%s AND name=%s AND score_kind=%s",
            (user_uri, scope, name, score_kind),
        )
        row = cur.fetchone()
        return float(row[0]) if row else None


def delete_score(user_uri: str, scope: str, name: str, score_kind: str) -> bool:
    with conn() as c, c.cursor() as cur:
        cur.execute(
            "DELETE FROM user_signal WHERE user_uri=%s AND scope=%s AND name=%s AND score_kind=%s",
            (user_uri, scope, name, score_kind),
        )
        c.commit()
        return cur.rowcount > 0


def ranked(user_uri: str, scope: str, score_kind: str, limit: int = 50):
    """List of (name, value, updated_at_iso) ordered by value desc."""
    if score_kind not in VALID_SCORE_KINDS:
        raise ValueError(f"score_kind must be one of {sorted(VALID_SCORE_KINDS)}; got {score_kind!r}")
    with conn() as c, c.cursor() as cur:
        cur.execute(
            """
            SELECT name, value, updated_at
            FROM user_signal
            WHERE user_uri=%s AND scope=%s AND score_kind=%s
            ORDER BY value DESC, name ASC
            LIMIT %s
            """,
            (user_uri, scope, score_kind, limit),
        )
        return [(r[0], float(r[1]), r[2].isoformat()) for r in cur.fetchall()]


# ── binding_labels: free-language labels on bindings ─────────────────────

def add_label(binding_id: int, label: str, added_by: str) -> None:
    label = label.strip()
    if not label:
        raise ValueError("label must be a non-empty string")
    with conn() as c, c.cursor() as cur:
        cur.execute(
            """
            INSERT INTO binding_labels (binding_id, label, added_by)
            VALUES (%s, %s, %s)
            ON CONFLICT (binding_id, label)
            DO UPDATE SET added_by = EXCLUDED.added_by, added_at = NOW()
            """,
            (binding_id, label, added_by),
        )
        c.commit()


def remove_label(binding_id: int, label: str) -> bool:
    with conn() as c, c.cursor() as cur:
        cur.execute(
            "DELETE FROM binding_labels WHERE binding_id=%s AND label=%s",
            (binding_id, label.strip()),
        )
        c.commit()
        return cur.rowcount > 0


def labels_for_binding(binding_id: int):
    with conn() as c, c.cursor() as cur:
        cur.execute(
            "SELECT label FROM binding_labels WHERE binding_id=%s ORDER BY label",
            (binding_id,),
        )
        return [r[0] for r in cur.fetchall()]


def distinct_labels_in_scope(scope: str):
    """All labels currently in use within a scope. For autocomplete."""
    with conn() as c, c.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT bl.label
            FROM binding_labels bl
            JOIN bindings b ON b.id = bl.binding_id
            WHERE b.scope = %s
            ORDER BY bl.label
            """,
            (scope,),
        )
        return [r[0] for r in cur.fetchall()]


def bindings_by_label(scope: str, label: str, limit: int = 200):
    with conn() as c, c.cursor() as cur:
        cur.execute(
            """
            SELECT b.id, b.scope, b.name, b.relationship, b.target_type, b.target_ref,
                   b.qualifier, b.permanence, b.created_by, b.created_at
            FROM bindings b
            JOIN binding_labels bl ON bl.binding_id = b.id
            WHERE b.scope = %s AND bl.label = %s
            ORDER BY b.created_at DESC
            LIMIT %s
            """,
            (scope, label, limit),
        )
        cols = [d[0] for d in cur.description]
        out = []
        for row in cur.fetchall():
            d = dict(zip(cols, row))
            d["created_at"] = row[-1].isoformat() if row[-1] else None
            out.append(d)
        return out


# ── CLI for spot checks ──────────────────────────────────────────────────

def _cli() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_set = sub.add_parser("set-score")
    p_set.add_argument("--user", required=True)
    p_set.add_argument("--scope", required=True)
    p_set.add_argument("--name", required=True)
    p_set.add_argument("--kind", required=True, choices=sorted(VALID_SCORE_KINDS))
    p_set.add_argument("--value", required=True, type=float)

    p_get = sub.add_parser("ranked")
    p_get.add_argument("--user", required=True)
    p_get.add_argument("--scope", required=True)
    p_get.add_argument("--kind", required=True, choices=sorted(VALID_SCORE_KINDS))
    p_get.add_argument("--limit", type=int, default=50)

    p_add = sub.add_parser("add-label")
    p_add.add_argument("--binding-id", required=True, type=int)
    p_add.add_argument("--label", required=True)
    p_add.add_argument("--by", required=True)

    p_labels = sub.add_parser("labels-for")
    p_labels.add_argument("--binding-id", required=True, type=int)

    p_by_label = sub.add_parser("by-label")
    p_by_label.add_argument("--scope", required=True)
    p_by_label.add_argument("--label", required=True)

    p_distinct = sub.add_parser("distinct-labels")
    p_distinct.add_argument("--scope", required=True)

    args = ap.parse_args()

    if args.cmd == "set-score":
        set_score(args.user, args.scope, args.name, args.kind, args.value)
        print(f"set: ({args.user}, {args.scope}, {args.name}, {args.kind}) = {args.value}")
    elif args.cmd == "ranked":
        for n, v, t in ranked(args.user, args.scope, args.kind, args.limit):
            print(f"{v:>10.4f}  {n}  ({t})")
    elif args.cmd == "add-label":
        add_label(args.binding_id, args.label, args.by)
        print(f"label '{args.label}' added to binding {args.binding_id} by {args.by}")
    elif args.cmd == "labels-for":
        for lbl in labels_for_binding(args.binding_id):
            print(lbl)
    elif args.cmd == "by-label":
        for b in bindings_by_label(args.scope, args.label):
            print(json.dumps(b, indent=2))
    elif args.cmd == "distinct-labels":
        for lbl in distinct_labels_in_scope(args.scope):
            print(lbl)


if __name__ == "__main__":
    _cli()
