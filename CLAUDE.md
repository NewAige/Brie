# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An internal bank Prompt Library: staff browse, search and copy approved AI prompts, and suggest changes through a review-and-approve workflow. **Gitea is the engine; this app is a prompt-focused client.** Prompts are plain markdown in one Gitea repo (`bank/prompt-library`) — the app stores no prompt data of its own.

`PLAN.MD` is the build spec. Code comments reference it by section (e.g. "spec §8") and by phase (A: levels, B: roles, C: audit, D: drafts, E: self-publish); read the relevant section before changing behavior it specifies.

## Commands

```bash
# One-command local dev environment (starts Gitea, provisions users/repo/OAuth,
# writes .env, starts all containers). App at http://localhost:8080.
python3 scripts/seed.py

# Backend tests — no environment or running Gitea needed (conftest.py sets dummy env vars)
cd backend
pip install -r requirements-dev.txt
python -m pytest tests -q
python -m pytest tests/test_ownership.py -q        # single file
python -m pytest tests -k owner_mergeable -q       # single test by name

# Backend outside docker (needs .env values in the environment)
cd backend && uvicorn app.main:app --port 8000

# Frontend dev server (proxies /api and /auth to localhost:8000)
cd frontend && npm run dev
npm run build

# Full stack via docker
docker compose up -d --build
```

There is no linter configured. Test credentials for the seeded dev environment are in README.md (e.g. `uma.user` / `Password123!` for a Contributor).

## Architecture

Three containers (`docker-compose.yml`): `gitea` (port 3000, SQLite backend, owns auth/repos/PRs/RBAC), `backend` (FastAPI, not host-exposed), `frontend` (static React bundle served by nginx on port 8080, which proxies `/api` and `/auth` to the backend).

Backend (`backend/app/`):

- `gitea.py` — thin async client for the Gitea API. Every call carries the **individual user's OAuth token**; there is no service account for normal reads/writes, so Gitea enforces real permissions per request.
- `frontmatter.py` — the single place that splits YAML front-matter from the prompt body. The copy button copies **only the body**; keep that split here and unit-tested.
- `roles.py` — roles (`admin` / `approver` / `contributor` / `browser`) are **derived live from Gitea** (repo permissions + membership in the org's `contributors` team), cached 60s per session, never stored. Any Gitea error yields `browser`.
- `ownership.py` — the **only place the app makes its own authorization decision**: whether a PR is "owner-mergeable" (merged by the `pl-bot` service account on behalf of a prompt's owner). Governance levels apply: a file is owner-mergeable only if `level: community` on both main and the PR head; brand-new prompts are self-mergeable only by their PR author. Everything else defers to Gitea (branch protection on `main`, 1 approval required).
- `prompt_index.py` — in-memory index of all prompts, rebuilt only when main's head SHA changes. Access control is preserved because each request first fetches the head SHA with the requesting user's token.
- `forks.py` / `routers/drafts.py` — read-only users suggesting edits get a transparent fork; personal drafts live on a `drafts` branch in the user's own fork (privacy enforced by Gitea fork visibility, not app-side filtering).
- `routers/` — `auth` (OAuth2 code flow), `prompts`, `drafts`, `pulls` (suggestions/review), `activity`, `admin`.
- `db.py` — SQLite holds only sessions and copy events (`prompt path + timestamp`, no user id).

Frontend (`frontend/src/`): React 18 + react-router, no state library. `api.js` is the single fetch wrapper; pages in `pages/`, shared pieces in `components/`.

## Invariants to preserve

- **Fail closed.** Authorization checks (`roles.py`, `ownership.py`) treat any error — Gitea failure, malformed payload, unparseable front-matter — as "not allowed", never "allowed". Keep pure decision functions (`derive_role`, `ownership.decide`) separate from fetching so they stay unit-testable without Gitea.
- **Tokens never reach the browser.** Gitea tokens live server-side; the browser gets only an httpOnly session cookie. Nothing token-like in localStorage or readable by JS.
- **Whether someone may merge is decided by Gitea** (branch protection + permissions), except the owner-merge path in `ownership.py`, which is why that file is written so defensively.
- **The UI never says "branch", "commit", "pull request" or "fork"** — git is an implementation detail; user-facing language is "suggest an edit", "publish", "suggestions".
- **No external network calls at runtime**, server-side or browser-side: all frontend assets bundled locally, dependencies installed at build time only.
- Every authoring path produces a `level: community` prompt. Bank tier is promotion-only and **not yet built** — see `docs/bank-upgrade.md` before touching levels.

## v1 scope guardrails

Deliberately out of scope (PLAN.MD §2): model calls of any kind (no "run this prompt"), comment threads, analytics beyond most-copied, mobile.
