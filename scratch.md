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

### → amebo, 2026-06-01: minimum to test Goal end-to-end

Golda wants to test. View will implement the picker form in
parallel. Smallest possible amebo asks, in this order:

**1. List endpoint** (blocks the picker; everything else is gravy):

```
GET /api/goals/?status=active
→ 200 [{"id": <int|string>, "title": "...", "status": "active"}, ...]
```

Auth: same as `/api/goals/{id}` (cookie via Pattern B). Empty
list is fine (returns []). Field names match the catalog block
already in `impl/components.yaml.example`:

```yaml
amebo-goal:
  pickers:
    data-path:
      source: "/api/goals/?status=active"
      label_field: "title"
      value_field: "id"
```

If `title` or `id` is named differently in your DB, either rename
in the response or update the catalog `label_field`/`value_field`
— either side is one-line.

**2. Confirm `<amebo-goal data-path="<real-id>">` renders something
useful.** View can install with a real id once (1) ships; if the
component just shows "Goal #42" with no title/status/last-event,
the install feels empty. Contract §2 lists what makes it feel
worth installing. Spot-check the bundle in `demo.html` against a
real id.

**3. Optional, visible:** ship `embed/icons/goal.svg` so the
topnav shows a goal icon instead of a generic cube. Skipping is
fine for the first test.

That's it. Ping back here when (1) lands.

**View's parallel work** (not blocking you): wire
`pickers`-driven form into the chooser modal. When the user picks
"Goal", view fetches `${script_origin}/api/goals/?status=active`
through the existing `/up/amebo/` proxy, renders a `<select>`,
collects the chosen id, POSTs `tag=amebo-goal&data-path=<id>` to
`/components/install`. The boundary holds.

### Open need: better cross-session sockets (2026-06-01)

Coordination today is file-based (scratch.md + git pull). Sessions
only see each other's work when they pull. Saw this concretely
when the contract doc landed and amebo session hadn't picked it
up because they were heads-down on coding-orchestration.

What we need: a real-time push channel so sessions notify each
other when something lands. Could be amebo's job since it already
runs as a service with auth, channels, threads. Likely fits in
amebo's design as a new channel type or a small pub/sub surface,
but not designing it now. Logging the need.

Not blocking current work. Pickers + icons land via the current
file-based flow when amebo gets to it.

### Shipped this cycle (PR #1, merged to main, 2026-06-01)

- Install creates a topnav icon (catalog `icon` with FA-cube fallback) →
  click opens a full-bleed `/c/<inst>/` page.
- Chooser modal closes on success via OOB swap.
- Per-component page has a red Delete button in a danger-zone that
  confirms + redirects home.
- `+` (add top-level catcode) moved into the topnav.

Live at `https://demos.linkedtrust.us/abra-view/`.

### → amebo session, 2026-06-01: contract for making Goal useful

Wrote it up properly. The **contract** for installing and rendering
provider components lives in [`component-contract.md`](component-contract.md)
— that's the source of truth, including the three picker mechanisms
(`prompts` / `pickers` / `picker_tag`), the render-contract
expectations, and the install/uninstall flow.

For Goal specifically, what amebo needs to provide:

- **A list endpoint** for the install-time picker. View recommends
  `pickers` (§3 in the contract). For amebo-goal this is
  `GET /api/goals/?status=active` returning `[{id, title, status, ...}]`.
  See the updated `impl/components.yaml.example` for the catalog
  block to add.
- **A useful render** of `/api/goals/{id}` inside the bundle. The
  contract §2 lists what makes a component feel useful at a glance
  (title, status, last activity, next run, action affordances,
  recent events). View won't enforce this, but a thin render makes
  the install feel broken even when wiring works.
- **Icons**: `embed/icons/goal.svg` and `embed/icons/digest.svg`
  both 404. View falls back to a generic FA cube. Ship them or
  switch the catalog to FA classes.
- **Error handling** inside the bundle when `/api/goals/{bad-id}`
  returns 4xx (contract §2).

View's follow-on work (separate, doesn't block amebo): wire
`pickers` form rendering into the chooser modal, multi-attr collect
on install POST.

`impl/components.yaml.example` updated with a populated
`amebo-goal` entry showing the recommended `pickers` block. Copy
that into your dev `~/.abra/components.yaml` when ready to test.

---

## amebo session

(Owns amebo repo: embed bundle, backend APIs, OAuth.)

---
</content>
