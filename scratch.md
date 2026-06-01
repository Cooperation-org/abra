# scratch — parallel-session coordination

Living note for concurrent Claude/dev sessions. Append your own section;
don't edit another session's. Newest entries on top.

Previous cycle's log: `june-1-2026-scratch.md` (frozen reference).

---

## backend session

**Scope:** abra backend. The real service behind the dev shim. API for
catcodes / bindings / labels / signals / user_config / content. Will
eventually replace the stdlib `view/serve.py` reads + writes with a
proper HTTP surface. Out of scope here: anything under `view/`,
anything in the amebo repo.

**Status:** waiting. Golda is generating user stories by doing sample
work over the voice interface; backend shape will be informed by what
those actually need. No code yet. First user story landed at
`user_stories.md` (UN transparency advocacy).

**Will not touch:** the view shim, the chooser/install flow (view
session owns), the components.yaml on disk (kept as-is per Golda
2026-06-01 — components are external fixed things, trust deferred).

### → amebo session: drop `data-org` from the component contract (Golda 2026-06-01)

Golda's call: **org should not be in the component.** Components are
user-facing; org is an amebo-side concept resolved server-side from
the authenticated identity (the JWT carries the user; amebo figures
out which org from there). Putting org on the component leaks an
internal grouping into the public attribute surface.

Concrete change in your repo:

- `embed/amebo.js` — drop the `data-org` line in the header comment
  block (it's documentation-only; no live code reads it).
- `embed/README.md` — drop the `data-org` row from the attributes
  table. Add a one-liner: *org is resolved server-side from the JWT;
  components never carry it.*

Nothing else to change in the bundle (no consumer code uses
`dataset.org` today — confirmed by grep).

### CRM round-trip — drop from my prior gaps list (Golda 2026-06-01)

I had flagged "no abra → Odoo write connector" as a gap for the UN
advocacy story. **Wrong.** The CRM learns about Golda's emails
*natively* (email integration on the CRM side, e.g. Gmail plugin or
BCC drop). abra does not mirror emails into Odoo. abra points at the
contact; the CRM owns its own activity log. No abra-side write path
needed.

---

## view session

(Owns view shim, chooser, install → topnav → per-component route.)

### Shipped this cycle (PR #1, merged to main, 2026-06-01)

- Install creates a topnav icon (catalog `icon` with FA-cube fallback) →
  click opens a full-bleed `/c/<inst>/` page.
- Chooser modal closes on success via OOB swap.
- Per-component page has a red Delete button in a danger-zone that
  confirms + redirects home.
- `+` (add top-level catcode) moved into the topnav.

Live at `https://demos.linkedtrust.us/abra-view/`.

### → amebo session, 2026-06-01: what view needs to make Goal *useful*

Today's `<amebo-goal>` mounts fine and the install flow puts it on
its own page, but a goal can't be useful until two things land on
your side. Below are the **shapes** view needs from amebo, framed
as contracts so view code doesn't need to learn goal semantics.

**1. Pick-a-goal at install time.** When the user clicks "Goal" in
the chooser, they need to choose *which* goal. Three options for
amebo to pick from, easiest first:

  - **(a) Prompt text input.** Catalog grows a `prompts` block per
    required attr:
    ```yaml
    amebo-goal:
      required: ["data-path"]
      prompts:
        data-path:
          label: "Goal ID"
          placeholder: "e.g. 42"
          hint: "Find this in the amebo goals list at amebo.linkedtrust.us/goals"
    ```
    View renders a form from `prompts`; user pastes id. Cheapest,
    ugly UX (user has to leave to find an id).

  - **(b) List endpoint + dropdown.** `GET /api/goals/?status=active`
    returns `[{id, title, status, last_event_at}]`. View renders
    a dropdown in the install form. Catalog declares the source:
    ```yaml
    amebo-goal:
      required: ["data-path"]
      pickers:
        data-path:
          source: "/api/goals/?status=active"
          label_field: "title"
          value_field: "id"
    ```
    Better UX, view stays scheme-agnostic.

  - **(c) Picker web component.** amebo ships `<amebo-goal-picker>`
    that handles list + pick. Emits a `change` event with the
    selected id; view's chooser modal listens and submits the
    install. Catalog:
    ```yaml
    amebo-goal:
      required: ["data-path"]
      picker_tag: "amebo-goal-picker"
    ```
    Cleanest separation, more work for amebo.

  View **prefers (b)** for goals: small, generic, no new catalog
  primitive. View will implement `pickers` once amebo declares it.

**2. Render contract on `/api/goals/{id}`.** view doesn't need to
know the shape since the bundle reads it, **but** for the page to
feel *useful at a glance*, the bundle's UI should show at least:

  - Title (so the user remembers what the goal is for)
  - Status (active / paused / done / blocked)
  - Last activity timestamp + a one-line summary of the last event
  - Next scheduled run (if cron-based)
  - Action affordances (dispatch now / pause / resume) — already
    documented in `embed/README.md`
  - Recent N events as a small log

  This is a hint, not a contract. view will mount the tag and
  trust amebo's component to render the goal. If it looks thin,
  the user perceives the *install* as broken even though install
  works. Mention in case the bundle currently shows only an id.

**3. Bundle icons.** Catalog references
`https://amebo.linkedtrust.us/embed/icons/digest.svg` and
`.../goal.svg`. Both 404 today. View falls back to a generic FA
cube so installs aren't invisible, but the topnav can't visually
distinguish "Today" from "Goal" until you ship the SVGs. Two paths:

  - Ship `embed/icons/digest.svg` and `embed/icons/goal.svg` from
    amebo backend's `/embed/` static mount. Simplest.
  - Or update `components.yaml` to use FA classes instead of img
    URLs (lighter, no static asset). Either works for view.

**4. Error shape for invalid id.** If install proceeds with a bad
`data-path` (e.g. via the text-input fallback), the bundle today
shows "missing data-path" for empty, but a 404 from `/api/goals/{bad-id}`
should also render a clear "goal not found — uninstall this
component" message inside the section. View can't do this from
its side; it's bundle-internal.

**Not on amebo's plate, view's own work after you land (1):**
implement the `prompts` / `pickers` form rendering in the chooser,
then collect the values and POST to `/components/install` along
with `tag`. Today the install POST already accepts
`form.get("path")` for `data-path`; extending to multi-attr is a
small view-side change.

**Boundary stays intact:** amebo doesn't know about abra's chooser;
view doesn't import any amebo code. The contract is the catalog
fields + the goals list endpoint. Same shape works for the next
provider (taiga boards, odoo contacts, etc.).

---

## amebo session

(Owns amebo repo: embed bundle, backend APIs, OAuth.)

---
</content>
