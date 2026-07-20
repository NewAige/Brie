"""Minimal admin surface (PLAN.MD phase E).

See who has which role; toggle Contributor-ness (= membership in the org's
`contributors` team); and add or remove who has access to the library repo at
all. Everything else about roles stays in Gitea/AD.

"Add a user" here means granting an existing Gitea account access to the
library repo as a direct collaborator (Browser by default, promotable from
there); "remove a user" means revoking that access — not deleting the Gitea
account, whose lifecycle stays in Gitea/AD.

Every call here uses the ADMIN'S OWN token, never the bot: the bot's scope is
deliberately limited to repository writes (ownership.py), and user/team
management is exactly the kind of power it must not hold. Two consequences the
docs spell out: adding or removing a collaborator needs repo **admin** rights,
and changing team membership needs **org owner** rights, which a plain
repo-admin may lack — Gitea's 403 is surfaced verbatim so the admin sees the
real reason. In production, LDAP team sync overwrites manual assignment on its
next run, making the contributor toggle advisory there.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import gitea
from ..config import settings
from ..deps import UserSession, require_admin
from ..roles import CONTRIBUTORS_TEAM

router = APIRouter(prefix="/api/admin")

# Effective repo permission (collaborators/{username}/permission) -> app role
# for non-team-members. Mirrors roles.derive_role's ordering: admin > write
# (approver) > read. Team membership upgrades "read" to contributor below.
_PERMISSION_ROLES = {"admin": "admin", "write": "approver", "read": "browser"}

# Repo permissions an admin may hand out when adding a user. We expose only the
# two that map to a role this page understands — `read` (Browser, then
# promotable to Contributor with the toggle below) and `write` (Bank Approver).
# Granting `admin` (repo-owner power) stays a deliberate Gitea-side action.
_GRANTABLE_ROLES = {"read": "Browser", "write": "Bank Approver"}


@router.get("/users")
async def list_users(session: UserSession = Depends(require_admin)):
    """Everyone with access to the library repo, with their derived role and
    contributors-team membership. Union of direct collaborators and team
    members, so LDAP-synced team users appear even without a direct grant."""
    team = await _find_team(session.token)
    team_members = await _team_member_names(session.token, team) if team else set()

    collaborators = await _paged(session.token, f"{settings.repo_api}/collaborators")
    names: dict[str, dict] = {}  # username -> user payload (may be sparse)
    for user in collaborators:
        if isinstance(user, dict) and user.get("login"):
            names[user["login"]] = user
    for member in team_members:
        names.setdefault(member, {"login": member})

    # The owner-merge service account holds a write grant by design; listing
    # it as an "Approver" would only invite someone to fiddle with it.
    names.pop(settings.bot_username, None)

    users = []
    for username, payload in sorted(names.items()):
        role = await _effective_role(session.token, username, username in team_members)
        users.append({
            "username": username,
            "full_name": payload.get("full_name") or "",
            "role": role,
            "contributor": username in team_members,
        })
    return {"users": users, "team_found": team is not None}


class ContributorUpdate(BaseModel):
    member: bool


@router.put("/users/{username}/contributor")
async def set_contributor(username: str, update: ContributorUpdate,
                          session: UserSession = Depends(require_admin)):
    """Add or remove a user from the contributors team, as the admin.

    Gitea authorizes this itself (org owner needed); its error — including
    the 403 a non-org-owner admin gets — passes through verbatim.
    """
    team = await _find_team(session.token)
    if team is None:
        raise HTTPException(
            status_code=404,
            detail=f"No team named '{CONTRIBUTORS_TEAM}' exists on the "
                   f"'{settings.repo_owner}' org — create it in Gitea first "
                   "(scripts/seed.py does this in dev).")
    method = "PUT" if update.member else "DELETE"
    await gitea.api(session.token, method,
                    f"/teams/{team['id']}/members/{username}")
    verb = "added to" if update.member else "removed from"
    return {"message": f"{username} {verb} the contributors team. "
                       "Their role updates on their next sign-in or within a minute.",
            "username": username, "contributor": update.member}


class AddUser(BaseModel):
    username: str
    permission: str = "read"  # "read" -> Browser, "write" -> Bank Approver
    # When `email` and `password` are both given, a brand-new Gitea account is
    # created first (needs a Gitea SITE-ADMIN token); otherwise the username is
    # assumed to already exist and is only granted access.
    email: str | None = None
    password: str | None = None
    full_name: str | None = None
    # Gitea's own flag: force a password change on first sign-in. On by default
    # so the admin-chosen password is only ever a one-time handoff.
    must_change_password: bool = True


@router.post("/users")
async def add_user(payload: AddUser, session: UserSession = Depends(require_admin)):
    """Add a user to the library, optionally creating their Gitea account first.

    Two modes, both ending in a collaborator grant so the user appears in the
    roster with a real role (`read` -> Browser, promotable to Contributor with
    the toggle above; `write` -> Bank Approver; repo-owner is not grantable):

    - **Create + grant** — when `email` and `password` are supplied, first
      `POST /admin/users` to create the account. This is a Gitea *site-admin*
      operation: an app-admin who is only a repo admin / org owner gets Gitea's
      403, surfaced verbatim. On success the account exists and is granted access.
    - **Grant existing** — with no email/password, only the collaborator grant
      runs, for an account that already exists (e.g. AD-provisioned).

    Everything runs as the admin's own token, so Gitea enforces the real
    permission and its errors (403 not-site-admin, 422 user-exists, …) pass
    through unchanged.
    """
    username = payload.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="A username is required.")
    if payload.permission not in _GRANTABLE_ROLES:
        raise HTTPException(
            status_code=400,
            detail="permission must be 'read' (Browser) or 'write' (Bank Approver).")
    if username == settings.bot_username:
        raise HTTPException(
            status_code=400,
            detail="The service account is managed by the server, not here.")

    email = (payload.email or "").strip()
    password = payload.password or ""
    creating = bool(email or password)
    if creating and not (email and password):
        raise HTTPException(
            status_code=400,
            detail="Creating a new account needs both an email and a password.")

    if creating:
        await gitea.api(session.token, "POST", "/admin/users", json={
            "username": username,
            "email": email,
            "password": password,
            "full_name": (payload.full_name or "").strip(),
            "must_change_password": payload.must_change_password,
        })

    # PUT is create-or-update: granting someone who already has access just
    # resets their permission, which is a reasonable "fix their access" action.
    await gitea.api(session.token, "PUT",
                    f"{settings.repo_api}/collaborators/{username}",
                    json={"permission": payload.permission})

    role = _PERMISSION_ROLES[payload.permission]
    lead = f"{username} — account created — " if creating else f"{username} "
    return {"message": f"{lead}now has access to the library as a "
                       f"{_GRANTABLE_ROLES[payload.permission]}."
                       + (" They'll be asked to set a new password on first "
                          "sign-in." if creating and payload.must_change_password
                          else ""),
            "username": username, "role": role, "created": creating}


@router.delete("/users/{username}")
async def remove_user(username: str,
                      session: UserSession = Depends(require_admin)):
    """Revoke a user's access to the library: drop them from the contributors
    team (if a member) and remove their direct collaborator grant.

    This removes access, not the Gitea account — account lifecycle stays in
    Gitea/AD. A user whose access comes only from an LDAP-synced team reappears
    on the team's next sync (the page is advisory there). Team removal needs
    org-owner rights and 403s verbatim otherwise; it runs first so that a
    non-owner admin's request fails cleanly instead of half-revoking.
    """
    if username == settings.bot_username:
        raise HTTPException(status_code=400,
                            detail="The service account cannot be removed here.")
    if username == session.username:
        raise HTTPException(status_code=400,
                            detail="You can't remove your own access.")

    team = await _find_team(session.token)
    in_team = bool(team) and \
        username in await _team_member_names(session.token, team)
    if in_team:
        await gitea.api(session.token, "DELETE",
                        f"/teams/{team['id']}/members/{username}")

    try:
        await gitea.api(session.token, "DELETE",
                        f"{settings.repo_api}/collaborators/{username}")
    except HTTPException as exc:
        # 404 = no direct grant (a team-only user); the team removal above was
        # the real revoke, so this is success. Anything else is a real error.
        if exc.status_code != 404:
            raise
    return {"message": f"{username} no longer has access to the library.",
            "username": username}


@router.delete("/users/{username}/account")
async def delete_account(username: str,
                         session: UserSession = Depends(require_admin)):
    """Permanently delete a user's Gitea account — the destructive counterpart
    to account creation, and a step beyond `remove_user`'s access revoke.

    Uses `DELETE /admin/users/{username}?purge=true`: a Gitea *site-admin*
    operation (403 verbatim otherwise). `purge` is required because a normal
    delete refuses any user who still owns content — and contributors own their
    drafts fork — so this also destroys their forks, drafts, and comments. It
    cannot be undone. The service account and the admin's own account are
    refused outright.
    """
    if username == settings.bot_username:
        raise HTTPException(status_code=400,
                            detail="The service account cannot be deleted here.")
    if username == session.username:
        raise HTTPException(status_code=400,
                            detail="You can't delete your own account.")

    await gitea.api(session.token, "DELETE", f"/admin/users/{username}",
                    params={"purge": "true"})
    return {"message": f"The Gitea account '{username}' was permanently deleted, "
                       "along with anything it owned (forks, drafts, comments).",
            "username": username}


# --- helpers ----------------------------------------------------------------

async def _find_team(token: str) -> dict | None:
    """The org's `contributors` team, matched like roles.derive_role does
    (case-insensitive name, this org only). None when it doesn't exist."""
    teams = await _paged(token, f"/orgs/{settings.repo_owner}/teams")
    for team in teams:
        if isinstance(team, dict) and \
                str(team.get("name") or "").lower() == CONTRIBUTORS_TEAM:
            return team
    return None


async def _team_member_names(token: str, team: dict) -> set[str]:
    members = await _paged(token, f"/teams/{team['id']}/members")
    return {m["login"] for m in members if isinstance(m, dict) and m.get("login")}


async def _effective_role(token: str, username: str, in_team: bool) -> str:
    """Same vocabulary as roles.derive_role, but from the admin's vantage
    point: the collaborator-permission endpoint reports the user's effective
    repo permission (direct or team-granted). Unreadable ⇒ browser."""
    try:
        data = await gitea.api(
            token, "GET",
            f"{settings.repo_api}/collaborators/{username}/permission")
    except HTTPException:
        return "browser"
    permission = str((data or {}).get("permission") or "")
    role = _PERMISSION_ROLES.get(permission, "browser")
    if role == "browser" and in_team:
        return "contributor"
    return role


async def _paged(token: str, path: str) -> list[dict]:
    """All pages of a Gitea list endpoint. The page cap is a safety bound —
    an admin page that misses a row past page 10 is stale, not insecure."""
    items: list[dict] = []
    for page in range(1, 11):
        batch = await gitea.api(token, "GET", path,
                                params={"page": page, "limit": 50})
        if not batch:
            break
        items.extend(batch)
        if len(batch) < 50:
            break
    return items
