# Prompt Library Phase 3: Three Levels (Bank / Community / Personal) + Four Roles

## Context

The library today is a **flat, single-tier catalog**: one Gitea repo (`bank/prompt-library`), folders = categories, every prompt governed identically (1-approval branch protection on `main`, plus phase-2 owner-merge letting a prompt's owner self-publish edits via the `pl-bot` service account). The target model adds a governance dimension:

- **Bank level** — controlled prompts; every change needs Bank Approver sign-off.
- **Community level** — owner-maintained shared prompts; the owner self-approves edits to their own prompts and reviews peers' suggestions.
- **Personal level** — private per-user drafts, invisible to others.

And four roles: **Browser** (read-only, cannot even suggest), **Contributor** (personal + community authoring, suggest on Bank), **Bank Approver** (today's Gitea-write approver), **Admin** (plus a minimal in-app user-management page).

**Gap vs. today:** no level taxonomy exists (only category + `status`, and `status` gates nothing except hiding `deprecated`); nothing is private ("Nothing in the app is private today" — docs/phase-2-ownership.md); every signed-in user can suggest/create (no Browser tier); approvers approve everything (no Bank scoping); Admin is a display label only.

**Decisions confirmed with the user:**
1. Personal drafts live in the user's **Gitea fork** (phase-3 Option A from docs) — real Gitea-enforced privacy.
2. Peer edits to Community prompts are **approved by the prompt owner** (extend owner-merge to owner-approves-others).
3. Browser vs Contributor = membership in a Gitea org team **`contributors`** (AD-group-synced in prod).
4. Admin surface = **minimal**: one page listing users/roles + contributors-team assignment via Gitea APIs.

## Design decisions

- **Level designation:** `level: bank | community` front-matter field, read **from `main`** (same discipline as `owner`). **Missing/invalid level ⇒ `bank`** — fail-closed; all 7 seed prompts become Bank with zero migration. Rejected folder-convention (folders are categories; would break every path rule) and separate-repo (multiplies index/search/write paths).
- **Level-change invariant:** a PR is owner/peer-mergeable only if every touched file is `community` **on main AND on the PR head**. Head check prevents an owner self-merging a flip to `level: bank` (forged bank-approved status). Bank files are never owner-mergeable — this *tightens* phase-2.
- **New files stay approver-gated** (existing "authoring is not ownership" rule stands). Contributors get instant-save via Personal drafts; "Publish" = send for review. Community self-approval applies to *edits* after first approval.
- **Roles stay derived live from Gitea** (no app-stored roles): `admin` perm → admin; `push` → approver; read + `contributors` team (via `GET /user/teams` with the user's own token, matched on team name + org) → contributor; read only → browser. Gitea error ⇒ browser (fail closed). 60s per-session role cache; mutating endpoints only are gated.
- **Drafts branch:** long-lived `drafts` branch in the user's fork, files at their real future `<category>/<slug>.md` path. Publish exports the single file through the existing `_propose_change` flow (fresh branch off synced fork main) so a publish PR never drags other drafts along. Level chosen at publish time.

## Phases (each independently shippable, in order)

### Phase A — Levels + tightened owner-merge ✅ DONE (2026-07-19, see Handoff notes)
- `backend/app/frontmatter.py` — `parse_prompt` emits `level` (`"community"` iff exactly that, else `"bank"`).
- `backend/app/ownership.py` — add `level_of(raw)` beside `owner_of` (fail-closed → `"bank"`); extend `decide` to take per-path `FileFacts(owner, level)` from main **plus** `levels_on_head`; deny unless community on both. `owner_mergeable` additionally fetches each path at `pr["head"]["sha"]` via `raw/{path}?ref=` (same try/except-deny pattern; still capped by `MAX_PR_FILES`).
- `backend/app/routers/prompts.py` — `_public` exposes `level`; `create_prompt` renders `level: community` for user-created prompts (approver reviews before it lands).
- Frontend: level badge on `PromptCard.jsx` / `PromptDetail.jsx` ("Bank approved" vs "Community · maintained by <owner>").
- Seed/template: add `level` + `owner` lines to `seed/prompt-library/_templates/prompt-template.md`; `level: bank` on seed prompts; one seeded community prompt owned by `uma.user` for demo.
- Tests (`backend/tests/test_ownership.py`, `test_frontmatter.py`): community+owned → allowed; bank+owned → **denied** (new tightening); absent level → bank → denied; community-on-main/bank-on-head → denied; mixed PR → denied; `level_of` junk → bank.

### Phase B — Browser role via `contributors` team
- New `backend/app/roles.py` — pure `derive_role(perms, team_names)` + async `get_role(session)` (`GET /repos/...` + `GET /user/teams`, org-checked, 60s TTL cache cleared on logout). `backend/app/routers/auth.py:83` `/api/me` delegates to it.
- `backend/app/deps.py` — `require_contributor` dependency (403 for browsers); applied to `suggest_edit` and `create_prompt` in `backend/app/routers/prompts.py`. GETs and `/events/copy` stay open.
- `frontend/src/App.jsx` — labels `Browser / Contributor / Bank Approver / Admin`; hide New-prompt / Suggest / Make-a-copy buttons for browsers (cosmetic; server re-checks).
- `scripts/seed.py` — create org team `contributors` (read perm), attach repo, add `uma.user`; add `ben.browser` account with plain read. Update `docs/deployment.md` AD mapping (staff → Browser; prompt-contributors team → Contributor; prompt-approvers → write).
- Tests: `derive_role` unit tests (push beats team; team+read → contributor; wrong-org team → browser); endpoint 403 for browser on suggest/create.
- **Verify in dev:** OAuth token works against `GET /user/teams` on the deployed Gitea version.

### Phase C — Owner approves peer suggestions (Community)
- `backend/app/ownership.py` — predicate already collapses to "merger owns every file, all community on main+head" regardless of PR author; add `pr_author` to `Decision` for audit.
- `backend/app/routers/pulls.py` — `list_pulls` annotates contributors' PRs and adds `needs_your_review` (allowed && author != me); `_owner_merge` message distinguishes self vs peer publish.
- `backend/app/db.py` — `owner_merges` gains `pr_author`, `kind` (`self`|`peer`) via guarded `ALTER TABLE` in `init_db`.
- `frontend/src/pages/Suggestions.jsx` — "Needs your review" filter + peer-approval button copy.
- Tests: peer author + owner merger + community → allowed; peer + bank → denied; merger not owner → denied.

### Phase D — Personal drafts (largest)
- Extract fork helpers (`_ensure_fork`, `_sync_fork`, commit helpers) from `backend/app/routers/prompts.py` into shared `backend/app/forks.py`.
- New `backend/app/routers/drafts.py` (prefix `/api/drafts`, all `require_contributor`): ensure fork + `drafts` branch; `GET /api/drafts` (recursive tree of drafts branch, `parse_prompt` each, annotate `on_main` / `pending_pr`); `POST` create (reuse `NewPrompt` model + `slugify` path derivation); `GET/PUT/DELETE /{path}`; `POST /{path}/publish {level}` → 409 checks then existing `_propose_change`.
- Frontend: `Drafts.jsx` page + "My drafts" nav (hidden for browsers); `NewPrompt.jsx` gains "Save as personal draft"; publish dialog with level choice.
- Docs: replace phase-3 sketch; state honestly that Gitea instance admins can read private forks (private from peers, not admins).
- **Verify in dev:** fork of private repo is created private; fork-name 409 collision surfaces a clear error; `sync_fork` never touches `drafts`; approvers (write users) can fork.
- Tests: path validation reuse; publish rendering includes chosen level; 409 on existing path / pending PR; browser 403 on all drafts endpoints.

### Phase E — Minimal Admin page
- New `backend/app/routers/admin.py` (`/api/admin`, `require_admin` via the admin's own token — never the bot): `GET /users` (org members + contributors-team membership + collaborator perms); `PUT /users/{username}/contributor {member}` (team member add/remove).
- Frontend: `AdminUsers.jsx` + `/admin` route for role `admin`.
- Docs: note that team mutation needs Gitea **org owner** (surface 403 verbatim), and LDAP team-sync overwrites manual assignment in prod (page becomes advisory there).
- Tests: non-admin 403; users-list shape with mocked Gitea payloads.

## Invariants to preserve throughout
- Merge-time re-check: buttons are advisory; `merge_pull` always re-runs `owner_mergeable` before the bot acts.
- Owner/level always read from `main` (plus head for level); never trust the PR's version for authorization.
- Everything fails closed: unreadable/unparseable ⇒ bank / unowned / browser.
- Bot account scope stays `write:repository`; admin endpoints use the admin's own token.

## Handoff notes

### Phase A — implemented 2026-07-19 (this working tree, uncommitted)

**What landed** (all bullets from the Phase A plan):

- `backend/app/frontmatter.py` — new `prompt_level(meta)` helper (`"community"` iff the front-matter says exactly that as a scalar; anything else — missing, `Community`, a list, junk YAML — is `"bank"`). `parse_prompt` now emits `level`, so `/api/prompts`, `/api/prompts/{path}` and the search index all carry it with no further changes (`prompt_index.py` builds entries via `parse_prompt`).
- `backend/app/ownership.py` — `level_of(raw)` added beside `owner_of`. `decide` signature changed: `decide(username, paths, facts_on_main: dict[str, FileFacts | None], levels_on_head: dict[str, str])` where `FileFacts(owner, level)` is read from main. Denies unless every touched file is owned by the merger **and** `community` on main **and** `community` on the PR head; a path missing from `levels_on_head` denies (covers delete-on-head and unreadable-head). `owner_mergeable` now also fetches each path at `pr["head"]["sha"]` via `raw/{path}?ref=` (same fail-closed try/except; missing head sha denies; still capped by `MAX_PR_FILES`). Callers of `owner_mergeable` (pulls.py) needed no changes — its signature is unchanged.
- `backend/app/routers/prompts.py` — `_public` exposes `level`; `create_prompt` renders `level: community` in new-prompt front-matter (placed after `status`, before `author`, matching the template order).
- Frontend — new `frontend/src/components/LevelBadge.jsx` ("Bank approved" / "Community · maintained by <owner>", with a `compact` variant for cards showing just "Community"); wired into `PromptCard.jsx` and `PromptDetail.jsx`; `.badge-bank` / `.badge-community` styles in `styles.css`. Also tightened the existing "You maintain this" badge in `PromptDetail.jsx` to show only for `community` prompts — its tooltip promises approver-free publishing, which is no longer true for owned bank files.
- Seed — `_templates/prompt-template.md` gains `level` + `owner` lines; all 7 existing seed prompts got `level: bank`; new demo community prompt `internal-ops/weekly-status-update-drafter.md` (`level: community`, `owner: uma.user`, status approved).
- Tests — `test_ownership.py` rewritten for the new `decide` signature; new cases: owned bank file denied (the tightening), community-on-main/bank-on-head denied (forged-level attack), missing head level denied, mixed-level PR denied, `level_of` junk table. `test_frontmatter.py` covers `parse_prompt`'s `level` default and exact-match rule. **`python -m pytest tests -q` → 47 passed.** (Run needs the usual dummy env vars — `GITEA_PUBLIC_URL` etc. — since `config.py` loads settings at import.)

**Deviations from the plan wording:** none material. The level-parse logic lives once in `frontmatter.prompt_level`; `ownership.level_of` is a thin wrapper over it (the plan sketched them as siblings — kept single-source instead).

**Not yet done / for the next session:**

1. **Not committed** — the working tree holds all Phase A changes plus PLAN.MD; review and commit.
2. **Dev-stack re-seed caveat:** `scripts/seed.py::push_seed_content` treats 409 as "already present" and never updates existing files. An **existing** dev Gitea will therefore keep seed prompts *without* `level` lines (they'll correctly render as Bank via fail-closed default, so this is cosmetic-only), and will *gain* the new community demo prompt. For a clean demo of the community flow, wipe the Gitea volume and re-seed, or manually commit the `level:` lines to the dev repo.
3. **End-to-end check not run** (no dev Gitea up in this session): item 5 of the Verification section — the forged-level PR — exercises the new `raw/{path}?ref=<head sha>` fetch against a real Gitea and is the one integration path unit tests can't cover. Do this when the stack is next up.
4. **Phase B is next** (Browser role via `contributors` team). Nothing in Phase A blocks it. Note for Phase B's seed work: `scripts/seed.py` currently gives `uma.user` plain read — Phase B moves contributor-ness to the org team, and adds `ben.browser`.

## Verification (end-to-end, dev stack)
1. Run `scripts/seed.py` against dev Gitea; confirm accounts `ben.browser` / `uma.user` / `adam.approver` and the `contributors` team.
2. As **ben.browser**: browse/search/copy works; New-prompt/Suggest hidden; direct `POST /api/prompts` → 403.
3. As **uma.user** (contributor): save a personal draft → invisible to adam in Gitea and the app; publish as community → PR → adam approves → prompt shows Community badge; edit own community prompt → "Publish" self-merge works; edit a **bank** prompt → only "Send for review" (owner-merge denied).
4. Peer flow: adam (or a second contributor) suggests an edit to uma's community prompt → uma sees "Needs your review" and publishes it; audit row records `kind=peer` + both usernames.
5. Attempt the forged-level attack: PR that flips `level: community → bank` on an owned file → owner-merge denied.
6. As **pl-admin**: `/admin` lists users; toggling uma's contributor membership changes her role chip on next login/cache expiry.
7. `pytest backend/tests` green, including the new ownership/level/role suites.
