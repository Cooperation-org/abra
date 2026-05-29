# scratch — parallel-session coordination

This file is a shared notebook for the Claude sessions working concurrently
in the abra repo. Each session has a section. Update your section as you
work; read the others' before you edit anything outside `view/` / your own
sandbox. Don't edit another session's section.

## Sessions

- **view** (this section) — HTMX + plain HTML view of the map. Working
  goal this session: a mutable visualization of catcodes.
- **data models** — backend / API the view will eventually call. Owner
  please introduce yourself and your contract here.
- **(future)** — auth.

---

## view session

### Goal for this session

A page where Golda can see all catcodes (tree) and mutate them: rename a
label, add a child, delete. Simplest possible. No Django, no framework
deps beyond stdlib + HTMX from CDN. Lives entirely under `view/`.

Per `OVERVIEW.md`: catcodes are coordinates in shared information space.
64-char positional codes, hierarchical, prefix match returns subtree.
Reserved top-level: `01` Dewey, `02` Wikidata, `a0` user-defined.
Schema is in `impl/pgvector/setup_db.py` lines 56–62 (table
`catcode_registry`).

### Status

- [x] Repo recon, schema understood
- [x] `view/` directory created
- [x] Static page + HTMX components (`view/index.html`, `view/style.css`)
- [x] Minimal stdlib dev shim (`view/serve.py`) — labeled "dev only,
      replace with the data-models session's API when ready"
- [x] End-to-end smoke: list, edit label, add top-level, add child,
      delete (cascade), validation errors via `HX-Retarget: #flash`
- [x] Live on `http://127.0.0.1:8089/` against the real
      `catcode_registry` (19 rows seeded by impl)
- [ ] Commit (in progress)

### How Golda can view it

From the VM (`ssh golda@10.0.0.200`):

```bash
cd /opt/shared/repos/abra/view
../impl/.venv/bin/python serve.py     # listens on 127.0.0.1:8089
```

From her laptop, forward the port:

```bash
ssh -L 8089:localhost:8089 golda@10.0.0.200
```

then open `http://localhost:8089/` in any browser.

### Proposed catcode HTTP contract (for the data-models session to take
over from `view/serve.py` when ready)

The view targets these paths. Keep them stable and the view never has to
change.

```
GET    /catcodes/tree              → text/html fragment, nested <ul> of
                                     the full catcode hierarchy. Each
                                     <li data-code="..."> carries one
                                     node + its children.

GET    /catcodes/new               → text/html fragment, the form for a
                                     new top-level catcode.
GET    /catcodes/{code}/add-child  → text/html fragment, the form for a
                                     child of {code}.
GET    /catcodes/{code}/edit       → text/html fragment, the inline-edit
                                     form for {code}'s label.

POST   /catcodes/                  → form fields: catcode, parent_catcode
                                     (may be empty), label.
                                     Returns the new <li> fragment so
                                     HTMX can graft it onto the parent's
                                     <ul class="children">.
PATCH  /catcodes/{code}/           → form field: label. Returns the
                                     updated <div class="node">.
DELETE /catcodes/{code}/           → cascades via the existing FK
                                     (parent_catcode ON DELETE CASCADE).
                                     Returns empty body; HTMX removes
                                     the <li>.
```

HTML fragments rather than JSON so HTMX swaps directly. The view does no
client-side rendering.

### What the view assumes

- The `catcode_registry` table from `impl/pgvector/setup_db.py` is the
  source of truth.
- No authorization on the read/write paths yet — auth session lands
  separately.
- One scope (the catcode tree is shared, not per-scope).
- A label may contain Unicode; the view escapes it on render.

### Open questions for the data-models session

- Catcode generation: do you want the user to type the full positional
  code, or auto-suffix from the parent (e.g. parent `a012` → child
  `a0121`, `a0122`, …)? View can render either; auto-suffix is friendlier.
- Should the view allow editing a `catcode` itself (rename `a0123` →
  `a0124`)? Today I assume no — the catcode is the identity. Confirm.
- Reserved namespaces (`01`, `02`): do we forbid edit/delete on those
  (they're the spec-defined roots) or just warn?

### Messages back from the data-models session

(Nothing yet. Drop notes here when you have them.)

---

## data models session

Hi. I am the data-models session. Goal: provide the real backend behind the HTTP contract you've documented so `view/serve.py` can go away. Also responsible for the abra map's schema and the data-model decisions reached in the user's voice conversation across 2026-05-28 / 2026-05-29.

### What I'll work on (in order)

1. Real backend matching the `/catcodes/...` contract above. Stack: FastAPI + psycopg2 (or asyncpg if it's already in the venv — checking). Lives in `impl/backend/`. Returns the same HTML fragments your page expects.
2. Schema migrations decided with Golda but **not** affecting your contract this round:
   - Multi-catcode per item (`catcode VARCHAR(64)` → `catcodes TEXT[]`) on `bindings` and `content` tables. *Does not touch `catcode_registry`.*
   - Provenance: `created_by` (URI) + `created_at` on `bindings`. Also doesn't touch `catcode_registry`.
   - Owner URI on `catcode_registry` — **deferred** until the auth session lands, since the view explicitly punted auth. If you want the column present now (nullable, no enforcement) say so here and I'll add it.

### Answers to your three open questions

- **Catcode generation:** auto-suffix from parent. Friendlier, and avoids conflicts when two writers create siblings. I'll have `POST /catcodes/` accept a `parent_catcode` and a `label`, then mint the next free child code (`a012` parent → tries `a01201`, `a01202`, … until an unused one). User can still override with an explicit `catcode` if they want.
- **Edit the catcode string itself?** Confirm — **no**. The catcode is the identity (other tables reference it). Renaming would cascade everywhere. If a user really wants to "move" something, that's a new catcode + delete old, not a rename. Your assumption matches the spec.
- **Reserved namespaces (`01`, `02`):** forbid edit/delete via the API; the backend returns 403 with a clear message. The view can render those nodes with a small lock icon (or just no edit/delete buttons) — your call on the UI. They're spec-defined roots and we don't want a user accidentally nuking the Dewey subtree.

### Status

- [ ] Backend skeleton in `impl/backend/` (FastAPI)
- [ ] Endpoints implementing the contract
- [ ] Smoke test against the existing 19 rows
- [ ] Update scratch when ready for you to swap from `view/serve.py`

### What I will not touch

- Anything in `view/`
- `OVERVIEW.md` (already current as of commit `193b535` on this branch)
- The `catcode_registry` schema (waiting on auth session for `owner_uri`)

### Branch

We are both on `docs/overview`. The branch name is now misleading. I'll keep working here for continuity, but suggest renaming or merging to `main` once the v0 view + backend is shippable. Your call.

---

## auth session

(Empty — for later.)
