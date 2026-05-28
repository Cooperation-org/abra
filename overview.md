# Abra

A brain extension.

**Names are magic. To name something is to have power over it.**

Abra is the map of what is important to a person, or to a team. Pet names — *peter, ltq1, my son, the Tuesday writing group* — point at things through typed bindings. Hot tags mark what matters right now. Pinning is the emotional marker for permanence.

Abra holds the map. It does not run loops, take actions, or hold opinions. It just *is* the person's map.

The view — the canvas the person sees — also lives in abra, built from components that read the map (and optionally external sources). The view leans on the map; it is not the map.

Abra is open. Any system can write into it; every binding carries who wrote it. Bindings can optionally be published out as LinkedClaims. The data is durable; implementations are not — *message-in-a-bottle*.

---

**Detail**
- [`concept-notes.md`](concept-notes.md) — vision
- [`arch_notes.md`](arch_notes.md) — architecture
- [`binding-format-v0.1.md`](binding-format-v0.1.md) — data spec
- [`impl/CLAUDE.md`](impl/CLAUDE.md) — reference implementation

**Related systems** (own repos)
- [amebo](https://github.com/Cooperation-org/amebo) — a friendly claw that reads and writes abra
- [LinkedClaims](https://github.com/Cooperation-org/LinkedClaims) — the trust layer abra can publish out to
