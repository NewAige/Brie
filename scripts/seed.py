#!/usr/bin/env python3
"""One-command local dev environment for the Prompt Library.

Brings up Gitea, provisions everything the app needs, writes .env, then starts
the backend and frontend:

    python3 scripts/seed.py

Creates (idempotently):
  - Gitea admin        pl-admin / seed-admin-pass-1   (instance admin)
  - Approver account   adam.approver / Password123!   (write on the repo)
  - User account       uma.user / Password123!        (read on the repo)
  - Service account    pl-bot / <random>             (write on the repo)
  - Org `bank` with private repo `prompt-library`, seeded from seed/prompt-library/
  - Branch protection on main requiring 1 approval
  - A confidential OAuth2 application, credentials written to .env

In production none of this runs: accounts come from AD via LDAP, and the
OAuth app is registered by an admin in the Gitea UI (see docs/deployment.md).
"""

import base64
import json
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GITEA_URL = "http://localhost:3000"
APP_URL = "http://localhost:8080"

ADMIN_USER = "pl-admin"
ADMIN_PASS = "seed-admin-pass-1"
ADMIN_EMAIL = "pl-admin@example.local"

USERS = [
    # (username, password, email, full name, repo permission)
    ("adam.approver", "Password123!", "adam@example.local", "Adam Approver", "write"),
    ("uma.user", "Password123!", "uma@example.local", "Uma User", "read"),
]

# Service account that executes owner-merges (docs/phase-2-ownership.md §3).
# Write access, so it can merge; the app is what decides when it may.
BOT_USER = "pl-bot"
BOT_EMAIL = "pl-bot@example.local"

ORG = "bank"
REPO = "prompt-library"
SEED_DIR = ROOT / "seed" / "prompt-library"


def sh(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(args)}")
    return subprocess.run(args, check=check, capture_output=True, text=True)


def gitea_cli(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return sh("docker", "exec", "-u", "git", "brie-gitea", "gitea", *args, check=check)


def api(token: str, method: str, path: str, payload: dict | None = None,
        ok_statuses: tuple = (), ok_message: str = "") -> dict | list | None:
    """Call the Gitea API. Statuses in `ok_statuses` return None instead of
    raising — that is how "already exists" is treated as success.

    `ok_message` narrows a tolerated status to responses whose body contains
    that substring, so a status Gitea overloads (403 means both "already
    exists" and "you may not do this") doesn't swallow the real failure.
    """
    req = urllib.request.Request(
        f"{GITEA_URL}/api/v1{path}",
        method=method,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Authorization": f"token {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            body = resp.read()
            return json.loads(body) if body else None
    except urllib.error.HTTPError as err:
        detail = err.read().decode()[:300]
        if err.code in ok_statuses and (not ok_message or ok_message in detail):
            return None
        raise RuntimeError(f"{method} {path} -> HTTP {err.code}: {detail}") from err


def wait_for_gitea(timeout: int = 120) -> None:
    print("Waiting for Gitea to become healthy...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{GITEA_URL}/api/healthz", timeout=3) as resp:
                if resp.status == 200:
                    print("  Gitea is up.")
                    return
        except OSError:
            pass
        time.sleep(2)
    sys.exit("Gitea did not become healthy in time. Check: docker compose logs gitea")


def ensure_user(username: str, password: str, email: str, full_name: str = "",
                admin: bool = False) -> None:
    args = ["admin", "user", "create", "--username", username, "--password", password,
            "--email", email, "--must-change-password=false"]
    if admin:
        args.append("--admin")
    result = gitea_cli(*args, check=False)
    if result.returncode == 0:
        print(f"  Created user {username}")
    elif "already exists" in (result.stderr + result.stdout):
        print(f"  User {username} already exists")
    else:
        sys.exit(f"Failed to create user {username}: {result.stderr or result.stdout}")
    if full_name:
        gitea_cli("admin", "user", "change-full-name", "--username", username,
                  "--full-name", full_name, check=False)


def admin_token() -> str:
    result = gitea_cli("admin", "user", "generate-access-token",
                       "--username", ADMIN_USER, "--scopes", "all",
                       "--token-name", f"seed-{int(time.time())}", "--raw")
    return result.stdout.strip().splitlines()[-1]


def ensure_org_repo(token: str) -> None:
    api(token, "POST", "/orgs", {"username": ORG, "visibility": "private"},
        ok_statuses=(409, 422))
    created = api(token, "POST", f"/orgs/{ORG}/repos", {
        "name": REPO, "private": True, "auto_init": True,
        "default_branch": "main",
        "description": "Approved AI prompts — plain markdown, reviewed via pull requests",
    }, ok_statuses=(409,))
    print(f"  Repo {ORG}/{REPO} {'created' if created else 'already exists'}")


def push_seed_content(token: str) -> None:
    files = sorted(p for p in SEED_DIR.rglob("*") if p.is_file())
    for file in files:
        rel = file.relative_to(SEED_DIR).as_posix()
        content = base64.b64encode(file.read_bytes()).decode()
        result = api(token, "POST", f"/repos/{ORG}/{REPO}/contents/{rel}", {
            "content": content,
            "message": f"Seed: add {rel}",
        }, ok_statuses=(409, 422))
        print(f"  {rel}: {'added' if result else 'already present'}")


def ensure_collaborators(token: str) -> None:
    for username, _pw, _email, _name, permission in USERS:
        api(token, "PUT", f"/repos/{ORG}/{REPO}/collaborators/{username}",
            {"permission": permission})
        print(f"  {username}: {permission} access")


def ensure_branch_protection(token: str) -> None:
    payload = {
        "branch_name": "main",
        "rule_name": "main",
        "required_approvals": 1,
        "block_on_rejected_reviews": True,
        "block_on_outdated_branch": False,
        "enable_push": True,  # approvers may push; merges still need an approval
    }
    # Gitea answers "Branch protection already exist" with 403, not 409/422, so
    # a re-run needs 403 tolerated here or the whole script dies at step 6.
    # Matched on the message so a genuine permissions 403 still fails loudly.
    result = api(token, "POST", f"/repos/{ORG}/{REPO}/branch_protections",
                 payload, ok_statuses=(403, 409, 422),
                 ok_message="already exist")
    print(f"  Branch protection on main {'created' if result else 'already present'} "
          "(1 approval required)")


def ensure_bot(token: str) -> str | None:
    """Create the owner-merge service account and mint it an API token.

    Returns the token, or None if one already exists — Gitea shows a token's
    value only at creation, so a re-run keeps whatever .env already holds
    rather than silently minting a second, unrecorded credential.
    """
    # No login is ever performed as this account — the password exists only
    # because Gitea requires one at creation. The API token is the credential.
    ensure_user(BOT_USER, secrets.token_urlsafe(24), BOT_EMAIL, "Prompt Library Bot")
    api(token, "PUT", f"/repos/{ORG}/{REPO}/collaborators/{BOT_USER}",
        {"permission": "write"})
    print(f"  {BOT_USER}: write access")

    # Scoped to repo write only — this account never needs admin or user scopes.
    # Whether a token already exists is read from the CLI's own error: listing
    # tokens over the API needs the bot's OWN credentials (an admin token gets
    # 401 there), and we deliberately don't keep a usable bot password.
    result = gitea_cli("admin", "user", "generate-access-token",
                       "--username", BOT_USER, "--scopes", "write:repository",
                       "--token-name", "owner-merge", "--raw", check=False)
    output = (result.stdout + result.stderr).strip()
    if result.returncode != 0:
        if "already exists" in output:
            print("  Bot token already exists (value cannot be re-read; "
                  "keeping current .env)")
            return None
        sys.exit(f"Failed to mint bot token: {output}")
    print("  Bot token minted")
    return result.stdout.strip().splitlines()[-1]


def ensure_oauth_app(token: str) -> tuple[str, str] | None:
    redirect = f"{APP_URL}/auth/callback"
    existing = api(token, "GET", "/user/applications/oauth2") or []
    for app in existing:
        if app.get("name") == "Prompt Library":
            print("  OAuth app already registered (existing secret cannot be re-read; "
                  "keeping current .env)")
            return None
    app = api(token, "POST", "/user/applications/oauth2", {
        "name": "Prompt Library",
        "redirect_uris": [redirect],
        "confidential_client": True,
    })
    print("  OAuth app registered")
    return app["client_id"], app["client_secret"]


def write_env(creds: tuple[str, str] | None, bot_token: str | None) -> None:
    env_path = ROOT / ".env"
    if env_path.exists() and creds is None:
        # OAuth creds are unchanged, but a freshly minted bot token still has
        # to be recorded — it is unreadable after this moment.
        if bot_token:
            _upsert_env(env_path, {"BOT_USERNAME": BOT_USER, "BOT_TOKEN": bot_token})
            print("  .env already exists — updated bot credentials only")
        else:
            print("  .env already exists — leaving it unchanged")
        return
    if creds is None:
        sys.exit(".env is missing but the OAuth app already exists. Delete the "
                 "'Prompt Library' OAuth2 application in Gitea (pl-admin → Settings → "
                 "Applications) and re-run, so a fresh secret can be issued.")
    client_id, client_secret = creds
    env_path.write_text(
        f"""GITEA_PUBLIC_URL={GITEA_URL}
GITEA_INTERNAL_URL=http://gitea:3000
APP_PUBLIC_URL={APP_URL}
OAUTH_CLIENT_ID={client_id}
OAUTH_CLIENT_SECRET={client_secret}
SESSION_SECRET={secrets.token_urlsafe(48)}
REPO_OWNER={ORG}
REPO_NAME={REPO}
COOKIE_SECURE=false
BOT_USERNAME={BOT_USER}
BOT_TOKEN={bot_token or ''}
""")
    print(f"  Wrote {env_path}")


def _upsert_env(env_path: Path, values: dict[str, str]) -> None:
    """Set keys in an existing .env, replacing any current line for each."""
    lines = env_path.read_text().splitlines()
    for key, value in values.items():
        replacement = f"{key}={value}"
        for i, line in enumerate(lines):
            if line.startswith(f"{key}="):
                lines[i] = replacement
                break
        else:
            lines.append(replacement)
    env_path.write_text("\n".join(lines) + "\n")


def main() -> None:
    print("[1/9] Starting Gitea…")
    # .env may not exist yet; compose requires it for the backend, so create a
    # placeholder that this script overwrites below.
    env_path = ROOT / ".env"
    if not env_path.exists():
        env_path.write_text("# placeholder — will be filled by scripts/seed.py\n"
                            "GITEA_PUBLIC_URL=http://localhost:3000\n")
    subprocess.run(["docker", "compose", "up", "-d", "gitea"], cwd=ROOT, check=True)
    wait_for_gitea()

    print("[2/9] Creating accounts…")
    ensure_user(ADMIN_USER, ADMIN_PASS, ADMIN_EMAIL, "Prompt Library Admin", admin=True)
    for username, password, email, full_name, _perm in USERS:
        ensure_user(username, password, email, full_name)
    token = admin_token()

    print("[3/9] Creating org and repo…")
    ensure_org_repo(token)

    print("[4/9] Seeding prompt content…")
    push_seed_content(token)

    print("[5/9] Granting access…")
    ensure_collaborators(token)

    print("[6/9] Protecting main…")
    ensure_branch_protection(token)

    print("[7/9] Creating owner-merge service account…")
    bot_token = ensure_bot(token)

    print("[8/9] Registering OAuth application…")
    creds = ensure_oauth_app(token)
    write_env(creds, bot_token)

    print("[9/9] Building and starting backend + frontend…")
    subprocess.run(["docker", "compose", "up", "-d", "--build", "backend", "frontend"],
                   cwd=ROOT, check=True)

    print(f"""
Done. Prompt Library is at {APP_URL}

Test accounts (password for both: Password123!)
  uma.user       — member: browse, search, copy, suggest edits, and publish
                   changes to prompts they own, with no approver
  adam.approver  — approver: all of the above + approve & publish anything

Owner-merges run as {BOT_USER} (credential in .env as BOT_TOKEN) and are
logged to the owner_merges table. Blank BOT_TOKEN disables the feature.

Gitea admin: {ADMIN_USER} / {ADMIN_PASS} at {GITEA_URL}
""")


if __name__ == "__main__":
    main()
