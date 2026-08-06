# Goals component — design note

Author: golda + claude (session 2026-06-05)
Status: design sketch. Not built. Other sessions please leave a
note inline if you want to push back before this gets implemented.

## What we want

Two stacked things, not one:

1. **A storage convention** for monthly goals in abra. Where they
   live in the catcode tree, how the pet name is shaped, how each
   goal's blob references other things in the map (CRM contacts,
   repo paths, server resources) via URI rather than copying.
2. **A goals-list web component** that reads the convention,
   follows the URIs out, and shows a live status per goal pulled
   from where the goal actually lives (repo state, CRM activity,
   task tracker status).

These can be designed and shipped separately. (1) is the durable
shape; (2) sits on top.

## Why both

The first `<amebo-create-goal>` slice (shipped 2026-06-01) handles
*one* free-text capture at a time. It doesn't know:

- where in the catcode tree the goal belongs by month
- that "marten" is the team's Taiga fork + local task tracker
- that a goal's context should resolve out to the repo, the CRM
  contact, the project doc

So today's component is a thought-placer, not a goals dashboard.
We want a real goals surface that does both: capture and review.

## Part 1 — storage convention

### Catcode placement

Goals live at a **calendar-shaped catcode** under the user's tree.
For golda, monthly goals for June 2026 sit under:

    a001 / golda / 2026 / 06 / goals

Concrete catcodes get assigned in the registry as you go (positional,
not semantic — see `arch_notes.md`). A new month opens a new node.

A goal pet name is the slug: `golda/2026-06/decode-trust-hire-repo`
or `2026-06-goal-decode-trust-hire-repo`. Pick one shape and stick
to it — proposing the second because abra's `name` field is flat
and slashes inside the name complicate URL routing in the view.

**Open: pick the shape.** Vote: `2026-06-goal-<slug>` keeps it flat,
sortable, prefix-searchable.

### Bindings per goal

For each goal name, the standard binding set:

| rel       | target                                  | qualifier        | permanence |
|-----------|------------------------------------------|------------------|------------|
| `IS`      | short title (text)                       | —                | INTRINSIC  |
| `ABOUT`   | content blob id (full context)           | `intent`         | CURRENT    |
| `HAS`     | catcode `a001...goals` (the month node)  | `catcode`        | INTRINSIC  |
| `RELATED` | `crm:odoo/contact/<id>`                  | `who`            | CURRENT    |
| `RELATED` | `git:Cooperation-org/<repo>/path`        | `repo`           | CURRENT    |
| `RELATED` | `tasks:taiga/issue/<n>` (= marten)       | `tracker`        | CURRENT    |
| `RELATED` | other pet names (e.g. `marten`, `mtc`)   | `project`        | CURRENT    |
| `RUN_BY`  | `amebo:claw/<goal-uuid>` (if clawable)   | —                | CURRENT    |
| label     | `goal`                                   | (unified labels) | —          |
| label     | `2026-06` (the period)                   | (unified labels) | EPHEMERAL  |

The point: the goal name *carries* its month, its context, and its
outward references. The content blob doesn't have to repeat any of
that — readers (and the component) resolve URIs as they render.

### URI schemes the component needs to resolve

- `crm:odoo/contact/<id>` — CRM contact (Odoo). Returns name + last
  activity.
- `git:<org>/<repo>` or `git:<org>/<repo>/<path>` — repo state.
  Returns last commit, last touched-by-claude tag, open PR count.
- `tasks:taiga/issue/<n>` — marten (our Taiga fork). Returns title +
  status. **abra needs to know "marten" is the team's term for the
  Taiga fork** — this belongs in `~/.abra/sources.yaml` as a
  scheme alias: `tasks:` → `marten.linkedtrust.us`.
- `name:<scope>/<name>` — another abra name. Resolves to its IS or
  most-recent ABOUT.

The component doesn't hard-code these. It asks the view (or amebo)
to resolve a URI; the view consults `sources.yaml`.

### Short-name resolution (aliases)

The user types "marten" and means "our Taiga fork + local task
tracker." abra already has the primitive: a pet name with IS-binding
to a content blob that names what it is. Today amebo doesn't read
abra's pet-name vocabulary into its context window.

**Two ways to close that gap:**

- **A.** Amebo, when interpreting voice/Slack input for goals,
  fetches the user's top ~50 pet names + their IS-bindings as
  context. (Like `_existing_names` in `intentions_service.py`
  does today, but enriched with what each name *is*.)
- **B.** abra exposes a `/resolve?term=marten` endpoint that
  returns "Taiga fork (marten.linkedtrust.us)" — amebo calls it
  when it sees an unknown term.

Recommend A (cheap, already partially built). B is a future surface.

## Part 2 — goals-list web component

Working name: `<amebo-goals-month>` (or just expand `<amebo-goals>`
with a `data-period` attr).

### What it shows

A list of goals for a period (default: current month). Each row:

- title (from IS-binding)
- one-line context teaser (from the ABOUT blob's first sentence)
- status pulled live from the strongest external reference:
  - if `tasks:taiga` ref → task status from marten
  - else if `git:` ref → last commit date + open PR for that path
  - else if `crm:odoo` ref → last activity date
  - else "no live status" (only abra-side data)
- last-touched date (max of all live sources)
- if clawable: the next-scheduled run from the amebo goal

### How it fetches

Per Pattern B (see `arch_notes.md` and `component-contract.md`):
the component talks directly to amebo cross-origin, not through
the view as a proxy. Today's deployment uses the proxy because
shared OAuth isn't built (see `~/work/6-1-2026-abra-amebo-cleanup.md`
items 1 and 2). The component should be written *for* Pattern B —
it'll work through the proxy today and through direct cross-origin
once OAuth lands.

### New backend route

`GET /api/goals/period?period=2026-06&scope=golda` on amebo.

Pipeline inside amebo:
1. Read abra: names in scope with label `goal` AND label `2026-06`
   (or whose HAS:catcode binding sits under `a001/golda/2026/06`).
2. For each, pull bindings.
3. Resolve external URIs in parallel: marten (Taiga API), git (gh
   CLI or GitHub API), Odoo (odoo-cli or XML-RPC).
4. Sort by last-touched desc.
5. Return one JSON list with everything the component needs to
   render without further round-trips.

This is roughly the shape of `digest`, but goal-shaped and
period-scoped. Could share the underlying resolver code with digest.

### Voice + Slack + Claude Code parity

The same goal data should be reachable three ways:

- **Voice → Claude Code → abra.** Write the goal directly with
  AbraWriter (the cross-repo path from intentions_service.py works
  for this). Use the storage convention above.
- **Slack → amebo.** `goals` slash-command lists current month;
  free text creates one (`<amebo-create-goal>` logic, reused).
- **Web component.** Read-only today. Adding inline edit + commit
  later is straightforward.

All three end up at the same abra rows. No duplication.

## Open questions

1. **Pet-name shape:** `2026-06-goal-<slug>` vs `<slug>` with bindings
   carrying the period. Recommend the former.
2. **Period label semantics:** `2026-06` as a label (current sketch)
   vs as a catcode prefix only (no label). Recommend both — label
   is cheap to filter on, catcode is the durable spatial position.
3. **Which sources.yaml change for marten:** new scheme `marten:` vs
   keeping `tasks:taiga` and aliasing `marten` as a name. Recommend
   the second: `marten` is a *pet name* for the tracker, not a new
   scheme.
4. **Resolver placement:** amebo-side (one route does the work) vs
   per-source connectors abra-side. Recommend amebo for v0 — it's
   already where the digest-style aggregation lives.
5. **Bundle delivery:** add to existing `embed/amebo.js` (already
   exports five elements) vs ship a second bundle. Recommend the
   first until the bundle hits some real size limit.

## Dependencies on the cleanup punch list

(`~/work/6-1-2026-abra-amebo-cleanup.md`)

- **#1a (real OAuth on view):** not a hard block. The component runs
  through the existing proxy today; the JWT gets minted from
  `DEV_USER` env. Same caveat as every other component.
- **#1b (route view writes through AbraWriter):** doesn't touch goal
  creation. Skippable.
- **#3 (package AbraWriter):** voice → Claude Code → AbraWriter path
  uses the sys.path hack today. Works on this VM. Worth doing
  before this gets reused on a different VM.

So this can ship without the cleanup landing. Just don't pretend the
auth is real.

## Dependency on `security-design.md`

The bigger plan for #1a lives in
[`../security-design.md`](../security-design.md) (working draft).
Goals can ship in the env-fallback window (its §7 step 2) without
waiting for the security migration. **One thing to pin before
writing any goals:** §5.1 (identity URI shape). Every goal row
gets a `created_by`. If we write them as `urn:abra:local:golda`
today and switch to `urn:abra:google/<sub>` later, we backfill.
Pick the canonical URI shape once, use it for every goal write
from now on, and the security migration becomes a pure ACL +
session change instead of also being a data rewrite.

## Suggested order to build

1. Pet-name shape + sources.yaml alias for marten. Smallest possible
   PR. Lets voice/Claude Code start writing real monthly goals today.
2. Backend route `/api/goals/period`. Just abra reads first, no
   external resolution. Lets the component render *something*.
3. Add the external-URI resolvers one at a time: marten first
   (highest signal), then git, then Odoo.
4. The web component. Initially read-only, no inline edit.
5. Wire Slack list/create commands to the same data.

Steps 1 + 2 can be one session. Steps 3–5 are sequential.

---

## For other sessions

This is a plan, not code. Push back inline if you disagree with the
storage shape — the rest of this design rests on it. Concrete
disagreements: edit this section in your own commit, not anyone
else's.

(view session) — your install/render path already handles this
component shape (whole-feature-tab install, scheme-agnostic). No
new view-side work expected unless you want a smarter empty-state
or period switcher.

(backend session) — when the real abra backend HTTP surface lands,
`/api/goals/period` can move there instead of living in amebo. For
now amebo is fine because it already does external-URI resolution
for digest.
