# pgvector implementation of abra

**Before doing anything, read these in order:**
1. `../../concept-notes.md` — what abra IS and why it exists
2. `../../arch_notes.md` — architecture: bindings, scopes, sources, hot tags
3. `../../binding-format-v0.1.md` — the data format spec with examples
4. `~/.abra/sources.yaml` — this user's data sources and connected systems

This implementation may be replaced, but write clean code with best practices. The data it creates must be reusable by other tools.

## File naming

**ALWAYS date files with DATE FIRST and semantics in the name.**
- Format: `MM-DD-YYYY-descriptive-name.ext` or `MM-DD-descriptive-name.ext` (year implicit from directory)
- Example: `02-14-2026-processing-status.md` or `02-14-processing-status.md`

## Implementation

This impl uses PostgreSQL + pgvector to store content blobs and bindings.

- Tables: `content` (blobs + embeddings + catcode), `bindings` (the core + catcode)
- Run `setup_db.py` to initialize
- Venv at `.venv/`, activate with `source .venv/bin/activate`
- Connection details are in `.env` (instance-specific, gitignored)

## Tools

- `write_binding.py` — **preferred for interactive processing.** Write bindings and content one at a time as they're approved. Can check for existing names before creating duplicates. Usable as library or CLI. Rejects PII.
- `import_bindings.py` — batch import from a staging JSON file. For bulk loads. Dry run by default, `--confirm` to write. Rejects PII.

## Connectors

CRM and other external system connectors live in `../connectors/`. Check `~/.abra/sources.yaml` sinks section for what's available and how to reach it. When processing notes and finding contact info, write PII to the CRM connector, not here.

## PII and multi-person notes

See root CLAUDE.md. No PII in this store. A single note may reference multiple people with contact info. The flow:

1. Strip PII from the note content, store the scrubbed blob in pgvector
2. For each person/entity mentioned:
   - Create their name (IS binding) in pgvector
   - Write their contact details to CRM via connector (or flag `HAS contact:pending-crm` if CRM not ready)
   - Create `HAS crm:odoo/contact/ID` binding linking the name to their CRM record
   - Create ABOUT or RELATED binding linking the name to the note's content_id
3. PII lives in the CRM. Relationships live here. The note blob is clean.
