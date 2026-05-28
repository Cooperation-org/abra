# Abra — Overview

A one-page introduction. For detail, see `concept-notes.md`,
`arch_notes.md`, `binding-format-v0.1.md`, and `impl/CLAUDE.md`.

---

## What abra is

Abra is the map of what is important and what is known about a
person — or about a team. The names they use, the things they care
about, the relationships, the blobs of recorded memory, and the
pointers to where the rest of their world lives (a CRM, a task tracker,
a git repo, a calendar).

It is a *brain extension*. Names are the handles. *To name something
is to have power over it.*

## The person's contract

A person never has to learn abra's taxonomy. They use their own pet
names: *my son, the Tuesday writing group, MTC, ltq1, that thing I'm
noodling on*. Abra maps to the way they think, not the other way
around. They are never asked to classify a name into a system
category. Those distinctions, where they matter, are inferred by
agents reading the map.

The user's surface is just names and their own sense of what is hot.

## What abra holds

- **Pet names** in a scope — a person's namespace, or a team's
- **Bindings** — typed edges from a name to a thing (`IS`, `HAS`,
  `ABOUT`, `RELATED`, `SAME_AS`, plus an open set of labels that
  emerge from use)
- **Catcodes** — positions in a shared spatial information space
- **Hot tags** — the person's own sense of what is prominent right now
- **Content blobs** — recorded memory, searchable via embeddings
- **Pointers to external** — CRM records, task tracker tickets, git
  repo paths, files, URIs

## What abra doesn't do

Run loops. Take actions. Hold opinions. Watch over time. Abra just
*is* the map.

## Multi-writer with provenance

Abra is open. Any system — a claw (like amebo), an importer, the user
typing on the CLI, a future agent — can write into it. Every binding
carries who wrote it and when. The map can hold disagreements: two
systems can write conflicting bindings; both stay, both visible with
their provenance.

## Optional publish out

A binding can optionally be published to the world as a LinkedClaim —
a signed, portable attestation. Not every binding becomes a claim.
The person, or the system writing the binding, decides what to share.

---

## The view (the canvas)

Abra is the map. The **view** is a separate thing that *leans on* the
map but is not itself the map. It is the user-facing canvas — the
visual face of what abra holds.

How a person arranges their view is up to them. For some, it looks
like a Pinterest board of pinned people and projects. For others,
a calendar grid. For others, a journal of recent activity. For others,
a daily digest by email and they never open a canvas at all. The
shape follows the person, who can rearrange verbally ("show me my MTC
stuff bigger", "make the right side photos of people I've talked to
recently", "give me a unified feed of everything from Slack and email
and Discord this week").

The view lives in abra, because it is the face of the person's map.

## Components

The view is built from components. A component is a small, pluggable
widget that pulls from abra (and often from external data sources)
and renders something in the canvas:

- A *unified inbox feed* component pulling from Slack, email,
  Discord, SMS — surfacing in one place, optional notification
- A *photos of hot contacts* component pulling from abra's contact
  pointers and the CRM's photos
- A *what claw did today* component pulling amebo's event log
- A *what's hot this week* component reading abra hot tags
- A *map of places* component for community/place-oriented users
- A *journal* component reading content blobs over time

Components are mix-and-match. The user (or a friend setting up for
them) picks the ones that fit. New components can be written without
changing abra.

---

## How abra connects to the other two systems

- **Amebo** reads abra to know who it is helping. Writes back to abra
  when something matters enough to enter the durable map (the emotion
  signal as the gatekeeper). Amebo can run without abra; it just
  becomes less personal.
- **LinkedTrust** is queried by amebo (and other agents) for trust
  scores when acting. Abra can publish bindings out as LinkedClaims
  to contribute to the trust web.

The three systems are independent. Abra works without amebo.
Amebo works without abra. LinkedTrust is its own service.

For the full picture of how they compose, see the amebo overview and
the LinkedClaims overview in their respective repos.

---

## Detail docs

- `concept-notes.md` — vision, why abra exists
- `arch_notes.md` — architecture, catcodes, scopes, sources
- `binding-format-v0.1.md` — data format spec
- `impl/CLAUDE.md` — reference implementation (pgvector + Odoo)
