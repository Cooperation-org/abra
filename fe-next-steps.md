# Front-end next steps

Handoff doc for the next view-session. Read this, the linked design
docs, and the memory index — that's enough to pick up cold.

Last cycle ended **2026-06-05** with the view shim live at
[`https://demos.linkedtrust.us/abra-view/`](https://demos.linkedtrust.us/abra-view/).
All work landed on `main`; no in-flight branches.

---

## What this is — the 90-second orientation

### Abra (this repo)

**A brain extension.** The map of what is important to a person, or
to a team. Pet names (`peter`, `ltq1`, `arige`) point at things
through typed *bindings*. *Catcodes* are positional coordinates in a
shared hierarchical information space (`a00101` = golda,
`a00104` = democracy, etc.). Hot tags + labels mark what's prominent
now. Content blobs hold the actual text behind a name.

Abra has two subsystems with a clean boundary inside one repo:

- **The map** (`impl/`): names, bindings, catcodes, content, labels,
  user_signal, user_config. Lives in Postgres via pgvector. Library +
  DB, not a service.
- **The view** (`view/`): the daily-drive UI. A stdlib `http.server`
  shim (`view/serve.py`) fronted by nginx at `demos.linkedtrust.us/abra-view/`.
  Reads the map; lets the user mutate via HTMX-driven write surfaces.
  This is what *you*, the view session, own end to end.

Abra is **open**: any system can write, every binding carries
`created_by`. Abra is **standalone**: it does not require amebo or any
other provider. Bindings can optionally publish out as LinkedClaims to
the trust web.

### Amebo (sibling repo, separate session)

**The friendly claw.** A loop runner. Owns *claws* (computational
units a Claude loop executes), events, digest, Q&A. Has its own DB,
its own OAuth, its own org model. Ships **web components**
(`amebo-claws`, `amebo-create-claw`, `amebo-digest`) as `embed/amebo.js`,
served from its backend. Hosted at `amebo.linkedtrust.us` (when wired)
or `127.0.0.1:8000` locally.

Amebo is **independently complete**: every claw works without abra
being reachable. Some claws may optionally read or write *context
stores* (per [`context-store-contract.md`](context-store-contract.md))
which abra happens to implement over `(scope, catcode)`. Amebo never
depends on those URLs being abra-shaped.

### LinkedTrust / LinkedClaims (further sibling)

Trust scoring + claim publication. Abra can publish bindings out as
LinkedClaims; LinkedTrust can return trust scores abra-side composition
might use. Not relevant for most view-session work; flagged for
completeness.

### Separation of concerns (the hard boundary)

Three repos, three sessions, three responsibilities:

| | Owns | Does not own |
|---|---|---|
| **abra** (view + map) | the map, the UI, view-side composition + scoring | loop behaviour, PII, task lifecycle, conversation threads, trust scoring |
| **amebo** | claws, events, OAuth, the user-facing intent loop | the map, identity registry, anything cross-provider |
| **LinkedTrust** | claim publication, trust scoring | both above |

Rules that hold both ways:

- **Abra never imports amebo. Amebo never imports abra.** They
  communicate via three contracts:
  [`component-contract.md`](component-contract.md) (provider components
  abra renders), [`capability-design.md`](capability-design.md)
  (per-(user, catcode) action enablement), and
  [`context-store-contract.md`](context-store-contract.md) (generic
  HTTP store for claws).
- **Web components ship cross-origin, Pattern B.** The view embeds
  amebo's bundle; the bundle calls amebo's API directly with
  `credentials: 'include'`. View does not proxy upstream APIs (the
  earlier `/abra-view/up/amebo/*` proxy was superseded by Pattern B,
  with one defensive exception: stripping empty query params on the
  way through).
- **abra is the store; the view never invents its own catalogs or
  registries.** Things the user "has" (installs, capabilities, signals)
  live in abra's data model, addressable from the view.
- **Per `OVERVIEW.md`'s Zero app noise rule**: every visible string in
  the view is user content or user-editable. No system-generated
  section headers, no developer-mental-model labels. This is the rule
  the previous session violated and got corrected on; bake it in.

### Where the view session fits

You own `view/` end to end:

- The shim (`view/serve.py`) that reads the map and serves HTML.
- The templates (`index.html`, `bindings.html`, `recent.html`,
  `cat.html`, `name.html`) and `style.css`, `edit.js`.
- The install / uninstall flow and the topnav.
- Catcode tree mutations + bindings list + recent feed.
- The integration points where amebo's bundle gets mounted on
  `/c/<inst>/`.

You do NOT touch:

- `impl/` — the data-models session owns DB schema, migrations,
  primitives. Coordinate via `scratch.md` if you need shape changes.
- The amebo repo — except when Golda explicitly asks you to leave a
  review or note on their docs.
- Other team members' home dirs or running services.

---

## What shipped this cycle

| Surface | Notes |
|---|---|
| Three-view topnav (Categories / Bindings / Recent) | On every page including `/c/<inst>/`. Wraps on mobile. |
| Per-catcode page `/cat/<code>/` | Voice-pasteable. No app-noise labels. |
| Per-name page `/names/<name>/` | Full page direct; htmx fragment via `HX-Request`. |
| Recent feed | Reverse-chrono; `<details>` per item with one-line excerpt; master collapse/expand; catcode subtree filter. |
| Component install / uninstall | Idempotent install POST; chooser greys out installed cards with a red minus to uninstall in place; install rolls back on writer-reject. |
| Drag-to-reorder bindings list | Edit-mode only; persists via `user_signal` `score_kind='long'`. |
| Edit mode | Single body class gates every write affordance. Per-binding × delete in item view. |
| Cache busting | Auto mtime-based `?v=<mtime>`; immutable cache on versioned assets; `no-store` on HTML. |
| Tintable component icons | CSS mask + `currentColor` so provider SVGs adopt the host theme. |
| Legacy contact cleanup | 283 deleted, 3919 promoted to `golda/contacts`, 1039 archived into `last-seen/<year>`. Democracy hoisted to `a00104`. |

---

## Durable docs to read first

In this repo (sibling files, all in `main`):

- [`OVERVIEW.md`](OVERVIEW.md) — the *Zero app noise rule* lives here. Every visible string is user content or user-editable. Memorise it.
- [`arch_notes.md`](arch_notes.md) — broader architecture, *Goals and claws*, *Context stores and claws* sections.
- [`component-contract.md`](component-contract.md) — provider component contract (catalog fields, install/render/uninstall flow, Pattern B).
- [`capability-design.md`](capability-design.md) — per-(user, catcode) item-action enablement (working draft).
- [`context-store-contract.md`](context-store-contract.md) — generic `<store_url>/entries` POST/GET for claws to record/read context.
- [`security-design.md`](security-design.md) — **next-session topic**. Attack surfaces ranked, layered defense sketched, open questions in §5. Pick one from §5 and drive it before code.
- [`user_stories.md`](user_stories.md) — Golda's verbatim stories. Read #2 (contacts/CRM) and #3 (goals/tasks) before touching capabilities or actions.

In `scratch.md` (cross-session coordination):

- View-session entries are under `## view session`. Newest on top.
- Amebo / data-models entries are above; durable contracts live in the docs, scratch is just pointers and in-flight notes.

In memory (`~/.claude/projects/-home-golda/memory/`):

- `feedback_no_app_noise.md` — the rule. No `<h2>Subcategories</h2>` style labels.
- `feedback_print_demo_link.md` — end every cycle with the live URL on its own line.
- `feedback_contracts_go_in_docs.md` — durable contracts go in repo docs, not scratch. Scratch points to docs.
- `feedback_no_assumptions.md` — verify with tools before stating as fact.
- `feedback_concise_communication.md` — single screen, one focused question at a time.
- `feedback_no_em_dashes.md` — applies to user-facing copy (press releases, public articles). Internal docs are flexible.

---

## Obvious next work items

### Now-shaped (small, well-scoped, unblock real value)

1. **Context store endpoint** at `/store/<scope>/<catcode>/entries` per [`context-store-contract.md`](context-store-contract.md). Two endpoints (POST + GET), backed by `content` + `bindings` writes under the configured catcode. Amebo's claws already hold `data-stores` URLs pointing here. Without this, the claw loop can't close.

2. **EXECUTES_VIA bindings rendered on a goal's item view.** When viewing a name with `EXECUTES_VIA` bindings (the connector to amebo claws), surface a small "claws attached" section showing claw status + a link to amebo's `/claws/<uuid>` page. Concrete example to test: `golda:share-marten-taiga-community` under `a00101050601`.

3. **Per-binding URL** `/bindings/<id>/` — for voice-paste-on-a-specific-row workflows. Today only names and catcodes are addressable; bindings need their own URL too. Trivial route + a `name_detail_html` linkifier change.

### Bigger-shaped (need a design beat before code)

4. **OAuth + scope ACL** per [`security-design.md`](security-design.md) §§3.1–3.2. Read §5 first, pick the open questions you want to drive. Probably one whole session on its own.

5. **`amebo-claws-attach` action component** wired into the per-item view per [`capability-design.md`](capability-design.md) §5. Needs the capability enablement UI from §4. Concrete user story: #3 in [`user_stories.md`](user_stories.md).

### Deferred (real but not yet)

- MEDIUMs from the code review in scratch: orphan-install rendering, silent delete feedback, hardcoded `_resolve_uri` schemes, `_proxify_script` registry-keyed instead of hostname.
- Signed catalog feed (so `components.yaml` doesn't need per-user SRI bookkeeping forever).
- Public-by-opt-in scopes (per `security-design.md` §5.8).

---

## How to orient

1. `git pull origin main` in `/opt/shared/repos/abra/`. Branch is `docs/overview`; cycle ends with a PR to `main` per the merged-PR cadence (this cycle landed PRs #1–#24).
2. View shim lives in `view/serve.py` (one file, stdlib only). Templates: `view/{index,bindings,recent,cat,name,recent}.html`. CSS: `view/style.css`. Edit JS: `view/edit.js`. Restart: kill the `serve.py` process, relaunch with `ABRA_VIEW_BASE=/abra-view ../impl/.venv/bin/python serve.py`. Nginx fronts it via `/etc/nginx/app-proxies/abra-view.conf`.
3. Read `scratch.md` top-down before writing — other sessions may have pinged you.
4. End every cycle: PR + merge to main, print the demo link.

---

**Live demo: https://demos.linkedtrust.us/abra-view/**
