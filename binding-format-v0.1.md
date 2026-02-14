# Abra Binding Format v0.1

See concept-notes.md for vision, arch_notes.md for architecture discussion.

## The binding

A binding connects a name to a thing, with a typed edge.

    (name, relationship, target, qualifier, permanence)

- **name** — a short pet name in a scope. "peter", "ltq1", "may-trip", "cptf".
- **relationship** — a labeled edge. IS, HAS, ABOUT, RELATED are the initial set. Open — other labels will emerge.
- **target** — what the name points to. Could be inline text, a URI, a file path, another name, a position in a formal information space, an entry in an external system (Taiga, pgvector, etc). Abra doesn't own the target, just the pointer.
- **qualifier** — optional short phrase. Context for the edge. "stack for", "candidate for", "action toward", "connection to".
- **permanence** — INTRINSIC (definitional, durable), CURRENT (true now, may change), EPHEMERAL (purpose-bound, may expire).

## Scope

Names live in scopes — a person's namespace or a group's. Scope must be discoverable by any tool loading the bindings but doesn't need to be in every record. Could be a directory, a metadata header, a database column.

## Properties

**One name, many bindings.** "peter" IS [meeting notes blob]. "peter" HAS [email]. "peter" RELATED "ltq1" qualifier "knows podcast host".

**Names can exist before their IS is defined.** You can tag things RELATED to "ltq1" before writing up what ltq1 is. The name is a handle. The definition can come later.

**Targets can be in external systems.** A contact points to a CRM record (`crm:odoo/contact/12345`). A todo points to a task manager (`tasks:taiga/issue/789`). Abra holds the pointer, the external system holds the structured data. Which systems are connected is configuration, not code.

**The relationship set is open.** IS, HAS, RELATED are starting points. Some labels the system will understand; others are just meaningful to humans and LLMs.

**Definitions are natural language.** The target of an IS binding is typically a blob of text that may mention other names. Some references a parser can resolve; some need a human or LLM to interpret.

## Examples

A meeting note processed from ~/2025:

    name: peter
    peter IS [blob: "Peter - met at DWeb camp, works on backend infra,
               knows host of TechStuff podcast, interested in
               decentralized identity. Could be good partner for
               LinkedTrust visibility push."]
    peter HAS email:peter@example.com (CURRENT)
    peter RELATED ltq1 "potential partner" (EPHEMERAL)
    peter RELATED podcast-outreach "connection to host" (EPHEMERAL)

A goal (definition to be written later):

    name: ltq1
    ltq1 IS [to be defined — LinkedTrust Q1 2026 plan,
             contracts + ecosystem visibility]
    ltq1 RELATED peter "potential partner" (EPHEMERAL)
    ltq1 RELATED podcast-outreach "channel" (EPHEMERAL)

A future trip with known incompleteness:

    name: may-trip
    may-trip IS [blob: "Trip in May, details partially on paper
                  not in system yet"]
    may-trip RELATED flights "to book" (EPHEMERAL)

Community work:

    name: cptf
    cptf IS [blob: "Community Protection Task Force"]
    cptf RELATED tpd-meeting "action toward" (EPHEMERAL)
    cptf HAS todo:draft-outreach-email → [pointer to Taiga or checklist]
    cptf RELATED rein-in-ice "goal" (CURRENT)

## The catcode registry

The catcode registry is fundamental — it defines the positions that exist in the shared information space. See arch_notes.md for full details.

Each entry: catcode, parent catcode, canonical label. Bindings and content reference catcodes. Pet names point to catcodes through bindings. Multiple names can point to the same catcode.

Deleting a catcode cascades: removes its subtree and all bindings/content referencing it. The registry is the primary structure.

## Hot tags

Not part of the binding format. Runtime/agent concern. A lightweight indicator that a name and some of its context should be in working memory. Not all context — just enough. The agent or UI maintains the hot list.

## What this format does NOT specify

- How bindings are serialized (JSON, SQL, triples, flat files — implementation choice)
- How blobs are stored (pgvector, files, inline — implementation choice)
- How scope is encoded (directory structure, column, header — implementation choice)
- How todos are managed (Taiga, checklist app, etc — external system, abra just points to it)
- How the hot list works (agent/UI concern)
