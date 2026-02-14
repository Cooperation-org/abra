# Abra Architecture Notes - Feb 14, 2026

Working notes toward a durable, minimal data format. See concept-notes.md for vision.

## Three levels

Keep these distinct. They are often confused.

1. **Spec** — the binding format, catcode design, relationship types, PII rules. Universal, implementation-agnostic. Lives at the top level of this repo (arch_notes, binding-format-v0.1, concept-notes).

2. **Implementation** — how a particular tool stores and queries bindings. pgvector, SQLite, a graph DB, flat files — any of these. Lives in impl/ subdirectories. May be replaced entirely.

3. **Instance** — what a running deployment connects to. This user's sources, this server's Postgres, this team's Odoo CRM. Lives in per-user config (~/.abra/sources.yaml) and gitignored .env files. Different for every person and server.

Spec defines the shape. Implementation stores it. Instance configures what's connected.

## Core insight

A name is a lightweight handle — a short pet name that points to something, with a typed binding. Not a container for content. The content lives wherever it lives. Abra is the registry of bindings.

## Pet names and scopes

Names are short, personal, natural — the words you think with. "amber", "ltq1", "joe". They live in small specific scopes: a person's or group's namespace. My "joe" is not your "joe".

Scope doesn't need to be in every record but must be discoverable by any tool loading the bindings — via directory, metadata, column, whatever.

## The code space (catcode)

The catcode registry is a fundamental structure — the backbone of abra. It defines what positions exist in the shared information space. Bindings and content reference catcodes. Pet names point to catcodes. The registry exists independently of both.

### The catcode

A 64-character string that encodes position in a shared hierarchical information space. 2 characters per level, 32 levels max, alphanumeric (0-9, a-z) = 1,296 branches per level, sequential. No separators in the string (colons used for human readability only).

The string is a spatial coordinate. It's not a label or a UUID — it's a point in space. Prefix match on any length returns the entire subtree beneath that point. Two things with similar prefixes are neighbors. The system discovers relatedness through proximity, without explicit links.

### The catcode registry

Each entry: catcode, parent catcode, canonical label. The label is a description of what that region of space contains — not a pet name.

- Deleting a catcode cascades: removes its subtree and all bindings/content referencing it
- Multiple pet names (in different scopes) can point to the same catcode
- The registry is the primary structure; bindings are secondary

### Top-level allocation

Top-level prefixes are reserved for major well-known category schemes:

Reserved top-level prefixes:

- `01` — Dewey Decimal
- `02` — Wikidata
- (others as needed)
- `a0` — user-defined root

These are populated on demand, not bulk-imported.

### User-defined space

Codes are positional, not semantic. Each level just increments sequentially. The hierarchy gives meaning, the code is just an address.

- `a0` — user-defined root
- `a001` — version 0
- `a00101` — first user (golda)
- `a0010101` — golda/contacts
- `a001010101` — golda/contacts/first-contact
- `a0010102` — golda/meetings
- `a001010201` — golda/meetings/first-meeting
- `a00102` — second user or team (linkedtrust)

Teams get their own region under user-defined. Under that, each defines its own hierarchy.

### Levels can represent any dimension

Levels aren't just topic categories. A level can represent a time period (2025), geography (arizona), organizational unit, or any other organizing dimension.

**Future:** AND — an entity at the intersection of multiple positions in the space. For now, a catcode is a single path.

### Multiple codes per entity

An entity can have codes in multiple spaces. Leanne has a code in golda's personal hierarchy AND may have a code in the linkedtrust team hierarchy. These are different positions, relatable to each other.

### Relationship to pet names

Pet names are how you talk. The code is where something sits spatially. A name can bind to a catcode. External systems (e.g. CRM) can carry the catcode as a column, connecting their records into the shared space.

### Processing collections

When starting to process a collection (e.g. a directory of meeting notes), the agent should guess a category placement for the collection and ask the user before proceeding. E.g. "These look like 2025 meeting notes — place under `usrv00gvzmtg025`?" This sets the parent catcode for items in that collection.

### Migration from original Abra

The original Perl Abra used 16-char positional codes (`catcode varchar(16)`) with 76,000+ entries. These map naturally into a region of the new 64-char space and can be bulk imported.

## The binding

    (name, relationship, target, qualifier, permanence)

- **name** — the pet name, within its scope
- **relationship** — a labeled edge. IS, HAS, RELATED are the initial three. The set is open — anyone can use any label. Some labels the system will understand and act on; others are meaningful to humans and LLMs but opaque to the system.
- **target** — what it points to. A blob of text, a file, a URI, another name, a position in a formal space — whatever. Abra doesn't own the content, just the pointer.
- **qualifier** — optional short phrase giving context ("stack for", "candidate for")
- **permanence** — INTRINSIC, CURRENT, or EPHEMERAL

One name can have many bindings.

## Initial relationship types

**IS** — definitional. The name exists because of this. "abra" IS the thing in concept-notes.md. Target can be a sentence or a whole document.

**HAS** — possession/attribute. "amber" HAS a phone number. Binding is stable, target value may change.

**ABOUT** — context, notes, what you know. "peter" ABOUT [blob from meeting notes]. Distinct from IS (identity) and HAS (attributes). IS is minimal — just the name. ABOUT carries the richness.

**RELATED** — associative, purpose-driven, often temporary. A podcast tagged for ltq1 right now. Should generally have a qualifier. Often ephemeral.

These are starting points. Other edge labels will emerge from use.

## Directionality

Bindings go from a name to a thing. You can query in reverse but the binding points name → target.

## Nesting and composability

A definition blob (target of IS) is natural language that may mention other names. Some references are formal (resolvable names), some are just language a human or LLM interprets. Names build on each other.

## External systems

Some relationship types naturally point to structured data in specialized systems. Abra doesn't replicate those systems — it binds names to entries in them.

- **Contacts → CRM** (e.g. Odoo). Abra holds the pet name and relationships. The CRM holds email, phone, title, org, interaction history.
- **Todos → task manager** (e.g. Taiga). Abra knows a name HAS a todo. The task manager holds status, assignee, due date.
- **Documents → file system or CMS**. Abra points to files, the files live where files live.

The binding target for an external system entry uses a reference like `crm:odoo/contact/12345` or `tasks:taiga/issue/789`. Implementations define how to resolve these references. Which external systems a user or team connects to is configuration, not code — belongs in per-user or per-team data (e.g. sources.yaml or similar).

## Data landscape (sources, sinks, connected systems)

An agent needs to know the user's full data landscape — not just where data comes from, but where it goes, and what systems are bidirectional.

- **Sources** — one-way inflows. A directory of notes, a LinkedIn export, paper notes not yet digitized.
- **Sinks** — where data gets written. A CRM for contacts, a task manager for todos.
- **Connected systems** — bidirectional. A CRM is both: you pull contacts out, you push new ones in.

This is meta, not bindings. Per-user, private, works across implementations. A lightweight manifest (e.g. `~/.abra/sources.yaml`) that any agent reads on startup. Describes: who you are, what your scope is, what data sources and sinks you have, what state they're in, how to reach them.

## Hot tags

Runtime/agent concern, not part of the data format. Lightweight indicator: keep this name and some of its context in working memory. Not all context — just enough. Maintained by whatever agent or UI is running.

## Format

Implementation agnostic. JSON, SQL, triples, flat files — the shape matters, not the encoding.
