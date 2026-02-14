# Odoo CRM connector for abra

Start by reading ../../../concept-notes.md — what abra IS and why it exists.

This connector writes contact data (PII) to Odoo CRM. The binding store (pgvector) holds names and relationships but NO PII. This connector is the bridge.

Connection details come from `~/.abra/sources.yaml` under `sinks.crm`. Never hardcode connection info.

The `abra_catcode` field in Odoo maps to our catcode — the 64-char positional code in the shared information space.
