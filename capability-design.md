# Capability Design (working draft)

A **capability** is the per-user decision to enable an item-action
web component on a particular category, plus the small slice of
config that decision needs.

This doc is a working design, not a contract yet. It extends
[`component-contract.md`](component-contract.md) §3 (the item-context
activation placeholder) toward something concrete.

---

## 1. Mental model

A **web component** is the JS bundle a provider ships and a user's
abra catalog records. Today's contract handles one shape — *whole-
tab* components like `amebo-digest`, `amebo-goals`, `amebo-claws` —
which install once and become topnav destinations.

A **capability** is a different shape, layered on top:

```
capability = (user, catcode, item-action component, small config)
```

Concretely:

- `(golda, a0010101 contacts, crm-create-reminder) → enabled, {target: "default"}`
- `(golda, a00101050601 goals, taiga-create-task) → enabled, {project_id: "cash-tracker"}`
- `(some-other-user, a0010101, *)` → no entries → no actions appear

Capabilities are how the user says "when I'm looking at items under
this category, give me these verbs to act on them."

Capabilities and web components are deeply connected: a capability
*is* a web component that has been enabled, with the right kind of
component (an item-action one) and the right context (a catcode).

---

## 2. Catalog change

The catalog (`~/.abra/components.yaml`) currently treats every entry
as a whole-tab install. To support capabilities cleanly, each entry
declares a `kind`:

```yaml
components:
  amebo-goals:
    kind: tab                 # default; installs as a topnav entry
    name: "Goals"
    ...

  crm-create-reminder:
    kind: action              # appears in item view as a button
    name: "Create reminder"
    description: "Drop a follow-up reminder into the CRM"
    icon: "https://crm.linkedtrust.us/embed/icons/reminder.svg"
    script: "https://crm.linkedtrust.us/embed/crm.js"
    provider: "crm-odoo"
    enabled_on_schemes: ["crm:odoo/contact"]   # what items make sense
    config_schema:                              # what config the user provides
      target_tag:
        label: "Tag prefix for reminders"
        default: "abra-followup"
    integrity: "sha384-..."
    added_by: "urn:abra:user/golda"
    added_at: "2026-06-04"
```

`kind: tab` is the default for back-compat; existing entries don't
change. `kind: action` is the new shape.

`enabled_on_schemes` (optional) lets the action declare what items it
makes sense on. The capability-picker UI greys out actions whose
schemes don't match anything under the target catcode.

`config_schema` (optional) declares the per-(user, catcode) values
the user supplies at enablement time. Tiny field set: label,
default, optional `enum` for picklists.

---

## 3. Storage

Capability enablement and per-cap config live in `user_config`
(migration 002, already present), keyed by a deterministic path:

```
user_config.key   =  cap.<catcode>.<action-tag>
user_config.value =  { enabled: true, config: { … } }
```

Examples:

```
cap.a0010101.crm-create-reminder        {enabled: true, config: {target_tag: "abra-followup"}}
cap.a00101050601.taiga-create-task      {enabled: true, config: {project_id: "cash-tracker"}}
```

This reuses existing infra, no migration, JSONB absorbs whatever
shape the catalog's `config_schema` describes. If query patterns get
painful later (e.g. "list every catcode where action X is enabled"),
promote to a real `user_capability` table with one migration.

Provider-global config (which Odoo instance, OAuth tokens) lives in
the **component's** own backend per Pattern B. abra never holds those
secrets. abra only knows: "this user enabled this tag on this
catcode."

---

## 4. UI flow

### Enabling a capability on a catcode

From the categories tree in edit mode:

1. Click a catcode (e.g. `golda/contacts`).
2. A capability panel opens showing every `kind: action` entry in
   the catalog. Actions whose `enabled_on_schemes` doesn't match
   any binding under that catcode appear greyed but available
   ("enable anyway").
3. Each row: name + description + a tiny form for the
   `config_schema` fields + an Enable button.
4. On submit: write the `user_config` row.

### Action appearing in item view

When the user is viewing one item (a name's detail):

1. abra resolves the catcodes of that name's bindings.
2. For each catcode, read `user_config` rows matching
   `cap.<catcode>.*` with `enabled: true`.
3. For each enabled action whose `enabled_on_schemes` matches at
   least one of the item's bindings (or unconstrained), render an
   action button with the catalog's icon and name.
4. Click → mount the action component with the item context:
   ```html
   <crm-create-reminder
     data-up="https://crm.linkedtrust.us"
     data-name="leanne-ussher"
     data-target-tag="abra-followup"
   ></crm-create-reminder>
   ```
   The action component runs its own UX (modal, inline form, dispatch)
   and writes to its own backend. abra is done.

The action component MUST clean up after itself (close modal,
emit `done` event). abra catches `done` and re-renders the item
view if state changed.

---

## 5. Concrete examples

### crm-create-reminder (contacts → Odoo)

- catalog entry: `kind: action`, `enabled_on_schemes: ["crm:odoo/contact"]`
- enablement: user opts in on `golda/contacts` with `target_tag: "abra-followup"`
- item view: every contact card shows a "Create reminder" button
- click: modal asks for topic + due date, writes reminder to Odoo, closes

### taiga-create-task (goals → Marten)

- catalog entry: `kind: action`, `enabled_on_schemes: ["amebo:goal", "amebo:intentions"]`
- enablement: user opts in on `golda/2026/june/goals` with
  `project_id: "cash-tracker"`
- item view: every goal shows a "Make task" button
- click: short form (title prefilled from goal), POSTs to Taiga, closes

### amebo-claws-attach (any item → schedule a claw)

- catalog entry: `kind: action`, `enabled_on_schemes: []` (works on anything)
- enablement: user opts in on whichever catcodes they want claws to be
  attachable on (could be all of them, could be just goals + tasks)
- item view: "Attach claw" button
- click: prompt for intention, amebo schedules

Note that `amebo-claws` (the `kind: tab` Claws view) and
`amebo-claws-attach` (the `kind: action` verb) are **separate
catalog entries** pointing at the same bundle. Same JS, two
mountpoints. Cleaner than overloading one tag.

---

## 6. Open questions

- **Word choice**: "capability" is fine here; "action" is the verb
  affordance on the item. Both stay.
- **Enablement entry point**: edit-mode click on a catcode? Or a
  separate "capabilities" view in the topnav? Probably the former
  to keep it co-located with the category.
- **Per-component config UX**: the catalog declares a `config_schema`.
  How rich does it get? For v0, three field types are enough: text,
  picklist, boolean. Anything richer, the component's own setup
  flow handles.
- **Disabling**: capability rows toggle `enabled: false` or get
  deleted. Probably soft-toggle so the previous config is recoverable.
- **Auditability**: do we want to track when a capability was
  enabled, by whom? `user_config` doesn't carry provenance today;
  if we care, add `created_by` + `created_at` to the value blob.
- **Cross-scope capabilities**: a `linkedtrust` scope catcode that
  should connect to the same Odoo as `golda` — does that just mean
  each user enables it on their own slice? Yes, capabilities are
  per-user. The catcode is shared, the enablement is not.

---

## 7. What this displaces

Component contract §3 ("Item-context activation — forthcoming")
becomes "implemented per `capability-design.md`" once this is
landed and a first action component exists. Until then, both docs
stay as working drafts.

---

**Status:** working draft. Discussion ongoing in
[`scratch.md`](scratch.md). No code yet.
