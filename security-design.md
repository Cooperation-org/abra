# Security & OAuth Design (working draft for next session)

Captured 2026-06-05 for the next session. Sketches attack surfaces,
a layered defense, and the open design questions that need decisions
before code.

Status: working draft, not a contract. Once the open questions land,
this graduates to the contract spec.

Related:
- [`component-contract.md`](component-contract.md) — provider component contract
- [`capability-design.md`](capability-design.md) — per-(user, catcode) item-action enablement
- [`context-store-contract.md`](context-store-contract.md) — generic claw context store
- `feedback_oauth_required.md` (memory) — OAuth is the standard for every new project

---

## 1. Current state we are designing around

- **View shim** runs locally and reads `SCOPE` from env to decide whose
  data to render. `USER_URI` is env-derived (`urn:abra:local:<USER>`).
- **Postgres roles**: `abra_user` (view shim, full access),
  `amebo_writer` (amebo backend: SELECT all 7 tables, INSERT only on
  `bindings` + `content`, no UPDATE/DELETE).
- **amebo** runs as system user `amebo` (uid 997), unix-isolated.
  Carries org-scoped auth on its API; mints per-user JWTs in some
  flows.
- **demos.linkedtrust.us** is publicly fronted: Caddy → nginx →
  127.0.0.1:8089 view shim.
- **Multiple scopes** already in abra DB: `golda`, `linkedtrust`,
  `untp`, possibly others as team members onboard.
- **`~/.abra/components.yaml`** is per-user, holds the trust catalog,
  defended by file perms + bundle SRI hash.

---

## 2. Attack surfaces, ranked by realistic risk

### 2.1 Cross-scope read in abra DB

Anyone with `abra_user` credentials reads every scope. amebo (as
`amebo_writer`) also reads everything. Most concrete: a compromised
amebo, a stolen `.env` from any process, or any local user who can
read the role's password — exposes all scopes.

### 2.2 Cross-scope write

`AbraWriter` writes with whatever `ABRA_WRITER_URI` env says. amebo
can INSERT into *any* scope. No DB-level check that the writer is
authorized to write to that scope. So an attacker with amebo's writer
creds can plant rows in `golda`'s data while appearing as anyone.

### 2.3 Identity spoofing on the view shim

The shim trusts `SCOPE` env and mints amebo JWTs from a constant
`DEV_USER`. On a shared VM, another user could SSH in, start their
own shim with `SCOPE=golda`, and read everything. nginx fronts the
shim; nginx does not authenticate.

### 2.4 Context store endpoint (not yet built)

Per `context-store-contract.md`, `POST /store/<scope>/<catcode>/entries`
will accept context entries. If unauthenticated, anyone with the URL
writes. Claw store URLs leak via amebo logs, scratch, screenshots —
trivially picked up by anyone watching the wire.

### 2.5 Capability config tampering

`user_config` rows underlie the per-(user, catcode) capability
enablement model (`cap.<catcode>.<tag>` keys). If writes aren't gated
on the authenticated user_uri, one user can enable destructive
actions on another's catcodes.

### 2.6 Catalog poisoning

`~/.abra/components.yaml` is per-user. SRI hash defends against
bundle tampering. Lower risk if home dirs are mode 0700, but a
shared-VM user with sudo can still alter it. Secondary risk: a
malicious entry pointing at a plausible-but-different bundle URL.

### 2.7 Bundle / origin trust

Pattern B has bundles talking cross-origin direct to providers
(amebo). Provider auth is the provider's problem. Risk we accept;
we depend on amebo's auth being correct, and on TLS to amebo.

---

## 3. Layered defense, in dependency order

### 3.1 Real identity at the entry point

Replace `DEV_USER` with shared OAuth login. Per `feedback_oauth_required.md`,
**both** Google and Bluesky/ATProto are supported. After OAuth:

- The shim establishes the session's `USER_URI` from the OAuth
  identity.
- A signed, http-only session cookie carries the identity across
  requests.
- No more env-trust for who the user is.

### 3.2 Scope ACL table

```sql
CREATE TABLE scope_access (
    user_uri    TEXT        NOT NULL,
    scope       VARCHAR(255) NOT NULL,
    can_read    BOOL        NOT NULL DEFAULT TRUE,
    can_write   BOOL        NOT NULL DEFAULT FALSE,
    granted_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    granted_by  TEXT,                          -- who granted it
    PRIMARY KEY (user_uri, scope)
);
```

Default for a new user: own scope (derived from OAuth or self-chosen)
gets `can_read=TRUE, can_write=TRUE`. Everything else: no row → no
access. Teammates get explicit grants.

View shim enforces `WHERE scope IN (<readable scopes>)` on every
query, derived from the session's user_uri.

### 3.3 Postgres row-level security as defense in depth

After the application layer enforces scope filtering, RLS policies on
`bindings`, `content`, `labels`, `user_config`, `user_signal`,
`scope_access` filter by `scope` using a per-session variable set
from the authenticated user.

This protects against SQL injection, stolen creds, accidental joins
that skip the filter, and misconfigured roles.

Migration cost: real but bounded. Could ship application-layer first,
retrofit RLS in a follow-on. Or do both together — RLS only matters
when there is real multi-tenant data flowing.

### 3.4 Context store auth: per-claw bearer tokens

When abra issues a store URL to a claw, also issue a token bound to
`(user_uri, catcode, claw_uri)`. The claw POSTs with
`Authorization: Bearer <token>`. Store accepts only that token, and
only for the catcode it was issued for. Tokens are revocable.

This lets a leaked store URL be useless without the matching token.

### 3.5 `user_config` writes gated on authenticated user_uri

The write path validates `user_config.user_uri == session_user_uri`.
A user cannot write `cap.<catcode>.X` for a different user. Reads
follow the same rule.

### 3.6 `AbraWriter` stamps `created_by` from the session, not env

The writer URI comes from the authenticated session, not from
`ABRA_WRITER_URI` env. Server-side, not client-controlled. The env
override stays available only as a CLI / batch convenience.

---

## 4. Two convenience priorities we must protect

- **Voice-paste URLs.** OAuth login produces a session cookie. Voice
  can paste any abra URL; the session carries the auth. URLs
  themselves carry no secret — they identify what to act on, not who
  is acting.
- **Multi-session collaboration.** Your scope is readable to teammates
  only via explicit `scope_access` grants. No implicit sharing, no
  surprise data leaks. Granting takes one row.

---

## 5. Open design questions to decide next session

### 5.1 Identity URI shape

OAuth subject → URI. Concrete options:

- Google → `urn:abra:google/<sub>`
- Bluesky/ATProto → `did:plc:<…>` (the user's actual DID)
- Self-hosted → `urn:abra:local:<handle>` (current local convention)

Need one canonical form for `created_by`, `scope_access.user_uri`,
`user_config.user_uri`. Could allow multiple URIs per identity (an
`identity_link` table) so a person who logs in via both Google and
Bluesky is recognised as one user.

### 5.2 Scope vs identity

Today `SCOPE=golda` is both her identity *and* her data namespace.
Should they be separate?

- Identity: `urn:abra:google/123…` (or did:plc:…)
- Default scope: `golda` (a short, memorable label she chose)

Cleaner separation, more moving parts. The identity authenticates the
user; the scope addresses the data. One identity can own multiple
scopes; one scope can be shared across many identities.

### 5.3 amebo's slot in the auth chain

Does amebo accept abra's session token directly (shared OAuth cookie
across origins), or does amebo do its own OAuth dance and we trust
the cross-origin call?

Pattern B says shared OAuth. Concretely:

- **(a)** Same OAuth provider, separate sessions. User signs in once
  to each origin. Cookies for `demos.linkedtrust.us` and
  `amebo.linkedtrust.us` are distinct but share an upstream identity.
  Standard and simple.
- **(b)** Same-site cookie via a shared parent domain. Sticky if both
  origins live under `linkedtrust.us`. Riskier — broader cookie
  exposure.
- **(c)** Token exchange: abra hands amebo a short-lived JWT signed
  by abra. amebo verifies abra's signing key. More work, cleanest
  decoupling.

Default leaning: **(a)** for now, **(c)** when the bundle needs
abra-signed claims (e.g. proof of which catcode it is acting on).

### 5.4 Postgres RLS vs application-layer filter

Both? App-layer first for speed, RLS as defense in depth later? Or
land RLS at the same migration so we don't ship a window where the
app layer is the only thing standing between users?

### 5.5 Token issuance + revocation for context stores

- Where do bearer tokens live? `store_token(token_hash, user_uri,
  scope, catcode, claw_uri, expires_at)`?
- Are tokens long-lived per claw, or rotated?
- How does a claw learn about revocation? Lazy (next request 401s) is
  probably enough.

### 5.6 Default-deny vs default-allow on new scopes

When a new scope appears in the DB (a teammate signs up, an import
creates rows), is it visible to anyone? Default-deny is safer and
matches the principle of least privilege. Default-allow is friendlier
for small teams.

Leaning default-deny with a small bootstrap convenience: at first
OAuth login, the user gets a self-named scope automatically granted
to them.

### 5.7 Cross-scope SAME_AS bindings

If `golda` has a `SAME_AS` binding pointing at a name in `linkedtrust`,
does she automatically see the linkedtrust row when reading her own
data? Probably no — the binding is a pointer, not a permission. Reads
that follow SAME_AS should still go through `scope_access` checks.

### 5.8 Public surfaces

Does abra ever serve unauthenticated reads? Possibilities:

- A user opts a single catcode in as "public" (no auth required for
  read). Useful for sharing.
- LinkedClaims publish-out — published bindings become public, but
  via the LinkedClaims layer, not via abra's read API.

Default: nothing public until explicitly opted in.

### 5.9 Catalog trust at scale

Today catalog is per-user, ~/.abra/components.yaml, with SRI hash.
Future: a signed catalog feed (`catalog.linkedtrust.us/abra-trusted`)
that users subscribe to. Out of scope for v1, worth noting as the
direction.

---

## 6. What to build in v1 vs defer

**v1 (must ship together to avoid a half-secure window):**
- 3.1 (OAuth login, session cookie, `USER_URI` from auth)
- 3.2 (scope ACL table, application-layer enforcement)
- 3.5 (user_config gated on session)
- 3.6 (AbraWriter stamps from session)

**v2 (defense in depth):**
- 3.3 (Postgres RLS)
- 3.4 (context-store bearer tokens) — only blocked until the
  context-store endpoint exists, which is itself v2
- Identity-link table if multiple OAuth providers are needed

**v3 / future:**
- Signed catalog distribution
- Public-by-opt-in scopes
- Cross-scope SAME_AS resolution policy

---

## 7. Migration path

The view shim currently runs against a known scope from env. To
introduce auth without breaking development:

1. Add OAuth endpoints and session cookie support.
2. Keep env fallback for unattended/CLI use. When session is present,
   it wins; otherwise fall back to env. Eventually remove fallback.
3. Backfill `scope_access` for current scopes (`golda`,
   `linkedtrust`, `untp`) granted to the owning identity.
4. Flip application-layer enforcement on for all DB queries.
5. Smoke-test on demos.linkedtrust.us with a fresh OAuth login.

---

**Status:** working draft. All open questions tracked here; nothing
shipped. Next session picks one of the questions in §5, drives it to
a decision, updates this doc, and starts building.
