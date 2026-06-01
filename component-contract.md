# Component Contract v0.1

The contract between an abra-side **view** and a **provider** (amebo, Taiga, Odoo, future) for installing and rendering a web component into a user's map.

The view never imports the provider; the provider never imports the view. The contract is:

1. The catalog entry (`components.yaml`) — what the view reads to know the component exists and where to load the bundle from.
2. The bundle URL — a single JS file the provider serves that registers the custom-element tag and calls the provider's own API.
3. The provider's own API — what the bundle fetches at render time, on the provider's host, cross-origin (Pattern B).

Adding a provider does not change view code. The view stays scheme-agnostic.

---

## 1. Catalog entry

Lives in `~/.abra/components.yaml` (example: `impl/components.yaml.example`). Loader: `impl/pgvector/components.py`.

```yaml
components:
  <custom-element-tag>:
    name:        "Human display name"   # required, shown in chooser + topnav title
    description: "One-line description"  # required, shown in chooser card
    icon:        "https://.../icon.svg"  # optional, shown as topnav nav-icon
    script:      "https://.../bundle.js" # required, the JS bundle URL
    provider:    "amebo"                 # required, audit field
    schemes:     ["amebo:digest"]        # optional, URI schemes this tag handles
    required:    ["data-up"]             # required attrs on the tag
    integrity:   "sha384-..."            # required for prod; SRI hash of script
    added_by:    "urn:abra:user/golda"   # required, audit field
    added_at:    "2026-06-01"            # required, audit field
```

Field rules:

- `name`, `description`, `script`, `provider`, `required`, `added_by`, `added_at` are required. The view skips entries missing any of these.
- `icon` is optional. If absent or 404, the topnav falls back to a generic Font Awesome cube. Providers should ship icons via their own static mount (e.g. `<host>/embed/icons/<name>.svg`).
- `schemes` describes URI schemes the component can render. Empty list means the component is self-contained.
- `required` lists the `data-*` attributes the view will set on the tag. For v0, only **whole-feature-tab components** install via this catalog, so `required` is typically `["data-up"]` (the provider's host) or `[]` (self-contained). Components that need a specific item are handled by item-context activation, not by install (see §3).
- `integrity` SHOULD be set in production; the view skips SRI when the value ends in `REPLACE_ME` and emits the bundle script without `integrity`.

---

## 2. Render contract

When the user navigates to `/c/<inst>/`, the view emits one tag with the attrs from the install binding:

```html
<your-tag
  data-up="<provider-host>"
  data-scheme="<scheme>"
  data-ref="<scheme-uri>"
></your-tag>
<script src="<bundle-url>" integrity="<hash>" crossorigin="anonymous"></script>
```

`data-up` is the provider's host (cross-origin per Pattern B; not a proxy). `data-scheme` and `data-ref` are set when the catalog declares `schemes`. The bundle reads these and fetches from `${data-up}/api/...` with `credentials: 'include'`.

The bundle MUST handle failure modes inside the rendered section, not by silently no-op'ing:

- The API returns 4xx: render a clear inline error.
- Network/5xx: render a retry affordance with the actual error message.

The bundle SHOULD render content that justifies the install. A title-only render makes the install feel broken even when wiring works. For example, a Goals tab should show titles, statuses, last activity, and any actions the provider supports.

---

## 3. Item-context activation (forthcoming)

A second pattern, distinct from whole-feature-tab installs:

When the user is viewing a specific item (a name, a binding, a person, a goal), some components should be *available to act on that item* — find solutions, surface who else is working on it, run a lookup, attach a label. These components are not installed as tabs. They activate from item context.

Design forthcoming; not yet wired. This section is a placeholder so the install-flow path stays narrow: today's catalog handles the whole-feature-tab case only. Singular-item components stay out of the catalog until the item-context design lands.

---

## 4. Install + uninstall flow

Owned by abra-view. Documented here so providers know what the bundle does NOT need to do.

### Install

1. User clicks the puzzle piece in the topnav. View GETs `/components/chooser`, returns a modal listing every catalog entry.
2. User clicks a card. View POSTs `/components/install` with `tag=<key>` and writes a binding under `view:component.<inst>` (the IS-binding stores the tag; HAS bindings carry any attrs).
3. View returns a topnav anchor for the new instance (`href="/c/<inst>/"`) plus an OOB swap clearing the chooser modal. The user sees the new nav icon and can click straight to it.

### Render

1. User clicks the topnav anchor. View GETs `/c/<inst>/`, returns a full page with the topnav + the full-bleed `<your-tag>` + the bundle `<script>`.
2. Bundle hydrates, fetches from `${data-up}/api/...`, renders.

### Uninstall

1. The per-component page has a red Delete button in a `.danger-zone` block with a confirm prompt.
2. On confirm, view DELETEs `/components/<inst>`, removes all bindings under `view:component.<inst>`, redirects home.

The provider is not involved in install or uninstall — the install binding is local to abra.

---

## 5. Provider checklist

To add a provider to a user's abra:

1. Provider serves a bundle at a stable URL (e.g. `<host>/embed/<name>.js`).
2. Provider's bundle registers one or more custom-element tags.
3. Provider's bundle reads `dataset.up` and fetches from `${dataset.up}/api/...` with `credentials: 'include'`.
4. Provider may ship `<host>/embed/icons/<tag>.svg` (one per tag) to give the topnav a meaningful icon.
5. User adds an entry to `~/.abra/components.yaml` with the catalog fields above, pasting the script URL and the SRI hash.

That last step is intentionally manual — the SRI hash + `added_by`/`added_at` audit fields are the trust story for v0. Signed catalog distribution can come later.

---

**Related docs:**

- [`arch_notes.md`](arch_notes.md) — the broader architecture; this file expands the "Components" section.
- [`impl/components.yaml.example`](impl/components.yaml.example) — a populated example.
- [Pattern B explainer in `arch_notes.md`](arch_notes.md) — cross-origin direct + shared OAuth.
