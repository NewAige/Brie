# Raising a prompt from Community to Bank

**Status: not built.** This documents the intended model and what an
implementation would have to get right. Nothing in the app currently offers a
"raise to Bank" action.

## The rule

Bank is not a tier you publish *into*. It is a tier a prompt is *promoted to*,
by a Bank Approver, after it is already live in the Community library.

Every authoring path therefore produces a Community prompt:

- **New prompt** (`POST /api/prompts`) hard-codes `level: community`
  (`backend/app/routers/prompts.py`).
- **Publishing a draft** (`POST /api/drafts/{path}/publish`) accepts a `level`,
  but the UI no longer offers a choice — `frontend/src/pages/Drafts.jsx` always
  sends `community`, for approvers too.

The `level: "bank"` branch in `publish_draft` is the last remnant of the old
"choose your tier at publish time" model. It is still gated to approvers
server-side, so it is not a hole, but it is no longer reachable from the UI and
should be removed when the promotion flow below lands.

## Why promotion rather than choice at creation

A Bank prompt is one whose every future edit requires a Bank Approver. Granting
that at creation lets an approver mint bank-tier content in a single step, with
no separate record of the decision and no version of the prompt that anyone
reviewed in the library first. Promotion separates authorship from the
governance decision: the prompt exists, is visible, and has a history before
anyone raises its tier.

## What an implementation needs

A `POST /api/prompts/{path}/level` endpoint, approver-only, that flips
front-matter `level: community` → `bank`, plus a "Raise to Bank" action on
`PromptDetail` visible only when `level === 'community'` and the viewer is an
approver.

Three things it must get right:

1. **It is a real authorization boundary, not a UI affordance.** Gate on
   `roles.derive_role` server-side, exactly as `drafts.py:_is_approver` does.
   Hiding the button is not the control.

2. **It must not become a self-merge.** `ownership.decide` deliberately refuses
   to owner-merge any PR whose head turns a community file into `level: bank`
   (`levels_on_head` check) — precisely so a bank prompt cannot be minted
   without an approver seeing it. A promotion endpoint that opened a PR and
   auto-merged it under the promoting approver's own ownership would route
   around that check. Promotion should go through the normal approver merge
   path, or commit directly under an explicit approver-only route — not through
   `try_publish_now`.

3. **Demotion is a separate question.** Bank → Community hands maintenance back
   to an owner who may no longer exist, or who never agreed to it. Decide who
   may do it and who inherits ownership before building it; it is not simply
   the same endpoint with the values swapped.

## Related

- `docs/phase-2-ownership.md` — the ownership predicate and why main is the
  sole authority on ownership facts.
- `backend/app/ownership.py` — `decide`, including the `levels_on_head` guard
  that this feature must not undermine.
