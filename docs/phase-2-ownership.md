# Phase 2 — Prompt ownership and author merge rights

**Status:** built. Predicate in [`ownership.py`](../backend/app/ownership.py),
merge path in [`pulls.py`](../backend/app/routers/pulls.py), unit tests in
[`test_ownership.py`](../backend/tests/test_ownership.py). Requires
`BOT_USERNAME`/`BOT_TOKEN` in `.env` (blank disables owner-merge); the dev
service account is provisioned by `scripts/seed.py`. Integration testing
against the dev stack is still outstanding.
**Depends on:** phase 1 (create + copy prompts), shipped — every prompt created
through the app already carries `owner:` in its front-matter.

## Goal

An author can publish changes to a prompt **they own** without waiting for an
approver. Everything else — edits to prompts they don't own, and any change
touching more than one owner's prompts — still needs an approver.

Concretely: the EMEA team copies `customer-support/account-balance-faq.md`,
gets their own prompt, and from then on maintains it themselves. They never
gain the ability to approve edits to anyone else's prompt.

---

## Where phase 1 left things

| Piece | State |
|---|---|
| `owner:` in front-matter | **Written** on create and copy (`create_prompt`, [`prompts.py`](../backend/app/routers/prompts.py)) |
| `owner` / `copied_from` in the API | **Exposed** via `_public()` and `parse_prompt()` |
| Anything reading `owner` for authorization | **Nothing** — it is inert metadata today |
| Merge authorization | Entirely Gitea's; the app enforces nothing ([`pulls.py`](../backend/app/routers/pulls.py) docstring says so explicitly) |

Prompts that predate phase 1 (the seed content) have **no** `owner` field. They
are unowned, and must stay approver-only. See "Migration" below.

## The constraint that decides the design

Current branch protection on `main` (from `scripts/seed.py`, confirmed live):

```
required_approvals: 1
enable_approvals_whitelist: false     ← any user with write access may approve
enable_merge_whitelist: false
block_on_rejected_reviews: true
```

`/api/me` derives role from real repo permissions: `admin` → admin,
`push` → approver, otherwise → user.

So a member (`uma.user`) has **no** write access. They cannot approve or merge
anything, including their own prompt. And the naive fix is a trap:

> Granting a member write access so they can merge their own prompt
> **also gives them approval rights over every other prompt**, because
> `enable_approvals_whitelist` is false. There is no per-file permission
> in Gitea that expresses "may merge only files they own."

Therefore **owner-merge cannot be delegated to Gitea**. It must be authorized
by the app, and executed with a credential that has merge rights — a service
account. That makes the app a real security boundary for the first time, which
is why the checks below are written defensively.

---

## Design

### 1. Ownership model

`owner` is a single Gitea username, v1. Read from front-matter on `main` —
never from the PR's own version of the file (see Security).

Team ownership is deliberately deferred, but the field is forward-compatible:
resolving `owner` against Gitea teams later widens who matches without a
schema change or a migration.

### 2. Authorization rule

A PR is **owner-mergeable** by user `U` when *all* of:

1. Every file the PR touches is a valid prompt path (`is_prompt_file`).
2. Every one of those files **already exists on `main`**. A PR that creates a
   new prompt is never owner-mergeable — otherwise anyone could self-publish a
   brand-new prompt by writing `owner: themselves`, which is authoring, not
   ownership.
3. For every touched file, `owner` **as read from `main`** equals `U`.
4. The PR touches at least one file, and is open and mergeable.

Any file failing any check ⇒ not owner-mergeable ⇒ normal approver flow. The
mixed-ownership PR is the case naive checks leak; rule 3 covers it by
quantifying over *all* files, not any.

### 3. Merge execution

```
POST /api/pulls/{id}/merge
  ├── user is approver/admin ──────────► existing path: user's own token
  └── user is a member
        ├── owner_mergeable(user, pr)? ─► service account approves + merges
        └── otherwise ──────────────────► 403, existing message
```

The service account (`pl-bot`, write access, credential in env alongside the
OAuth secret) is used **only** after the app's own check passes, and only for
that one PR id. It is never used for reads — those stay on the user's token so
Gitea's access control keeps applying.

Merge commit message records both identities:
`Publish (owner merge): <title>` … `Merged by <user> as owner of <path>.`

### 4. UI

- Prompt detail, when `owner == me`: badge reading **"You maintain this"**.
- Suggestions list: a PR that is owner-mergeable by the viewer gets
  **"Publish"** instead of the approver's "Approve & publish", with helper text
  "You own this prompt — publishing applies your change immediately."
- Everyone else's view is unchanged.

### 5. Transferring ownership

Out of scope for phase 2, but needs an answer before this ships to real teams:
if the owner leaves, an admin must be able to reassign. Simplest version —
`owner` is an ordinary front-matter field, so an approver can already change it
through the normal suggest-edit flow. Worth confirming that is sufficient
rather than building a transfer UI.

---

## Security

The app becomes the authority, so these are load-bearing:

- **Read `owner` from `main`, never from the PR.** Reading it from the PR head
  lets an author add `owner: me` to someone else's prompt in the same PR that
  edits it, and self-approve. This is the single most important rule here.
- **Re-check immediately before merging**, not only when rendering the button.
  The PR can gain commits between page load and click.
- **Fail closed.** Any error reading a file, parsing front-matter, or listing
  PR files ⇒ not owner-mergeable. Never treat "couldn't determine" as "allowed".
- **Cap PR file count** (e.g. 50). Beyond that, fall through to approver
  review rather than paginating a security check.
- **Log every owner-merge** — actor, PR id, paths — so the bypass is auditable.
  Existing copy-event logging is deliberately PII-free; this is a different
  category and does need the username.

## Testing

Unit tests (no Gitea) over the predicate, given a fake file/PR fixture:

- single owned file → allowed
- single unowned file → denied
- **two files, one owned one not → denied** (the leak case)
- new file not on main, even with `owner: me` → denied
- `owner` absent (seed prompts) → denied
- `owner` differs between main and PR head → denied, uses main's value
- empty file list → denied

Integration, against the dev stack: `uma.user` copies a prompt, an approver
publishes it, then `uma.user` edits and publishes their own copy without an
approver — and is still refused on `adam.approver`'s prompt.

## Migration

Seed prompts have no `owner`, so they stay approver-only — correct default, no
backfill required. If you want existing prompts owned, an admin sets `owner`
per file through the normal edit flow. Do **not** bulk-assign ownership by
guessing from `author:` or git history; `author` records who wrote it, which is
not the same claim as who may publish without review.

## Out of scope (deliberately)

- Team ownership (field is forward-compatible; see above)
- Ownership transfer UI
- Private prompts — see below

---

## Appendix: private prompts (phase 3 sketch)

Asked during phase 2 planning; recorded here so phase 2 doesn't foreclose it.
**Nothing in the app is private today** — one repo, every signed-in user reads
all of it, and `status: draft` hides nothing (Browse filters only `deprecated`).

Three options, in increasing cost:

| | Mechanism | Verdict |
|---|---|---|
| **A. Personal drafts in the user's fork** | Prompt lives in the author's existing Gitea fork; visible only to them until they choose "Publish", which opens the PR | **Recommended.** Honest privacy — enforced by Gitea permissions, not UI. Needs the index to read the user's fork alongside `main`. |
| **B. `visibility: private` field** | One repo, a field hides it from other users in the app | **Not real privacy.** Anyone with Gitea access can clone the repo and read it. Acceptable only as noise reduction, and must not be labelled "private". |
| **C. Team-scoped repos** | Separate repo per team with real permissions | Correct for genuinely confidential content, but multi-repo touches indexing, search, categories, and every write path. |

Option A composes naturally with phase 2: a fork is already per-user, phase 1
already commits there for read-only members, and "publish my draft" is the
existing PR flow with the owner-merge rule applied. If private prompts are
wanted, do A after phase 2 rather than folding it in.
