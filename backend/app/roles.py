"""Role derivation from live Gitea state (PLAN.MD phase B).

Four roles, never stored by this app — always re-derived from what Gitea says
about the user right now, so AD/LDAP changes propagate without any app-side
user management:

- ``admin``       — repo admin permission
- ``approver``    — push (write) permission: today's Bank Approver
- ``contributor`` — read access + membership in the org's ``contributors``
                    team (AD-group-synced in production)
- ``browser``     — read access only: browse, search, copy; may not author

Everything fails closed: a Gitea error, a malformed payload, a team in the
wrong org — all yield ``browser``. The split between the pure mapping
(`derive_role`, unit-testable) and the fetching/caching (`get_role`) mirrors
ownership.py's decide/owner_mergeable.
"""

import time

from fastapi import HTTPException

from . import gitea
from .config import settings

# Membership in this team (on the library repo's org) is what distinguishes a
# Contributor from a Browser. In production the team is populated by Gitea's
# LDAP group sync (docs/deployment.md §3).
CONTRIBUTORS_TEAM = "contributors"

# How long a derived role may be reused before re-asking Gitea. Mutating
# endpoints re-check at most this much later; a role downgrade in Gitea takes
# effect within a minute without hammering Gitea on every request.
ROLE_TTL = 60  # seconds

# session_id -> (expires_at, role). Process-local; cleared on logout.
_cache: dict[str, tuple[float, str]] = {}


def derive_role(perms: dict, teams: list[dict]) -> str:
    """Pure mapping from Gitea facts to an app role.

    `perms` is the ``permissions`` object from ``GET /repos/{owner}/{repo}``;
    `teams` is the raw list from ``GET /user/teams``. Repo permissions win
    over team membership (push beats team). Team matching requires BOTH the
    team name and the owning org to match, so a same-named team on some other
    org grants nothing.
    """
    perms = perms or {}
    if perms.get("admin"):
        return "admin"
    if perms.get("push"):
        return "approver"
    for team in teams or []:
        if not isinstance(team, dict):
            continue
        name = str(team.get("name") or "")
        org = str(((team.get("organization") or {}) or {}).get("username") or "")
        if name.lower() == CONTRIBUTORS_TEAM and org.lower() == settings.repo_owner.lower():
            return "contributor"
    return "browser"


async def get_role(session_id: str, token: str) -> str:
    """The user's current role, cached per session for ROLE_TTL seconds.

    Reads use the USER's own token, so Gitea reports the truth for exactly
    this user. Any Gitea failure yields ``browser`` — an authorization we
    cannot verify is one we don't grant.
    """
    cached = _cache.get(session_id)
    if cached and cached[0] > time.time():
        return cached[1]
    try:
        repo = await gitea.api(token, "GET", settings.repo_api)
        perms = (repo or {}).get("permissions") or {}
        # Teams only matter when repo permissions alone don't already decide.
        teams = [] if (perms.get("admin") or perms.get("push")) else await _user_teams(token)
        role = derive_role(perms, teams)
    except HTTPException:
        role = "browser"
    _cache[session_id] = (time.time() + ROLE_TTL, role)
    return role


def forget(session_id: str) -> None:
    """Drop the cached role (on logout, alongside the session row)."""
    _cache.pop(session_id, None)


async def _user_teams(token: str) -> list[dict]:
    """All teams the user belongs to, across pages. The page cap is a
    safety bound, not a correctness one: a missed page can only miss a
    grant, never mint one (fail closed)."""
    teams: list[dict] = []
    for page in range(1, 11):
        batch = await gitea.api(token, "GET", "/user/teams",
                                params={"page": page, "limit": 50})
        if not batch:
            break
        teams.extend(batch)
        if len(batch) < 50:
            break
    return teams
