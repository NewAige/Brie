"""Archiving a prompt: retire it from the library, keep it by direct link.

Archive is the phase-C sibling of the promote endpoint (test_promote.py): a
single sha-guarded direct commit to main, made with the archiving approver's
own token. These tests fake only the two Gitea calls it makes (contents GET +
PUT on main) and exercise the real router: the approver gate, the confirm
stop-gap, the 404/409s, the one-line diff, and that a blob-sha conflict
surfaces as a retryable 409 with no internal retry.
"""

import base64

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import gitea, roles
from app.config import settings
from app.deps import UserSession, current_session
from app.main import app

ADAM = "adam.approver"
PATH = "customer-support/escalation-email-tone.md"
LIVE = """---
title: Escalation Email Tone
category: customer-support
tags: [tone, escalation]
status: approved
level: community
author: uma.user
owner: uma.user
intended_use: Calm down an angry thread.
---

Write a calm escalation email.

---

Keep the horizontal rule above intact.
"""
ARCHIVED = LIVE.replace("status: approved", "status: archived")


class FakeGitea:
    """Just the contents API on the library repo's main branch."""

    def __init__(self):
        self.main_files: dict[str, str] = {PATH: LIVE}
        self.blob_sha = "blob-1"
        self.put_fails_with: int | None = None
        self.put_attempts = 0
        self.writes: list[dict] = []

    async def api(self, token, method, path, *, params=None, json=None, raw=False):
        lib = settings.repo_api
        if method == "GET" and path.startswith(f"{lib}/contents/"):
            name = path.removeprefix(f"{lib}/contents/")
            if name in self.main_files:
                return {"type": "file", "sha": self.blob_sha, "encoding": "base64",
                        "content": base64.b64encode(
                            self.main_files[name].encode()).decode()}
            raise HTTPException(status_code=404, detail="not found")
        if method == "PUT" and path.startswith(f"{lib}/contents/"):
            self.put_attempts += 1
            if self.put_fails_with:
                raise HTTPException(status_code=self.put_fails_with,
                                    detail="sha mismatch")
            self.writes.append(json)
            name = path.removeprefix(f"{lib}/contents/")
            self.main_files[name] = base64.b64decode(json["content"]).decode()
            return {"content": {"path": name}}
        raise AssertionError(f"unexpected Gitea call: {method} {path}")


@pytest.fixture
def fake(monkeypatch) -> FakeGitea:
    fg = FakeGitea()
    monkeypatch.setattr(gitea, "api", fg.api)
    return fg


@pytest.fixture
def make_client(monkeypatch):
    def make(role: str = "approver") -> TestClient:
        async def fake_get_role(session_id, token):
            return role
        monkeypatch.setattr(roles, "get_role", fake_get_role)
        app.dependency_overrides[current_session] = \
            lambda: UserSession("test-session", ADAM, "tok")
        return TestClient(app)
    yield make
    app.dependency_overrides.clear()


def _archive(client, path=PATH, confirm=True):
    return client.post(f"/api/prompts/{path}/archive", json={"confirm": confirm})


# --- the approver gate ------------------------------------------------------

@pytest.mark.parametrize("role", ["browser", "contributor"])
def test_non_approvers_get_403_and_nothing_is_written(fake, make_client, role):
    """The 403 is the control, not the hidden button — it comes from the
    live-derived role (roles.get_role), which the fixture stubs."""
    with make_client(role) as client:
        resp = _archive(client)
    assert resp.status_code == 403
    assert fake.put_attempts == 0
    assert fake.main_files[PATH] == LIVE


@pytest.mark.parametrize("role", ["approver", "admin"])
def test_approver_and_admin_may_archive(fake, make_client, role):
    with make_client(role) as client:
        assert _archive(client).status_code == 200


# --- the confirm stop-gap ---------------------------------------------------

def test_archive_without_confirm_is_400_with_no_write(fake, make_client):
    """The stop-gap is server-side too: confirm:false writes nothing, so a
    stray call can never retire a prompt."""
    with make_client() as client:
        resp = _archive(client, confirm=False)
    assert resp.status_code == 400
    assert fake.put_attempts == 0
    assert fake.main_files[PATH] == LIVE


def test_archive_missing_confirm_is_422(fake, make_client):
    """`confirm` is required — omitting it fails validation before any write."""
    with make_client() as client:
        resp = client.post(f"/api/prompts/{PATH}/archive", json={})
    assert resp.status_code == 422
    assert fake.put_attempts == 0


# --- the happy path ---------------------------------------------------------

def test_archive_changes_exactly_the_status_line(fake, make_client):
    with make_client() as client:
        resp = _archive(client)
    assert resp.status_code == 200
    assert resp.json()["status"] == "archived"

    (write,) = fake.writes
    assert write["branch"] == "main"
    assert write["sha"] == "blob-1"  # sha-guarded: compare-and-swap on main
    committed = base64.b64decode(write["content"]).decode()
    # One-line diff: everything except the status line is byte-identical,
    # including `level: community` and the `---` horizontal rule in the body.
    assert committed == ARCHIVED
    assert committed.count("status:") == 1
    assert "level: community" in committed


def test_archive_commit_message_names_the_decision(fake, make_client):
    with make_client() as client:
        _archive(client)
    message = fake.writes[0]["message"]
    assert message.startswith("Archive: Escalation Email Tone")
    assert f"Archived by {ADAM}" in message


# --- state checks read main, never the caller -------------------------------

def test_already_archived_is_409_with_no_write(fake, make_client):
    fake.main_files[PATH] = ARCHIVED
    with make_client() as client:
        resp = _archive(client)
    assert resp.status_code == 409
    assert fake.put_attempts == 0


@pytest.mark.parametrize("bad", ["foo.md", "_templates/x.md",
                                 "customer-support/readme.md"])
def test_invalid_path_is_404_with_no_write(fake, make_client, bad):
    # Even present on main: templates and READMEs are not library prompts,
    # so they have no status to change.
    fake.main_files[bad] = LIVE
    with make_client() as client:
        assert _archive(client, path=bad).status_code == 404
    assert fake.put_attempts == 0


def test_prompt_not_on_main_is_404_with_no_write(fake, make_client):
    with make_client() as client:
        resp = _archive(client, path="customer-support/does-not-exist.md")
    assert resp.status_code == 404
    assert fake.put_attempts == 0


# --- concurrency ------------------------------------------------------------

@pytest.mark.parametrize("gitea_status", [409, 422])
def test_sha_conflict_surfaces_as_409_without_retry(fake, make_client, gitea_status):
    """If main moves between the read and the write, Gitea refuses the stale
    sha. The endpoint reports a retryable conflict and does NOT re-read and
    retry internally — re-reading means re-deciding."""
    fake.put_fails_with = gitea_status
    with make_client() as client:
        resp = _archive(client)
    assert resp.status_code == 409
    assert "changed while" in resp.json()["detail"]
    assert fake.put_attempts == 1, "must not retry a conflicted archive"
