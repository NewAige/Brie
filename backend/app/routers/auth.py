"""OAuth2 Authorization Code flow with Gitea (confidential client, spec §5).

The browser never sees a Gitea token: it gets an opaque session id in an
httpOnly cookie, and all Gitea calls happen server-side with the token looked
up from the session store.
"""

import secrets
import time
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse

from .. import db, gitea, roles
from ..config import settings
from ..deps import SESSION_COOKIE, UserSession, current_session

router = APIRouter()


@router.get("/auth/login")
async def login():
    state = secrets.token_urlsafe(32)
    db.create_state(state)
    params = urlencode({
        "client_id": settings.oauth_client_id,
        "redirect_uri": settings.redirect_uri,
        "response_type": "code",
        "state": state,
    })
    # The browser goes to Gitea's public URL; Gitea authenticates the user
    # (against AD/LDAP in production) — this app never sees a password.
    return RedirectResponse(f"{settings.gitea_public_url}/login/oauth/authorize?{params}")


@router.get("/auth/callback")
async def callback(request: Request, code: str = "", state: str = "",
                   error: str = "", error_description: str = ""):
    if error:
        return RedirectResponse(f"/login?error={error}")
    # CSRF protection: the state must be one we issued, unexpired, unused.
    if not state or not db.consume_state(state):
        return RedirectResponse("/login?error=state_mismatch")
    if not code:
        return RedirectResponse("/login?error=missing_code")

    tokens = await gitea.exchange_code(code)
    access_token = tokens["access_token"]
    user = await gitea.api(access_token, "GET", "/user")

    session_id = secrets.token_urlsafe(32)
    db.create_session(
        session_id,
        username=user["login"],
        access_token=access_token,
        refresh_token=tokens.get("refresh_token"),
        expires_at=time.time() + float(tokens.get("expires_in", 3600)),
    )

    response = RedirectResponse("/")
    response.set_cookie(
        SESSION_COOKIE, session_id,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.session_max_age,
        path="/",
    )
    return response


@router.post("/auth/logout")
async def logout(request: Request):
    session_id = request.cookies.get(SESSION_COOKIE)
    if session_id:
        db.delete_session(session_id)
        roles.forget(session_id)
    response = JSONResponse({"ok": True})
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.get("/api/me")
async def me(session: UserSession = Depends(current_session)):
    user = await gitea.api(session.token, "GET", "/user")
    # Role comes from the user's REAL permissions and team memberships in
    # Gitea — never from anything this app stores (spec §6, PLAN.MD phase B).
    role = await roles.get_role(session.session_id, session.token)
    return {
        "username": user["login"],
        "full_name": user.get("full_name") or user["login"],
        "role": role,
    }
