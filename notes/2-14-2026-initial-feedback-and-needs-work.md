# Initial Review & Needs Work - Feb 14, 2026

Unvarnished review of abra concept and v0.1 implementation after initial design session.

## What's strong

**The core insight is real and unsolved.** Twenty-five years after the first build, no tool lets people think in their own words and have the system keep up. Obsidian, Notion, Roam are document-first. Abra is name-first. You name things the way you think about them, and the system holds the meaning. That's a fundamentally different starting point.

**The binding model is genuinely minimal.** Five fields. Open relationship types. Implementation agnostic. Closer to triples than to a schema. The decision to keep IS/HAS/RELATED as starting points but leave the set open is correct — you'll discover what relationships matter by using it.

**The separation of data from implementation is disciplined.** Top level has no code, the impl is explicitly replaceable, the format spec stands alone. Rare and will pay off.

**Names before definitions is the right call.** You can say "tag this for cptf" before you've written what cptf is. Matches how thought actually works — you use a word before you fully define it, and the definition crystallizes through use.

## What's weak or missing

**The permanence model is underspecified.** INTRINSIC, CURRENT, EPHEMERAL — what actually happens when something is EPHEMERAL? Who decides it's expired? No timestamp, no review cycle, no mechanics. Fine for v0.1 but will matter fast with hundreds of EPHEMERAL bindings.

**Hot tags have no spec at all.** Described as "runtime/agent concern" and hand-waved. But hot tags are the killer feature — they're what makes the system reduce cognitive load. How many? How does the agent decide what to load? What when you have 50 names and can only hold 10 in context? Needs real thought. Difference between a knowledge graph (plenty exist) and a brain extension (nothing does this well).

**The formal information space is a sketch.** The 16-byte hierarchical codes are mentioned but not connected to anything current. This is the piece that gives you implicit relatedness. Vector embeddings give some of this for free (semantic similarity) but it's fuzzy. The original Abra had structural proximity — more precise. How this maps to modern implementation is unresolved.

**Scope boundaries are vague.** What happens when I tag something in my scope RELATED to a name in team scope? Can I see team bindings? Override them? What if team's "peter" and my "peter" differ? Multi-user story needs work.

**No query model.** Way to put data in but no defined way to get it out. "Show me everything about ltq1" — what does that mean? All bindings where name=ltq1? All content reachable by traversal? Query semantics will shape how useful the system actually is.

## How this helps people, teams, communities

**For individuals:** A memory prosthetic. Not capture-everything — "I can think in my own words and the system keeps up." The real value is preserving intention. Tagging a podcast RELATED ltq1 "candidate" captures a thought that would evaporate. Three weeks later, that thought is still there. Most productivity systems capture tasks and documents. Abra captures the connections between them, in your language.

**For teams:** Scoped namespaces are genuinely powerful. Team shares vocabulary ("trust-core" means the same to everyone) while individuals keep their own mappings. How teams actually communicate: shared jargon plus personal context. Hot tags dashboard = shared situational awareness, not just a dashboard. Teams can use path-style scoping like lt.golda.peter — similar to Spritely/dustyweb's edge names, where you navigate through social paths ("lt team's golda's peter"). This gives you discovery and disambiguation through the team graph.

**For communities:** The LinkedTrust connection matters. "joe IS my handyman" is a binding in my scope, but structurally it's a verifiable claim. Community members sharing bindings (group scope) = community knowledge graph from natural language, not formal ontologies. A neighborhood where "joe" means the reliable handyman, "cptf" means the community protection task force — institutional memory built from the bottom up.

**The deeper thing:** Most knowledge management is about organizing information. Abra is about empowering intention. The RELATED binding with a qualifier is literally "this thing matters to me because of this." That's an intention, not a tag. Systems that preserve intention compound over time.

## Risks

**Adoption friction.** Concept is intuitive but practice requires a tagging habit. If the LLM agent does most tagging work, manageable. If it falls on the user, it'll die from neglect like every other PKM system.

**The LLM dependency.** System is most useful when mediated by an LLM. Powerful but fragile — coupling to a specific interaction mode. A binding format that only works well with LLM interpretation is less durable than one also useful to simple tools.

**Scale of ambiguity.** 194 notes will produce hundreds of names. Many provisional, ambiguous, or stale. Without disambiguation, expiry, and review workflows, the namespace gets noisy fast.

## Bottom line

Concept is sound, gap is real, binding format is clean enough to start with. Biggest risk isn't the data model — it's the agent/interface layer (hot tags, query, disambiguation) that turns a pile of bindings into something that actually reduces cognitive load. Data format is the foundation, but the experience is the building, and the building isn't designed yet.
