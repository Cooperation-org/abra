# Abra implementations

**Before doing anything, read these in order:**
1. `../concept-notes.md` — what abra IS and why it exists
2. `../arch_notes.md` — architecture: catcodes, bindings, scopes, sources
3. `../binding-format-v0.1.md` — the data format spec with examples
4. `~/.abra/sources.yaml` — this user's data sources and connected systems

Each subdirectory is a separate implementation. They may be in different languages/stacks. They are throwaway — the data they create is not.

learnings.md in this directory captures what we learn across implementations.

## Shared resources (impl level)

- **`.venv/`** — Python virtual environment shared by all impl code. Run with `.venv/bin/python`.
- **`.env`** — all secrets and connection config (PG creds, ODOO_API_KEY). Gitignored. Never commit.
- **`import_linkedin.py`** — bulk import LinkedIn/Google contacts to Odoo + pgvector. Dry run by default, `--confirm` to write.

## Directory layout

```
impl/
├── .venv/                     # shared Python venv
├── .env                       # shared secrets (gitignored)
├── import_linkedin.py         # bulk contact import script
├── pgvector/                  # binding store + content (PostgreSQL + pgvector)
│   ├── setup_db.py            # initialize schema
│   ├── write_binding.py       # write bindings one at a time (library + CLI)
│   ├── import_bindings.py     # batch import from staging JSON
│   └── query.py               # query bindings and content (CLI)
└── connectors/
    └── odoo/
        └── connector.py       # Odoo CRM connector (XML-RPC)
```

## How to run things

All scripts use the shared venv and .env:

```bash
cd /opt/shared/repos/abra/impl

# Initialize database (first time only)
.venv/bin/python pgvector/setup_db.py

# Import LinkedIn + Google contacts (dry run first)
.venv/bin/python import_linkedin.py ~/Connections.csv ~/Contacts.csv
.venv/bin/python import_linkedin.py ~/Connections.csv ~/Contacts.csv --confirm

# Write a single binding
.venv/bin/python pgvector/write_binding.py --scope golda --name peter --rel IS --target-type text --target-ref "Peter Smith"

# Query bindings (anyone on the team can use these)
.venv/bin/python pgvector/query.py who "credentials"       # find people by topic
.venv/bin/python pgvector/query.py about eric-shepherd      # everything about a name
.venv/bin/python pgvector/query.py when 2025-10             # who did I meet in Oct?
.venv/bin/python pgvector/query.py when 2025-07 2025-09     # date range
.venv/bin/python pgvector/query.py search "cooperative"     # search note content
.venv/bin/python pgvector/query.py related linkedtrust      # who is related to X?
.venv/bin/python pgvector/query.py refs                     # list LT reference docs
.venv/bin/python pgvector/query.py names kevin              # list names by prefix

# Use as library in a processing session
.venv/bin/python
>>> import sys; sys.path.insert(0, 'pgvector'); sys.path.insert(0, 'connectors/odoo')
>>> from write_binding import AbraWriter
>>> from connector import OdooConnector
>>> writer = AbraWriter()
>>> crm = OdooConnector()
```

## What goes where

**This is critical. Do not mix these up.**

| Data | Where | Why |
|------|-------|-----|
| PII (email, phone, address) | Odoo CRM only | Access-controlled, not in binding store |
| Bindings (name IS, HAS, ABOUT, RELATED) | pgvector | Durable, no PII |
| Content blobs (scrubbed note text) | pgvector content table | Searchable via embeddings |
| CRM pointer | pgvector binding: `HAS uri crm:odoo/contact/ID` | Links name to CRM record |
| Catcode registry | pgvector catcode_registry table | Tree of positions in space |

## Catcodes

Catcodes are 64-char positional codes, NOT labels or tags. They are spatial coordinates in the catcode registry tree.

```
a0           user-defined root
a001         version 0
a00101       golda
a0010101     golda/contacts
a0010102     golda/meetings
```

A catcode on a contact in Odoo or a binding in pgvector means "this entity is placed at this position in the tree." Multiple catcodes per entity = the entity exists in multiple positions.

## Processing notes (~/2025-notes)

194 meeting/call notes to process. Flow per note:

1. Read note, extract entities (people, orgs, topics)
2. Strip PII from note content
3. Store scrubbed blob in pgvector `content` table
4. For each person mentioned:
   - Match against existing CRM contacts (`crm.find_contact`)
   - Create in CRM if new (`crm.create_contact` — PII goes here)
   - Create bindings in pgvector: IS, HAS crm:odoo/contact/ID, ABOUT content_id
5. Create RELATED bindings for topics/goals (e.g. `lt RELATED content_id`)

Status: LinkedIn/Google contacts imported (4,437). ~60 notes processed (Feb 2026). 62 content blobs, 11,112 bindings, 4,057 unique names.
