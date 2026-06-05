#!/usr/bin/env python3
"""Dev shim for the abra view subsystem.

Serves the static page + the HTMX HTML-fragment endpoints the catcode
tree needs. This is **scaffolding**, not part of abra. It exists so the
view runs end-to-end while the data-models session builds the real
backend; when that lands, the contract (documented in
`/opt/shared/repos/abra/scratch.md`) is identical and this file is
deleted.

Run from this directory:

    ../impl/.venv/bin/python serve.py        # uses port 8089

stdlib only, plus psycopg2 from the existing impl venv.
"""
from __future__ import annotations

import html
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit


def url_path_seg(s: str) -> str:
    """URL-encode a string for safe use as a path segment. Escapes /,
    %, #, ?, space, etc. Use this for names that go INTO URLs
    (`/names/<name>/`, `?q=<name>`). esc() is HTML-escape for display,
    not URL safety."""
    return quote(s or "", safe="")
import base64
import hashlib
import hmac
import json as _json
import time
import urllib.error
import urllib.request

import psycopg2

# ── env ──────────────────────────────────────────────────────────────────
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
ENV_PATH = ROOT / "impl" / ".env"

# The team's writer with provenance. The view writes through this for
# every mutation so `created_by` lands on every row (data-models
# migration 001). We never INSERT bindings via direct SQL.
sys.path.insert(0, str(ROOT / "impl" / "pgvector"))
from write_binding import AbraWriter  # noqa: E402


def _load_env(path: Path) -> None:
    """Minimal .env parser (KEY=value, ignore comments + blanks).
    Doesn't override anything already in os.environ."""
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        os.environ.setdefault(key, val)


_load_env(ENV_PATH)

PG = dict(
    host=os.getenv("PG_HOST", "10.0.0.100"),
    port=os.getenv("PG_PORT", "5432"),
    user=os.getenv("PG_USER", "cobox"),
    password=os.getenv("PG_PASSWORD", ""),
    dbname=os.getenv("PG_DATABASE", "abra"),
)
PORT = int(os.getenv("ABRA_VIEW_PORT", "8089"))
# Empty when accessed directly on the port; "/abra-view" when behind the
# team's nginx path-prefix proxy. The app generates URLs with this prefix
# and the dispatcher strips it from incoming paths, so both modes work.
BASE = os.getenv("ABRA_VIEW_BASE", "").rstrip("/")
CATCODE_RE = re.compile(r"^[a-z0-9]{2,64}$")


def u(path: str) -> str:
    """Prepend the base path. `path` always starts with '/'."""
    return BASE + path


class FormError(Exception):
    """Validation problem the user can fix. Surfaces to #flash via
    HX-Retarget so it never wipes out the tree or a form they were
    halfway through."""


def conn():
    return psycopg2.connect(**PG)


# ── DB primitives ────────────────────────────────────────────────────────

def db_list() -> list[tuple[str, str | None, str]]:
    with conn() as c, c.cursor() as cur:
        cur.execute(
            "SELECT catcode, parent_catcode, label FROM catcode_registry ORDER BY catcode"
        )
        return cur.fetchall()


def db_get(code: str) -> tuple[str, str | None, str] | None:
    with conn() as c, c.cursor() as cur:
        cur.execute(
            "SELECT catcode, parent_catcode, label FROM catcode_registry WHERE catcode = %s",
            (code,),
        )
        return cur.fetchone()


def db_insert(code: str, parent: str | None, label: str) -> None:
    """Create a new catcode via AbraWriter so writes are stamped."""
    w = AbraWriter()
    try:
        w.register_catcode(code, parent or None, label)
    finally:
        w.close()


def db_update_label(code: str, label: str) -> None:
    """Catcode label edit. AbraWriter doesn't ship an explicit update for
    `catcode_registry.label` (it's the address-space registry, separate
    from binding writes), so this stays direct SQL until a writer method
    lands. The catcode itself is identity and never mutates here."""
    with conn() as c, c.cursor() as cur:
        cur.execute(
            "UPDATE catcode_registry SET label = %s WHERE catcode = %s",
            (label, code),
        )


def db_delete(code: str) -> None:
    """Delete a catcode (cascades). Uses AbraWriter so any future
    audit-log hook on deletes runs."""
    w = AbraWriter()
    try:
        w.delete_catcode(code)
    finally:
        w.close()


# ── Bindings browse — read-only ──────────────────────────────────────────
# Default scope is configurable; future change is a scope picker in the UI.
SCOPE = os.getenv("ABRA_VIEW_SCOPE", "golda")

# Writer URI for this user. Mirrors the AbraWriter default so view-side
# signals (e.g. user_signal scores) share the same identity as binding
# writes. Real auth replaces this with the actual logged-in user URI.
USER_URI = os.getenv("ABRA_WRITER_URI", f"urn:abra:local:{os.getenv('USER', 'golda')}")

# The catcode under which the home tree renders by default. Today's
# convention: `a001` ("version 0") holds the user's top-level subtrees
# (golda, gitonga, linkedtrust, ...). Reserved roots (`01` Dewey, `02`
# Wikidata, `a0` user-defined root) are still queryable, just not the
# default home. When auth + per-user config land, this moves into
# `user_config` keyed by the user URI.
HOME_ROOT = os.getenv("ABRA_VIEW_HOME_ROOT", "a001")
# Category-label suffixes that act as label-portals (clicking links to
# ?label=<word> in the people view instead of the catcode subtree). Set
# this via env until per-user config lands; empty default means no
# portals — the user opts in by configuring them.
PORTAL_LABELS = {
    s.strip().lower()
    for s in os.getenv("ABRA_VIEW_PORTAL_LABELS", "").split(",")
    if s.strip()
}

# ── upstream proxy config (per-scheme, env until sources.yaml lands) ────
# When the URI-scheme registry from data-models is populated, the proxy
# reads upstream + auth from there. Until then, single env var per scheme.
UPSTREAM = {
    "amebo": os.getenv("AMEBO_UPSTREAM", "http://127.0.0.1:8000").rstrip("/"),
}

# JWT secret for minting per-user tokens to upstream services. Env-driven;
# falls back to amebo's local .env on the same VM (dev convenience only —
# in production this is set explicitly).
_JWT_SECRET = os.getenv("JWT_SECRET_KEY", "")
if not _JWT_SECRET:
    _amebo_env = Path("/opt/shared/repos/amebo/backend/.env")
    if _amebo_env.exists():
        for _line in _amebo_env.read_text().splitlines():
            if _line.startswith("JWT_SECRET_KEY=") and not _line.startswith("#"):
                _JWT_SECRET = _line.split("=", 1)[1].strip()
                break

# Dev-only identity. Until the auth session lands, every proxied request
# carries this identity. Real auth replaces this with the actual logged-in
# user; nothing in the proxy logic changes.
DEV_USER = {
    "user_id": int(os.getenv("ABRA_VIEW_DEV_USER_ID", "1")),
    "org_id":  int(os.getenv("ABRA_VIEW_DEV_ORG_ID",  "1")),
    "email":   os.getenv("ABRA_VIEW_DEV_EMAIL",       "golda@example.com"),
    "role":    os.getenv("ABRA_VIEW_DEV_ROLE",        "admin"),
}


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def mint_jwt(user: dict, ttl_seconds: int = 900) -> str:
    """Minimal HS256 JWT minter. No PyJWT/jose dep so the dev shim stays
    stdlib-only. When the auth session lands, replace this with whatever
    standard library they pick."""
    if not _JWT_SECRET:
        raise FormError("no JWT_SECRET_KEY configured — set in env or amebo .env")
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload = {**user, "type": "access", "iat": now, "exp": now + ttl_seconds}
    h = _b64url(_json.dumps(header,  separators=(",", ":")).encode("utf-8"))
    p = _b64url(_json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{h}.{p}".encode("ascii")
    sig = hmac.new(_JWT_SECRET.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{h}.{p}.{_b64url(sig)}"


# ── Components (view:component.<id> bindings) ───────────────────────────
# A "component" is one user-installed view module on the homepage. Storage
# is the pure-binding namespace data-models confirmed in scratch:
#   name=view:component.<id>
#     IS   / text   →  scheme key (e.g. "amebo:digest")
#     HAS  / text qualifier="path"  → target_ref everything-after-scheme
#     HAS  / int  qualifier="position" → display order (future drag)
# Reads union all three to materialise an instance.

def _new_component_id() -> str:
    """8-char hex from /dev/urandom — short enough to be readable, long
    enough to avoid collision in any one user's homepage."""
    return os.urandom(4).hex()


def db_list_components() -> list[dict]:
    """All installed components for the current SCOPE, in stored order."""
    with conn() as c, c.cursor() as cur:
        cur.execute(
            """
            SELECT b.name, b.relationship, b.target_ref, b.qualifier
            FROM bindings b
            WHERE b.scope = %s AND b.name LIKE 'view:component.%%'
            ORDER BY b.name, b.id
            """,
            (SCOPE,),
        )
        by_id: dict[str, dict] = {}
        for name, rel, target_ref, qualifier in cur.fetchall():
            inst = name[len("view:component."):]
            d = by_id.setdefault(inst, {"id": inst, "scheme": "", "path": "", "position": 0})
            if rel == "IS":
                d["scheme"] = target_ref
            elif rel == "HAS" and qualifier == "path":
                d["path"] = target_ref or ""
            elif rel == "HAS" and qualifier == "position":
                try: d["position"] = int(target_ref)
                except (ValueError, TypeError): pass
        return sorted(by_id.values(), key=lambda x: (x["position"], x["id"]))


def db_install_component(scheme: str, path: str = "") -> str | None:
    """Create a new component instance. Returns the new instance id, or
    None if the underlying write was rejected (e.g. by PII filter).
    All writes go through AbraWriter so created_by is stamped."""
    inst = _new_component_id()
    name = f"view:component.{inst}"
    w = AbraWriter()
    try:
        is_id = w.write_binding(SCOPE, name, rel="IS", target_type="text",
                                target_ref=scheme, qualifier="component scheme")
        if is_id is None:
            return None
        if path:
            has_id = w.write_binding(SCOPE, name, rel="HAS", target_type="text",
                                     target_ref=path, qualifier="path")
            if has_id is None:
                # Roll back the IS write so we don't leave a half-install.
                with conn() as c, c.cursor() as cur:
                    cur.execute(
                        "DELETE FROM bindings WHERE scope=%s AND name=%s",
                        (SCOPE, name),
                    )
                return None
    finally:
        w.close()
    return inst


def db_uninstall_component(inst: str) -> None:
    """Delete every binding under view:component.<inst>. Direct SQL —
    AbraWriter has no batch-delete helper today."""
    with conn() as c, c.cursor() as cur:
        cur.execute(
            "DELETE FROM bindings WHERE scope = %s AND name = %s",
            (SCOPE, f"view:component.{inst}"),
        )


def db_top_names(q: str | None, catcode: str | None, label: str | None = None,
                 limit: int = 50) -> list[tuple[str, int, str | None, str | None]]:
    """Names with binding count, most-recent date, and a teaser qualifier.
    Sort: count desc, then most-recent desc.
    Filters stack: q is name substring; catcode is prefix-match against the
    hierarchical catcode address (so `a001` returns the full subtree); label
    filters to names that carry that label in the unified `labels` table
    (data-models migration 003), expiry-aware."""
    args: list = [SCOPE, SCOPE]
    where = ""
    if q:
        where += " AND b.name ILIKE %s"
        args.append(f"%{q}%")
    if label:
        where += """
            AND b.name IN (
                SELECT name FROM labels
                WHERE scope = %s AND label = %s
                  AND (expires_at IS NULL OR expires_at > NOW())
            )
        """
        args.extend([SCOPE, label])
    if catcode:
        # Multi-category: a binding can live under several catcodes
        # (`catcodes TEXT[]` per data-models migration 001). Prefix match
        # against any element gives subtree filtering. COALESCE keeps any
        # pre-migration rows that only carried the legacy single catcode.
        where += """
            AND EXISTS (
                SELECT 1 FROM unnest(COALESCE(b.catcodes, ARRAY[b.catcode])) cc
                WHERE cc LIKE %s
            )
        """
        args.append(catcode + "%")
    # LEFT JOIN user_signal so user-set drag order (score_kind='long')
    # wins when present; falls back to binding-count + most-recent.
    sql = f"""
        SELECT b.name,
               COUNT(*) AS n,
               MAX(COALESCE(b.source_date, b.created_at::date))::text AS most_recent,
               (SELECT qualifier FROM bindings
                WHERE scope = %s AND name = b.name AND qualifier IS NOT NULL
                ORDER BY COALESCE(source_date, created_at::date) DESC NULLS LAST LIMIT 1) AS teaser,
               MAX(us.value) AS sig_value
        FROM bindings b
        LEFT JOIN user_signal us
          ON us.user_uri  = %s
         AND us.scope     = b.scope
         AND us.name      = b.name
         AND us.score_kind = 'long'
        WHERE b.scope = %s {where}
        GROUP BY b.name
        ORDER BY sig_value DESC NULLS LAST, n DESC, most_recent DESC NULLS LAST
        LIMIT {int(limit)}
    """
    # SQL above expects: %s for teaser-subquery scope, then USER_URI for the
    # user_signal join, then the outer scope used by the WHERE clause,
    # then args already collected for q/label/catcode filters.
    full_args = [SCOPE, USER_URI, SCOPE, *args[2:]]
    with conn() as c, c.cursor() as cur:
        cur.execute(sql, full_args)
        # Drop sig_value before returning — callers expect 4 columns.
        return [row[:4] for row in cur.fetchall()]


def db_catcode_label(code: str) -> str | None:
    with conn() as c, c.cursor() as cur:
        cur.execute("SELECT label FROM catcode_registry WHERE catcode = %s", (code,))
        row = cur.fetchone()
        return row[0] if row else None


def db_ancestors(code: str) -> list[tuple[str, str]]:
    """Ancestor (catcode, label) pairs from root → immediate parent."""
    with conn() as c, c.cursor() as cur:
        cur.execute(
            """
            WITH RECURSIVE chain AS (
                SELECT catcode, parent_catcode, 0 AS depth
                FROM catcode_registry WHERE catcode = %s
                UNION ALL
                SELECT cr.catcode, cr.parent_catcode, ch.depth + 1
                FROM catcode_registry cr
                JOIN chain ch ON cr.catcode = ch.parent_catcode
                WHERE ch.parent_catcode IS NOT NULL AND ch.depth < 32
            )
            SELECT c.catcode, COALESCE(r.label, c.catcode)
            FROM chain c
            LEFT JOIN catcode_registry r ON r.catcode = c.catcode
            WHERE c.depth > 0
            ORDER BY c.depth DESC
            """,
            (code,),
        )
        return [(r[0], r[1]) for r in cur.fetchall()]


# ── User-editable view chrome ────────────────────────────────────────────
# Every visible piece of view chrome (tab text, headings, lead text, column
# labels) is editable inline. Overrides persist in abra itself as IS-bindings
# under `name = view:<key>`, NOT in browser localStorage. abra is the store.
#
# Defaults below are the *first-time* strings; the user replaces any of them
# by entering edit mode and typing. When data-models lands a richer
# user_config story, these IS-bindings migrate cleanly.

# UI preference keys (`view:ui.*`) → the body class they toggle. The user
# clicks a toggle, JS POSTs the new state, and on next render the server
# applies the body class. Same mechanism as VIEW_DEFAULTS; different shape
# (boolean rather than free text).
UI_PREFS: dict[str, str] = {
    "ui.show-codes":    "show-codes",
    "ui.hide-col.rel":  "hide-rel",
    "ui.hide-col.qual": "hide-qual",
    "ui.hide-col.tgt":  "hide-tgt",
    "ui.hide-col.date": "hide-date",
    "ui.hide-col.from": "hide-from",
}

# Defaults are empty. Nothing on the screen is from me; if Golda hasn't
# named a piece of chrome, it shows as a minimal click affordance only
# (a colour dot for tabs, a thin marker for the edit toggle). She names
# them in edit mode and they appear; until then, only her data shows.
VIEW_DEFAULTS: dict[str, str] = {
    "tab.categories":          "",
    "tab.bindings":            "",
    "tab.showcodes":           "",
    "tab.edit":                "",
    "cat.h1":                  "",
    "cat.lead":                "",
    "cat.new":                 "",
    "bind.h1":                 "",
    "bind.lead":               "",
    "bind.search.placeholder": "",
    "bind.col.rel":            "",
    "bind.col.qual":           "",
    "bind.col.tgt":            "",
    "bind.col.date":           "",
    "bind.col.from":           "",
    "recent.h1":               "",
    "recent.lead":             "",
}


def db_get_view_texts() -> dict[str, str]:
    """Return user overrides for editable view chrome strings."""
    with conn() as c, c.cursor() as cur:
        cur.execute(
            "SELECT name, target_ref FROM bindings "
            "WHERE scope = %s AND relationship = 'IS' AND name LIKE 'view:%%'",
            (SCOPE,),
        )
        out: dict[str, str] = {}
        for name, target_ref in cur.fetchall():
            out[name[len("view:"):]] = target_ref
        return out


def db_set_view_text(key: str, value: str) -> None:
    """Upsert one view-text override as an IS-binding. Empty value clears it.
    Writes go through AbraWriter so `created_by` is stamped (data-models
    migration 001). Delete is direct SQL (writer has no explicit delete-
    binding helper today)."""
    name = "view:" + key
    with conn() as c, c.cursor() as cur:
        cur.execute(
            "DELETE FROM bindings WHERE scope = %s AND name = %s AND relationship = 'IS'",
            (SCOPE, name),
        )
    if value:
        w = AbraWriter()
        try:
            w.write_binding(
                SCOPE, name, rel="IS", target_type="text", target_ref=value,
                qualifier="view chrome override",
            )
        finally:
            w.close()


def tx(key: str, overrides: dict[str, str]) -> str:
    """View-text accessor: returns the user override or the default."""
    return overrides.get(key, VIEW_DEFAULTS.get(key, key))


def asset_version() -> str:
    """Max mtime of style.css and edit.js as a stringified int. Embedded
    in HTML as `?v=<asset_version>` so the version auto-bumps the
    instant either file is edited. No manual ?v=N pumping; no stale
    assets after a CSS change."""
    mt = 0
    for fname in ("style.css", "edit.js"):
        p = HERE / fname
        try:
            if p.exists():
                m = int(p.stat().st_mtime)
                if m > mt:
                    mt = m
        except OSError:
            pass
    return str(mt or 1)


def apply_view_texts(html: str, overrides: dict[str, str]) -> str:
    """Replace `__T_<key>__` with override-or-default (escaped),
    `__BODY_CLASS__` with the space-joined body classes from UI prefs,
    and `__ASSET_VER__` with the current asset-mtime version so cached
    style.css / edit.js auto-invalidate the moment they change."""
    def replace(m):
        return esc(tx(m.group(1), overrides))
    html = re.sub(r"__T_([a-z][a-z0-9._]*)__", replace, html)
    classes = [cls for key, cls in UI_PREFS.items() if overrides.get(key) == "1"]
    html = html.replace("__BODY_CLASS__", " ".join(classes))
    html = html.replace("__ASSET_VER__", asset_version())
    return html


def db_recent_content(limit: int = 50, q: str | None = None,
                      catcode: str | None = None) -> list[dict]:
    """Most-recent content blobs in the active scope.

    A content blob counts as 'under' a catcode subtree if EITHER the
    content row carries that catcode (legacy or array column) OR any
    binding pointing at the content carries that catcode. Bindings
    are the dominant placement path (~97% of content is catcoded via
    bindings only), so a filter that ignored them would silently hide
    most of the data.

    Unfiltered: requires an inbound binding so the feed reflects the
    user's named/related items rather than the full raw import pile.
    """
    placeholders: list = []
    if catcode:
        prefix = catcode + "%"
        reach_clause = """
            (
              EXISTS (
                SELECT 1 FROM bindings b
                WHERE b.scope = %s
                  AND b.target_type = 'content'
                  AND b.target_ref = c.id::text
                  AND EXISTS (
                    SELECT 1
                    FROM unnest(COALESCE(b.catcodes, ARRAY[b.catcode])) bc
                    WHERE bc LIKE %s
                  )
              )
              OR EXISTS (
                SELECT 1
                FROM unnest(COALESCE(c.catcodes, ARRAY[c.catcode])) cc
                WHERE cc LIKE %s
              )
            )
        """
        placeholders.extend([SCOPE, prefix, prefix])
    else:
        reach_clause = """
            EXISTS (
                SELECT 1 FROM bindings b
                WHERE b.scope = %s
                  AND b.target_type = 'content'
                  AND b.target_ref = c.id::text
            )
        """
        placeholders.append(SCOPE)

    where = ""
    if q:
        where += " AND c.content ILIKE %s"
        placeholders.append(f"%{q}%")

    sql = f"""
        SELECT c.id, c.source_file, c.note_date::text, c.content,
               c.created_at::text,
               (SELECT array_agg(DISTINCT b.name)
                  FROM bindings b
                 WHERE b.scope = %s
                   AND b.target_type = 'content'
                   AND b.target_ref = c.id::text) AS names
          FROM content c
         WHERE {reach_clause} {where}
         ORDER BY COALESCE(c.note_date, c.created_at::date) DESC,
                  c.id DESC
         LIMIT {int(limit)}
    """
    # Leading %s is the names subquery's scope; reach + q follow.
    full_args = [SCOPE, *placeholders]
    with conn() as c, c.cursor() as cur:
        cur.execute(sql, full_args)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def db_delete_binding(binding_id: int) -> None:
    """Delete one binding by id within the active scope. Scope check
    keeps a user from deleting another scope's row by guessing id."""
    with conn() as c, c.cursor() as cur:
        cur.execute(
            "DELETE FROM bindings WHERE scope = %s AND id = %s",
            (SCOPE, binding_id),
        )


def db_name_detail(name: str) -> list[dict]:
    """All bindings for one name in the active scope, joined to content
    when the binding points at a content row."""
    # CASE-wrapped cast: prevents Postgres from evaluating ::integer on
    # non-numeric target_refs (e.g. text targets), which would 500.
    sql = """
        SELECT b.id, b.relationship, b.target_type, b.target_ref, b.qualifier,
               b.source_date::text, b.catcode, b.created_at::text, b.created_by,
               c.source_file, c.note_date::text, c.content
        FROM bindings b
        LEFT JOIN content c ON c.id = (
            CASE WHEN b.target_type = 'content' AND b.target_ref ~ '^[0-9]+$'
                 THEN b.target_ref::integer ELSE NULL END
        )
        WHERE b.scope = %s AND b.name = %s
        ORDER BY b.relationship, b.id
    """
    with conn() as c, c.cursor() as cur:
        cur.execute(sql, (SCOPE, name))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


# ── HTML fragments ───────────────────────────────────────────────────────

def esc(s: str | None) -> str:
    return html.escape(s or "", quote=True)


def link_for_category(code: str, label: str) -> str:
    """Where clicking a category label goes.

    Convention: a category whose last path segment is a recognised
    label-portal word (today: `hot`) is a link to that label's filter
    in the people view. Everything else links to the catcode subtree.

    The convention is narrow so plain structural categories
    (`linkedtrust/2026/projects`) keep their subtree behaviour. To
    add other portal labels later, this list will move to per-user
    config (see scratch.md / data-models user_config story).
    """
    from urllib.parse import quote
    tail = (label or "").rsplit("/", 1)[-1].strip().lower()
    if tail in PORTAL_LABELS:
        return u("/bindings/") + "?label=" + quote(tail)
    # Dedicated per-catcode page. Routable, voice-pasteable.
    return u(f"/cat/{code}/")


def row_html(code: str, label: str) -> str:
    """One node's row (not its children) — the unit that edit returns to.
    Display only the tail of the slash-path (`golda/contacts` → `contacts`):
    the parent context is already visible in the tree indent. The stored
    label keeps its full path; the edit form (separate) shows the full
    value for renaming."""
    e = esc(code)
    tail = (label or "").rsplit("/", 1)[-1]
    lbl = esc(tail)
    href = esc(link_for_category(code, label))
    # Confirm uses the full label (clear scope) — codes are hidden by default.
    confirm_label = label or code
    return (
        f'<div class="node-row" id="row-{e}">'
        f'<span class="code">{e}</span>'
        f'<a class="label" href="{href}">{lbl}</a>'
        f'<span class="actions">'
        f'  <button type="button" hx-get="{u(f"/catcodes/{e}/edit")}"'
        f'          hx-target="#row-{e}" hx-swap="outerHTML">edit</button>'
        f'  <button type="button" hx-get="{u(f"/catcodes/{e}/add-child")}"'
        f'          hx-target="#children-{e}" hx-swap="beforeend">+ child</button>'
        f'  <button type="button" class="danger"'
        f'          hx-delete="{u(f"/catcodes/{e}/")}"'
        f'          hx-confirm="Delete &quot;{esc(confirm_label)}&quot; and everything under it? This cannot be undone."'
        f'          hx-target="#li-{e}" hx-swap="outerHTML">delete</button>'
        f"</span>"
        f"</div>"
    )


def li_html(code: str, label: str, children_html: str = "") -> str:
    e = esc(code)
    return (
        f'<li id="li-{e}">'
        f"{row_html(code, label)}"
        f'<ul class="children" id="children-{e}">{children_html}</ul>'
        f"</li>"
    )


def tree_html() -> str:
    rows = db_list()
    by_parent: dict[str | None, list[tuple[str, str]]] = {}
    for code, parent, label in rows:
        by_parent.setdefault(parent, []).append((code, label))

    def render(parent: str | None) -> str:
        kids = by_parent.get(parent, [])
        if not kids:
            return ""
        return "".join(li_html(code, label, render(code)) for code, label in kids)

    if not rows:
        return (
            '<p class="muted">No catcodes yet. '
            'Press <em>+ new top-level</em> to add one (e.g. <code>a0</code>).</p>'
        )
    # Default view: render children of HOME_ROOT, not the universe.
    # Reserved roots (Dewey, Wikidata, true top-level) are reachable
    # by direct URL or future "show all top-level" toggle.
    return f'<ul class="tree">{render(HOME_ROOT)}</ul>'


def edit_form_html(code: str, label: str) -> str:
    e = esc(code)
    return (
        f'<form class="edit-form" id="row-{e}"'
        f'      hx-patch="{u(f"/catcodes/{e}/")}"'
        f'      hx-target="#row-{e}" hx-swap="outerHTML">'
        f'<label for="label-{e}">label</label>'
        f'<input type="text" id="label-{e}" name="label" value="{esc(label)}" required autofocus style="flex:1">'
        f'<button type="submit" class="primary">save</button>'
        f'<button type="button" hx-get="{u(f"/catcodes/{e}/row")}" hx-target="#row-{e}" hx-swap="outerHTML">cancel</button>'
        f"</form>"
    )


def add_top_form_html() -> str:
    """The topnav `+` adds a new category as a sibling of the
    existing home entries (children of HOME_ROOT), not a true
    top-level catcode. Reserved roots are managed elsewhere."""
    return (
        '<form class="add-form" id="new-form"'
        f'      hx-post="{u("/catcodes/")}"'
        '      hx-target="ul.tree" hx-swap="beforeend">'
        f'<span class="prefix">{esc(HOME_ROOT)}</span>'
        '<label for="new-suffix">suffix</label>'
        '<input type="text" id="new-suffix" name="suffix" placeholder="e.g. 04" required pattern="[a-z0-9]+" autofocus>'
        '<label for="new-label">label</label>'
        '<input type="text" id="new-label" name="label" required style="flex:1">'
        f'<input type="hidden" name="parent_catcode" value="{esc(HOME_ROOT)}">'
        '<button type="submit" class="primary">add</button>'
        f'<button type="button" hx-get="{u("/catcodes/new/cancel")}" hx-target="#new-slot" hx-swap="innerHTML">cancel</button>'
        "</form>"
    )


def add_child_form_html(parent_code: str) -> str:
    """Sits as a <li> at the end of the parent's children ul."""
    p = esc(parent_code)
    return (
        f'<li class="add-li" id="add-li-{p}">'
        f'<form class="add-form"'
        f'      hx-post="{u("/catcodes/")}"'
        f'      hx-target="#add-li-{p}" hx-swap="outerHTML">'
        f'<span class="prefix">{p}</span>'
        f'<label for="suf-{p}">suffix</label>'
        f'<input type="text" id="suf-{p}" name="suffix" placeholder="e.g. 01" required pattern="[a-z0-9]+" autofocus>'
        f'<label for="lab-{p}">label</label>'
        f'<input type="text" id="lab-{p}" name="label" required style="flex:1">'
        f'<input type="hidden" name="parent_catcode" value="{p}">'
        f'<button type="submit" class="primary">add</button>'
        f'<button type="button" hx-get="{u(f"/catcodes/{p}/add-child/cancel")}"'
        f'        hx-target="#add-li-{p}" hx-swap="outerHTML">cancel</button>'
        f"</form>"
        f"</li>"
    )


def error_html(message: str) -> str:
    return f'<p class="error">{esc(message)}</p>'


# ── Component HTML fragments (chooser modal + installed list) ────────────

# abra owns two catalogs side-by-side (per data-models 2026-06-01):
#   components.yaml — trust catalog of web components (tag → name, icon,
#                     script, integrity, schemes, required attrs)
#   sources.yaml    — URI-scheme → resolver/embed/auth mapping
# The chooser reads components; the renderer cross-refs schemes when
# the component declares any. Both files load lazily; missing either
# just degrades gracefully.

def _load_components() -> dict:
    try:
        sys.path.insert(0, str(ROOT / "impl" / "pgvector"))
        import components as _components  # type: ignore
        return _components.components() or {}
    except Exception:
        return {}


def _proxify_script(url: str) -> str:
    """Route trusted-provider scripts through the view-side proxy so the
    bundle loads from a single origin (no CORS, no cookie domain games)
    and the SRI hash from the catalog still applies — proxy is byte
    pass-through. Recognises amebo.* hosts by hostname until a provider
    registry lands."""
    if not url:
        return url
    if "://amebo." in url or "://amebo/" in url:
        from urllib.parse import urlparse
        p = urlparse(url)
        return u("/up/amebo") + p.path + (f"?{p.query}" if p.query else "")
    return url


def component_chooser_html() -> str:
    """Modal listing every component in ~/.abra/components.yaml — the
    user's trust catalog. Empty state names the gap honestly."""
    catalog = _load_components()
    if not catalog:
        return (
            '<div class="modal" data-modal>'
            '<div class="modal-card">'
            '<button type="button" class="modal-close" onclick="this.closest(\'[data-modal]\').remove()" aria-label="close">×</button>'
            '<h3>Nothing to install yet</h3>'
            '<p class="muted">No components are registered. Populate '
            '<code>~/.abra/components.yaml</code> with the components you '
            'trust to make them installable here.</p>'
            '</div></div>'
        )
    # Tags currently installed → render grayed out plus a red minus
    # to uninstall from here. One install per tag.
    installed_by_tag = {c["scheme"]: c for c in db_list_components()}
    cards = []
    for tag, c in catalog.items():
        icon = c.get("icon") or ""
        icon_html = (
            f'<img class="chooser-icon" src="{esc(icon)}" alt="" loading="lazy">'
            if icon else ""
        )
        title = c.get("name") or tag
        desc = c.get("description") or ""
        if tag in installed_by_tag:
            inst = installed_by_tag[tag]["id"]
            # Uninstall + re-render chooser inline. The DELETE returns
            # empty; the after-request handler refetches the chooser so
            # the card flips back to installable in one user click.
            refresh_chooser = (
                f"if(event.detail.successful) htmx.ajax('GET', "
                f"'{u('/components/chooser')}', "
                f"{{target:'#modal-slot', swap:'innerHTML'}});"
            )
            cards.append(
                f'<div class="chooser-card installed" aria-disabled="true" title="already installed">'
                f'{icon_html}'
                f'<span class="chooser-text">'
                f'<span class="chooser-title">{esc(title)}</span>'
                f'<span class="chooser-desc">{esc(desc)}</span>'
                f'</span>'
                f'<button type="button" class="chooser-uninstall"'
                f' hx-delete="{u(f"/components/{esc(inst)}")}"'
                f' hx-confirm="Uninstall this component?"'
                f' hx-target="#modal-slot" hx-swap="innerHTML"'
                f' hx-on::after-request="{refresh_chooser}"'
                f' aria-label="uninstall">'
                f'<i class="fa-solid fa-circle-minus"></i></button>'
                f'</div>'
            )
        else:
            cards.append(
                f'<button class="chooser-card" type="button"'
                f' hx-post="{u("/components/install")}"'
                f' hx-vals=\'{{"tag":"{esc(tag)}"}}\''
                f' hx-target="#topnav-installed" hx-swap="beforeend"'
                f' hx-disabled-elt="this">'
                f'{icon_html}'
                f'<span class="chooser-text">'
                f'<span class="chooser-title">{esc(title)}</span>'
                f'<span class="chooser-desc">{esc(desc)}</span>'
                f'</span>'
                f'</button>'
            )
    return (
        '<div class="modal" data-modal onclick="if(event.target===this)this.remove()">'
        '<div class="modal-card">'
        '<button type="button" class="modal-close" onclick="this.closest(\'[data-modal]\').remove()" aria-label="close">×</button>'
        '<h3>Add a component</h3>'
        f'<div class="chooser-grid">{"".join(cards)}</div>'
        '</div></div>'
    )


def component_element_html(comp: dict) -> str:
    """Render one installed component. The IS-binding under
    view:component.<id> stores the **tag** (e.g. "amebo-digest"); the
    catalog tells us which custom element + which attrs are required.
    Thin-wiring components get data-up/data-scheme/data-path/data-org;
    self-contained components just get the tag."""
    catalog = _load_components()
    tag = comp["scheme"]  # the IS target IS the component tag
    spec = catalog.get(tag) or {}
    schemes = spec.get("schemes") or []
    required = set(spec.get("required") or [])
    scheme = schemes[0] if schemes else ""
    inst = comp["id"]
    path = comp.get("path") or ""

    attrs = []
    if "data-up" in required:
        attrs.append(f' data-up="{u("/up/amebo")}"')
    if scheme:
        attrs.append(f' data-scheme="{esc(scheme)}"')
        attrs.append(f' data-ref="{esc(scheme)}{("/" + esc(path)) if path else ""}"')
    if "data-path" in required:
        attrs.append(f' data-path="{esc(path)}"')
    if "data-org" in required:
        attrs.append(f' data-org=""')

    return (
        f'<section class="component" id="component-{esc(inst)}" data-component-id="{esc(inst)}">'
        f'<{esc(tag)}{"".join(attrs)}></{esc(tag)}>'
        f'</section>'
    )


def _topnav_anchor_html(comp: dict, catalog: dict) -> str:
    """One topnav <a> for one installed component. Icon from catalog,
    falls back to a generic cube. Click navigates to /c/<inst>/."""
    tag = comp["scheme"]
    spec = catalog.get(tag) or {}
    name = spec.get("name") or tag
    icon = spec.get("icon") or ""
    inst = comp["id"]
    if icon:
        icon_src = _proxify_script(icon) if "://amebo" in icon else icon
        # CSS mask so the imported SVG inherits currentColor from the
        # topnav — matches light/dark theme. Providers author with
        # currentColor (per amebo); here is where the host tint actually
        # applies (img tags don't carry parent color into SVG content).
        icon_html = (
            f'<span class="nav-icon mask-icon" role="img" aria-label="{esc(name)}" '
            f'style="--icon-url:url(&quot;{esc(icon_src)}&quot;)"></span>'
        )
    else:
        icon_html = '<i class="fa-solid fa-cube"></i>'
    return (
        f'<a href="{u(f"/c/{esc(inst)}/")}" class="nav" '
        f'title="{esc(name)}" aria-label="{esc(name)}" '
        f'data-component-id="{esc(inst)}">{icon_html}</a>'
    )


def topnav_installed_html() -> str:
    """All installed components rendered as topnav anchors. Loaded into
    the topnav slot via htmx GET on page load."""
    comps = db_list_components()
    if not comps:
        return ""
    catalog = _load_components()
    return "".join(_topnav_anchor_html(c, catalog) for c in comps)


def component_page_html(inst: str) -> str:
    """Full HTML page rendering one installed component full-bleed.
    Reuses the homepage topnav (so installs stay visible) and loads the
    provider bundle for this component. Returns "" if instance unknown."""
    comps = db_list_components()
    comp = next((c for c in comps if c["id"] == inst), None)
    if not comp:
        return ""
    catalog = _load_components()
    tag = comp["scheme"]
    spec = catalog.get(tag) or {}
    name = spec.get("name") or tag
    elem = component_element_html(comp)
    script_url = spec.get("script")
    script_tag = ""
    if script_url:
        proxied = _proxify_script(script_url)
        integrity = spec.get("integrity") or ""
        attrs = f' src="{esc(proxied)}"'
        if integrity and not integrity.endswith("REPLACE_ME"):
            attrs += f' integrity="{esc(integrity)}" crossorigin="anonymous"'
        script_tag = f"<script{attrs}></script>"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>abra · {esc(name)}</title>
  <link rel="stylesheet" href="{BASE}/style.css?v={asset_version()}">
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
  <script src="https://unpkg.com/htmx.org@1.9.12" integrity="sha384-ujb1lZYygJmzgSwoxRggbCHcjc0rB2XoQrxeTUQyRjrOnlCoYta87iKBWq3EsdM2" crossorigin="anonymous"></script>
</head>
<body>
  <nav class="topnav">
    <a href="{BASE}/" class="nav" aria-label="Categories" title="Categories"><i class="fa-solid fa-folder-tree"></i></a>
    <a href="{BASE}/bindings/" class="nav" aria-label="Bindings" title="Bindings"><i class="fa-solid fa-list"></i></a>
    <a href="{BASE}/recent/" class="nav" aria-label="Recent" title="Recent"><i class="fa-solid fa-arrow-down-wide-short"></i></a>
    <a href="#" class="nav" onclick="history.back();return false" aria-label="back"><i class="fa-solid fa-arrow-left"></i></a>
    <button type="button" class="nav add-component write-only"
            hx-get="{BASE}/components/chooser"
            hx-target="#modal-slot"
            hx-swap="innerHTML"
            aria-label="add a component"><i class="fa-solid fa-puzzle-piece"></i></button>
    <span id="topnav-installed"
          hx-get="{BASE}/components/menu"
          hx-trigger="load"
          hx-swap="innerHTML"></span>
    <span class="spacer"></span>
    <button type="button" class="nav edit-toggle"
            onclick="document.body.classList.toggle('editing')" aria-label="edit"><i class="fa-solid fa-pen"></i></button>
  </nav>

  <div class="page">
    <header>
      <h1>{esc(name)}</h1>
    </header>
    <main>
      <div id="flash" aria-live="polite"></div>
      {elem}
      <div class="danger-zone write-only">
        <p class="muted danger-warn">Deleting removes this component from your map. The data in {esc(tag.split('-')[0] if '-' in tag else 'the provider')} is not touched.</p>
        <button type="button" class="btn-danger"
                hx-delete="{BASE}/components/{esc(inst)}"
                hx-confirm="Delete this component? This removes it from your map."
                hx-on::after-request="if(event.detail.successful) window.location.href='{BASE}/'">
          <i class="fa-solid fa-trash"></i> Delete this component
        </button>
      </div>
    </main>
    <footer>
      <p class="muted">
        <a href="https://github.com/Cooperation-org/abra">abra</a> ·
        view subsystem
      </p>
    </footer>
  </div>
  <div id="modal-slot"></div>
  {script_tag}
</body>
</html>"""


# Linkify http(s) URLs inside a text block. Used for content blob bodies
# where the substance is just text that may carry useful published links.
URL_RE = re.compile(r"https?://[^\s<>\"'`]+")


def linkify(text: str) -> str:
    """HTML-escape, then turn http(s) URLs into clickable links.
    Trailing punctuation that follows a URL (.,;:!?) is left outside."""
    out: list[str] = []
    last = 0
    for m in URL_RE.finditer(text):
        out.append(esc(text[last:m.start()]))
        url = m.group(0)
        # Don't swallow trailing punctuation into the link.
        trim = ""
        while url and url[-1] in ".,;:!?)”“’":
            trim = url[-1] + trim
            url = url[:-1]
        if url:
            out.append(
                f'<a href="{esc(url)}" target="_blank" rel="noopener noreferrer">{esc(url)}</a>'
            )
        out.append(esc(trim))
        last = m.end()
    out.append(esc(text[last:]))
    return "".join(out)


def _resolve_uri(target_ref: str) -> str | None:
    """Resolve a non-http URI target to a real URL when we know the
    provider. Currently hardcoded for the live LinkedTrust deployment;
    will move into sources.yaml when its scheme entries carry per-path
    URL templates."""
    # Odoo CRM contacts: crm:odoo/contact/<id> → Odoo deep link.
    m = re.fullmatch(r"crm:odoo/contact/(\d+)", target_ref)
    if m:
        cid = m.group(1)
        return (
            f"https://crm.linkedtrust.us/web#id={cid}"
            "&model=res.partner&view_type=form"
        )
    # Taiga: tasks:taiga/issue/<id> → Marten board (the team's Taiga UI).
    m = re.fullmatch(r"tasks:taiga/issue/(\d+)", target_ref)
    if m:
        return f"https://marten.linkedtrust.us/board?story={m.group(1)}"
    return None


def render_target(target_type: str, target_ref: str) -> str:
    """A binding's target rendered usable: http(s) becomes a link, name
    becomes an in-app link to that name's bindings, content becomes an
    anchor to the inline blob, anything else stays as readable text."""
    if not target_ref:
        return ""
    if target_type == "content":
        # The accordion <details> is the row itself; clicking the summary
        # opens the content below, so we don't need a scroll-anchor link.
        return f'<span class="content-ref">note</span>'
    if target_type == "name":
        from urllib.parse import quote
        href = u(f"/bindings/") + f"?q={quote(target_ref, safe='')}"
        return f'<a href="{esc(href)}">name: {esc(target_ref)}</a>'
    if target_type == "uri":
        if target_ref.startswith(("http://", "https://")):
            return (
                f'<a href="{esc(target_ref)}" target="_blank" '
                f'rel="noopener noreferrer">{esc(target_ref)}</a>'
            )
        # Known non-http URI schemes get resolved to a clickable link.
        # Pointer-scheme registry resolution (sources.yaml) can take
        # over once it carries a per-scheme URL template; until then,
        # the well-known providers are hardcoded so the data is at
        # least navigable.
        resolved = _resolve_uri(target_ref)
        if resolved:
            return (
                f'<a href="{esc(resolved)}" target="_blank" '
                f'rel="noopener noreferrer">{esc(target_ref)}</a>'
            )
        return f'<span class="uri">{esc(target_ref)}</span>'
    if target_type == "text":
        return f'<span class="text-target">{esc(target_ref)}</span>'
    # Unknown / future target_type — render the raw value but typed.
    return f'<span class="other-target">{esc(target_type)}: {esc(target_ref)}</span>'


# ── Bindings view fragments ──────────────────────────────────────────────

def binding_list_html(rows: list[tuple], q: str | None,
                      catcode: str | None = None, label: str | None = None) -> str:
    # No author text — empty list is empty. Nothing to read but what's there.
    if not rows:
        return ""
    items = []
    for name, n, most_recent, teaser in rows:
        href = u(f"/names/{url_path_seg(name)}/")
        date_str = most_recent or "—"
        teaser_html = f'<span class="teaser">{esc(teaser)}</span>' if teaser else ""
        items.append(
            f'<li>'
            f'<span class="drag-handle" aria-label="drag to reorder"><i class="fa-solid fa-grip-vertical"></i></span>'
            f'<details class="name-card">'
            f'<summary>'
            f'<a class="name-text" href="{u(f"/bindings/?q={url_path_seg(name)}")}">{esc(name)}</a>'
            f'{teaser_html}'
            f'<span class="meta">{n}× · {esc(date_str)}</span>'
            f'</summary>'
            f'<div class="detail-card" '
            f'hx-get="{href}" '
            f'hx-trigger="toggle from:closest details once" '
            f'hx-target="this" hx-swap="innerHTML">'
            f'<p class="muted">Loading…</p>'
            f'</div>'
            f'</details>'
            f'</li>'
        )
    return f'<ul class="binding-list">{"".join(items)}</ul>'


def _one_line_excerpt(text: str, n: int = 140) -> str:
    """First non-empty line of text, trimmed to n chars with ellipsis.
    Used as the collapsed summary so the user can see which entry is
    which without expanding it."""
    if not text:
        return ""
    line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    if len(line) > n:
        line = line[:n].rstrip() + "…"
    return line


def recent_feed_html(items: list[dict]) -> str:
    """Reverse-chrono feed of content blobs. Each entry is a <details>
    so it can collapse to a compact summary (date + one-line excerpt)
    or expand to the full body. A master toggle in the page collapses
    or expands all entries at once."""
    if not items:
        return ""  # Zero app noise.
    parts: list[str] = []
    for r in items:
        cid = r["id"]
        date = r.get("note_date") or (r.get("created_at") or "")[:10] or ""
        src = r.get("source_file") or ""
        body = r.get("content") or ""
        names = r.get("names") or []
        excerpt = _one_line_excerpt(body)
        name_links = " · ".join(
            f'<a class="name-text" href="{u(f"/bindings/?q={url_path_seg(n)}")}">{esc(n)}</a>'
            for n in names
        )
        src_html = (
            f'<span class="feed-src muted">{esc(src)}</span>'
            if src else ""
        )
        parts.append(
            f'<details class="feed-item" id="feed-{cid}" open>'
            f'<summary class="feed-head">'
            f'<span class="feed-date">{esc(date)}</span>'
            f'<span class="feed-excerpt">{esc(excerpt)}</span>'
            f'</summary>'
            f'<div class="feed-body">{linkify(body)}</div>'
            + (f'<footer class="feed-names">{src_html}{name_links}</footer>' if (names or src) else "")
            + f'</details>'
        )
    return "".join(parts)


def name_detail_html(name: str, rows: list[dict]) -> str:
    """One name's detail. Each binding is its own row; bindings that point
    at a content blob accordion the blob inline beneath the row, so
    expanding a row never jumps the page. Columns (rel/qual/tgt/date/from)
    can be hidden/shown via the toggles in the page chrome.

    In edit mode (body.editing) each row gets a small × delete button.
    The item header carries an FA pen icon as a quick edit-mode toggle
    so the user doesn't have to scroll to the topnav."""
    if not rows:
        return ""

    items: list[str] = []
    content_count = 0
    for r in rows:
        bid = r["id"]
        rel = r["relationship"]
        qual = r.get("qualifier") or ""
        date = r.get("source_date") or (r.get("created_at") or "")[:10] or ""
        prov = r.get("created_by") or ""
        target_type = r.get("target_type") or ""
        target_ref = r.get("target_ref") or ""

        has_content = target_type == "content" and r.get("content")
        if has_content:
            content_count += 1

        del_btn = (
            f'<button type="button" class="bind-delete"'
            f'   hx-delete="{u(f"/bindings/{bid}")}" hx-confirm="Delete this binding?"'
            f'   hx-target="closest .bind-row" hx-swap="outerHTML"'
            f'   aria-label="delete binding">×</button>'
        )

        cols = (
            f'<span class="col-rel">{esc(rel)}</span>'
            f'<span class="col-qual">{esc(qual) or "—"}</span>'
            f'<span class="col-tgt">{render_target(target_type, target_ref)}</span>'
            f'<span class="col-date">{esc(date)}</span>'
            f'<span class="col-from">{esc(prov)}</span>'
            f'{del_btn}'
        )

        if has_content:
            ref = esc(target_ref)
            items.append(
                f'<details class="bind-row has-content" id="content-{ref}" open>'
                f'<summary>{cols}</summary>'
                f'<div class="content-blob">'
                f'<div class="body">{linkify(r["content"])}</div>'
                f'</div>'
                f'</details>'
            )
        else:
            items.append(f'<div class="bind-row">{cols}</div>')

    return f'<div class="bindings">{"".join(items)}</div>'


# ── request handler ──────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    server_version = "AbraView/0.1"

    def log_message(self, fmt, *args):  # quieter logs
        sys.stderr.write(f"[{self.log_date_time_string()}] {fmt % args}\n")

    # method routing
    def do_GET(self): self._dispatch("GET")
    def do_POST(self): self._dispatch("POST")
    def do_PATCH(self): self._dispatch("PATCH")
    def do_DELETE(self): self._dispatch("DELETE")

    def _dispatch(self, method: str) -> None:
        try:
            path = urlsplit(self.path).path
            # If we're mounted under a base path (behind nginx), strip it.
            # Both direct (BASE="") and proxied modes route the same way.
            if BASE and path.startswith(BASE):
                path = path[len(BASE):] or "/"
            handler = self._route(method, path)
            if handler is None:
                return self._send(404, "text/plain", b"not found")
            result = handler()
            if result is None:
                return  # handler already sent its own response (proxy)
            self._send(200, "text/html; charset=utf-8", result.encode("utf-8"))
        except FormError as e:
            # Validation problem: render into #flash without disturbing the
            # target the request was aimed at.
            self._send(
                200, "text/html; charset=utf-8", error_html(str(e)).encode("utf-8"),
                extra_headers={"HX-Retarget": "#flash", "HX-Reswap": "innerHTML"},
            )
        except Exception as e:
            # Genuine 500. Don't swallow — surface to the user AND log.
            import traceback
            traceback.print_exc()
            self._send(
                500, "text/html; charset=utf-8", error_html(str(e)).encode("utf-8"),
                extra_headers={"HX-Retarget": "#flash", "HX-Reswap": "innerHTML"},
            )

    def _route(self, method: str, path: str):
        # static
        if method == "GET" and path == "/":
            return lambda: apply_view_texts(
                (HERE / "index.html").read_text().replace("__BASE__", BASE),
                db_get_view_texts(),
            )
        if method == "GET" and path in ("/bindings", "/bindings/"):
            from urllib.parse import parse_qs as _pq
            qs = urlsplit(self.path).query
            params = _pq(qs)
            q = (params.get("q", [""])[0] or "").strip()
            catcode = (params.get("catcode", [""])[0] or "").strip()
            label = (params.get("label", [""])[0] or "").strip()
            # Always view bindings by category. If no filter is given,
            # default to HOME_ROOT (the user's category subtree) so the
            # bare /bindings/ URL is never a flat splat of every name.
            if not catcode and not label:
                catcode = HOME_ROOT
            # No chip at the default home root — it's the baseline view,
            # not a filter the user picked. Chip appears only when the
            # user has navigated into a narrower category or a label.
            chip = ""
            if label:
                chip = self._chip_html(label, clear_qs="")
            elif catcode and catcode != HOME_ROOT:
                lbl = db_catcode_label(catcode) or catcode
                chip = self._chip_html(lbl,
                    clear_qs="?q=" + (q or "") if q else "")
            return lambda: apply_view_texts(
                (HERE / "bindings.html").read_text()
                .replace("__BASE__", BASE)
                .replace("__Q__", esc(q))
                .replace("__CATCODE__", esc(catcode))
                .replace("__LABEL__", esc(label))
                .replace("__CHIP__", chip),
                db_get_view_texts(),
            )
        if method == "GET" and path == "/style.css":
            return lambda: self._static("style.css", "text/css")
        if method == "GET" and path == "/edit.js":
            return lambda: self._static("edit.js", "application/javascript")
        if method == "GET" and path in ("/recent", "/recent/"):
            from urllib.parse import parse_qs as _pq
            qs = urlsplit(self.path).query
            params = _pq(qs)
            catcode = (params.get("catcode", [""])[0] or "").strip()
            def _render_recent():
                items = db_recent_content(
                    limit=50,
                    catcode=catcode or None,
                )
                feed = recent_feed_html(items)
                return apply_view_texts(
                    (HERE / "recent.html").read_text()
                    .replace("__BASE__", BASE)
                    .replace("__FEED__", feed),
                    db_get_view_texts(),
                )
            return _render_recent

        # bindings browse
        if method == "GET" and path == "/bindings/list":
            return lambda: self._bindings_list()
        # Single-binding delete (edit-mode in item view).
        m = re.fullmatch(r"/bindings/(\d+)/?", path)
        if m and method == "DELETE":
            bid = int(m.group(1))
            return lambda: (db_delete_binding(bid) or "")
        # Drag-to-reorder: persists per-name 'long' scores in user_signal.
        if method == "POST" and path == "/signals/reorder":
            return self._post_reorder
        m_name = re.fullmatch(r"/names/([^/]{1,200})/?", path)
        if m_name and method == "GET":
            from urllib.parse import unquote
            name = unquote(m_name.group(1))
            return lambda: self._name_detail(name)
        # Per-catcode page (voice-pasteable URL).
        m_cat = re.fullmatch(r"/cat/([a-z0-9]{2,64})/?", path)
        if m_cat and method == "GET":
            code = m_cat.group(1)
            return lambda: self._cat_view(code)

        # tree + new-top
        if method == "GET" and path == "/catcodes/tree":
            return tree_html
        if method == "GET" and path == "/catcodes/new":
            return add_top_form_html
        if method == "GET" and path == "/catcodes/new/cancel":
            return lambda: ""

        # node-scoped: /catcodes/{code}/...
        m = re.fullmatch(r"/catcodes/([a-z0-9]{2,64})/?(edit|row|add-child|add-child/cancel)?", path)
        if m:
            code, sub = m.group(1), m.group(2)
            if method == "GET" and sub == "edit":
                return lambda: self._get_form_edit(code)
            if method == "GET" and sub == "row":
                return lambda: self._get_row(code)
            if method == "GET" and sub == "add-child":
                return lambda: self._get_form_add_child(code)
            if method == "GET" and sub == "add-child/cancel":
                return lambda: ""
            if method == "PATCH" and sub is None:
                return lambda: self._patch_label(code)
            if method == "DELETE" and sub is None:
                return lambda: self._delete(code)

        # collection POST
        if method == "POST" and path == "/catcodes/":
            return self._post_create

        # Upstream proxy: /up/<scheme>/<anything> → forward to the
        # upstream registered for <scheme>, with a per-user JWT minted
        # on every request. Scheme-agnostic: every consumer (amebo,
        # future taiga, future odoo) goes through the same path.
        m = re.fullmatch(r"/up/([a-z][a-z0-9_-]*)(/.*)?", path)
        if m:
            scheme, sub = m.group(1), m.group(2) or "/"
            return lambda: self._proxy(scheme, sub, method)

        # Components: chooser modal, install POST, topnav menu, uninstall DELETE.
        if method == "GET" and path == "/components/chooser":
            return component_chooser_html
        if method == "GET" and path == "/components/menu":
            return topnav_installed_html
        if method == "POST" and path == "/components/install":
            return self._install_component
        m = re.fullmatch(r"/components/([a-f0-9]{4,32})/?", path)
        if m and method == "DELETE":
            inst = m.group(1)
            return lambda: (db_uninstall_component(inst) or "")
        # Per-instance full-bleed page: /c/<inst>/
        m = re.fullmatch(r"/c/([a-f0-9]{4,32})/?", path)
        if m and method == "GET":
            inst = m.group(1)
            return lambda: component_page_html(inst)

        # view-text override: writes user's edit to abra as IS-binding
        m = re.fullmatch(r"/view-text/([a-z][a-z0-9._-]*)/?", path)
        if m and method == "POST":
            key = m.group(1)
            return lambda: self._post_view_text(key)

        return None

    # helpers
    def _static(self, name: str, content_type: str) -> str:
        # served as text either way; we set content-type via _send.
        # (returning bytes-as-str path simplified — keep small.)
        path = HERE / name
        if not path.exists():
            return ""
        return path.read_text()


    def _read_form(self) -> dict[str, str]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        return {k: v[0] for k, v in parse_qs(raw, keep_blank_values=True).items()}

    def _send(self, status: int, ctype: str, body: bytes,
              extra_headers: dict[str, str] | None = None) -> None:
        # endswith — not exact match — so the prefix-mounted variant
        # (/abra-view/style.css) still gets the right content type.
        # Strip the query string first; otherwise ?v=2 cache-busts break
        # this check and CSS gets served as text/html.
        url_path = urlsplit(self.path).path
        url_qs = urlsplit(self.path).query
        is_asset = (url_path.endswith("/style.css")
                    or url_path.endswith("/edit.js"))
        if url_path.endswith("/style.css") and status == 200:
            ctype = "text/css; charset=utf-8"
        if url_path.endswith("/edit.js") and status == 200:
            ctype = "application/javascript; charset=utf-8"
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # Versioned assets are content-addressed by mtime in the query
        # string, so the browser can cache them forever — the URL
        # changes as soon as the file does. Unversioned assets and
        # every HTML response stay no-store so an edit shows up on the
        # very next request.
        if is_asset and "v=" in url_qs and status == 200:
            self.send_header(
                "Cache-Control",
                "public, max-age=31536000, immutable",
            )
        else:
            self.send_header("Cache-Control", "no-store")
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    # handlers
    def _proxy(self, scheme: str, subpath: str, method: str) -> None:
        """Forward an upstream call. Mints a per-user JWT and writes the
        response directly to self.wfile (so we don't load the whole body
        into memory — bundles can be hundreds of KB)."""
        upstream_base = UPSTREAM.get(scheme)
        if not upstream_base:
            return self._send(404, "text/plain",
                              f"no upstream registered for scheme '{scheme}'".encode())
        # Build upstream URL. Strip empty-value query params before
        # forwarding so an `?status=&limit=20` from a bundle becomes
        # `?limit=20`: some upstreams (amebo today) treat an empty
        # value as 'invalid' rather than 'omitted', which breaks the
        # default-no-filter call. View doesn't care about the params'
        # meaning; this is purely defensive normalization.
        raw_qs = urlsplit(self.path).query
        if raw_qs:
            from urllib.parse import parse_qsl, urlencode
            pairs = [(k, v) for k, v in parse_qsl(raw_qs, keep_blank_values=True) if v != ""]
            qs = urlencode(pairs)
        else:
            qs = ""
        url = upstream_base + subpath + (("?" + qs) if qs else "")
        # Read request body (POST / PATCH / PUT). DELETE/GET typically no body.
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length) if length else None

        headers = {
            "Authorization": f"Bearer {mint_jwt(DEV_USER)}",
        }
        # Forward content-type for bodies — let upstream see JSON as JSON.
        ct = self.headers.get("Content-Type")
        if ct:
            headers["Content-Type"] = ct
        # Forward accept so the static bundle still serves application/javascript.
        ah = self.headers.get("Accept")
        if ah:
            headers["Accept"] = ah

        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                upstream_body = resp.read()
                ctype = resp.headers.get("Content-Type", "application/octet-stream")
                self._send(resp.status, ctype, upstream_body)
        except urllib.error.HTTPError as e:
            # Pass upstream errors through unchanged so the browser sees
            # the real status + body for debugging.
            self._send(e.code,
                       e.headers.get("Content-Type", "text/plain") if e.headers else "text/plain",
                       e.read())
        # The handler returns None; the route lambda's ""-empty return
        # would have done a normal _send, but we've already sent here.
        # Mark already-sent by returning a sentinel.
        return None  # noqa

    def _install_component(self) -> str:
        # The chooser sends `tag` (the custom-element tag, also the key
        # in components.yaml). `path` is optional — only meaningful for
        # components whose `required` includes data-path.
        form = self._read_form()
        tag = (form.get("tag") or form.get("scheme") or "").strip()
        path = (form.get("path") or "").strip()
        if not tag:
            raise FormError("tag is required")
        catalog = _load_components()
        if tag not in catalog:
            raise FormError(f"unknown component: {tag}")
        # Idempotent: if this tag is already installed, close the modal
        # silently. A stale chooser (cached HTML, double-click) cannot
        # create a duplicate. Only the OOB modal-close is returned, so
        # nothing gets appended to #topnav-installed.
        existing = [c for c in db_list_components() if c["scheme"] == tag]
        if existing:
            return '<div id="modal-slot" hx-swap-oob="innerHTML"></div>'
        # db_install_component still stores under the legacy `scheme`
        # column — we pass the tag through it until that column is
        # renamed. Renderer always cross-refs the catalog by this value.
        inst = db_install_component(tag, path)
        if inst is None:
            raise FormError("install rejected by the writer (PII filter or "
                            "permissions). Nothing was saved.")
        # Re-fetch from DB so the rendered anchor reflects what was actually
        # persisted, not what we synthesized in memory. Defensive against
        # silent writer rejections and future schema drift.
        comp = next((c for c in db_list_components() if c["id"] == inst), None)
        if comp is None:
            raise FormError("install succeeded but the row could not be "
                            "read back. Refresh and try again.")
        anchor = _topnav_anchor_html(comp, catalog)
        # Out-of-band: clear the chooser modal so the new nav entry is visible.
        anchor += '<div id="modal-slot" hx-swap-oob="innerHTML"></div>'
        return anchor

    def _bindings_list(self) -> str:
        from urllib.parse import parse_qs as _pq
        qs = urlsplit(self.path).query
        params = _pq(qs)
        q = (params.get("q", [""])[0] or "").strip()
        catcode = (params.get("catcode", [""])[0] or "").strip()
        label = (params.get("label", [""])[0] or "").strip()
        rows = db_top_names(q or None, catcode or None, label=label or None, limit=50)
        return binding_list_html(rows, q or None, catcode=catcode or None, label=label or None)

    def _chip_html(self, text: str, clear_qs: str = "") -> str:
        href = u("/bindings/") + (clear_qs or "")
        # Just the value + ×. No "filter:" / "category:" prefix — those
        # are author words; she only sees the data.
        return (
            f'<div class="filter-chip">'
            f'<span>{esc(text)}</span>'
            f'<a href="{esc(href)}" class="clear">×</a>'
            f'</div>'
        )

    def _name_detail(self, name: str) -> str:
        rows = db_name_detail(name)
        frag = name_detail_html(name, rows)
        # htmx accordion fetches and grafts the fragment inline. A direct
        # browser visit needs a full page so the URL is shareable and
        # voice-pasteable.
        if self.headers.get("HX-Request"):
            return frag
        return apply_view_texts(
            (HERE / "name.html").read_text()
            .replace("__BASE__", BASE)
            .replace("__NAME__", esc(name))
            .replace("__DETAIL__", frag),
            db_get_view_texts(),
        )

    def _cat_view(self, code: str) -> str:
        """Dedicated page for one catcode. Voice-pasteable URL. Shows
        the catcode's label, its immediate subtree, and a load-on-render
        bindings list filtered to its subtree."""
        label = db_catcode_label(code)
        if label is None:
            return ""  # 404 handled by dispatcher (empty body)
        # Subtree: render this code's children inline via tree_html-style
        # iteration. Reuse db_list + a focused render so we don't pull
        # the universe.
        rows = db_list()
        by_parent: dict[str | None, list[tuple[str, str]]] = {}
        for c, parent, lbl in rows:
            by_parent.setdefault(parent, []).append((c, lbl))
        def render(parent: str | None) -> str:
            kids = by_parent.get(parent, [])
            if not kids:
                return ""
            return "".join(li_html(cc, ll, render(cc)) for cc, ll in kids)
        # Zero app noise: empty when there are no subcategories.
        subtree = (
            f'<ul class="tree">{render(code)}</ul>'
            if by_parent.get(code) else ""
        )
        # Parent label split on "/" so each piece is its own link to the
        # matching ancestor catcode, plus the current page's leaf appended
        # as plain text.
        ancestors = db_ancestors(code)
        if ancestors:
            parent_code, parent_label = ancestors[-1]
            pieces = parent_label.split("/")
            if len(pieces) > 1:
                ancestor_by_label = {al: ac for ac, al in ancestors}
                links = []
                for i, piece in enumerate(pieces):
                    prefix_label = "/".join(pieces[: i + 1])
                    ac = ancestor_by_label.get(prefix_label)
                    if ac:
                        links.append(
                            f'<a href="{u(f"/cat/{url_path_seg(ac)}/")}">'
                            f'{esc(piece)}</a>'
                        )
                    else:
                        links.append(esc(piece))
            else:
                links = [
                    f'<a href="{u(f"/cat/{url_path_seg(parent_code)}/")}">'
                    f'{esc(parent_label)}</a>'
                ]
            current_leaf = label.split("/")[-1]
            links.append(esc(current_leaf))
            parent_link = "/".join(links)
        else:
            parent_link = f'<a href="{BASE}/">top</a>'
        return apply_view_texts(
            (HERE / "cat.html").read_text()
            .replace("__BASE__", BASE)
            .replace("__CODE__", esc(code))
            .replace("__LABEL__", esc(label))
            .replace("__SUBTREE__", subtree)
            .replace("__PARENT_LINK__", parent_link),
            db_get_view_texts(),
        )

    def _get_form_edit(self, code: str) -> str:
        row = db_get(code)
        if row is None:
            raise FormError(f"unknown catcode: {code}")
        return edit_form_html(row[0], row[2])

    def _get_row(self, code: str) -> str:
        row = db_get(code)
        if row is None:
            raise FormError(f"unknown catcode: {code}")
        return row_html(row[0], row[2])

    def _get_form_add_child(self, code: str) -> str:
        if db_get(code) is None:
            raise FormError(f"unknown parent: {code}")
        return add_child_form_html(code)

    def _patch_label(self, code: str) -> str:
        form = self._read_form()
        label = (form.get("label") or "").strip()
        if not label:
            raise FormError("label is required")
        if db_get(code) is None:
            raise FormError(f"unknown catcode: {code}")
        db_update_label(code, label)
        return row_html(code, label)

    def _delete(self, code: str) -> str:
        # Idempotent: if it's gone already, that's fine — HTMX removes the row.
        if db_get(code) is None:
            return ""
        db_delete(code)
        return ""

    def _post_reorder(self) -> str:
        """Persist a per-user 'long' score per name based on drag order.
        Body: {"names": ["a", "b", "c"]} where index 0 is the most
        important. Writes value = (N - index) so DESC sort matches order."""
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            data = _json.loads(raw)
        except Exception:
            raise FormError("invalid json")
        names = data.get("names") or []
        if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
            raise FormError("names must be a list of strings")
        sys.path.insert(0, str(ROOT / "impl" / "pgvector"))
        import signals as _signals  # type: ignore
        total = len(names)
        for i, name in enumerate(names):
            _signals.set_score(USER_URI, SCOPE, name, "long", float(total - i))
        return ""

    def _post_view_text(self, key: str) -> str:
        form = self._read_form()
        value = (form.get("value") or "").strip()
        if key not in VIEW_DEFAULTS and key not in UI_PREFS:
            raise FormError(f"unknown view-text key: {key}")
        # Empty value clears the override and reverts to default.
        db_set_view_text(key, value)
        # For editable text, return resolved string; for UI booleans, return
        # the persisted value so the client can echo state.
        if key in VIEW_DEFAULTS:
            return esc(value or VIEW_DEFAULTS[key])
        return esc(value)

    def _post_create(self) -> str:
        form = self._read_form()
        label = (form.get("label") or "").strip()
        parent = (form.get("parent_catcode") or "").strip() or None
        # Two paths: top-level uses `catcode` field; child uses `suffix`.
        if "suffix" in form:
            if not parent:
                raise FormError("child form is missing parent_catcode")
            code = parent + form["suffix"].strip()
        else:
            code = (form.get("catcode") or "").strip()

        if not label:
            raise FormError("label is required")
        if not CATCODE_RE.fullmatch(code):
            raise FormError(f"invalid catcode: {code!r} (a–z, 0–9, 2–64 chars)")
        if db_get(code) is not None:
            raise FormError(f"catcode {code} already exists")
        if parent and db_get(parent) is None:
            raise FormError(f"parent {parent} does not exist")

        db_insert(code, parent, label)

        # If this was a child add, return the new <li> to replace the add-form li.
        if "suffix" in form:
            return li_html(code, label)
        # Top-level add: re-render the full tree (simplest correct).
        return tree_html()


def main() -> None:
    print(f"abra view dev shim → http://127.0.0.1:{PORT}/")
    print(f"   db {PG['user']}@{PG['host']}:{PG['port']}/{PG['dbname']}")
    print("   stop with Ctrl-C")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
