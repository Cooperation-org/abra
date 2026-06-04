# User stories — what abra + amebo need to do for Golda

Brief TLDRs on top, Golda's actual words underneath. More stories will
land here as voice work generates them. We'll simplify into capabilities
later; the aspirational goal is for abra to **map to her** rather than
force her into a fixed taxonomy.

---

## 1. UN transparency specification advocacy

**TLDR:** An initiative with linked artifacts (spec URL, PR URL, her
core principles), outbound emails to people that need to be mirrored
into the CRM, a running "latest state" of where the effort is, and an
intelligent amebo service that checks for new responses and surfaces
what's popping up. Not a fixed tracker — an agent that's intelligent
the way Claude code is.

**Golda, verbatim:**

> I'm working on a lot of different things. I'm working on, for example
> — these are just examples, but I'm really working on them — I'm
> trying to get people to provide comments on a UN transparency
> specification. So in abra, I would store, for example, the link to
> the specification, the link to my PR that I'm trying to get people
> to comment on, some core principles of accountability that I want,
> and I need to be able to copy probably to the CRM — actually, my
> emails to people. And then I need something to kind of keep a
> latest state of what's going on with that. And probably, it might
> wind up doing a service, um, which has to be sort of an intelligent
> tool service. It can't be too fixed. So amebo has to be intelligent
> about it the way Claude code would be, to check if anybody has
> responded to my comments. I need to have things check where, um,
> like, what's the latest state, which things are popping up that I
> need to work on.

---

## 2. Contacts: strong-tie marker, category-level CRM linkage, per-item follow-up reminders

**TLDR:** Three threads, one architecture lesson.

1. **Strong-tie marker.** Some contacts feel deeply connected even after
   years of silence (Golda's example: Arige). She wants a way to mark
   that. Doesn't dictate the mechanism — a label, a score, a pin, some
   new primitive. The point is the marker, not the shape.

2. **Category-level capability enablement.** The contacts *category*
   (not abra core) is the right place to say "things here are live-
   connected to my CRM." Per-user config, not a universal abra
   concept. Other people may not have a CRM or may organise contacts
   differently. So the catcode is shared, but the **capability bound
   to the catcode** is per-user. This implies a config layer:
   `(user, catcode) → enabled capabilities/connectors`.

3. **Item-context action: follow-up reminder.** From one contact's
   view, Golda wants to say "follow up with them on topic X" and have
   that become a reminder inside the Odoo CRM. The action is item-
   context activation (the placeholder pattern in
   [`component-contract.md`](component-contract.md) §3) provided by a
   CRM-aware web component. Abra never imports CRM logic; the
   component knows the CRM and writes back to it.

**Architectural insight:** abra stays neutral. The category exists
for everyone. The capability ("contacts here live-talk to my CRM")
is per-user data, stored as something like
`config:catcode/<code>/capabilities: [crm-odoo-reminder, …]`. The
web component reads this config when it activates from item view,
and only shows actions whose capabilities are enabled for the
current category.

**Open shape questions** (defer until designing):
- Where does the per-(user, catcode) capability config live? A
  binding under `view:capability.<code>`? A `user_config` row keyed
  by catcode? A new `user_capabilities` table?
- Does the strong-tie marker reuse `user_signal` (the score
  primitive), or is it a dedicated label, or a new thing? The score
  table can carry it; whether the UI affordance is "drag to top" or
  "click a star" is the design question.
- For item-context actions: do they appear as a small action strip
  inside the item view, or as a floating menu, or as new top-nav
  entries that only light up when an item is selected?

**Golda, verbatim (2026-06-04, walking):**

> If I see an old contact, like, some of them I feel super strongly
> connected to even though we haven't spoken in years. So I feel like
> I want some way to indicate that. I'm not gonna dictate right now
> what that should be. But, like, for example, Arige, she is a super
> strong contact of mine, and I just want to be able to somehow
> indicate that to myself. I'm not sure how. I don't wanna make
> things too hard or too specific, but just that sort of a user
> story.
>
> Some people who I might wanna follow up with, and that feels like
> maybe contacts are of a type that can then connect to the CRM,
> because in the CRM I'm gonna have reminders where I wanna go ahead
> and remind myself to follow up with them on a certain thing. So
> what I would wanna be able to do is look at this contact and be
> like, oh, you know, I should follow up with them on a particular
> topic, and have that become a reminder in the CRM system. And
> that's something that we're working on independently in the Odoo
> CRM.
>
> So it feels like that somehow needs to connect maybe to a different
> web component, because I don't want abra to know about the CRM
> system. That's too hardcoded. Abra is just about information and
> relationships. But one of those relationships can be to a CRM. So
> all of the contacts, like the whole category of contacts basically,
> can be something where I'd be like, under this category, we enable
> this capability, which is to connect these things under this
> category to the CRM. So that feels right that everything under
> contacts can be sort of live-connected to the CRM for me. But that
> would be something that's sort of configuration or data for me
> that's not a universal abra thing. Other people have a different
> opinion about how they wanna deal with their contacts, or whether
> they even have a contacts category. So we don't wanna hard-code
> that. But for me, I want to be able to say that my contacts are
> connected to my CRM and that one of the actions I want to have on
> those is to be able to create a reminder for myself.

---
</content>
