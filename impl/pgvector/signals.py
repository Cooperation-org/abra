#!/usr/bin/env python3
"""Per-user signals — scoring and labels.

Read/write helpers for the user_signal table (migration 002) and the
labels table (migration 003). Importable by any backend or script;
usable as a small CLI for spot checks.

Pure data layer. No HTTP — callers import directly.

Scope: **view-side ordering** of abra-held things (names, bindings,
content). When the user drags items on their canvas, we persist the
score here; when the view renders a list, it reads `ranked(...)`.

Out of scope: source-side ordering. Per Pattern B (scratch.md ~13:00),
embeds talk directly to their source cross-origin. The ordering of
items WITHIN an embed (which goals first, which emails first) is the
source's concern, not abra's.

Pluggable external scorer (planned, not built):
  `ranked()` returns from the local user_signal table by default. We
  may want to delegate to an external scorer URL (e.g. LinkedTrust
  trust scores, or any third-party ranker). The hook will be a
  `scorer=` arg or per-scope config; default unchanged. Stubbed for
  when the second scorer is real.
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


# ── labels: free-language labels on NAMES (per migration 003) ────────────
#
# Labels attach to (scope, name). They're the unifying primitive — hot_tags
# is now a bridge alias for labels.label='hot'. Use these helpers; do not
# write to binding_labels (dropped) or hot_tags directly (use set_hot via
# write_binding for the legacy path, or set_label with label='hot' for the
# unified path).

def set_label(scope: str, name: str, label: str, added_by: str,
              expires_at=None) -> None:
    """Upsert a label on a name. Multiple labels per (scope, name) allowed."""
    label = label.strip()
    if not label:
        raise ValueError("label must be a non-empty string")
    with conn() as c, c.cursor() as cur:
        cur.execute(
            """
            INSERT INTO labels (scope, name, label, added_by, expires_at)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (scope, name, label)
            DO UPDATE SET added_by = EXCLUDED.added_by,
                          added_at = NOW(),
                          expires_at = EXCLUDED.expires_at
            """,
            (scope, name, label, added_by, expires_at),
        )
        c.commit()


def remove_label(scope: str, name: str, label: str) -> bool:
    with conn() as c, c.cursor() as cur:
        cur.execute(
            "DELETE FROM labels WHERE scope=%s AND name=%s AND label=%s",
            (scope, name, label.strip()),
        )
        c.commit()
        return cur.rowcount > 0


def labels_for_name(scope: str, name: str):
    """All labels on a given name. Filters out expired."""
    with conn() as c, c.cursor() as cur:
        cur.execute(
            """
            SELECT label, added_by, added_at, expires_at
            FROM labels
            WHERE scope=%s AND name=%s
              AND (expires_at IS NULL OR expires_at > NOW())
            ORDER BY label
            """,
            (scope, name),
        )
        return [
            {
                "label": r[0],
                "added_by": r[1],
                "added_at": r[2].isoformat() if r[2] else None,
                "expires_at": r[3].isoformat() if r[3] else None,
            }
            for r in cur.fetchall()
        ]


def distinct_labels_in_scope(scope: str):
    """All labels currently in use within a scope. For autocomplete."""
    with conn() as c, c.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT label
            FROM labels
            WHERE scope = %s
              AND (expires_at IS NULL OR expires_at > NOW())
            ORDER BY label
            """,
            (scope,),
        )
        return [r[0] for r in cur.fetchall()]


def names_by_label(scope: str, label: str, limit: int = 500):
    """Names in scope carrying the given label (unexpired). Returns the
    label rows joined with any IS binding's target for context."""
    with conn() as c, c.cursor() as cur:
        cur.execute(
            """
            SELECT l.name, l.added_by, l.added_at, l.expires_at
            FROM labels l
            WHERE l.scope = %s AND l.label = %s
              AND (l.expires_at IS NULL OR l.expires_at > NOW())
            ORDER BY l.added_at DESC
            LIMIT %s
            """,
            (scope, label, limit),
        )
        return [
            {
                "name": r[0],
                "added_by": r[1],
                "added_at": r[2].isoformat() if r[2] else None,
                "expires_at": r[3].isoformat() if r[3] else None,
            }
            for r in cur.fetchall()
        ]


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

    p_add = sub.add_parser("set-label")
    p_add.add_argument("--scope", required=True)
    p_add.add_argument("--name", required=True)
    p_add.add_argument("--label", required=True)
    p_add.add_argument("--by", required=True)
    p_add.add_argument("--expires-at", default=None,
                       help="ISO timestamp; omit for no expiry")

    p_labels = sub.add_parser("labels-for")
    p_labels.add_argument("--scope", required=True)
    p_labels.add_argument("--name", required=True)

    p_by_label = sub.add_parser("names-by-label")
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
    elif args.cmd == "set-label":
        set_label(args.scope, args.name, args.label, args.by, args.expires_at)
        print(f"label '{args.label}' set on ({args.scope}, {args.name}) by {args.by}")
    elif args.cmd == "labels-for":
        for row in labels_for_name(args.scope, args.name):
            print(json.dumps(row))
    elif args.cmd == "names-by-label":
        for row in names_by_label(args.scope, args.label):
            print(json.dumps(row))
    elif args.cmd == "distinct-labels":
        for lbl in distinct_labels_in_scope(args.scope):
            print(lbl)


if __name__ == "__main__":
    _cli()
