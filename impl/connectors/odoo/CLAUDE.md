# Odoo CRM connector for abra

**Read first:** `../../../concept-notes.md`, then `../../CLAUDE.md` (impl-level docs).

## What this does

Writes contact data (PII) to Odoo CRM via XML-RPC API. The binding store (pgvector) holds names and relationships but **NO PII**. This connector is the bridge.

## Connection config

- **CRM config**: `~/.abra/sources.yaml` under `sinks.crm` (url, db, user, catcode field name)
- **API key**: `ODOO_API_KEY` env var, loaded from `../../.env` (impl-level)
- **Database**: `linkedtrust_crm` on VM 100 (postgres). See `/opt/shared/cobox/linkedtrust-crm-setup.md`
- **Catcode field**: `x_abra_catcode` on `res.partner` — text field holding abra catcodes

There is also an `odoo-cli` shell tool (see `/opt/shared/cobox/linkedtrust-crm-setup.md`) for quick CRM operations without Python.

## Usage

```python
import sys; sys.path.insert(0, 'connectors/odoo')
from connector import OdooConnector

crm = OdooConnector()
if crm.is_ready():
    # Create contact (PII goes here, NOT in pgvector)
    odoo_id = crm.create_contact(name="Peter Smith", email="peter@example.com",
                                  company="Acme", catcode="a0010101")

    # Search
    found = crm.find_contact(email="peter@example.com")
    found = crm.find_contact(name="Peter")

    # Update
    crm.update_contact(odoo_id, company_name="New Corp")
```

## Catcodes in Odoo

The `x_abra_catcode` field holds abra catcodes — 64-char positional codes from the catcode registry. These are spatial coordinates, NOT labels or tags. Example: `a0010101` = golda/contacts.

For multiple positions, comma-separate: `a0010101,a0010201`.
