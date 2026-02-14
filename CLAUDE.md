# Abra

Read concept-notes.md for vision and arch_notes.md for data format before working here.

## IMPORTANT

**NEVER make architectural decisions without discussing with the user first.** Always discuss before writing to spec files or arch docs. This includes new concepts, changes to the data format, reserved namespaces, hierarchy design — anything structural. Discuss first, write second.

## Separation of concerns

Three levels — keep them distinct (see arch_notes.md for details):

1. **Spec** (this repo, top level) — binding format, catcode design, relationship types. Universal.
2. **Implementation** (impl/ subdirs) — how a tool stores/queries bindings. Replaceable.
3. **Instance** (~/.abra/, .env files) — this server's connections, this user's sources/sinks, processing status. Never in the repo.

Instance-level data (connection configs, processing state, sources.yaml) belongs in ~/.abra/ or gitignored files, NOT committed to the repo.

## Rules

- **No PII in the binding store.** Emails, phone numbers, addresses belong in access-controlled systems (CRM, secure vault, etc.), not in the open binding store. Bindings can point to those systems but must not contain the PII itself.

- The data format (bindings) is the durable layer. Implementations are throwaway. Any data created by an implementation must be reusable by other tools.
- Implementations go in subdirectories, not the top level. They may be in completely different languages/stacks and are not required to share code.
- Top level is for vision docs, data format spec (versioned), and notes only. No code, no configs, no dependency files.
- concept-notes.md is human-edited only. Do not modify it except for typos.
- Names can exist before their IS is defined. If a name appears that might collide with an existing one, ask the user.
