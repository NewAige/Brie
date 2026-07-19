"""Role derivation and the browser gate (PLAN.MD phase B).

`derive_role` is pure, so the permission/team matrix is covered without a
Gitea. `get_role` is exercised with a faked `gitea.api` (caching, fail-closed
on error), and the endpoint gate with FastAPI's TestClient: browsers get 403
on the authoring endpoints while copy-event logging stays open.
"""

import asyncio

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import gitea, roles
from app.deps import UserSession, current_session
from app.main import app

UMA = "uma.user"


def team(name: str = "contributors", org: str = "bank") -> dict:
    return {"name": name, "organization": {"username": org}}


# --- derive_role ------------------------------------------------------------

def test_admin_perm_wins():
    assert roles.derive_role({"admin": True, "push": True}, [team()]) == "admin"


def test_push_beats_team():
    assert roles.derive_role({"push": True}, [team()]) == "approver"


def test_read_plus_team_is_contributor():
    assert roles.derive_role({"pull": True}, [team()]) == "contributor"


def test_read_without_team_is_browser():
    assert roles.derive_role({"pull": True}, []) == "browser"


def test_wrong_org_team_is_browser():
    """A `contributors` team on some OTHER org grants nothing here."""
    assert roles.derive_role({"pull": True}, [team(org="other-org")]) == "browser"


def test_wrong_team_name_is_browser():
    assert roles.derive_role({"pull": True}, [team(name="staff")]) == "browser"


def test_team_match_is_case_insensitive():
    assert roles.derive_role({}, [team(name="Contributors", org="Bank")]) == "contributor"


def test_malformed_payloads_fail_closed():
    assert roles.derive_role(None, None) == "browser"
    assert roles.derive_role({}, [None, "junk", {}, {"name": "contributors"},
                                  {"name": "contributors", "organization": None}]) == "browser"


# --- get_role ---------------------------------------------------------------

def fake_gitea(monkeypatch, *, perms: dict, teams: list, calls: list):
    async def fake_api(token, method, path, **kwargs):
        calls.append(path)
        if path.startswith("/repos/"):
            return {"permissions": perms}
        if path == "/user/teams":
            return teams
        raise AssertionError(f"unexpected Gitea call: {path}")
    monkeypatch.setattr(roles.gitea, "api", fake_api)


def test_get_role_derives_and_caches(monkeypatch):
    calls = []
    fake_gitea(monkeypatch, perms={"pull": True}, teams=[team()], calls=calls)
    roles._cache.clear()

    assert asyncio.run(roles.get_role("sess-1", "tok")) == "contributor"
    fetched = len(calls)
    assert asyncio.run(roles.get_role("sess-1", "tok")) == "contributor"
    assert len(calls) == fetched  # second call served from cache

    roles.forget("sess-1")
    assert asyncio.run(roles.get_role("sess-1", "tok")) == "contributor"
    assert len(calls) > fetched  # forget() forces a re-fetch


def test_get_role_skips_team_fetch_for_writers(monkeypatch):
    calls = []
    fake_gitea(monkeypatch, perms={"push": True}, teams=[], calls=calls)
    roles._cache.clear()
    assert asyncio.run(roles.get_role("sess-2", "tok")) == "approver"
    assert "/user/teams" not in calls


def test_get_role_gitea_error_is_browser(monkeypatch):
    async def boom(*args, **kwargs):
        raise HTTPException(status_code=500, detail="gitea down")
    monkeypatch.setattr(roles.gitea, "api", boom)
    roles._cache.clear()
    assert asyncio.run(roles.get_role("sess-3", "tok")) == "browser"


# --- endpoint gate ----------------------------------------------------------

@pytest.fixture
def make_client(monkeypatch):
    """TestClient signed in as uma.user with a forced role. The lifespan runs
    (init_db against the conftest temp DB), so DB-backed endpoints work."""
    def make(role: str) -> TestClient:
        async def fake_get_role(session_id, token):
            return role
        monkeypatch.setattr(roles, "get_role", fake_get_role)
        app.dependency_overrides[current_session] = \
            lambda: UserSession("test-session", UMA, "tok")
        return TestClient(app)
    yield make
    app.dependency_overrides.clear()


NEW_PROMPT = {"title": "Escalation email tone", "category": "customer-support",
              "body": "Write a calm escalation email."}
SUGGESTION = {"body": "New body text.", "note": "Tightened wording."}


def test_browser_gets_403_on_suggest(make_client):
    with make_client("browser") as client:
        resp = client.post("/api/prompts/customer-support/some-prompt.md/suggest",
                           json=SUGGESTION)
    assert resp.status_code == 403
    assert "read-only" in resp.json()["detail"]


def test_browser_gets_403_on_create(make_client):
    with make_client("browser") as client:
        resp = client.post("/api/prompts", json=NEW_PROMPT)
    assert resp.status_code == 403


def test_browser_may_still_log_copy_events(make_client):
    with make_client("browser") as client:
        resp = client.post("/api/events/copy",
                           json={"path": "customer-support/some-prompt.md"})
    assert resp.status_code == 200


def test_contributor_passes_the_gate(monkeypatch, make_client):
    """Not 403: the request reaches the handler proper (which then fails on
    our stubbed Gitea — that error code is not what's under test)."""
    async def gitea_down(*args, **kwargs):
        raise HTTPException(status_code=502, detail="no gitea in unit tests")
    monkeypatch.setattr(gitea, "api", gitea_down)
    with make_client("contributor") as client:
        resp = client.post("/api/prompts/customer-support/some-prompt.md/suggest",
                           json=SUGGESTION)
    assert resp.status_code != 403
