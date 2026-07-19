"""Thin async client for the Gitea API.

Every READ carries an individual user's OAuth token, so Gitea enforces the real
permissions on every request (spec §5).

The one deliberate exception is `bot_api`, added in phase 2: owner-merges are
executed with a service account, because Gitea cannot express "may merge only
the files they own" (docs/phase-2-ownership.md). It is used only to write, only
after the app's ownership check has passed, and never for reads.
"""

import httpx
from fastapi import HTTPException

from .config import settings

_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(base_url=settings.gitea_internal_url, timeout=30)
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


class GiteaError(HTTPException):
    pass


def _error_detail(resp: httpx.Response) -> str:
    try:
        data = resp.json()
        if isinstance(data, dict):
            return data.get("message") or data.get("error_description") or resp.text[:300]
    except Exception:
        pass
    return resp.text[:300] or f"Gitea returned HTTP {resp.status_code}"


async def api(token: str, method: str, path: str, *, params: dict | None = None,
              json: dict | None = None, raw: bool = False):
    """Call the Gitea API as the given user. `path` is relative to /api/v1.

    Returns parsed JSON (or text when raw=True). Raises GiteaError with
    Gitea's own status code and message on failure.
    """
    return await _request(f"Bearer {token}", method, path,
                          params=params, json=json, raw=raw)


async def bot_api(method: str, path: str, *, params: dict | None = None,
                  json: dict | None = None, raw: bool = False):
    """Call the Gitea API as the service account.

    Callers MUST have already authorized the action themselves — this
    credential has write access to the whole repo, so it is the app's own
    checks, not Gitea's, that bound what it may do. See ownership.py.

    Gitea personal access tokens use the `token` scheme, not `Bearer`.
    """
    if not settings.owner_merge_enabled:
        raise GiteaError(status_code=503,
                         detail="Publishing as owner is not configured on this server.")
    return await _request(f"token {settings.bot_token}", method, path,
                          params=params, json=json, raw=raw)


async def _request(authorization: str, method: str, path: str, *,
                   params: dict | None = None, json: dict | None = None,
                   raw: bool = False):
    resp = await get_client().request(
        method, f"/api/v1{path}",
        params=params, json=json,
        headers={"Authorization": authorization},
    )
    if resp.status_code >= 400:
        raise GiteaError(status_code=resp.status_code, detail=_error_detail(resp))
    if raw:
        return resp.text
    if resp.status_code == 204 or not resp.content:
        return None
    return resp.json()


async def exchange_code(code: str) -> dict:
    """Back-channel (server-to-server) authorization-code exchange."""
    return await _token_request({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.redirect_uri,
    })


async def refresh_tokens(refresh_token: str) -> dict:
    """Silent token refresh so users aren't bounced to re-login hourly."""
    return await _token_request({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    })


async def _token_request(fields: dict) -> dict:
    resp = await get_client().post(
        "/login/oauth/access_token",
        data={
            "client_id": settings.oauth_client_id,
            "client_secret": settings.oauth_client_secret,
            **fields,
        },
        headers={"Accept": "application/json"},
    )
    if resp.status_code >= 400:
        raise GiteaError(status_code=401, detail=_error_detail(resp))
    return resp.json()
