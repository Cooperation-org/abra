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

### 2.8 Shared-VM `.env` exposure

This VM has ~17 dev users with shell access. `/opt/shared/repos/abra/impl/.env`
holds Postgres credentials for `abra_user` (full DB access). If the
file is group- or world-readable, every shell user on the VM gets
god-mode on the abra DB — bypassing every higher layer in this doc.
Same applies to `/opt/shared/repos/amebo/backend/.env` (already
fixed to 640 + ACL during the unix-isolation pass, 2026-06-03).

Mitigation: enforce mode 600 (or 640 with a per-process ACL) on
every `.env` under `/opt/shared/`. Audit periodically. This is the
cheapest, highest-leverage hardening step in this doc.

**Partial mitigation applied 2026-06-05:** all golda-owned `.env`
files under `/opt/shared/repos/` chmod'd to 600 (abra/impl, abra/impl/pgvector,
trust_claim, trust_claim_backend, site-linkedtrust-us, testimonies-world,
azlocal-rag). Other team members' .env files remain at 664 (see §9
quick-wins log for the per-owner status). Team-wide note needed.

### 2.9 Lateral exposure via 0.0.0.0 binds + permissive ufw (mitigated)

Discovered 2026-06-05. The VM ufw was allowing 8000-8099 and 3000-3099
inbound from `Anywhere`, AND several backend services bind `0.0.0.0`
instead of `127.0.0.1`. Combined effect: every backend service was
reachable from anything that could route to the VM's IP. This VM has
no public IP (vmbr0 internal only), so realistic exposure was confined
to other VMs on the same /24 and team members SSH'd into VM 200. But
the architecture would have exposed services directly to the internet
the moment any proxmox-host port-forward in those ranges was added.

The 0.0.0.0 binds today (audit 2026-06-05):
- `amebo` :8000 — kene-owned; should bind 127.0.0.1 + nginx-front
- `azlocal-rag` :8050 — golda-owned
- A few others (4175, etc.)

**Mitigation applied 2026-06-05:** ufw rules scoped to `10.0.0.0/24`
on both port ranges. v6 Anywhere rules removed (no v6 internal
addressing). Per-service `0.0.0.0` → `127.0.0.1` bind changes are
pending per-owner (kene note at `~/work/6-5-2026-kene-amebo-hardening.md`).

Log audit at the same time confirmed no compromise evidence: amebo
journal shows zero external IPs hitting :8000 over 7-day window.

### 2.10 Group-writable shared repos under `/opt/shared/repos/`

`/opt/shared/repos/amebo/` is `drwxrwsr-x` (sgid + group-writable by
`devteam`). Any of the ~17 devteam users can drop or modify files in
amebo's tree, including code. Modified code runs with whatever
capabilities amebo holds (Anthropic key, Slack tokens, amebo_writer
PG role) — bypassing every auth layer. This is the same shape of
risk as §2.8 (.env exposure) but for code instead of credentials.

Audit other shared repos for the same pattern. Mitigation: drop
group-write (`chmod -R g-w`) on repos that don't need it. Coordinate
with each repo owner.

---

## 3. Layered defense, in dependency order

### 3.1 Real identity at the entry point

Replace `DEV_USER` with shared OAuth login. Per `feedback_oauth_required.md`,
**both** Google and Bluesky/ATProto are supported. After OAuth:

- The shim establishes the session's `USER_URI` from the OAuth
  identity.
- A signed session cookie carries the identity across requests.
  Cookie flags: `Secure` (HTTPS only), `HttpOnly` (no JS access),
  `SameSite=Lax` — Lax not Strict, since Strict breaks the OAuth
  callback redirect.
- Cookie payload is a signed reference (e.g. a session id) or a
  short-lived signed JWT; either way the secret never leaves the
  server.
- No more env-trust for who the user is.

**Phasing Google vs Bluesky.** Building both at once roughly doubles
the v1 OAuth surface, *and* requires the identity-link table from
§5.1 from day one (a user who logs in via both must resolve to one
identity). Recommend: Google first, ship the full v1 bundle (auth +
scope ACL + session-stamped writes + RLS, see §5.4) with Google as
the only provider. Land Bluesky as a fast follow-on before declaring
v1 done. Identity-link table comes with Bluesky, not with Google.

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

**Corollary: no direct DML.** §3.6 is only universal if every
mutation flows through `AbraWriter`. Today `view/serve.py` has four
sites that bypass it (`db_delete_binding`, `db_update_label`,
`db_uninstall_component`, the delete branch of `db_set_view_text`).
Those need to be migrated to AbraWriter methods (adding any missing
ones — e.g. `delete_binding`, `update_catcode_label`) as part of
the same change. Tracked in `~/work/6-1-2026-abra-amebo-cleanup.md`
item #1b. No new DML outside the writer.

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

**Decision: ship both together at v1.** Multi-tenant data is already
flowing (`golda`, `linkedtrust`, `untp` scopes coexist in one DB).
Shipping app-layer enforcement first and adding RLS later opens a
real leak window for any app-layer bug that slips through review.
RLS is bounded work — one migration adding policies on the six
scope-bearing tables (`bindings`, `content`, `labels`, `user_config`,
`user_signal`, `scope_access`) and a per-session variable set from
the authenticated user. Land it with §3.1 / §3.2.

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

**Scope-name uniqueness.** Scope names are a flat namespace — two
users cannot both pick `golda`. At first-login the user proposes a
scope name; if taken, propose alternatives (slug of OAuth subject,
or `<name>-2`). Enforce with a UNIQUE constraint on `scope_access.scope`
plus a separate `scopes` table that owns the canonical list. The
existing scopes (`golda`, `linkedtrust`, `untp`) get backfilled
during §7 migration step 3.

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
- 8.1 (service account URIs in scope_access)
- 8.3 (AbraWriter stamps from auth context, non-OAuth paths too)
- 8.4 (trust_tier stamped at write time; read-time discipline in
  prompt-builders so untrusted content never inlines as instructions)
- 8.5 (app-layer scope check before every AbraWriter call)
- 8.8 (input-auth per service path: DKIM, signing-secret, HMAC)

**v2 (defense in depth):**
- 3.3 (Postgres RLS)
- 3.4 (context-store bearer tokens) — only blocked until the
  context-store endpoint exists, which is itself v2
- 8.2 (identity_link table for multi-provider mapping)
- 8.6 (API key auto-issuance on OAuth)
- 8.7 (claw provenance chain shape)

**v3 / future:**
- Signed catalog distribution
- Public-by-opt-in scopes
- Cross-scope SAME_AS resolution policy

---

## 6.1 View FE v1 decisions (from 2026-06-05 discussion)

How the view shim implements §3.1–3.2 + §3.6 for the v1 bundle:

- **Multi-scope renders as sibling roots in the category tree.** Not a
  switcher. A user with read on `golda` + `linkedtrust` sees both as
  top-level roots side by side; their own scope is just one root among
  several.
- **Edit mode stays a single global body class.** No per-scope or
  per-row gating in the UI. Writes to read-only scopes fail
  server-side; the failure surfaces to the user (toast / inline error).
  "Sometimes fails" is acceptable UX.
- **Grants happen via CLI in v1.** No grant UI in the view shim. A
  small `abra-grant <user_uri> <scope> [r|rw]` script covers it.
- **Default grant policy: read+write.** Teammates mostly collaborate;
  read-only is the exception.
- **No public read URLs in v1.** Every reader logs in. Public-by-opt-in
  (§5.8) stays deferred.
- **`created_by` displays quietly.** Small icon next to each binding
  row distinguishing human / service / claw writers. Writer's pet name
  on hover or in edit mode. No visible "Created by:" label — would
  violate `OVERVIEW.md`'s Zero app noise rule.
- **`created_by` carries non-human writers.** Bindings written by
  services / claws carry URIs like `urn:abra:service:email-poller` or
  `claw:<uuid>`. The display must distinguish those from human writers
  so trust signal is visible.
- **First-login bootstrap (backend).** Creates the user row + `USER_URI`
  + default `scope_access` grant on the user's own scope. Schema needs
  a `users` table; identity URI shape and scope-name uniqueness still
  open (§5.1, §5.6).

Resolutions of §5 questions implied above:

- **§5.2 (scope vs identity)**: separated. Scope = data namespace,
  rendered as a tree root. Identity = OAuth-derived URI, used in
  `created_by` and `scope_access.user_uri`. One identity can hold many
  scope_access rows → many tree roots.
- **§5.6 (default-deny)**: confirmed. First-login bootstrap
  auto-grants own scope; everything else explicit.
- **§5.8 (public surfaces)**: deferred. v1 requires login for all reads.

Still open for the backend session:

- §5.1 identity URI exact shape (`urn:abra:google/<sub>` is the
  leaning, not committed).
- §5.6 scope-name uniqueness + first-login picker UX.
- §3.6 prerequisite: migrate the four DML sites in `view/serve.py`
  through `AbraWriter` before session-stamping `created_by`.

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

## 8. Writer-side complement (non-OAuth contexts)

§3 covers the human-OAuth path on the view shim. Writes also enter
abra from non-human or differently-authed contexts: amebo's claw
runner, the email poller, the slack bot, CLI key holders. These need
the same trust shape as OAuth writes but get their identity and
trust tier from a different auth path.

The view session owns §3 (FE OAuth, session cookie, scope_access
enforcement, first-login bootstrap, created_by display). This section
is the backend complement, primarily on amebo and any service that
writes to abra. The two have to land together so writes from any
direction stamp the same provenance shape and respect the same scope
boundaries.

### 8.1 Service account URIs

Each non-human writer gets a stable identity:

- `urn:abra:service:email-poller`
- `urn:abra:service:slack-bot`
- `urn:abra:service:claw-runner`

Each gets a row in `scope_access` (§3.2) for the scopes it may write
to. Same table, same shape as a human user_uri. The `user_uri` column
is polymorphic by URI scheme; the application treats them uniformly.

### 8.2 External identity mapping (`identity_link`)

When slack delivers a message from a known user, or a CLI key is
used, the writer needs to resolve the external identity to the right
`user_uri` before stamping `created_by`. Sketch:

```sql
CREATE TABLE identity_link (
    provider     TEXT NOT NULL,   -- 'google', 'bluesky', 'slack', 'api-key'
    provider_id  TEXT NOT NULL,   -- google sub, did, slack uid, key id
    user_uri     TEXT NOT NULL,   -- canonical
    linked_at    TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (provider, provider_id)
);
```

Doubles as the identity-link surface from §5.1 (Google + Bluesky as
the same person).

### 8.3 AbraWriter stamps from auth context, not env

§3.6 covers this for the OAuth path. Same rule extends to amebo: the
"session" is whatever auth context the write happened in. Slack
trigger stamps the slack user's resolved `user_uri`. Cron-fired claw
stamps the claw's service account (or the owner's, per §8.7). Email
poller stamps the poller's URI. The `ABRA_WRITER_URI` env override
stays for CLI/batch convenience only.

### 8.4 Trust tier stamped at write time, derived from auth path

Every binding carries a `trust_tier` enum, set by the writer from the
auth path (not picked per-write by the caller):

- **verified** — OAuth-authenticated user session, or a signed CLI
  key tied to a `user_uri`.
- **attested** — service whose input passed verification (DKIM-validated
  email from allowlisted sender, signed slack webhook).
- **unverified** — raw inbound past coarse filtering only (From:
  allowlist with no DKIM, scraped page, model completion).

A `source` slug accompanies the tier (`email`, `slack`, `cli`,
`abra-fe`, `anthropic`, …) so consumers can tell where untrusted data
originated.

**Read-time discipline.** Prompt builders and tool dispatchers honor
the tier. Untrusted content gets wrapped explicitly as data, never
inlined as instructions. Tools that take action (post to slack, write
claws, spend anthropic credits) fire only on verified-tier triggers,
or require a verified confirmation step if untrusted content was in
context. This is the part that has to be enforced in the prompt-builder
and tool-dispatch layer, not trusted to the LLM.

**Open question:** are three tiers right, or do we need more
granularity (e.g. separate "model-output" from "raw-inbound")? Decide
before stamping starts.

### 8.5 App-layer scope check before every AbraWriter call

Today the `amebo_writer` PG role can INSERT to any scope. The app
layer must verify the auth context has `scope_access.can_write = true`
on the target scope before calling AbraWriter. RLS (§3.3) is the
second line; the app-layer check is the first and also gives a clean
error path instead of a DB exception.

### 8.6 API key story

Today `api_keys` rows are minted manually. To stamp writes correctly,
each key must map 1:1 to a `user_uri`. On first OAuth login the user
could auto-receive a CLI key bound to their `user_uri`, so new team
members can run `amebo-claw` without manual provisioning. Revocable
via the same row.

### 8.7 Claw provenance chain

When a claw runs and writes, two facts matter: which claw, and on
whose behalf. Two columns on bindings:

- `created_by`: `claw:<uuid>` (the immediate writer)
- `on_behalf_of`: `<owning_user_uri>` (the user the claw runs for)

Reads and displays show the chain. Same shape can carry "amebo wrote
this after a slack trigger from peter" (`created_by:
urn:abra:service:slack-bot`, `on_behalf_of: <peter-uri>`).

**Open question:** two columns vs a single `created_by` chain string
(`claw:<uuid>!on_behalf_of:<uri>`). Pin before writes start.

### 8.8 Input-auth before write, per service path

Each service-account write path needs its input-auth wired before any
data lands:

- **Slack**: signing-secret HMAC, workspace allowlist, user-id allowlist.
- **Email**: DKIM verification, From: allowlist.
- **Webhook**: shared-secret HMAC or mTLS.

These both gate whether the write happens *and* determine the
`trust_tier` (§8.4). Without input-auth, the service account is a
god-mode token waiting to leak.

---

## 9. Quick-wins log (operational hardening applied 2026-06-05)

Distinct from §3/§8 which design the long-term layered defense. This
section logs the cheap-and-safe operational fixes already applied so
future sessions don't redo them and so the audit trail lives next to
the design.

### 9.1 ufw scoped to internal subnet

Was: `8000:8099/tcp ALLOW Anywhere`, `3000:3099/tcp ALLOW Anywhere`
(plus v6 equivalents). Now: `ALLOW from 10.0.0.0/24` on both ranges,
v6 Anywhere rules deleted (no v6 internal addressing in use). Closes
the §2.9 surface for the dev port ranges. Smoke-tested: amebo :8000,
view shim :8089, demos.linkedtrust.us all 200.

### 9.2 golda-owned `.env` files chmod'd to 600

Files fixed:
- `/opt/shared/repos/abra/impl/.env`
- `/opt/shared/repos/abra/impl/pgvector/.env`
- `/opt/shared/repos/trust_claim/.env`
- `/opt/shared/repos/trust_claim_backend/.env`
- `/opt/shared/repos/site-linkedtrust-us/.env`
- `/opt/shared/repos/testimonies-world/backend/.env`
- `/opt/shared/repos/azlocal-rag/.env`

Already-correct (no change): `amebo/backend/.env` (640 + ACL since
2026-06-03), `mtc-watch/backend/.env` (600), `simpletip/backend/.env`
(600), `ae/.env` (600).

**Other team members' .env files still at 664** (not touched without
permission): alonovo (zakia), atmosphere-bot/changemaker/amebo
(kene), integral-mass-platform (peter/amos), procure-crawl (amos),
certify (asmaa), trust-claim-data-pipeline (kene), trust-squared
(agnes), trust-hire (amr). Team-wide note needed.

### 9.3 `~/.abra/` perms tightened

`~/.abra/` dir 755 → 700. `components.yaml` + `sources.yaml` 664 → 600.
Closes §2.6 for golda's catalog. Other team members' `~/.abra/` perms
not audited (per-home, low priority since shared-VM home dirs are
already mode 705).

### 9.4 Log audit, no compromise evidence

7-day window. SSH: only expected users from their usual IPs (golda
from Comcast + proxmox; amr from Egypt; zakia from Pakistan; peter
local). amebo journal: zero external IPs hitting :8000, only
127.0.0.1 + Slack webhooks, one local 401 (expected). nginx access:
only generic wordpress scanner crap (`/wp-admin/install.php?step=1`
from random IPs, all 404), no targeted amebo probes.

### 9.5 amebo hardening — applied same pass

Per Golda's "secure it, don't leave it open" call, all the items
originally flagged for kene-coordination were applied this seat. Note
at `~/work/6-5-2026-kene-amebo-hardening.md` for kene's awareness.

- **amebo bind 127.0.0.1.** `src/main.py` patched to read
  `API_HOST` env (defaults to 127.0.0.1). nginx still proxies the
  public chain at `api.amebo.linkedtrust.us` → `127.0.0.1:8000`,
  confirmed 200. Direct hit to `10.0.0.200:8000` now refused.
- **/api/docs gated.** `src/api/main.py` FastAPI constructor: `docs_url`,
  `redoc_url`, `openapi_url` resolve to `None` unless `ENABLE_DOCS=true`.
- **Slack /events signature verification added (was missing).** The
  `verify_slack_signature` function existed and ran on `/commands`
  but not `/events`. Anyone reachable to the URL could POST forged
  Slack-shaped payloads. Now verified before any payload parse.
  Unsigned POST returns 401 (confirmed).
- **Auth event logging on failures.** `routes/auth.py` now emits
  `logger.warning("auth.login.failed ...")` and
  `logger.warning("auth.signup.rejected ...")` before each 401/403
  raise. Success cases already had `logger.info` + `audit_logs`
  table writes.
- **`/opt/shared/repos/amebo/` → `chmod -R g-w`.** Was `drwxrwsr-x`
  (devteam writable). Now `drwxr-sr-x` (devteam read-only, sgid kept
  so files inherit group). Closes §2.10 for amebo. Other shared
  repos with the same pattern not audited yet.
- **`amebo/backend/.env.old` → 600.** Was 644, world-readable since
  February. Now only kene can read. Creds may still be valid
  somewhere; rotation noted for kene.

amebo restarted, smoke-tested: localhost health 200, public
`https://api.amebo.linkedtrust.us/health` 200, `/api/docs` 404,
unsigned `/slack/events` 401.

---

**Status:** working draft. All open questions tracked here; nothing
shipped. Next session picks one of the questions in §5, drives it to
a decision, updates this doc, and starts building.
