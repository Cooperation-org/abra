# abra view

The HTMX side of the abra view subsystem. v0 scope is one page: a tree of
catcodes you can browse and mutate (rename, add child, delete).

## Run

From this directory:

```bash
../impl/.venv/bin/python serve.py
```

Open `http://127.0.0.1:8089/`.

## Files

| File | Purpose |
|---|---|
| `index.html` | The page. Loads the tree via HTMX on page load. |
| `style.css` | Minimal styles, dark slate + teal. |
| `serve.py` | **Dev shim.** Stdlib `http.server` + psycopg2. Talks to the existing `catcode_registry` table directly. Goes away when the data-models session provides the real backend (same HTTP contract — see `/scratch.md`). |

## What the page does

- On load, fetches `/catcodes/tree` and renders the catcode hierarchy.
- Per-node inline actions: **edit** label, **+ child**, **delete**.
- Top-of-page **+ new top-level** for adding a new root.
- All mutations write to `catcode_registry` immediately.
- Errors render as a small inline banner; the server still returns the
  right status code so the rest of the page is unaffected.

## What the page does not do

- No authentication. Anyone who can reach the dev shim can mutate.
  Acceptable in dev; real auth lands when the auth session does.
- No history / undo. The schema's `created_at` is the only audit trail.
- No PII (the catcode_registry holds none — it's the coordinate space
  itself).
- No vendor lock-in: replace `serve.py` with anything that honours the
  contract in `/scratch.md` and the page keeps working.
