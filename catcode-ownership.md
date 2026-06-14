# Catcode Ownership — data scoping for abra

> Working design. Companion to [`security-design.md`](security-design.md) (threat
> model) and [`capability-design.md`](capability-design.md) (per-(user,catcode)
> *action* enablement). This doc is about **read/write data isolation**: who can
> see and change which content, enforced at the catcode level.

## Problem

`security-design.md` §2.1–2.2 names the top risk: **there is no enforced data
isolation.** Today isolation is only by `scope` (`golda`, `linkedtrust`, `amebo`,
`claude`, …) and *nothing checks it* — `amebo_writer` reads and writes every
scope. So a public demo instance (e.g. changemaker) searching the knowledge base
could surface another org's private notes, and a compromised writer URI could
write into any scope.

We want **per-org / per-principal data scoping** with no cross-org leak, and we
want it to be a *guarantee*, not a convention.

## Why catcodes

Catcodes are already a hierarchical, filesystem-like tree
(`a00101=golda`, `a00103=linkedtrust`, `a002=amebo`…), and **every binding and
content row already carries `catcode` + `catcodes[]` + `created_by`.** So the
data hooks exist; we add ownership to the tree and enforce it. The mental model
is unix: **catcode = directory, binding/content = file, ownership = principal,
mode = rwx.**

## Model

### Principals

A principal is a URI naming who is acting:

- `scope:<name>` — a scope (`scope:linkedtrust`)
- `org:<id>` — an amebo org (`org:1`)
- `user:<name>` — an individual (`user:golda`)
- `amebo:<team>` — amebo's service identity for a team (background/claw work)

The principal is **supplied per call** by the caller (amebo passes its per-turn
org/user identity — the same identity resolved by the auth/credential layer).
This replaces the global `SCOPE` env and the god `amebo_writer` role for
user-facing reads/writes.

### Ownership on the tree

`catcode_registry` gains:

| Column  | Meaning |
|---|---|
| `owner` | principal URI that owns the node |
| `grp`   | optional group principal (membership defined out-of-band) |
| `mode`  | rwx triad — owner / group / other (e.g. `0o750`) |

**Inheritance:** a catcode with no explicit `owner`/`mode` inherits from its
nearest ancestor that has one (walk up `parent_catcode`). The root defaults to
`owner=system, mode=0o755` unless overridden. So you set ownership once on a
subtree and children follow, exactly like directory perms.

### Access rules

For principal **P** and catcode **C**, P's permission on C is the first triad
that matches: P is C's `owner` → owner bits; P ∈ C's `grp` → group bits; else
other bits. (Resolve `owner`/`mode` via inheritance if unset.)

- **Read / search:** P sees an item iff P can **read at least one** catcode the
  item is filed under (`catcode` or any of `catcodes[]`). Same as being able to
  reach a file through any directory you can read — supports legitimate
  multi-filing without leaking.
- **Write / store:** P may write/insert an item under catcode C iff P can
  **write** C. `created_by` is stamped with P. Filing an item under multiple
  catcodes requires write on **each** target.
- **Register catcode:** creating a child under C requires **write on C** (like
  `mkdir` needing write on the parent).

## Enforcement — two stages, RLS is the target

**v1 — application chokepoint.** abra's read/store paths (`impl/pgvector/query.py`
and the context-store API) take the principal and filter: join `catcode_registry`,
apply the access rules, return only readable rows; reject writes to
non-writable catcodes. Ships fast. **Caveat — this is policy, not a guarantee:**
anyone with the `abra_user`/`amebo_writer` DB password bypasses it entirely
(`security-design.md` §2.1). So v1 is a *staging step*, not the real isolation.

**v2 — Postgres Row-Level Security (the real enforcement).** RLS policies on
`bindings` and `content` keyed off a session GUC the connection sets per request:

```sql
SET LOCAL abra.principal = 'org:1';
-- policy (sketch): a row is visible iff the principal can read one of its catcodes
```

With RLS, the check runs **inside the database** — a god role is no longer a
god reader, and the leak is closed even against direct DB access. This requires:
the connection layer to `SET LOCAL abra.principal` from the authenticated
principal on every transaction; policies expressing the access rules (a SQL
function `can_read(principal, catcode)` walking inheritance); and dropping
`amebo_writer`'s blanket read in favour of RLS-gated access. v2 is what makes the
isolation real; v1 buys correctness of *behaviour* while v2 is built.

## Migration / backfill

- Backfill `owner` from the existing `scope`: `scope:<scope>` owns its catcodes,
  `mode=0o700` (private) by default.
- Mark genuinely shared trees (reference docs, the LinkedClaims spec, public
  demo knowledge) world-readable (`0o755`) deliberately — nothing becomes
  world-readable by accident.
- **Default-deny for new catcodes:** a freshly registered catcode is private to
  its creator's principal until explicitly opened. New = closed.

## Relationship to capability-design

`capability-design.md` governs which *item-actions* a (user, catcode) pair may
invoke in the view (the `cap.<catcode>.<tag>` model). That's an enablement/UI
layer **on top of** read access. This doc is the layer beneath it: whether the
principal can read/write the data at all. Capabilities should never grant an
action on a catcode the principal can't read.

## Open decisions (deferred, not blocking v1)

1. **Group membership** — where `grp` membership is defined (an abra table vs.
   amebo's org/team model). Start with owner+other; add groups when a real
   shared-but-not-public case appears.
2. **Principal granularity** — enforce at `org`/`scope` level first; `user`-level
   ownership within an org is a later refinement.
3. **Multi-catcode write atomicity** — if an item is filed under several catcodes
   and the writer lacks write on one, reject the whole write (no partial filing).
