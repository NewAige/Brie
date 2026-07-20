"""Admin user-management endpoints (PLAN.MD phase E).

The Gitea side is faked at `gitea.api`; what's under test is the gate (only
admins get in), the users-list shape (union of collaborators and team members,
roles from effective permission + team membership, bot hidden), and that the
membership toggle hits the right Gitea endpoint with the ADMIN's token and
lets Gitea's own errors through verbatim.
"""

import dataclasses

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import roles
from app.config import settings
from app.deps import UserSession, current_session
from app.main import app
from app.routers import admin

ADMIN = "pl-admin"


@pytest.fixture
def make_client(monkeypatch):
    def make(role: str) -> TestClient:
        async def fake_get_role(session_id, token):
            return role
        monkeypatch.setattr(roles, "get_role", fake_get_role)
        app.dependency_overrides[current_session] = \
            lambda: UserSession("test-session", ADMIN, "admin-tok")
        return TestClient(app)
    yield make
    app.dependency_overrides.clear()


def user(login: str, full_name: str = "") -> dict:
    return {"login": login, "full_name": full_name}


class FakeGitea:
    """Answers the exact reads admin.py performs; records every call."""

    def __init__(self, *, teams=None, team_members=None, collaborators=None,
                 permissions=None):
        self.teams = teams if teams is not None else \
            [{"id": 7, "name": "contributors"}]
        self.team_members = team_members or []
        self.collaborators = collaborators or []
        self.permissions = permissions or {}
        self.calls = []

    async def __call__(self, token, method, path, *, params=None, json=None,
                       raw=False):
        self.calls.append((token, method, path))
        if method == "GET" and path == f"/orgs/{settings.repo_owner}/teams":
            return self.teams if (params or {}).get("page", 1) == 1 else []
        if method == "GET" and path == "/teams/7/members":
            return self.team_members if (params or {}).get("page", 1) == 1 else []
        if method == "GET" and path == f"{settings.repo_api}/collaborators":
            return self.collaborators if (params or {}).get("page", 1) == 1 else []
        if method == "GET" and path.startswith(f"{settings.repo_api}/collaborators/") \
                and path.endswith("/permission"):
            username = path.split("/")[-2]
            perm = self.permissions.get(username)
            if perm is None:
                raise HTTPException(status_code=404, detail="not a collaborator")
            return {"permission": perm}
        if method in ("PUT", "DELETE") and path.startswith("/teams/7/members/"):
            return None
        if method == "PUT" and path.startswith(f"{settings.repo_api}/collaborators/"):
            return None
        if method == "DELETE" and path.startswith(f"{settings.repo_api}/collaborators/"):
            return None
        raise AssertionError(f"unexpected Gitea call: {method} {path}")


@pytest.fixture
def fake_gitea(monkeypatch):
    def install(fake: FakeGitea) -> FakeGitea:
        monkeypatch.setattr(admin.gitea, "api", fake)
        return fake
    return install


# --- the gate ---------------------------------------------------------------

@pytest.mark.parametrize("role", ["browser", "contributor", "approver"])
def test_non_admin_gets_403(make_client, role):
    with make_client(role) as client:
        assert client.get("/api/admin/users").status_code == 403
        resp = client.put("/api/admin/users/uma.user/contributor",
                          json={"member": True})
        assert resp.status_code == 403
        assert client.post("/api/admin/users",
                           json={"username": "new.user"}).status_code == 403
        assert client.delete("/api/admin/users/uma.user").status_code == 403


# --- GET /users -------------------------------------------------------------

def test_users_list_shape(make_client, fake_gitea):
    fake = fake_gitea(FakeGitea(
        team_members=[user("uma.user")],
        collaborators=[user("adam.approver", "Adam Approver"),
                       user("ben.browser", "Ben Browser"),
                       user("uma.user", "Uma User")],
        permissions={"adam.approver": "write", "ben.browser": "read",
                     "uma.user": "read"},
    ))
    with make_client("admin") as client:
        resp = client.get("/api/admin/users")
    assert resp.status_code == 200
    data = resp.json()
    assert data["team_found"] is True
    assert data["users"] == [
        {"username": "adam.approver", "full_name": "Adam Approver",
         "role": "approver", "contributor": False},
        {"username": "ben.browser", "full_name": "Ben Browser",
         "role": "browser", "contributor": False},
        {"username": "uma.user", "full_name": "Uma User",
         "role": "contributor", "contributor": True},
    ]
    # Every read went out with the admin's own token — never the bot's.
    assert all(call[0] == "admin-tok" for call in fake.calls)


def test_team_only_member_appears_without_direct_grant(make_client, fake_gitea):
    """An LDAP-synced team member with no direct collaborator entry still
    shows up, as a contributor (read comes via the team)."""
    fake_gitea(FakeGitea(
        team_members=[user("ldap.person")],
        collaborators=[],
        permissions={"ldap.person": "read"},
    ))
    with make_client("admin") as client:
        data = client.get("/api/admin/users").json()
    assert data["users"] == [{"username": "ldap.person", "full_name": "",
                              "role": "contributor", "contributor": True}]


def test_bot_account_is_hidden(make_client, fake_gitea, monkeypatch):
    # Settings is a frozen dataclass — swap the module's reference instead.
    monkeypatch.setattr(admin, "settings",
                        dataclasses.replace(settings, bot_username="pl-bot"))
    fake_gitea(FakeGitea(
        collaborators=[user("pl-bot"), user("ben.browser")],
        permissions={"ben.browser": "read"},
    ))
    with make_client("admin") as client:
        data = client.get("/api/admin/users").json()
    assert [u["username"] for u in data["users"]] == ["ben.browser"]


def test_unreadable_permission_fails_closed_to_browser(make_client, fake_gitea):
    fake_gitea(FakeGitea(collaborators=[user("ghost")], permissions={}))
    with make_client("admin") as client:
        data = client.get("/api/admin/users").json()
    assert data["users"][0]["role"] == "browser"


def test_missing_team_is_reported_not_fatal(make_client, fake_gitea):
    fake_gitea(FakeGitea(teams=[], collaborators=[user("ben.browser")],
                         permissions={"ben.browser": "read"}))
    with make_client("admin") as client:
        data = client.get("/api/admin/users").json()
    assert data["team_found"] is False
    assert data["users"][0]["role"] == "browser"


# --- PUT /users/{username}/contributor --------------------------------------

def test_add_and_remove_member(make_client, fake_gitea):
    fake = fake_gitea(FakeGitea())
    with make_client("admin") as client:
        resp = client.put("/api/admin/users/ben.browser/contributor",
                          json={"member": True})
        assert resp.status_code == 200
        assert resp.json()["contributor"] is True
        resp = client.put("/api/admin/users/uma.user/contributor",
                          json={"member": False})
        assert resp.status_code == 200
        assert resp.json()["contributor"] is False
    mutations = [(m, p) for (_t, m, p) in fake.calls if m != "GET"]
    assert mutations == [("PUT", "/teams/7/members/ben.browser"),
                         ("DELETE", "/teams/7/members/uma.user")]


def test_membership_change_without_team_is_404(make_client, fake_gitea):
    fake_gitea(FakeGitea(teams=[]))
    with make_client("admin") as client:
        resp = client.put("/api/admin/users/ben.browser/contributor",
                          json={"member": True})
    assert resp.status_code == 404
    assert "contributors" in resp.json()["detail"]


def test_gitea_403_passes_through_verbatim(make_client, monkeypatch):
    """Team mutation needs org owner; a plain repo-admin sees Gitea's own
    message, not a rewrapped one."""
    async def fake_api(token, method, path, **kwargs):
        if method == "GET":
            return [{"id": 7, "name": "contributors"}]
        raise HTTPException(status_code=403,
                            detail="Must be an organization owner")
    monkeypatch.setattr(admin.gitea, "api", fake_api)
    with make_client("admin") as client:
        resp = client.put("/api/admin/users/ben.browser/contributor",
                          json={"member": True})
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Must be an organization owner"


# --- POST /users (add) ------------------------------------------------------

def test_add_user_as_browser(make_client, fake_gitea):
    fake = fake_gitea(FakeGitea())
    with make_client("admin") as client:
        resp = client.post("/api/admin/users", json={"username": "new.hire"})
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"message": "new.hire now has access to the library as a Browser.",
                    "username": "new.hire", "role": "browser"}
    # The default permission is read, sent as the admin, to the collaborator API.
    grant = [(t, m, p) for (t, m, p) in fake.calls
             if p == f"{settings.repo_api}/collaborators/new.hire"]
    assert grant == [("admin-tok", "PUT",
                      f"{settings.repo_api}/collaborators/new.hire")]


def test_add_user_as_approver(make_client, fake_gitea):
    fake_gitea(FakeGitea())
    with make_client("admin") as client:
        resp = client.post("/api/admin/users",
                           json={"username": "amy.approver", "permission": "write"})
    assert resp.status_code == 200
    assert resp.json()["role"] == "approver"
    assert "Bank Approver" in resp.json()["message"]


def test_add_user_rejects_ungrantable_permission(make_client, fake_gitea):
    fake_gitea(FakeGitea())
    with make_client("admin") as client:
        # "admin" is a real Gitea permission but not grantable from this page.
        resp = client.post("/api/admin/users",
                           json={"username": "eve", "permission": "admin"})
    assert resp.status_code == 400


def test_add_user_rejects_blank_username(make_client, fake_gitea):
    fake_gitea(FakeGitea())
    with make_client("admin") as client:
        resp = client.post("/api/admin/users", json={"username": "   "})
    assert resp.status_code == 400


def test_add_user_refuses_bot(make_client, fake_gitea, monkeypatch):
    monkeypatch.setattr(admin, "settings",
                        dataclasses.replace(settings, bot_username="pl-bot"))
    fake_gitea(FakeGitea())
    with make_client("admin") as client:
        resp = client.post("/api/admin/users", json={"username": "pl-bot"})
    assert resp.status_code == 400


def test_add_user_gitea_404_passes_through(make_client, monkeypatch):
    """Unknown username -> Gitea 404, surfaced verbatim so the admin knows why."""
    async def fake_api(token, method, path, **kwargs):
        raise HTTPException(status_code=404, detail="user does not exist")
    monkeypatch.setattr(admin.gitea, "api", fake_api)
    with make_client("admin") as client:
        resp = client.post("/api/admin/users", json={"username": "ghost"})
    assert resp.status_code == 404
    assert resp.json()["detail"] == "user does not exist"


# --- DELETE /users/{username} (remove) --------------------------------------

def test_remove_direct_collaborator(make_client, fake_gitea):
    """A user with only a direct grant (not in the team): team is skipped, the
    collaborator entry is dropped as the admin."""
    fake = fake_gitea(FakeGitea(
        collaborators=[user("ben.browser")], permissions={"ben.browser": "read"}))
    with make_client("admin") as client:
        resp = client.delete("/api/admin/users/ben.browser")
    assert resp.status_code == 200
    assert resp.json()["username"] == "ben.browser"
    mutations = [(m, p) for (_t, m, p) in fake.calls if m == "DELETE"]
    assert mutations == [("DELETE", f"{settings.repo_api}/collaborators/ben.browser")]


def test_remove_team_member_drops_both(make_client, fake_gitea):
    """A user who is both a team member and a collaborator loses both grants,
    team first."""
    fake = fake_gitea(FakeGitea(
        team_members=[user("uma.user")],
        collaborators=[user("uma.user")], permissions={"uma.user": "read"}))
    with make_client("admin") as client:
        resp = client.delete("/api/admin/users/uma.user")
    assert resp.status_code == 200
    mutations = [(m, p) for (_t, m, p) in fake.calls if m == "DELETE"]
    assert mutations == [("DELETE", "/teams/7/members/uma.user"),
                         ("DELETE", f"{settings.repo_api}/collaborators/uma.user")]


def test_remove_team_only_member_ignores_collaborator_404(make_client, monkeypatch):
    """A team-only user has no direct grant: the collaborator DELETE 404s and
    that is treated as success (the team removal was the real revoke)."""
    calls = []

    async def fake_api(token, method, path, **kwargs):
        calls.append((method, path))
        if method == "GET" and path == f"/orgs/{settings.repo_owner}/teams":
            return [{"id": 7, "name": "contributors"}] \
                if (kwargs.get("params") or {}).get("page", 1) == 1 else []
        if method == "GET" and path == "/teams/7/members":
            return [{"login": "ldap.person"}] \
                if (kwargs.get("params") or {}).get("page", 1) == 1 else []
        if method == "DELETE" and path == "/teams/7/members/ldap.person":
            return None
        if method == "DELETE" and \
                path == f"{settings.repo_api}/collaborators/ldap.person":
            raise HTTPException(status_code=404, detail="not a collaborator")
        raise AssertionError(f"unexpected Gitea call: {method} {path}")

    monkeypatch.setattr(admin.gitea, "api", fake_api)
    with make_client("admin") as client:
        resp = client.delete("/api/admin/users/ldap.person")
    assert resp.status_code == 200
    assert ("DELETE", "/teams/7/members/ldap.person") in calls


def test_remove_refuses_self(make_client, fake_gitea):
    fake_gitea(FakeGitea())
    with make_client("admin") as client:
        resp = client.delete(f"/api/admin/users/{ADMIN}")
    assert resp.status_code == 400
    assert "your own" in resp.json()["detail"]


def test_remove_refuses_bot(make_client, fake_gitea, monkeypatch):
    monkeypatch.setattr(admin, "settings",
                        dataclasses.replace(settings, bot_username="pl-bot"))
    fake_gitea(FakeGitea())
    with make_client("admin") as client:
        resp = client.delete("/api/admin/users/pl-bot")
    assert resp.status_code == 400


def test_remove_collaborator_error_other_than_404_propagates(make_client, monkeypatch):
    async def fake_api(token, method, path, **kwargs):
        if method == "GET" and path == f"/orgs/{settings.repo_owner}/teams":
            return []  # no team -> skip team removal
        if method == "DELETE":
            raise HTTPException(status_code=403, detail="Forbidden")
        raise AssertionError(f"unexpected Gitea call: {method} {path}")
    monkeypatch.setattr(admin.gitea, "api", fake_api)
    with make_client("admin") as client:
        resp = client.delete("/api/admin/users/ben.browser")
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Forbidden"
