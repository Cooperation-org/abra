# Context Store Contract v0.1 (working draft)

A **context store** is a place where a long-running agent (amebo
claw, future async worker, anything similar) records observations
and reads back fresh context. Multiple writers may put information
into the same store; the agent reads what's there.

This contract defines what a store looks like from the outside so
that an agent (e.g. a claw) does not know or care whether the store
is hosted by abra, the agent's own backend, or a third party. abra
is a convenient implementation; others can ship different ones.

This doc is a working draft, not a final contract. It complements
[`capability-design.md`](capability-design.md): a capability is the
per-user wiring that creates a claw and points it at a store URL;
this doc defines what that URL must do.

---

## 1. What a store is

A store is identified by a single base URL. The URL is opaque to
the agent — it does not parse the path. Two operations:

- **Write** a new entry into the store.
- **Read** entries from the store, newest first.

A store may have many writers (the claw itself, the user via UI,
other agents, future webhook senders). The claw reads everything;
the contract makes no statement about who wrote what beyond
provenance carried on each entry.

A store may persist indefinitely or rotate. That is the store's
business; the agent treats it as a black box.

---

## 2. The contract

All endpoints are HTTPS. Auth is per Pattern B (cross-origin
direct, shared OAuth or bearer token in `Authorization`). Bodies
are JSON.

### Write

```
POST <store_url>/entries
Content-Type: application/json

{
  "content":   "<text>",            // required
  "author":    "<uri>",             // required, who wrote this
  "kind":      "<short tag>",       // optional, e.g. "observation", "note"
  "tags":      ["a", "b"],          // optional
  "timestamp": "<ISO 8601>"         // optional; server stamps if absent
}
```

Response:

```
200 OK
{
  "id":        "<store-local entry id>",
  "timestamp": "<ISO 8601 the server recorded>"
}
```

The store SHOULD reject (`4xx`) on missing required fields. The
store MAY add server-side fields (e.g. its own provenance, dedupe
hash) but they are not part of the contract.

### Read

```
GET <store_url>/entries?since=<ISO 8601>&limit=<N>
```

Response:

```
200 OK
[
  {
    "id":        "<entry id>",
    "content":   "<text>",
    "author":    "<uri>",
    "kind":      "<tag>",
    "tags":      [...],
    "timestamp": "<ISO 8601>"
  },
  ...
]
```

Ordered newest first. `since` is exclusive. `limit` defaults to a
reasonable cap (the store decides; ~50 is typical). The list MAY
be empty.

### Optional: identify

```
GET <store_url>/about
→ 200 { "kind": "context-store", "version": "0.1", "writeable": true }
```

Lets a caller verify the URL implements this contract.

---

## 3. Abra as a store

abra implements this contract on top of a `(scope, catcode)`
pair. The store URL takes the shape:

```
https://<abra-host>/store/<scope>/<catcode>/
```

- **POST entries** → creates a `content` row plus an `ABOUT` binding
  under a name that the user chose for this store (e.g.
  `claw-cash-tracker-2026`). `created_by` is the `author` URI.
  `catcodes` carries the configured catcode.
- **GET entries** → SELECT content blobs joined via bindings under
  the configured catcode and name, ordered by date desc.

abra **does not invent** a new schema for context entries; it
reuses the binding + content primitives. The catcode is the
addressable place; the name groups entries that belong together.

This makes catcodes natural homes for "stuff this claw collects,"
and other things (the user, another agent) can write to the same
catcode through the same store URL.

---

## 4. Non-abra implementations

The contract is generic. Other stores can implement it without
touching abra:

- **Amebo's own DB** — a tiny endpoint that stores rows in amebo's
  Postgres. Same JSON shape, different storage. Lets a user run
  amebo standalone with no abra at all.
- **A flat-file store** — a CLI tool that appends JSONL files
  somewhere and serves them on request.
- **Google Drive / Notion / arbitrary doc store** — a small
  adapter that maps the contract onto the host's API.

A claw is given a store URL at creation time. It does not know or
care which kind. The user picks where they want their context to
live.

---

## 5. Connection to claws (amebo)

A claw config holds zero or more **store URLs**. At each tick, the
claw:

1. Calls `GET <store>/entries?since=<last-read>` on each configured
   store. Joins the results into the prompt context.
2. Optionally writes observations via `POST <store>/entries` with
   `author = <claw-uri>`.

A claw with zero stores configured runs purely on its own state
(no external context). A claw with one or more stores integrates
that context every tick.

amebo's role here is narrow: store the list of URLs on the claw,
call the endpoints. amebo never parses or asserts shape beyond the
contract above. No abra-specific code paths.

---

## 6. Open questions

- **Dedup**: if a claw writes the same observation twice, does the
  store dedupe? Probably yes (content + author + kind hash), but
  this is a store-internal decision.
- **Access control**: who can write to a store? For abra, the
  capability that created the store determines whose `author` URIs
  are accepted. For other implementations, their own auth model.
- **Rich payloads**: today's `content` is text. Some claws may want
  to attach a structured blob (JSON, image, file). v0 punts; if
  needed, store URLs can accept multipart and serve back a download
  URL.
- **Discovery**: how does a user find out a store exists? abra-side,
  the catcode tree shows it. Non-abra implementations are the
  user's problem to remember/share.

---

## 7. What this displaces

Nothing yet — this is a new layer. `capability-design.md` §5 will
gain a one-line reference: when the capability enables a claw, the
claw's store URL(s) are part of its config and can point at any
contract-compliant store, of which abra is one.

---

**Status:** working draft. amebo session is designing the claw
side; this is the boundary they should hit. Discussion in
[`scratch.md`](scratch.md).
