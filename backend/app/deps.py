"""Request dependencies: resolve the session cookie to a live Gitea token."""

import time
from dataclasses import dataclass

from fastapi import HTTPException, Request

from . import db, gitea

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
