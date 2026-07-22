"""Request dependencies: resolve the session cookie to a live Gitea token."""

import time
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request

from . import db, gitea, roles

SESSION_COOKIE = "pl_session"

# Refresh when the access token has less than this many seconds left.
REFRESH_MARGIN = 60


@dataclass
class UserSession:
    session_id: str
    username: str
    token: str


async def current_session(request: Request) -> UserSession:
    """Resolve the httpOnly session cookie to the user's Gitea access token,
    silently refreshing it when close to expiry. 401s if not signed in."""
    session_id = request.cookies.get(SESSION_COOKIE)
    if not session_id:
        raise HTTPException(status_code=401, detail="Not signed in")

    row = db.get_session(session_id)
    if row is None:
        raise HTTPException(status_code=401, detail="Session expired — please sign in again")

    token = row["access_token"]
    if row["expires_at"] - time.time() < REFRESH_MARGIN:
        if not row["refresh_token"]:
            db.delete_session(session_id)
            raise HTTPException(status_code=401, detail="Session expired — please sign in again")
        try:
            fresh = await gitea.refresh_tokens(row["refresh_token"])
        except HTTPException:
            db.delete_session(session_id)
            raise HTTPException(status_code=401, detail="Session expired — please sign in again")
        token = fresh["access_token"]
        db.update_session_tokens(
            session_id,
            access_token=token,
            refresh_token=fresh.get("refresh_token") or row["refresh_token"],
            expires_at=time.time() + float(fresh.get("expires_in", 3600)),
        )

    return UserSession(session_id=session_id, username=row["username"], token=token)


async def require_contributor(session: UserSession = Depends(current_session)) -> UserSession:
    """403 for browsers (PLAN.MD phase B): endpoints that author content —
    suggest, create — need at least the Contributor role. Reads and copy
    logging stay open to every signed-in user. Frontend hiding of the same
    buttons is cosmetic; this is the check that counts."""
    role = await roles.get_role(session.session_id, session.token)
    if role == "browser":
        raise HTTPException(
            status_code=403,
            detail="Your account is read-only in the Prompt Library. "
                   "Ask an admin to add you to the contributors team to "
                   "suggest edits or create prompts.")
    return session


async def require_approver(session: UserSession = Depends(current_session)) -> UserSession:
    """403 unless the user's live-derived role is `approver` or `admin` —
    the roles that may put a prompt in the Bank tier (docs/bank-upgrade.md).
    Fails closed like every role check: a Gitea error while deriving the role
    yields `browser`, which is denied here."""
    role = await roles.get_role(session.session_id, session.token)
    if role not in ("approver", "admin"):
        raise HTTPException(
            status_code=403,
            detail="Only a Bank Approver can change a prompt's level.")
    return session


async def require_admin(session: UserSession = Depends(current_session)) -> UserSession:
    """403 unless the user's live-derived role is `admin` (PLAN.MD phase E).
    Admin endpoints then act with the admin's OWN token — never the bot — so
    Gitea enforces the real permission on every mutation too."""
    role = await roles.get_role(session.session_id, session.token)
    if role != "admin":
        raise HTTPException(status_code=403,
                            detail="Only admins can manage users.")
    return session
