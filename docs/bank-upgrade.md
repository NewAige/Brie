# Raising a prompt from Community to Bank

**Status: not built — this is the design.** Nothing in the app offers a
"raise to Bank" action yet, but the UI already promises one: the draft publish
dialog tells every contributor *"A Bank Approver can raise it to Bank once
it's live"* (`frontend/src/pages/Drafts.jsx`). This document is the model that
promise commits us to: what already exists in the code, the intended design,
and what an implementation has to get right.

**Depends on:** PLAN.MD phases A–E (levels, roles, peer approval, drafts,
self-publish) — all shipped.

## The rule

Bank is not a tier you publish *into*. It is a tier a prompt is *promoted to*,
by a Bank Approver, after it is already live in the Community library.

Every authoring path therefore produces a Community prompt:

- **New prompt** (`POST /api/prompts`) hard-codes `level: community`
  (`backend/app/routers/prompts.py::create_prompt`) and, being community,
  self-publishes immediately via `pulls.try_publish_now`.
- **Publishing a draft** (`POST /api/drafts/{path}/publish`) accepts a
  `level`, but the UI always sends `community` — for approvers too
  (`frontend/src/pages/Drafts.jsx`). See "The dangling bank branch" below.
- **Suggest an edit** (`POST /api/prompts/{path}/suggest`) rewrites the body
  only, via `frontmatter.replace_body` — front-matter, including `level`, is
  preserved byte-for-byte. An edit cannot change a prompt's tier at all.

## Where the code stands today

The *enforcement* side of levels is fully built; only the promotion action is
missing. What exists, and where:

| Piece | State |
|---|---|
| `level` taxonomy (`community` / `bank`, fail-closed to `bank`) | Built — `frontmatter.prompt_level`, wrapped by `ownership.level_of` |
| Bank prompts never owner-mergeable | Built — `ownership.decide` denies unless `level: community` on main |
| Level flip cannot ride an owner-merge | Built — `decide` also requires `community` on the PR head (`levels_on_head`) |
| New prompts forced to community for self-publish | Built — phase E arm of `decide`: new file must declare `level: community` |
| Level badge in the UI | Built — `frontend/src/components/LevelBadge.jsx` ("Bank approved" / "Community · maintained by …") |
| Bank-level publish gated to approvers server-side | Built — `drafts.py::publish_draft` + `_is_approver` |
| **A way to raise a live community prompt to Bank** | **Missing — this document** |

One consequence worth stating plainly: because nothing can flip a level today,
the seven bank-level seed prompts are the *only* Bank prompts that can exist
through the app's own UI. The tier the whole governance model is named
for is currently unreachable for new content. That is the gap promotion fills.

## Why promotion rather than choice at creation

A Bank prompt is one whose every future edit requires a Bank Approver.
Granting that status at creation lets an approver mint bank-tier content in a
single step, with no separate record of the decision and no version of the
prompt that anyone reviewed in the library first. Promotion separates
authorship from the governance decision:

1. **The prompt exists first.** It is visible, copyable, and has history
   before anyone raises its tier. The thing being promoted is a concrete,
   reviewable artifact on `main` — not whatever an author says it will be.
2. **The decision has its own record.** Promotion is one commit that changes
   one line, made by an identifiable approver. "Who decided this is
   bank-grade, and when" is answerable from history without archaeology.
3. **The model stays simple to state:** everything starts community;
   Bank status is only ever granted, explicitly, by the role that will be
   accountable for every subsequent change.

## The dangling bank branch in `publish_draft`

`publish_draft` still accepts `level: "bank"` — the last remnant of the old
"choose your tier at publish time" model. It is gated to approvers
server-side (`_is_approver`), so it is not a hole, but the UI no longer sends
it: `Drafts.jsx` always publishes to community, for approvers too.

`create_prompt`'s comment currently describes this branch as the intentional
approver path into Bank. The promotion model supersedes that: **when the
endpoint below lands, remove the bank branch** (and its `_is_approver` gate,
tests, and the `Literal` widening) so that promotion is the *only* way a
prompt enters the Bank tier. One path means one audit story, one confirm
dialog, one place a mistake can happen — and even approvers' new prompts get
a lived-in community version before anyone commits to gating its every edit.

## Design

### Endpoint

```
POST /api/prompts/{path}/level      body: {"level": "bank"}
```

- Approver-only, checked **server-side** via `roles.get_role` — a new
  `require_approver` dependency in `deps.py`, beside `require_contributor`
  and `require_admin` (and replacing `drafts.py::_is_approver`, which is the
  same check inlined).
- v1 accepts only `Literal["bank"]`. Demotion is not the same endpoint with
  the values swapped (see below); constraining the type makes it
  structurally impossible until it is actually designed.
- 404 for an invalid path or a prompt not on `main`; 409 if the prompt is
  already `level: bank` — promotion is not idempotent-by-silence, the caller
  should know the state moved under them.

### Execution: a direct commit, not a suggestion

Branch protection on `main` has `enable_push: true` (`scripts/seed.py`) —
approvers hold write access and may push directly; only *merges* require an
approval. So promotion is a **single direct commit to `main`, made with the
promoting approver's own token**:

1. `GET contents/{path}?ref=main` with the approver's token — current text
   plus the blob sha.
2. Parse, verify `level == "community"` (409 otherwise), re-render the
   front-matter with `level: bank`, **body byte-identical**.
3. `PUT contents/{path}` on `main` with the blob sha from step 1 and a
   message naming the decision: `Raise to Bank: <title>` /
   `Raised by <approver>. Every future change now requires a Bank Approver.`

Why not open a PR and merge it through the normal review path:

- Gitea refuses self-approval, so an approver's own promotion PR would need a
  *second* approver — a stricter rule than we want, arrived at by accident.
- Routing it through the bot instead would mean teaching the owner-merge
  machinery an exception to its own `levels_on_head` guard (see below) —
  weakening the one check that makes forged Bank status impossible.
- The commit *is* the review record: an approver with push rights changing
  one line under their own name needs no ceremony on top.

Gitea remains a real second layer: even if the app's role check were somehow
bypassed, a non-writer's token cannot push to `main`.

### Concurrency

The Gitea contents API requires the current blob sha on update, which gives
compare-and-swap semantics for free: if the file changes between read and
write (an owner-merge lands mid-promotion), the PUT fails and the endpoint
returns a retryable conflict rather than silently clobbering the newer
version. Do not retry internally — re-reading means re-deciding, and the
approver should see what changed first.

### What falls out for free

- **The index updates itself** — `prompt_index` rebuilds when `main`'s head
  sha changes, which the promotion commit does.
- **Pending self-publishes are instantly revoked.** The Suggestions list's
  "Publish" button is advisory; `merge_pull` re-runs `owner_mergeable` at
  click time, which re-reads the level from `main`. Any open suggestion to
  the promoted prompt — the owner's own or a peer's — silently falls back to
  the approver flow the moment the commit lands. No queue to sweep.
- **The badge flips** — `LevelBadge` and `_public` already render whatever
  `main` says.

### Audit

Git is the authoritative record: the commit is authored by the approver's own
token and its message states the decision. Two things it does *not* cover:

- The **activity feed** (`routers/activity.py`) lists merged PRs; a direct
  commit will not appear there. If promotions should show up in-app, log a
  row (a `level_changes` table beside `owner_merges` — approver, path,
  timestamp) and merge it into the feed. Reasonable v1 cut: git-only, add
  the table when someone actually asks "who raised this?" inside the app.
- The **owner is not notified**. v1 has no notification machinery at all;
  the honest minimum is the confirm-dialog copy below, which makes the
  approver aware they are changing someone else's working arrangement.

## What the implementation must get right

1. **It is a real authorization boundary, not a UI affordance.** Gate on
   `roles.get_role` server-side. Hiding the button is not the control; the
   403 is. Fail closed like every other check: a Gitea error while deriving
   the role means `browser`, which means denied.

2. **It must not become a self-merge.** `ownership.decide` deliberately
   refuses to owner-merge any PR whose head turns a community file into
   `level: bank` (the `levels_on_head` check) — precisely so a Bank prompt
   cannot be minted without an approver deciding it. A promotion endpoint
   that opened a PR and pushed it through `try_publish_now` or `_owner_merge`
   would route around that check, or force an exception into it. Promotion
   goes through the direct-commit path above — the bot is never involved,
   and `ownership.py` does not change.

3. **Never trust the caller's view of the current level.** Read the prompt
   from `main` inside the endpoint, decide there, and let the sha-guarded
   write catch the race. The button's visibility (`level === 'community'` on
   a page loaded minutes ago) is a hint, nothing more — the same discipline
   as the merge-time re-check in `pulls.py`.

4. **Change one line.** The promotion commit re-renders front-matter with
   only `level` changed and the body untouched. A promotion that also
   "tidies" content is an unreviewed edit wearing a governance hat — and it
   makes the diff, which is the audit record, lie about what was decided.

## UI

- **`PromptDetail`**: a "Raise to Bank" action, rendered only when
  `level === 'community'` and the viewer's role is approver or admin
  (cosmetic — the server re-checks).
- **Confirm dialog**, because this changes another person's working
  arrangement and is not self-servedly reversible:

  > Raise **{title}** to Bank?
  > Bank prompts can only be changed with a Bank Approver's sign-off.
  > **{owner}** currently maintains this prompt and will no longer be able
  > to publish edits on their own.

- Per the UI-language invariant, nothing here says branch, commit, pull
  request, or fork — "raise", "sign-off", "publish".
- The owner's next visit tells the story passively: the "You maintain this"
  badge (already community-only since phase A) disappears, the badge reads
  "Bank approved", and their edit path offers only "Send for review".

## Demotion is a separate question

Bank → Community is **deliberately out of scope**, and not because it is the
same code with the values swapped. Promotion *removes* a permission and needs
only the remover's authority. Demotion *re-arms* one, and here is the trap:

Bank prompts keep their `owner:` front-matter — promotion must not strip it
(it records maintainership, and the "mine" filter in `list_prompts` uses it).
That owner may have left the bank, changed teams, or never agreed to maintain
the prompt again. The instant the level flips back to `community`, that
possibly-stale owner regains unattended self-publish over a prompt that spent
its Bank tenure under mandatory review. A demotion feature therefore has to
decide, before it is built:

- who may demote (approver? admin only? the approver who promoted?),
- who the receiving owner is — an explicit, confirmed assignment as part of
  the same commit, never whatever name happens to be in the front-matter,
- and whether the demoted prompt's Bank-era history needs marking.

Until then, the escape hatch is honest and adequate: an approver can edit
`level:` (and `owner:`) through the ordinary suggestion flow, where a second
approver reviews the change like any other.

## Testing

Unit (no Gitea, same style as `test_ownership.py` / `test_drafts.py`):

- browser / contributor → 403; the check hits `roles.get_role`, not a UI flag
- approver, community prompt on main → commit body has `level: bank`, body
  byte-identical to what main held, message names the approver
- already `bank` on main → 409, no write
- path not on main / invalid path → 404, no write
- blob-sha conflict from Gitea → surfaced as a retryable conflict, no retry
- `level` values other than `"bank"` → 422 (the `Literal` gate)
- regression: `decide` still denies community-on-main / bank-on-head — the
  guard promotion must not undermine (already in `test_ownership.py`; keep)
- `publish_draft`: the removed bank branch — publish always renders
  `level: community`, approver or not; update the phase-D tests accordingly

Integration (dev stack, extends the PLAN.MD checklist):

1. `uma.user` publishes a community prompt; `adam.approver` raises it to
   Bank → badge flips, promotion commit on `main` authored via adam's token.
2. uma opens the prompt: "You maintain this" gone, only "Send for review".
3. A suggestion opened *before* promotion no longer shows "Publish" for uma
   after it — and the merge endpoint refuses the owner path if she clicks a
   stale button.
4. uma calls `POST /api/prompts/{path}/level` directly → 403.
5. Raise the same prompt twice → second call 409s.

## Related

- `docs/phase-2-ownership.md` — the ownership predicate, and why `main` is
  the sole authority on ownership facts.
- `backend/app/ownership.py` — `decide`, including the `levels_on_head`
  guard this feature must not undermine, and the phase-E self-publish arm
  that makes "everything starts community" livable for authors.
- PLAN.MD "Design decisions" — why `level` is front-matter read from `main`,
  and why missing/invalid means `bank`.
