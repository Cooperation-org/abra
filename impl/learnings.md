# Implementation Learnings

Notes from building and using abra implementations. Survives even if specific impls get trashed.

## pgvector (Feb 2026)

- Started here. Processing notes interactively in a Claude Code session is better than a standalone API script — context accumulates, no per-call cost, agent can ask questions in real time.
- Sources (where data comes from) are meta, not bindings. Need a per-user manifest.
- **IS should be minimal.** Just the name (and maybe a primary URL). Not a bio, not context, not meeting notes. The LLM's instinct is to stuff everything into IS — had to be corrected twice. IS = identity, nothing more.
- **ABOUT emerged as a needed relationship type.** Context about someone — what you discussed, what they work on, opportunities. Distinct from IS (who they are) and HAS (contact info, URLs). This is the "open relationship types" design paying off immediately.
- **The qualifier on RELATED is doing real work.** "contact - currency design", "consultant - marketing strategy" — these are the retrieval handles. Without qualifiers, RELATED bindings are just tags. With them, they're intentions.
- **Multiple HAS per name is natural and needed.** Someone has a LinkedIn, a project URL, an email — each is a separate HAS binding.
- **Static site generation from catcode tree** — the original Abra nightly regenerated static pages from the category hierarchy, served them statically. Ran tucson.com this way. The catcode tree maps directly to URL paths / site structure. Code for this is in the original Perl Abra repo (~/abra-perl). Could be revived as a future implementation.
- **Original Perl Abra had catcodes AND itemcodes.** Categories had catcodes (positions in space). Items had itemcodes — a copy of the parent category's catcode for fast subtree queries (`LEFT(itemcode, $lvl) = LEFT(catcode, $lvl)`). Same 16-byte packed binary format. In new Abra this maps to: catcode_registry is the categories, bindings/content carry catcode references.
- **Catcodes is an array per entity.** A name can occupy multiple positions in the space. Two names that turn out to be the same real-world entity get linked via SAME_AS when discovered — not assumed upfront.
- **setup_db.py and write_binding.py have uncommitted edits** (catcode_registry table, registry methods) from Feb 14 session — made before full discussion was resolved. Review before running. Catcodes-as-array may require schema adjustments (array column or junction table instead of single VARCHAR(64)).
- **Pet names should reflect how the user actually thinks of the person right now.** Not just their real name. Someone you don't know directly but heard about through Leanne is `leo-in-au-with-leanne-ussher`, not `leo`. The name can change later when the relationship changes (e.g. you meet them and they become just `leo`). Pet names are personal handles, not database keys.
- **The filename is the clue for pet names.** When the user names a file `1-20-cole-new-thing-for-agents.txt`, "cole" is how they think of that person — use it as the pet name, not "cole-brown". The name in the filename reflects the user's mental model.
- **Need: a way to rename pet names.** Currently just a SQL UPDATE on bindings.name. Nothing else references the pet name as a foreign key, so renaming is safe — it won't break content links (those use content IDs) or CRM links (those use odoo IDs). But we should have a proper `rename_name(old, new)` method on AbraWriter rather than raw SQL. TODO.
- **Follow-up scheduling goes in the CRM as activities, context goes in pgvector as bindings.** Use Odoo's `mail.activity` to schedule follow-ups with due dates. The binding store has the relationship context (what you discussed, why they matter). The CRM has the action items (call them back Tuesday, wait til April).
- **Always create a CRM record even for unnamed entities if there's PII.** A phone number or email with no name still goes to the CRM — create with a placeholder name like "Wealth Management Co (unnamed)". Scrub PII from pgvector content, link to CRM via HAS binding.
- **Pass source_date on bindings.** The filename has the date, content.note_date captures it, but bindings.source_date should too — it tells you when the relationship was recorded.
- **LinkedIn/Google contacts imported (Feb 15).** 4,437 contacts loaded into Odoo CRM + pgvector bindings via import_linkedin.py. Deduped across both files. PII in CRM only.
- **Schema initialized (Feb 15).** catcode_registry seeded: a0 → a001 → a00101 (golda) → a0010101 (golda/contacts), a0010102 (golda/meetings). setup_db.py works.
- **Odoo connector works (Feb 15).** XML-RPC round-trip tested. Config in ~/.abra/sources.yaml, API key in impl/.env. Field is x_abra_catcode on res.partner.
