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
from urllib.parse import parse_qs, urlsplit

import psycopg2

# ── env ──────────────────────────────────────────────────────────────────
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
ENV_PATH = ROOT / "impl" / ".env"


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
    with conn() as c, c.cursor() as cur:
        cur.execute(
            "INSERT INTO catcode_registry (catcode, parent_catcode, label) VALUES (%s, %s, %s)",
            (code, parent or None, label),
        )


def db_update_label(code: str, label: str) -> None:
    with conn() as c, c.cursor() as cur:
        cur.execute(
            "UPDATE catcode_registry SET label = %s WHERE catcode = %s",
            (label, code),
        )


def db_delete(code: str) -> None:
    # FK ON DELETE CASCADE handles the subtree.
    with conn() as c, c.cursor() as cur:
        cur.execute("DELETE FROM catcode_registry WHERE catcode = %s", (code,))


# ── Bindings browse — read-only ──────────────────────────────────────────
# Default scope is configurable; future change is a scope picker in the UI.
SCOPE = os.getenv("ABRA_VIEW_SCOPE", "golda")


def db_top_names(q: str | None, limit: int = 50) -> list[tuple[str, int, str | None, str | None]]:
    """Names with binding count, most-recent date, and a teaser qualifier.
    Sort: count desc, then most-recent desc. With q, filter by ILIKE."""
    args: list = [SCOPE, SCOPE]
    where_q = ""
    if q:
        where_q = "AND b.name ILIKE %s"
        args.append(f"%{q}%")
    sql = f"""
        SELECT b.name,
               COUNT(*) AS n,
               MAX(COALESCE(b.source_date, b.created_at::date))::text AS most_recent,
               (SELECT qualifier FROM bindings
                WHERE scope = %s AND name = b.name AND qualifier IS NOT NULL
                ORDER BY COALESCE(source_date, created_at::date) DESC NULLS LAST LIMIT 1) AS teaser
        FROM bindings b
        WHERE b.scope = %s {where_q}
        GROUP BY b.name
        ORDER BY n DESC, most_recent DESC NULLS LAST
        LIMIT {int(limit)}
    """
    with conn() as c, c.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchall()


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


def row_html(code: str, label: str) -> str:
    """One node's row (not its children) — the unit that edit returns to."""
    e = esc(code)
    lbl = esc(label)
    # Confirm uses the label (friendly) — codes are hidden by default in the UI.
    confirm_label = label or code
    return (
        f'<div class="node-row" id="row-{e}">'
        f'<span class="code">{e}</span>'
        f'<span class="label">{lbl}</span>'
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
    return f'<ul class="tree">{render(None)}</ul>'


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
    return (
        '<form class="add-form" id="new-form"'
        f'      hx-post="{u("/catcodes/")}"'
        '      hx-target="#tree" hx-swap="innerHTML">'
        '<label for="new-catcode">catcode</label>'
        '<input type="text" id="new-catcode" name="catcode" placeholder="e.g. a0" required pattern="[a-z0-9]{2,64}" autofocus>'
        '<label for="new-label">label</label>'
        '<input type="text" id="new-label" name="label" required style="flex:1">'
        '<input type="hidden" name="parent_catcode" value="">'
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


def render_target(target_type: str, target_ref: str) -> str:
    """A binding's target rendered usable: http(s) becomes a link, name
    becomes an in-app link to that name's bindings, content becomes an
    anchor to the inline blob, anything else stays as readable text."""
    if not target_ref:
        return ""
    if target_type == "content":
        return f'<a href="#content-{esc(target_ref)}">content #{esc(target_ref)}</a>'
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
        # Non-http URIs (crm:, tasks:, did:, file:) — show plainly until
        # the pointer-scheme registry lands and we can resolve them.
        return f'<span class="uri">{esc(target_ref)}</span>'
    if target_type == "text":
        return f'<span class="text-target">{esc(target_ref)}</span>'
    # Unknown / future target_type — render the raw value but typed.
    return f'<span class="other-target">{esc(target_type)}: {esc(target_ref)}</span>'


# ── Bindings view fragments ──────────────────────────────────────────────

def binding_list_html(rows: list[tuple], q: str | None) -> str:
    if not rows:
        if q:
            return f'<p class="muted">No names match <code>{esc(q)}</code>.</p>'
        return '<p class="muted">No bindings in this scope.</p>'
    items = []
    for name, n, most_recent, teaser in rows:
        href = u(f"/names/{esc(name)}/")
        date_str = most_recent or "—"
        teaser_html = f'<span class="teaser">{esc(teaser)}</span>' if teaser else ""
        items.append(
            f'<li>'
            f'<details class="name-card">'
            f'<summary>'
            f'<span class="name-text">{esc(name)}</span>'
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
    header = f'<p class="muted">{len(rows)} name{"s" if len(rows) != 1 else ""}{" matching" if q else ""}.</p>'
    return header + f'<ul class="binding-list">{"".join(items)}</ul>'


def name_detail_html(name: str, rows: list[dict]) -> str:
    if not rows:
        return f'<p class="muted">No bindings for <code>{esc(name)}</code> in this scope.</p>'

    binding_lis = []
    content_blobs = []
    for r in rows:
        rel = r["relationship"]
        qual = r.get("qualifier") or ""
        date = r.get("source_date") or (r.get("created_at") or "")[:10] or ""
        prov = r.get("created_by") or ""
        target_type = r.get("target_type") or ""
        target_ref = r.get("target_ref") or ""

        if target_type == "content" and r.get("content"):
            content_blobs.append({
                "ref": target_ref,
                "src": r.get("source_file") or "",
                "date": r.get("note_date") or date,
                "body": r["content"],
            })

        binding_lis.append(
            f'<li>'
            f'<span class="rel">{esc(rel)}</span>'
            f'<span class="qual">{esc(qual) or "—"}</span>'
            f'<span class="tgt">{render_target(target_type, target_ref)}</span>'
            f'<span class="date">{esc(date)}</span>'
            f'<span class="prov">{esc(prov)}</span>'
            f'</li>'
        )

    parts = [
        f'<p class="muted">{len(rows)} binding{"s" if len(rows) != 1 else ""}'
        + (f" · {len(content_blobs)} content blob{'s' if len(content_blobs) != 1 else ''}" if content_blobs else "")
        + "</p>",
        f'<h4>bindings</h4>',
        f'<ul class="bindings">{"".join(binding_lis)}</ul>',
    ]
    if content_blobs:
        parts.append(f'<h4>content</h4>')
        for cb in content_blobs:
            parts.append(
                f'<div class="content-blob" id="content-{esc(cb["ref"])}">'
                f'<header>'
                f'<span>{esc(cb["date"]) if cb["date"] else ""}</span>'
                f'<span>{esc(cb["src"])}</span>'
                f'<span class="muted">#{esc(cb["ref"])}</span>'
                f'</header>'
                f'<div class="body">{linkify(cb["body"])}</div>'
                f'</div>'
            )
    return "".join(parts)


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
            body = handler() or ""
            self._send(200, "text/html; charset=utf-8", body.encode("utf-8"))
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
            return lambda: (HERE / "index.html").read_text().replace("__BASE__", BASE)
        if method == "GET" and path in ("/bindings", "/bindings/"):
            from urllib.parse import parse_qs as _pq
            qs = urlsplit(self.path).query
            q = (_pq(qs).get("q", [""])[0] or "").strip()
            return lambda: (
                (HERE / "bindings.html").read_text()
                .replace("__BASE__", BASE)
                .replace("__Q__", esc(q))
            )
        if method == "GET" and path == "/style.css":
            return lambda: self._static("style.css", "text/css")

        # bindings browse
        if method == "GET" and path == "/bindings/list":
            return lambda: self._bindings_list()
        m_name = re.fullmatch(r"/names/([^/]{1,200})/?", path)
        if m_name and method == "GET":
            from urllib.parse import unquote
            name = unquote(m_name.group(1))
            return lambda: self._name_detail(name)

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
        if self.path.endswith("/style.css") and status == 200:
            ctype = "text/css; charset=utf-8"
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    # handlers
    def _bindings_list(self) -> str:
        from urllib.parse import parse_qs as _pq
        qs = urlsplit(self.path).query
        q = (_pq(qs).get("q", [""])[0] or "").strip()
        rows = db_top_names(q or None, limit=50)
        return binding_list_html(rows, q or None)

    def _name_detail(self, name: str) -> str:
        rows = db_name_detail(name)
        return name_detail_html(name, rows)

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
