"""Thin async client for the Gitea API.

Every call carries an individual user's OAuth token — there is deliberately no
service account (spec §5, hard requirements). Gitea enforces the real
permissions on every request; this backend never makes authorization
decisions of its own.
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
    resp = await get_client().request(
        method, f"/api/v1{path}",
        params=params, json=json,
        headers={"Authorization": f"Bearer {token}"},
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
