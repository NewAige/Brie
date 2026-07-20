"""Minimal admin surface (PLAN.MD phase E).

One job: see who has which role, and toggle Contributor-ness (= membership in
the org's `contributors` team). Everything else about roles stays in Gitea/AD.

Every call here uses the ADMIN'S OWN token, never the bot: the bot's scope is
deliberately limited to repository writes (ownership.py), and team management
is exactly the kind of power it must not hold. A consequence the docs spell
out: Gitea requires **org owner** rights to change team membership, which a
plain repo-admin may lack — Gitea's 403 is surfaced verbatim so the admin
sees the real reason. In production, LDAP team sync overwrites manual
assignment on its next run, making this page advisory there.
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
