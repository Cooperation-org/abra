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
