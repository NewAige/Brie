# Production deployment

One Linux VM (2 vCPU / 4 GB is generous), Docker with the compose plugin,
internal network only. IT owns the VM, patching and backups; the app owner
owns the application code and containers.

## 1. Install

```bash
# as a deploy user on the VM
git clone <internal-git-url>/prompt-library-app.git /opt/prompt-library
cd /opt/prompt-library
cp .env.example .env        # fill in below
docker compose up -d gitea  # start Gitea first
```

Production values in `.env`:

```
GITEA_PUBLIC_URL=https://git.internal.example.local     # or same host, different port
GITEA_INTERNAL_URL=http://gitea:3000
APP_PUBLIC_URL=https://prompts.internal.example.local
OAUTH_CLIENT_ID=      # from step 4
OAUTH_CLIENT_SECRET=  # from step 4
SESSION_SECRET=       # python3 -c "import secrets; print(secrets.token_urlsafe(48))"
REPO_OWNER=bank
REPO_NAME=prompt-library
COOKIE_SECURE=true
```

TLS: terminate with the internal CA cert at your standard reverse proxy (or
add certs to the nginx container). Both hostnames are internal-DNS only; no
external-facing ports.

Build-time dependencies must come from internal mirrors on an egress-blocked
VM — both Dockerfiles take build args:

```bash
docker compose build \
  --build-arg PIP_INDEX_URL=https://pypi.internal.example.local/simple \
  --build-arg NPM_REGISTRY=https://npm.internal.example.local
```

(Or build images on a connected build host and ship them over.)

## 2. Gitea initial setup

1. Create the instance admin account on first run:
   `docker exec -u git brie-gitea gitea admin user create --admin --username <name> --password <pw> --email <email>`
2. Create the `bank` organization and the private `prompt-library` repository
   (default branch `main`), seeded with `seed/prompt-library/` content or your
   real prompts. Folders are categories; keep `_templates/` for authoring templates.
3. **Branch protection on `main`** (repo → Settings → Branches): require at
   least **1 approval** before merge. If prompts touching customer-facing or
   regulated language need a second approver, add a second rule for those
   paths with 2 required approvals.

## 3. LDAP / Active Directory

Gitea → Site Administration → Authentication Sources → Add → LDAP (via BindDN):

- Host: your AD domain controller; port 636 (LDAPS) with the internal CA cert.
- Bind DN: the **AD service account** created for this (the one-time IT ask).
- User search base / filter: per your AD layout, e.g.
  `(&(objectClass=user)(sAMAccountName=%s))`.
- Attribute mapping: username ← `sAMAccountName`, full name ← `displayName`,
  email ← `mail`.
- Enable **synchronization** so disabled AD accounts are deactivated in Gitea.

Map AD groups → Gitea teams where possible (Gitea's LDAP group sync), so role
assignment follows existing bank identity management:

- Team `staff` on org `bank`: **read** on `prompt-library` → app role
  "Browser" (browse, search, copy — cannot suggest or create).
- Team `contributors` on org `bank` (sync from an AD group such as
  `prompt-contributors`): **read** on `prompt-library` → app role
  "Contributor" (suggest edits, create prompts, maintain owned community
  prompts). **The team must be named exactly `contributors`** — the app
  derives the role by matching that team name on the library repo's org
  (`backend/app/roles.py`).
- Team `prompt-approvers`: **write** on `prompt-library` → app role
  "Bank Approver".
- Org owners / repo admins → app role "Admin".

Decide which AD groups map to approver vs. contributor vs. browser with the
business owner (spec open question §11).

**The in-app admin page** (`/admin`, visible to app role "Admin") lists
everyone with repo access and can add/remove users on the `contributors`
team. Two caveats:

- Gitea only lets an **org owner** change team membership — a user who is
  merely a repo admin will get Gitea's 403, which the page shows verbatim.
  Make the intended app admins owners of the `bank` org.
- Where the `contributors` team is populated by LDAP group sync (the setup
  above), the next sync **overwrites** manual changes made on the page. In
  that configuration treat the page as a read-only roster and manage
  contributor-ness through the AD group.

## 4. Register the OAuth application

As a Gitea **instance admin or org owner** (not an individual user account):
Settings → Applications → Create a new OAuth2 application.

- Application name: `Prompt Library`
- Redirect URI: `https://prompts.internal.example.local/auth/callback`
  — must match `APP_PUBLIC_URL`/auth/callback **exactly**.
- **Confidential client: yes.** (Do not register as a public client to get
  PKCE — as a confidential client the secret is the protection.)
- Copy the client secret immediately — it is shown once and cannot be
  recovered. Put both values in `.env`, then `docker compose up -d --build`.

## 5. Local-only checklist (spec §8)

All four doors, closed deliberately — the compose file already sets these,
verify after any upgrade:

1. **Runtime egress:** the VM needs no outbound internet. Dependencies are
   vendored at build time from internal mirrors.
2. **Mirroring & webhooks:** `GITEA__mirror__ENABLED=false`,
   `GITEA__migrations__ALLOWED_DOMAINS=` (empty),
   `GITEA__webhook__ALLOWED_HOST_LIST=127.0.0.1`. Documented as explicitly
   disabled — do not configure any mirror or external webhook.
3. **No external CDNs:** the frontend bundles every asset (fonts, JS, CSS);
   Gitea runs with `OFFLINE_MODE=true` (no Gravatar). Verify with the browser
   network tab: zero requests to non-internal hosts.
4. **No model API calls:** there is no LLM integration in v1. If prompt
   testing is ever added, it must target internal infrastructure only.

Also disabled: Gitea's update checker (`[cron.update_checker] ENABLED=false`),
self-registration, OpenID sign-in.

## 6. Backups & DR

- Nightly backup of `./data/` (Gitea repos + SQLite DBs, and the app's
  copy-event DB) under existing policy, with a tested restore.
- DR = restore `./data/` onto a new VM, `docker compose up -d`.
- Raise with IT: the patching path if the box is fully isolated (internal
  mirror, or a controlled connect-update-disconnect window), and backup
  retention/location.

## 7. Upgrades

- Pin Gitea to an exact version (or image digest) in `docker-compose.yml`
  before going to production; upgrade deliberately, reading Gitea release
  notes. Gitea must stay ≥ 1.23 (granular OAuth scopes).
- App upgrades: `git pull && docker compose up -d --build backend frontend`.

## 8. Gitea vs Forgejo

The stack was built and tested against Gitea 1.24. Forgejo is API-compatible
for everything this app uses (OAuth2, contents, branches, pulls, forks); if
the risk committee prefers the community-governed fork, swap the image and
re-run the acceptance checklist. Decide before install, not after.
