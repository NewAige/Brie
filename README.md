# Prompt Library

An internal web app where bank staff browse, search and **copy** approved AI
prompts, and suggest improvements that go through a review-and-approve
workflow before publication.

**One-line architecture:** Gitea is the engine; this app is a pretty,
prompt-focused client. Prompts are plain markdown in git — if this app
disappears tomorrow, nothing is lost.

```
Browser ──> frontend (nginx, static React bundle)
                │  /api  /auth
                ▼
            backend (FastAPI) ──> Gitea API (as the signed-in user)
                │
                ▼
            SQLite (copy-event log + sessions only — no prompt data)
```

Three containers, one `docker-compose.yml`:

| Service    | What it is                                    |
|------------|-----------------------------------------------|
| `gitea`    | Self-hosted Gitea 1.24, SQLite backend. Owns auth, repos, PRs, RBAC. |
| `backend`  | FastAPI. OAuth2 flow, Gitea API proxy, front-matter parsing, copy-event log. |
| `frontend` | Static React bundle served by nginx, which proxies `/api` and `/auth` to the backend. |

## Quick start (local development)

Prerequisites: Docker with the compose plugin, Python 3.10+.

```bash
python3 scripts/seed.py
```

That single command starts Gitea, provisions test users, the `bank/prompt-library`
repo with sample prompts, branch protection (1 approval required on `main`),
registers the OAuth application, writes `.env`, and starts the app.

Then open **http://localhost:8080** and sign in as:

| Account         | Password       | Role     | Can                                       |
|-----------------|----------------|----------|-------------------------------------------|
| `uma.user`      | `Password123!` | Member   | Browse, search, copy, suggest edits       |
| `adam.approver` | `Password123!` | Approver | All of the above + approve & publish      |
| `pl-admin`      | `seed-admin-pass-1` | Admin | Everything, incl. Gitea administration |

In production there are no local accounts: Gitea authenticates against
Active Directory via LDAP — see [docs/deployment.md](docs/deployment.md).

## How it works

- **Prompts are markdown files** in one Gitea repo. Folders are categories;
  `_templates/` is excluded from browsing. Each file is YAML front-matter
  (title, tags, status, …) plus the prompt body.
- **The copy button copies only the body** — never the front-matter. The
  split lives in one place (`backend/app/frontmatter.py`) and is unit-tested.
- **"Suggest an edit"** creates a branch, commit and pull request behind the
  scenes with the *suggester's own token*, so git history records them as the
  author. Users with read-only access are transparently given a fork. The UI
  never says "branch", "commit" or "pull request".
- **Approvers review and merge** from the Suggestions page. Whether someone
  may merge is decided by Gitea (branch protection on `main` + team/collaborator
  permissions), never by this app's code.
- **Roles are resolved from Gitea**: repo admin → Admin, write → Approver,
  read → Member. OAuth scopes do not grant permissions — Gitea checks the
  user's real rights on every call.
- **Activity** shows recently published changes (from Gitea) plus engagement
  leaderboards: top authors (front-matter authors), top contributors (merged
  suggestions from Gitea), and most favorited / copied / remixed prompts.
  Copy and remix events are logged locally as `prompt path + timestamp` and
  nothing else — no user id, no content, no PII. Favorites store
  `username + prompt path` (needed so a prompt can be starred once per user),
  but never any prompt content.
- **"Save as new prompt"** lets anyone copy an existing prompt into a new
  draft prompt of their own (credited via `derived_from` front-matter); it
  goes through the same review flow as suggestions.

## Security properties

- The app **never sees a password** — sign-in happens on Gitea (which
  delegates to AD/LDAP in production). OAuth2 Authorization Code flow,
  confidential client, `state` verified against CSRF.
- **Gitea tokens live server-side only.** The browser gets an httpOnly,
  SameSite=Lax (Secure in production) session cookie and nothing else —
  nothing token-like in `localStorage`/`sessionStorage` or readable by JS.
- **No service account.** Every read and write to Gitea carries the
  individual user's token; Gitea enforces the real permissions per request.
- Silent token refresh keeps sessions alive without re-login.
- **No external network calls at runtime**, server-side or browser-side:
  all frontend assets are bundled locally (no CDNs, no web fonts), Gitea runs
  in offline mode with mirrors/webhooks/update-checker disabled, and
  dependencies are installed at build time (point the Dockerfiles at internal
  mirrors via build args in production).

## Repository layout

```
backend/     FastAPI app (see backend/app/) + unit tests
frontend/    React app (Vite) + nginx config
seed/        Sample prompt-library content used by the dev seed script
scripts/     seed.py — one-command local dev environment
docs/        deployment.md — production install, LDAP, TLS, backups
```

## Running the backend tests

```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest tests -q
```

(The parsing and path tests also run with no dependencies beyond PyYAML:
they're plain functions with asserts.)

## v1 scope guardrails

Deliberately **not** in this app: model calls of any kind (no "run this
prompt"), comment threads, analytics beyond most-copied, mobile. See the
build spec, §2.
