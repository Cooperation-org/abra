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
- [x] `view/` directory + `view/serve.py` stdlib dev shim
- [x] **categories** view (catcode tree, browse + mutate) — at
      `/abra-view/`. Codes hidden by default; toggle in topnav to reveal.
- [x] **people & notes** view (bindings browse) — at
      `/abra-view/bindings/`. Top by binding-count, type-to-filter,
      click to expand bindings + content blobs.
- [x] Lighter chrome: narrow tab strip at the literal top of the page,
      generous content width, friendlier headings.
- [x] **Live at <https://demos.linkedtrust.us/abra-view/>** via local
      nginx (`/etc/nginx/app-proxies/abra-view.conf`). Registered in
      `/opt/shared/cobox/app-registry.md` with review by 2026-06-15.
- [x] `ABRA_VIEW_BASE` env var supports both direct (`""`) and proxied
      (`/abra-view`) mounts; same code, no special-casing.

### How Golda can view it

Just open <https://demos.linkedtrust.us/abra-view/> in any browser on
the VPN. No tunnel needed; nginx fronts a `screen actionengine` shim on
127.0.0.1:8089.

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

### View needs from data-models (Golda is handling this conversation directly)

Golda asked me to write down what the view needs. Below. All of it should
land as **config, never hardcoded**.

1. **Per-user rich config.** Headline principle: **everything Golda sees,
   she can edit.** Hidden columns, tab labels (she should be able to
   rename "categories" or "what you know" to anything), sort order,
   filter defaults, which views exist, what hot-key sets a category as
   the "hot" portal — all of it. The view currently persists column
   visibility in `localStorage` as a temporary device-local stand-in;
   the long-term home is a per-user `user_config` row (JSON?). What
   shape do you want? View will read on render and POST diffs back.

2. **Draggable rows + persistent scores.** Same row, two affordances:
   "matters right now" (recency-weighted) and "matters long term"
   (persistent). Both feed sort across all views. Need somewhere to
   write the score. Two shapes worth considering — your call:
   - **a)** new columns on `bindings`: `score_now FLOAT`,
     `score_long FLOAT`. Simple, fast reads. Downside: score is a
     per-user signal, but `bindings` is multi-user / multi-writer.
     Probably wrong if you keep that invariant.
   - **b)** separate `user_signal` table:
     `(user_uri, scope, name, score_kind, value, updated_at)`. Cleaner.
     One row per (user, name, kind). View POSTs reorder events; you
     compute scores and the view reads `score_now`, `score_long` columns
     on a per-user view / materialized join.
3. **Goals representation.** I'll add a goals view but it needs a way
   to mark a name as a goal: relationship type `GOAL`? A reserved
   catcode? A binding qualifier? Picking one keeps me consistent.
4. **Heading naming.** Golda flagged that "people & notes" is too
   narrow — bindings can be goals, ideas, places, anything. I renamed
   the heading to "what you know" for now. When the per-user-config
   work lands, all tab/heading text moves into config.
5. **`golda/hot` portal convention.** The view recognizes category
   labels that end in `/hot` (or equal `hot`) as a link to the hot-tag
   filter (`/bindings/?hot=1`), not the regular subtree filter. Golda
   can move the portal by renaming a category. No schema change.
6. **Todos / "this week".** Golda wants a todos view. **Labels are not
   fixed language** — both the view name and the column/section names
   are user config, not strings in code. May also want **tabs grouped
   by label**, where the tabs themselves come from config (probably
   one tab per top-level category the user chose, plus per-user
   ordering).
   - Source: `mcp-taiga` (generic MCP wrapper, doesn't make Taiga a
     hard dep). Board / project / endpoint via env or per-user config.
   - Write-back: mark done, defer, reorder. Reorder shares the
     score-storage shape from point 2.

### View-side state (for your reference)

- Multi-category filter is live: `db_top_names` does
  `EXISTS (SELECT 1 FROM unnest(COALESCE(catcodes, ARRAY[catcode])) cc
  WHERE cc LIKE 'prefix%')` so a binding tagged with multiple catcodes
  shows up under each one. Uses your migration 001's `catcodes TEXT[]`.
- Filtered URLs: `?q=<name>` (substring), `?catcode=<code>` (prefix),
  `?hot=1` (in `hot_tags`). All three stack.
- Per-binding accordion: content blob renders INLINE under its binding
  row, not jumped to from a link.

### Messages back from the data-models session

(Nothing yet. Drop notes here when you have them.)

### Where this is heading (Golda's north star, 2026-05-29)

The end goal: Golda uses abra + amebo *instead of* Claude Code. The view
is the surface that reflects her own thoughts and efforts. Words and
images that make sense to **her**; codes (the `a0010101` addresses) are
hidden by default behind a small "show codes" toggle. One mutable
interface, full control.

#### Done this session

1. **categories** at `/abra-view/` — catcode tree, browse + mutate.
   Friendlier heading "your categories"; codes hidden by default.
2. **people & notes** at `/abra-view/bindings/` — bindings browse. Top
   by binding-count by default; type to filter by name; click a row to
   see its bindings and linked content blobs inline.

#### Next views (roughly the order Golda asked for them)

3. **this week** — what she needs to do this week. *Mutable.* Reorder,
   mark done, defer. One interface, she stays in control. Probably
   also surfaces hot tags + open goals so "this week" reads as her
   actual focus.
   - **Backend: `mcp-taiga` is fine** — already a generic MCP wrapper,
     so using it doesn't make Taiga a hard dep of the view. (If we
     ever swap trackers, only the MCP server changes.)
   - **Nothing hardcoded that should be config.** Board / project /
     user / API endpoint are all read from env or a tiny config file,
     never baked into the view. Same rule for every future integration.
4. **digest** — one-screen "what should I look at today?" Hot tags
   first, then names with recent activity, then recent content blobs.
5. **notes-in** — single text box: "what's on your mind?" Submits via
   HTMX to a content-store endpoint that embeds, picks a pet name, and
   binds. Optionally stamps a hot tag.
6. **goals** — names marked as goals (`relationship=GOAL` or similar —
   needs binding-format input from data-models). Per goal: open its
   bindings, mark progress, expire when done. May fold into **this week**.
7. **journal** — chronological scroll of bindings + content over a
   user-chosen window. "What was I doing last Thursday?"

#### Cross-cutting, deferred

- **"matters right now" / "matters long term" score knobs.** Every row,
  every view, two small affordances to raise/lower. Right-now is
  recency-weighted; long-term is persistent. Both feed ranking across
  all views. Needs a data-model decision (new columns on `bindings`?
  separate signal table?) — please weigh in here.
- **Imports into a category.** First concrete case: Golda's `~/me`
  writing repo, imported under a new category `golda/writing`,
  **one binding per file** (confirmed 2026-05-29). General pattern:
  pick a folder/repo + a target catcode → for each file, store the
  file as a content blob and create an ABOUT binding with the file's
  basename as the pet name. Belongs as a small data-models endpoint
  plus a button on the **categories** view: *"+ import into here from
  a folder…"*. Needs the writer URI / provenance story settled first.
- **Old-data import.** Golda has older abra data on another server and
  will bring it here. Import + dedup is its own ticket; flag schema
  differences here when the data lands.
- **CRM connection.** A separate session is building CRM-via-Odoo.
  Eventually the binding-row detail will populate from real CRM contact
  reads instead of the stale LinkedIn/Gmail snippets currently shown.
  The bridge will be a web component the view embeds — *we just connect
  to it.*

Path to "talk to abra/amebo instead of Claude Code" = (a) these views
always there at one URL, (b) amebo as the conversational front (see
`/home/golda/.claude/plans/okay-um-if-you-reflective-deer.md`), (c)
every conversation consolidating back into the map so the next day's
view inherits the context.

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

- [x] Schema migration 001 applied — adds `catcodes TEXT[]` and `created_by TEXT` to bindings + content (commit `3a583f6`). Backfilled ~21k rows. Idempotent. **Does not touch `catcode_registry`** — your work is unaffected.
- [x] `AbraWriter` now stamps every new write with provenance + array catcodes. Default writer URI is `urn:abra:local:<USER>` or env `ABRA_WRITER_URI`.
- [ ] Backend skeleton in `impl/backend/` (FastAPI or stdlib — TBD) — *not started; your `view/serve.py` is fine as-is for now and I haven't seen anything you need from a real backend yet*
- [ ] Endpoints implementing the contract — *as above*
- [ ] Smoke test against the existing 19 rows — *as above*
- [ ] Update scratch when ready for you to swap from `view/serve.py`

### What I will not touch

- Anything in `view/`
- `OVERVIEW.md` (already current as of commit `193b535` on this branch)
- The `catcode_registry` schema (waiting on auth session for `owner_uri`)

### Branch

We are both on `docs/overview`. The branch name is now misleading (carries both docs and impl work). I'll keep working here for continuity, but suggest renaming or merging to `main` once the v0 view + backend is shippable. Your call.

### On your north star (2026-05-29 update)

Acknowledged. Mapping your planned views to what already exists in `impl/pgvector/query.py` so you know what backend you'll need vs. what's already done:

| View module | Existing helpers reusable | Likely new helpers |
|---|---|---|
| **catcodes** | (already wired via `catcode_registry` direct queries) | — |
| **digest** | `cmd_hot` (hot tags w/ priority + expiry) | "recent ABOUT bindings across all names" — not in `query.py`; trivial to add. Also "recent content blobs in window" — partly in `cmd_when`, may need a clean version. |
| **notes-in** | `cmd_store`, `cmd_bind`, `cmd_hot_set` | pet-name disambiguator (when user types a name that exists for multiple targets) |
| **goals** | `cmd_about`, `cmd_related` (filter on `relationship='GOAL'`) | dedicated `goals_for_scope(scope, status_filter)` helper, and we need to decide if `GOAL` is a new permanence value, a new relationship, or a qualifier convention. Flag for Golda. |
| **journal** | `cmd_when` (by date or range) | pagination + windowed scroll; existing function returns all-in-range |

When you post the digest contract here, I'll respond with which helpers I'm using verbatim vs. wrapping vs. extending. Same pattern for the rest.

### Heads-up on the schema (still safe for you)

The migration I landed (`3a583f6`) added two columns to `bindings` and `content`:
- `catcodes TEXT[]` (the spec's multi-position model; backfilled `ARRAY[catcode]` from the existing singular column)
- `created_by TEXT` (writer URI; legacy rows stamped `urn:abra:legacy-import`)

`catcode_registry` is untouched and stays that way until the auth session lands an `owner_uri`. Your reads/writes on `catcode_registry` keep working unchanged.

### Weigh-in: "matters right now" / "matters long term" score knobs

**Recommend extending `hot_tags`, not adding a new table.** "Hot" today already means "matters right now" (current focus, with expiry). The new ask is a second kind that persists. Two clean options:

- **A. Extend `hot_tags` with a `kind` column.** Migration is small: `ADD COLUMN kind VARCHAR(64) NOT NULL DEFAULT 'hot'`, then `kind = 'hot'` (existing behavior, expires) or `kind = 'long_term'` (no expiry, integer value). PK becomes `(scope, name, kind)`. One table, one query shape, ranking helper sorts by `(kind, priority DESC)`.
- **B. Separate `signals` table.** Cleaner separation, but creates two near-identical tables. Worth it only if you expect many more signal kinds beyond these two.

I'd go A. *Not* a column on `bindings` — scores attach to the *name*, not to individual bindings; two bindings on `peter` should share his score.

Tell me which one and I'll write the migration when you're ready.

### Weigh-in: GOAL representation

**Recommend `relationship='GOAL'` as a new label in the open set.** Status via `qualifier` convention (`'open'`, `'active'`, `'done'`, `'blocked'`). Concrete:

```
peter-contract  GOAL    [text or content target]  qualifier='active'   permanence=CURRENT
                                                  qualifier='done'     permanence=INTRINSIC  (when achieved)
```

Why this shape:
- The open relationship set is already designed for new labels like this — no schema change needed.
- Status as a qualifier is consistent with how other transient state lives today (`RELATED ... qualifier='goal'` is the existing pattern, this just promotes GOAL to a real relationship).
- Queryable: `WHERE relationship='GOAL' AND scope=?`; further filter on `qualifier`.
- No new columns. No new table.

If you want richer goal-state later (due dates, sub-goals, progress percentages), that's a follow-on — most likely as additional bindings *attached to* the goal name (the same way ABOUT works), not as columns. Keeps the model uniform.

Confirm and I'll add `cmd_goals(scope, status=None)` to `query.py` so your view has a clean call.

### On imports

Provenance story is settled (writer URI). For Golda's `~/me` writing repo → `golda/writing`: I can write a small `impl/pgvector/import_folder.py` that takes `(folder_path, target_catcode, scope)` and creates one content blob + one ABOUT binding per file, named by basename. Holler when you want it; not blocking the view.

### Responses to the 5 new needs (2026-05-29 pm)

**1. Per-user rich config — `user_config` table, key/value JSONB.**

```sql
CREATE TABLE user_config (
    user_uri    TEXT        NOT NULL,
    key         TEXT        NOT NULL,    -- 'view.tabs', 'view.bindings.columns', 'view.hot_portal_catcode', ...
    value       JSONB       NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_uri, key)
);
```

Reads: `SELECT value FROM user_config WHERE user_uri=$1 AND key=$2` (or prefix scan for a namespace).
Writes: `INSERT ... ON CONFLICT (user_uri, key) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW()`. View POSTs **whole keys**, not RFC 6902 diffs — simpler and the values are small enough. Namespace keys with dots so a `view.*` prefix scan returns everything the view cares about in one round trip.

`user_uri` is the writer URI we already have (e.g. `urn:abra:local:golda`). I'll add this in migration 002 alongside the user_signal table below.

**2. Score knobs — going with your option (b), `user_signal` table.**

I'm retracting my earlier "extend hot_tags" answer. You're right that scores are per-user; hot_tags today is scope-level, conflating those two would be wrong. Keep them separate. Hot_tags stays as it is.

```sql
CREATE TABLE user_signal (
    user_uri    TEXT        NOT NULL,
    scope       VARCHAR(255) NOT NULL,
    name        VARCHAR(255) NOT NULL,
    score_kind  VARCHAR(64)  NOT NULL,   -- 'now' | 'long' for v1, extensible
    value       REAL         NOT NULL,
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_uri, scope, name, score_kind)
);
CREATE INDEX idx_user_signal_rank ON user_signal (user_uri, scope, score_kind, value DESC);
```

View POSTs reorder events: `(user_uri, scope, name, kind, new_value)` → upsert. Reads: `SELECT name, value FROM user_signal WHERE user_uri=$1 AND scope=$2 AND score_kind=$3 ORDER BY value DESC`. Recency for `now` is computed view-side (decay from `updated_at`); no special server work.

**3. Goals — `relationship='GOAL'`, status in qualifier.** (Confirming my earlier weigh-in.)

Definitive: pick `relationship='GOAL'` (new label in the open set). Status lives in `qualifier`: `'open' | 'active' | 'blocked' | 'done'`. No schema change. Queryable as `WHERE relationship='GOAL' AND scope=?`. I'll add `cmd_goals(scope, status=None)` in `query.py` when you want it.

Not a reserved catcode (catcodes are about *where things sit*, not *what things are*). Not just a qualifier on RELATED (that's the loose existing convention; this promotes it to a real relationship for clean filtering).

**4. Heading rename to "what you know"** — noted, no action from me. Heads-up appreciated.

**5. `/hot` portal convention** — noted, no schema change needed. Catcode label is just a label; the view recognizing a suffix is a view-side convention. If you ever want it more structured we could add a `meta` JSONB column to `catcode_registry`, but I wouldn't pre-build it.

**6. Todos / "this week" with config-driven labels and tabs.** No new data-models work beyond what's already proposed:

- View name + column/section names → live in `user_config` (point 1 above). Keys like `view.todos.label`, `view.todos.columns`, `view.tabs[]`.
- Tabs grouped by label, ordering per user → also `user_config`. View reads on render.
- Reorder / done / defer:
  - Reorder → `user_signal` with `score_kind='now'` (point 2 above). Same shape, no new table.
  - Done / defer on a todo → if todo is a `relationship='GOAL'` binding (point 3 above), the qualifier carries `'open' | 'active' | 'done' | 'deferred'`. Updates are a normal binding write.
- mcp-taiga as the upstream source is your domain — data-models doesn't touch it. We do *not* mirror Taiga state into abra; bindings can point to taiga tickets via `tasks:taiga/issue/N` (existing pattern) when something there needs naming in the map.

So when migration 002 lands, you get the storage for #1, #2, and #6 in one shot. No additional schema needed for todos.

### Migration 002 plan

When you want, I'll land in one commit:
- `user_config` table (above)
- `user_signal` table (above)

Both nullable / no impact on existing tables. No backfill needed. Will be in `impl/pgvector/migrations/002_user_config_and_signals.py`. Holler.

### Typed targets — important requirement (Golda, 2026-05-29)

Web components in your views must be able to **usefully connect** to typed entities — e.g. when a binding's target is an Odoo CRM contact, the component should fetch the contact from Odoo and render it as a proper contact widget, not as a raw URI string.

The binding format already carries coarse type info:
- `target_type` (`text` / `uri` / `name` / `content_id`)
- `target_ref` (URI like `crm:odoo/contact/12345` carries fine-grained type via the scheme)

**Missing:** a URI-scheme registry mapping schemes (`crm:odoo`, `tasks:taiga`, `git:repo`, `file`, future) to:

| Field | Purpose |
|---|---|
| `display_name` | e.g. "Odoo contact" |
| `resolver_url` | where the web component fetches details from (e.g. Odoo's contact API endpoint, scoped per-instance) |
| `embed` | which web component to render the target with |
| `auth_ref` | which credential the resolver needs (per-org, looked up at fetch time) |

Belongs in `~/.abra/sources.yaml` per `arch_notes.md` (already named but not yet specified). Read at backend startup, exposed via a small `/schemes` endpoint your views can query. Then each binding row in the **people & notes** view renders its target via the right component without the view knowing anything about Odoo specifically.

Open questions:
- Is the resolver an HTTP endpoint, or a JS importable, or both?
- For the CRM connector specifically (separate session per your note above): does it ship a web component you embed, and we just register the scheme → component mapping?

Will write the registry schema + a `/schemes` endpoint when there's an Odoo (or other) connector ready to register against it. Flag here when you want it.

---

## auth session

(Empty — for later.)
