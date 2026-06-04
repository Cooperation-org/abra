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

### amebo → abra access narrowed (2026-06-03)

Was: amebo backend connected to abra DB as `abra_user` (full access).
Now: new PG role `amebo_writer` — SELECT on all 7 tables, INSERT on
`content` + `bindings` only, no UPDATE/DELETE anywhere. Sequence usage
granted. Smoke-tested: read OK, insert OK, update/delete denied.

`/opt/shared/repos/amebo/backend/.env` `ABRA_DATABASE_URL` updated to
the new role. **Backend needs restart to pick it up** — see Stage B
below.

Other systems (CRM, Taiga) deferred per Golda — not enforcing on those
for now.

### amebo unix isolation — Stage A done, Stage B pending (2026-06-03)

Stage A (done, no service disruption):
- Created system user `amebo` (uid 997, nologin, home `/var/lib/amebo`).
- Created `/opt/amebo-readable/repos/` (root:amebo 750). amebo can read,
  cannot write. Smoke-tested: read OK, write/append denied.
- Cloned: `LinkedClaims`, `marten`, `site-linkedtrust-us` (Cooperation-org),
  `changemaker` (Whats-Cookin). Shallow clones; 24M total.
- `/usr/local/sbin/amebo-readable-pull` + `/etc/cron.d/amebo-readable`
  pulls daily at 04:17 as root. amebo cannot poison the checkouts.

Pending for Golda:
- **`trust-hire`** not found in Cooperation-org or Whats-Cookin. Org?
- **`projects`** = Cooperation-org/projects (private). Needs SSH key
  for a service account, or rsync from `/opt/shared/projects`. Pick.
- Bulk-clone the other ~86 public Cooperation-org repos? Some are big
  (e.g. CAMEL framework). Confirm before pulling all.

Stage B (done 2026-06-03):
- `amebo-backend.service` now runs as `User=amebo` (uid 997). Process
  confirmed: pid running as amebo, uvicorn :8000, scheduler started, no
  errors in journal.
- `/opt/shared/repos/amebo/backend/.env` chmod 640 (was world-readable
  644) + `setfacl u:amebo:r`. Owner stays golda:devteam.
- `slack_helper.log` is mode 666 (world-write) so amebo can append
  without changes. Ugly but not blocking — flag for later relocation
  to a proper log dir.
- `/opt/shared/projects` is world-readable so amebo sees it directly
  per Golda. Defensive ACL: `setfacl u:amebo:---` applied to
  `/opt/shared/projects/Active/due-diligence/.env` (amos's prod secret,
  was 664 world-readable). The underlying leak is amos's call to fix.
- Frontend (uses kene's nvm) + Bluesky bot stay on kene.

Pending from Golda:
- `trust-hire` and `projects` are private; both now cloned via per-repo
  deploy keys against `ssh.github.com:443` (port 22 firewalled outbound
  on this VM). Cron pull works for both.

### Goals vs claws contract (Golda 2026-06-04, voice)

Two senses of "goal":
- **Claw** (amebo): computational unit a Claude loop executes. Strict
  schema, lives in amebo's `goals` table. User-facing surfaces should
  say "claw" (component renames `amebo-goals` → `amebo-claws`,
  `amebo-create-goal` → `amebo-create-claw`). Internal table name is
  amebo's call.
- **Goal** (abra): user's conceptual goal as prose + bindings. Aimed at
  intelligent readers (humans + AI). No strict schema. May or may not
  have claws attached.
- **Connector**: abra binding `amebo:claw/<uuid>`, relationship
  `EXECUTES_VIA` (or similar). Zero, one, or many claws per goal.

Contract written into `arch_notes.md` → "Goals and claws" section, and
External systems list updated. That is the durable source.

For amebo session: the rename is yours. Internal `goals` table can
stay. Web component surface should switch to claws.

For view session: an abra-side `goals` component (renders her
conceptual goals from bindings) is a new thing, separate from amebo's
claws component.

Sidenote — amebo's `abra_*` mirror tables in the amebo DB have 1
binding and 10 content rows vs live abra at 15091 bindings and 5822
content. The mirror is broken or never wired. Likely should be retired
in favor of live reads via the new `amebo_writer` PG role. Flag for
amebo session.

### Architecture confirmed 2026-06-04: amebo standalone, abra linkage opt-in

Golda confirmed the asymmetry. Amebo claws are independently complete;
the abra goal linkage is opt-in from abra's side only. Hard constraint:
amebo never depends on abra. Final contract in `arch_notes.md` under
"Goals and claws" with the "Amebo is independently complete" paragraph
and the connector spec.

#### For amebo session
- Rename user-facing surface from `amebo-goals` / `amebo-create-goal`
  to `amebo-claws` / `amebo-create-claw`. Internal `goals` table can
  stay; that is amebo's own model.
- Drop or stop populating the `abra_*` mirror tables in the amebo DB.
  They're stale (10 content / 1 binding vs live 5822 / 15091).
- Where amebo wants to decorate a claw with "serves goal: X", query
  live abra via `amebo_writer` at render time. Bindings: `target_type='amebo'`
  `target_ref='amebo:claw/<claw-uuid>'`. When abra is unreachable or
  not configured, omit the decoration. Do not block claw operations.
- Amebo's claws table needs no abra-goal column and no FK. Standalone
  use must remain first-class.

#### Strict scope rule (Golda 2026-06-04)
Amebo knows about its own claws. Amebo's web components manage amebo
claws only. Amebo does NOT ship a component that renders abra goals.
Anything that shows abra goals (or cross-links goals to claws) is
rendered abra-side from a separate source. Keeping the layers clean.

#### For amebo session (component side)
- Rename `amebo-goals` web component to `amebo-claws`. Internal
  `goals` table can stay; the rename is user-facing.
- Rename `amebo-create-goal` to `amebo-create-claw`. Same flow, just
  the user-facing name.
- The component manages amebo claws end-to-end: list, create, edit,
  status. No abra-goal context anywhere in the amebo-shipped UI.
- Mirror retirement still applies: drop the `abra_*` tables in amebo's
  DB. They were a previous-direction artifact and are stale.

#### For someone (TBD) on the abra side, later
When showing abra goals with their attached claws, the renderer reads
abra directly for the goals (the prose, the EXECUTES_VIA bindings),
and embeds amebo-claws (or a simpler decorator) inline for each
attached claw. Pattern B: the renderer crosses origins; the user's
shared OAuth identity carries through. Not for this session.

#### For backend session (me)
- Done: the 8 initial goals exist in abra under catcode
  `a00101050601` (golda/2026/june/goals).
- Pending: when "simple claws" land, write the EXECUTES_VIA bindings on
  the abra side (amebo session's create-claw flow can write directly,
  or we can wire a small abra-side endpoint).
- Open question to Golda before I build anything component-shaped:
  whether to ship an interim render route at /abra-view/goals/ in the
  view shim so the goals are visible right now, or wait for the view
  session to build the proper goals web component.

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

### → amebo, 2026-06-04: capability design draft + claw decoupling

Working design for **capabilities** lives at
[`capability-design.md`](capability-design.md). A capability is the
per-user decision to enable an item-action web component on a
particular catcode, plus a small config slice. Catalog grows a
`kind: tab | action` field; storage is `user_config` keyed by
`cap.<catcode>.<action-tag>`.

For amebo-claws, two natural shapes (doc §5):

- `amebo-claws` stays as `kind: tab` (Claws list view, today's
  install pattern).
- `amebo-claws-attach` (new) as `kind: action` — verb on individual
  items under catcodes where the user enables it. Same bundle,
  separate catalog tag.

**Decoupling principle Golda flagged (2026-06-04, walking):** amebo
must work without abra. A claw could be created via Slack, CLI, or
a different UI; abra is just one possible creator + context source.
So the claw-create endpoint should accept a **generic context
payload** (a list of URIs + a short prose summary + the user's
intention), opaque to amebo. amebo stores it. If amebo wants to
enrich later, it may, but it must not require abra to be reachable.

Captured in `capability-design.md` §5 under "Decoupling principle
for action components." When you design the claw create-endpoint
shape, please target that generic payload — no
`abra:`-prefixed scheme assumptions, no synchronous abra lookups.

No code yet, no ask blocking you. Calling out so the claws work
you're doing keeps abra firmly optional.

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

**2026-06-04: consolidated into backend session.** Prior amebo session
broke and stopped getting input. Golda transferred ownership to the
backend (abra) session. Single session now drives both abra-side and
amebo-side work for this thread.

### In progress here: rename amebo-goals → amebo-claws

Per the strict scope rule above, amebo's web components manage amebo
claws only. The component currently called `amebo-goals` becomes
`amebo-claws`. The flow currently called `amebo-create-goal` becomes
`amebo-create-claw`. Internal `goals` table can stay (amebo's own
model). No abra context anywhere in the amebo-shipped UI.

---
</content>
