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
CATCODE_RE = re.compile(r"^[a-z0-9]{2,64}$")


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


# ── HTML fragments ───────────────────────────────────────────────────────

def esc(s: str | None) -> str:
    return html.escape(s or "", quote=True)


def row_html(code: str, label: str) -> str:
    """One node's row (not its children) — the unit that edit returns to."""
    e = esc(code)
    return (
        f'<div class="node-row" id="row-{e}">'
        f'<span class="code">{e}</span>'
        f'<span class="label">{esc(label)}</span>'
        f'<span class="actions">'
        f'  <button type="button" hx-get="/catcodes/{e}/edit"'
        f'          hx-target="#row-{e}" hx-swap="outerHTML">edit</button>'
        f'  <button type="button" hx-get="/catcodes/{e}/add-child"'
        f'          hx-target="#children-{e}" hx-swap="beforeend">+ child</button>'
        f'  <button type="button" class="danger"'
        f'          hx-delete="/catcodes/{e}/"'
        f'          hx-confirm="Delete {e} and all children? This cannot be undone."'
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
        f'      hx-patch="/catcodes/{e}/"'
        f'      hx-target="#row-{e}" hx-swap="outerHTML">'
        f'<label for="label-{e}">label</label>'
        f'<input type="text" id="label-{e}" name="label" value="{esc(label)}" required autofocus style="flex:1">'
        f'<button type="submit" class="primary">save</button>'
        f'<button type="button" hx-get="/catcodes/{e}/row" hx-target="#row-{e}" hx-swap="outerHTML">cancel</button>'
        f"</form>"
    )


def add_top_form_html() -> str:
    return (
        '<form class="add-form" id="new-form"'
        '      hx-post="/catcodes/"'
        '      hx-target="#tree" hx-swap="innerHTML">'
        '<label for="new-catcode">catcode</label>'
        '<input type="text" id="new-catcode" name="catcode" placeholder="e.g. a0" required pattern="[a-z0-9]{2,64}" autofocus>'
        '<label for="new-label">label</label>'
        '<input type="text" id="new-label" name="label" required style="flex:1">'
        '<input type="hidden" name="parent_catcode" value="">'
        '<button type="submit" class="primary">add</button>'
        '<button type="button" hx-get="/catcodes/new/cancel" hx-target="#new-slot" hx-swap="innerHTML">cancel</button>'
        "</form>"
    )


def add_child_form_html(parent_code: str) -> str:
    """Sits as a <li> at the end of the parent's children ul."""
    p = esc(parent_code)
    return (
        f'<li class="add-li" id="add-li-{p}">'
        f'<form class="add-form"'
        f'      hx-post="/catcodes/"'
        f'      hx-target="#add-li-{p}" hx-swap="outerHTML">'
        f'<span class="prefix">{p}</span>'
        f'<label for="suf-{p}">suffix</label>'
        f'<input type="text" id="suf-{p}" name="suffix" placeholder="e.g. 01" required pattern="[a-z0-9]+" autofocus>'
        f'<label for="lab-{p}">label</label>'
        f'<input type="text" id="lab-{p}" name="label" required style="flex:1">'
        f'<input type="hidden" name="parent_catcode" value="{p}">'
        f'<button type="submit" class="primary">add</button>'
        f'<button type="button" hx-get="/catcodes/{p}/add-child/cancel"'
        f'        hx-target="#add-li-{p}" hx-swap="outerHTML">cancel</button>'
        f"</form>"
        f"</li>"
    )


def error_html(message: str) -> str:
    return f'<p class="error">{esc(message)}</p>'


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
            return lambda: (HERE / "index.html").read_text()
        if method == "GET" and path == "/style.css":
            return lambda: self._static("style.css", "text/css")

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
        if self.path == "/style.css" and status == 200:
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
