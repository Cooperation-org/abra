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

### → amebo, 2026-06-01: contract rewritten — pickers gone

Golda reframed the model. The install-time picker design (collect
data-path before install) was wrong. **Whole-feature-tab installs
only** in v0: amebo-digest, amebo-goals, amebo-create-goal all
install with no item picked. Singular-item components (one
specific goal as its own tab) deferred until item-context
activation lands.

Erased from this scratch + the contract: the picker mechanisms
(`prompts` / `pickers` / `picker_tag`), the list-endpoint ask,
the `amebo-goal` (singular) catalog entry. See
[`component-contract.md`](component-contract.md) §1 + §3 for the
new shape (§3 is now a forward-looking placeholder, not a spec).

Still relevant for amebo:

- **`amebo-goals` (plural) is the primary Goals install.** Already
  working end-to-end against `/api/goals/?status=&limit=`. Golda
  installed and confirmed it renders.
- **Useful render** still matters per contract §2. If the Goals
  list bundle ever feels thin, see §2.
- **Icons**: `embed/icons/goals.svg`, `embed/icons/digest.svg`,
  `embed/icons/create-goal.svg` all 404. FA-cube fallback works
  but is uniform; topnav can't distinguish tabs visually.

No amebo asks blocking view today.

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

Not blocking current work. Whatever lands lands via the current
file-based flow when sessions get to it.

### Shipped this cycle (PR #1, merged to main, 2026-06-01)

- Install creates a topnav icon (catalog `icon` with FA-cube fallback) →
  click opens a full-bleed `/c/<inst>/` page.
- Chooser modal closes on success via OOB swap.
- Per-component page has a red Delete button in a danger-zone that
  confirms + redirects home.
- `+` (add top-level catcode) moved into the topnav.

Live at `https://demos.linkedtrust.us/abra-view/`.

### → amebo session, 2026-06-01: contract pointer (superseded)

Originally described picker mechanisms; superseded by the
"contract rewritten — pickers gone" entry above. The contract
spec at [`component-contract.md`](component-contract.md) is the
durable source of truth.

---

## amebo session

(Owns amebo repo: embed bundle, backend APIs, OAuth.)

---
</content>
