# Three Systems

A conceptual overview of the three systems we are building, what each
one is, and how they compose. Written for humans first (a session or a
person can pick this up cold).

For detail on any one piece, follow the links to its own docs. This
file stays short on purpose.

---

## The trinity

Three independent services, each doing one thing well.

- **Abra** — *what is important to me (or my team).* The map.
- **Amebo** — *what gets done.* The friendly claw with hands.
- **LinkedTrust** — *who or what to trust.* A query endpoint.

Each works alone. Together they cover the three durable questions a
person or team has about their world:

> *Who and what do I care about? Who do I trust? What should be done?*

Abra answers the first. LinkedTrust answers the second. Amebo turns
the first two into action.

They use each other; sometimes they publish to each other. None of
them owns the others. They compose.

---

## Abra — the map of what's important

Abra is *a brain extension*. It is the durable map of what a person
(or a team) cares about — the names they think with, the
relationships, the things marked as hot, the blobs of recorded memory,
and pointers to where the rest of their world lives (git repos, CRM
records, task tracker tickets).

**The person's contract.** A person never has to learn abra's
taxonomy. They use their own pet names: *my son, the Tuesday writing
group, that thing I'm noodling on, MTC, ltq1*. The system maps to the
way they think. They never get asked "is this an organization or a
community?" — those distinctions, where they matter, are inferred by
agents reading the map. The user only sees their own words.

**What abra holds.**

- Pet names in a scope (a person's, or a team's)
- Bindings — typed edges from a name to a thing (`IS`, `HAS`, `ABOUT`,
  `RELATED`, `SAME_AS`, plus an open set of labels that emerge)
- Catcodes — positions in a shared spatial information space
- Hot tags — the person's own sense of what is prominent right now
- Content blobs — recorded memory, searchable via embeddings
- Pointers to external things — `crm:odoo/contact/12345`,
  `tasks:taiga/issue/789`, git repo paths

**What abra doesn't do.** Run loops. Take actions. Hold opinions.
Watch over time. It just *is* the person's map.

**Multi-writer with provenance.** Abra is open: any system (amebo,
another claw, the user directly via CLI, an importer) can write into
it, and every binding carries who-wrote-it and when. The map can hold
disagreements — two systems can write conflicting bindings; both
remain visible with their provenance.

**Optional publish out.** A binding can optionally be published to the
world as a LinkedClaim — a signed, portable attestation. Not every
binding becomes a claim. The person or system decides what to share.

**Detail docs:** `concept-notes.md` (vision), `arch_notes.md`
(architecture), `binding-format-v0.1.md` (data spec), `impl/CLAUDE.md`
(reference implementation).

---

## Amebo — the friendly claw

Amebo is the agent layer. It receives events, decides what they mean,
takes action, and emits events. It is the loop.

**The contract.** Amebo acts *for* a person or *for* an organization,
in conversation, with explicit consent. Its job is to be a helpful
friend with hands — not the boss, not the center. It is one friend
among several the user can call on.

**What amebo has.**

- A loop — receive → think → decide → act → emit event
- Conversation/processing threads (working memory during a task)
- Tool access and credentials per person and per org (OAuth, API keys,
  encrypted at rest)
- An event log of what it did
- Skills — composable behaviors loaded as needed
- Connection to abra (to know who it helps) and to LinkedTrust (to
  decide who to trust)

**What amebo doesn't hold.** The person's identity. The person's map.
The person's history of what matters. Those belong to abra. Amebo's
own state is transient — conversation threads decay, events GC out
unless they are consolidated into abra by the emotion signal (what
the person, or amebo's own judgement, marks as important).

**Decoupled from abra.** Amebo works without abra — it just becomes
less personal. With abra, it knows who it's helping and can write back
what it learns. Without abra, it still runs loops and takes actions
using its skills and tools.

**Detail docs:** in the `amebo` repo — `docs/ARCHITECTURE.md`,
`docs/ORGS_GOALS_CLAW.md`, `docs/POWERS_PLAN.md`,
`docs/SELF_FRIENDS_HOME.md`, `docs/HERMES_PATTERNS_AND_GAPS.md`.

---

## LinkedTrust — the trust endpoint

LinkedTrust is a query endpoint. You give it a URI (a person, an org,
a resource) and it gives you a trust score *relative to you*. The
score reflects whether you would trust them, based on the web of
attestations from sources you trust.

**The contract.** Simple in, simple out. The complexity behind the
endpoint — the LinkedClaims web, signed attestations, trust policy,
graph traversal — is encapsulated. Consumers don't need to understand
it.

**What LinkedTrust does.** Scores. It does not decide. The agent or
person asking the question decides what to do with the score.

**Two-way flows.**

- *Read:* amebo (and any other agent) queries LinkedTrust before
  acting on a non-trivial claim ("should I act on this email? trust
  this contact? rely on this source?").
- *Write:* abra (and any other publisher) can optionally push a
  binding out as a LinkedClaim, contributing to the web.

**When it matters.** Trust-mediated decisions, mostly on amebo's
side. Reputation surfacing in the canvas. Verification of attestations
about people, orgs, contributions, credentials. The full role grows
over time; we keep the door open architecturally now.

**Detail docs:** in the LinkedClaims repo and at
`live.linkedtrust.us`.

---

## How they compose

```
   [ Abra ]                [ Amebo ]                [ LinkedTrust ]
   what's important        the friendly             the trust
   to me (or us)           claw with hands          endpoint
   (the map)               (the loop)               (URI -> score)
        |                       |                         |
        |   reads to            |   asks before           |
        |   know who            |   trusting              |
        +---------------------->+------------------------>+
        |                       |                         |
        |    consolidates       |     publishes out       |
        |    when emotion       |     as LinkedClaim      |
        |    fires              |     (optional)          |
        |<----------------------+                         |
        |                       |                         |
        +-------- publish out as LinkedClaim (optional) ->+
```

Three independent services, three flows of use:

1. **Amebo reads abra** to understand who it is helping.
2. **Amebo asks LinkedTrust** before acting on something that requires
   trust judgement.
3. **Amebo writes back to abra** when something matters enough to
   become part of the durable map (the emotion signal as the
   gatekeeper — the GC rule).
4. **Abra optionally publishes** bindings out as LinkedClaims when
   the person or system decides to share with the world.

### The canvas (the user-facing view)

The user-facing canvas — the "home" view, however a person wants to
arrange it (Pinterest-like, calendar grid, journal, map, daily
digest) — **belongs to abra**. It is the visual face of abra's map:
hot tags rendered, bindings shown, relationships made visible.

Amebo and other friends *contribute overlays* to the canvas — "this is
in progress", "this needs your attention", "amebo finished this for
you" — but they don't own it. The canvas still renders even when
amebo is not running. You always have your map.

### Things outside the trinity

The three systems do not try to replace what already exists. Each
person or team has external systems that already work — a CRM holds
contact details, a task tracker holds tasks and due dates, a git repo
holds the mutating text blobs (skills, plans, project proposals)
read by both humans and agents. The trinity *points to* and *talks
with* those systems. It does not duplicate them.

---

## Why it's three

We deliberately split this way:

- **One thing for being you** (abra). Durable. No agency. Just *is*.
- **One thing for doing things** (amebo). Has agency. No identity.
  Just *acts*.
- **One thing for trust judgement** (LinkedTrust). No agency, no
  identity. Just *answers*.

Mixing these creates the messes we want to avoid: an agent that
thinks it is you, a map that takes actions you didn't ask for, a trust
system that imposes its own decisions.

Keeping them separate keeps each one simple and lets the user (or
their team) swap any of them. You could use a different claw than
amebo and keep your abra map. You could use a different trust system
and keep both. You could maintain your abra map without using any
agent at all.
