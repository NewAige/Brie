"""Raising a prompt from Community to Bank (docs/bank-upgrade.md).

The promotion endpoint is a single sha-guarded direct commit to main, made
with the promoting approver's own token. These tests fake only the two Gitea
calls it makes (contents GET + PUT on main) and exercise the real router:
the approver gate, the 404/409s, the one-line diff, and that a blob-sha
conflict surfaces as a retryable 409 with no internal retry.
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
COMMUNITY = """---
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
BANK = COMMUNITY.replace("level: community", "level: bank")


class FakeGitea:
    """Just the contents API on the library repo's main branch."""

    def __init__(self):
        self.main_files: dict[str, str] = {PATH: COMMUNITY}
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


def _raise(client, path=PATH, level="bank"):
    return client.post(f"/api/prompts/{path}/level", json={"level": level})


# --- the approver gate ------------------------------------------------------

@pytest.mark.parametrize("role", ["browser", "contributor"])
def test_non_approvers_get_403_and_nothing_is_written(fake, make_client, role):
    """The 403 is the control, not the hidden button — and it comes from the
    live-derived role (roles.get_role), which the fixture stubs."""
    with make_client(role) as client:
        resp = _raise(client)
    assert resp.status_code == 403
    assert "Bank Approver" in resp.json()["detail"]
    assert fake.put_attempts == 0
    assert fake.main_files[PATH] == COMMUNITY


@pytest.mark.parametrize("role", ["approver", "admin"])
def test_approver_and_admin_may_raise(fake, make_client, role):
    with make_client(role) as client:
        assert _raise(client).status_code == 200


# --- the happy path ---------------------------------------------------------

def test_promotion_changes_exactly_the_level_line(fake, make_client):
    with make_client() as client:
        resp = _raise(client)
    assert resp.status_code == 200
    assert resp.json()["level"] == "bank"

    (write,) = fake.writes
    assert write["branch"] == "main"
    assert write["sha"] == "blob-1"  # sha-guarded: compare-and-swap on main
    committed = base64.b64decode(write["content"]).decode()
    # One-line diff: everything except the level line is byte-identical,
    # including the `---` horizontal rule inside the body.
    assert committed == BANK
    assert committed.count("level:") == 1


def test_promotion_commit_message_names_the_decision(fake, make_client):
    with make_client() as client:
        _raise(client)
    message = fake.writes[0]["message"]
    assert message.startswith("Raise to Bank: Escalation Email Tone")
    assert f"Raised by {ADAM}" in message


# --- state checks read main, never the caller -------------------------------

def test_already_bank_is_409_with_no_write(fake, make_client):
    fake.main_files[PATH] = BANK
    with make_client() as client:
        resp = _raise(client)
    assert resp.status_code == 409
    assert fake.put_attempts == 0


def test_missing_level_counts_as_bank(fake, make_client):
    """No `level:` at all parses as Bank (fail closed, phase A) — so it is
    already the stricter tier and promotion 409s rather than writing."""
    fake.main_files[PATH] = COMMUNITY.replace("level: community\n", "")
    with make_client() as client:
        resp = _raise(client)
    assert resp.status_code == 409
    assert fake.put_attempts == 0


@pytest.mark.parametrize("bad", ["foo.md", "_templates/x.md",
                                 "customer-support/readme.md"])
def test_invalid_path_is_404_with_no_write(fake, make_client, bad):
    # Even present on main: templates and READMEs are not library prompts,
    # so they have no level to raise.
    fake.main_files[bad] = COMMUNITY
    with make_client() as client:
        assert _raise(client, path=bad).status_code == 404
    assert fake.put_attempts == 0


def test_prompt_not_on_main_is_404_with_no_write(fake, make_client):
    with make_client() as client:
        resp = _raise(client, path="customer-support/does-not-exist.md")
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
        resp = _raise(client)
    assert resp.status_code == 409
    assert "changed while" in resp.json()["detail"]
    assert fake.put_attempts == 1, "must not retry a conflicted promotion"


# --- the Literal gate -------------------------------------------------------

@pytest.mark.parametrize("level", ["community", "Bank", "secret", ""])
def test_only_bank_is_an_accepted_level(fake, make_client, level):
    """Demotion (and junk) is structurally impossible: anything but exactly
    "bank" fails validation before any Gitea call."""
    with make_client() as client:
        resp = _raise(client, level=level)
    assert resp.status_code == 422
    assert fake.put_attempts == 0
