"""Personal drafts (PLAN.MD phase D).

All Gitea traffic goes through a small in-memory fake covering the handful of
endpoints the drafts router touches (forks, branches, contents, raw, compare,
trees, pulls), so the tests exercise the REAL router + forks plumbing:
path validation reuse, the 409s, browser 403s, and that publishing renders
the chosen level into the front-matter.
"""

import base64

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import gitea, prompt_index, roles
from app.config import settings
from app.deps import UserSession, current_session
from app.main import app

UMA = "uma.user"
FORK_FULL = f"{UMA}/{settings.repo_name}"

DRAFT_PATH = "customer-support/escalation-email-tone.md"
DRAFT_CONTENT = """---
title: Escalation Email Tone
category: customer-support
status: draft
author: uma.user
owner: uma.user
intended_use: Calm down an angry thread.
---

Write a calm escalation email.
"""

NEW_DRAFT = {"title": "Escalation Email Tone", "category": "customer-support",
             "body": "Write a calm escalation email."}


class FakeGitea:
    """Just enough of the Gitea API, keyed on (method, path)."""

    def __init__(self):
        self.has_fork = True
        self.has_drafts_branch = True
        self.draft_files: dict[str, str] = {}
        self.fork_main_files: dict[str, str] = {}
        self.library_main_files: dict[str, str] = {}
        self.open_pr_files: list[str] = []
        self.changed_paths: list[str] = []  # commits unique to drafts branch
        self.commits: dict[str, list] = {}  # path -> newest-first commit dicts
        self.blobs: dict[str, str] = {}     # commit sha -> file content at it
        self.writes: list[tuple[str, str, dict]] = []

    def add_revision(self, path: str, sha: str, content: str, *,
                     message: str = "Draft: update", author: str = UMA,
                     date: str = "2026-01-01T00:00:00Z") -> None:
        """Register one draft save: a commit (prepended so the list stays
        newest-first, as Gitea returns) plus that revision's file content."""
        self.blobs[sha] = content
        self.commits.setdefault(path, []).insert(0, {
            "sha": sha,
            "commit": {"message": message,
                       "author": {"name": author, "date": date}},
        })

    def fork(self) -> dict:
        return {"full_name": FORK_FULL, "owner": {"login": UMA},
                "default_branch": "main"}

    async def api(self, token, method, path, *, params=None, json=None, raw=False):
        params = params or {}
        lib, fork = settings.repo_api, f"/repos/{FORK_FULL}"
        if method in ("POST", "PUT", "DELETE"):
            self.writes.append((method, path, json or {}))

        if (method, path) == ("GET", lib):
            return {"permissions": {"push": False}}
        if (method, path) == ("GET", f"{lib}/forks"):
            return [self.fork()] if self.has_fork else []
        if (method, path) == ("POST", f"{lib}/forks"):
            self.has_fork = True
            return self.fork()
        if (method, path) == ("POST", f"{fork}/sync_fork"):
            return None
        if (method, path) == ("GET", f"{fork}/branches/drafts"):
            if self.has_drafts_branch:
                return {"name": "drafts"}
            raise HTTPException(status_code=404, detail="no branch")
        if (method, path) == ("POST", f"{fork}/branches"):
            self.has_drafts_branch = True
            return {"name": "drafts"}
        if (method, path) == ("GET", f"{fork}/compare/main...drafts"):
            return {"commits": [{"files": [{"filename": p}]}
                                for p in self.changed_paths]}
        if (method, path) == ("GET", f"{fork}/git/trees/drafts"):
            return {"tree": [{"path": p, "type": "blob"}
                             for p in self.draft_files]}
        if (method, path) == ("GET", f"{fork}/commits"):
            return list(self.commits.get(params.get("path"), []))
        if method == "GET" and path.startswith(f"{fork}/raw/"):
            name = path.removeprefix(f"{fork}/raw/")
            ref = params.get("ref")
            if ref in self.blobs:          # a specific commit sha (history)
                return self.blobs[ref]
            if name in self.draft_files:   # the live drafts branch
                return self.draft_files[name]
            raise HTTPException(status_code=404, detail="not found")
        if path.startswith(f"{fork}/contents/"):
            name = path.removeprefix(f"{fork}/contents/")
            files = self.draft_files if (params.get("ref") or (json or {}).get("branch")) == "drafts" \
                else self.fork_main_files
            if method == "GET":
                if name in files:
                    return {"type": "file", "sha": "blob-sha",
                            "content": base64.b64encode(files[name].encode()).decode(),
                            "encoding": "base64"}
                raise HTTPException(status_code=404, detail="not found")
            if method in ("POST", "PUT"):
                if (json or {}).get("branch") == "drafts" and not (json or {}).get("new_branch"):
                    self.draft_files[name] = base64.b64decode(json["content"]).decode()
                return {"content": {"path": name}}
            if method == "DELETE":
                self.draft_files.pop(name, None)
                return None
        if method == "GET" and path.startswith(f"{lib}/contents/"):
            name = path.removeprefix(f"{lib}/contents/")
            if name in self.library_main_files:
                return {"type": "file", "sha": "lib-sha"}
            raise HTTPException(status_code=404, detail="not found")
        if (method, path) == ("GET", f"{lib}/pulls"):
            return [{"number": 1}] if self.open_pr_files else []
        if (method, path) == ("GET", f"{lib}/pulls/1/files"):
            return [{"filename": p} for p in self.open_pr_files]
        if (method, path) == ("POST", f"{lib}/pulls"):
            return {"number": 7}
        raise AssertionError(f"unexpected Gitea call: {method} {path}")


@pytest.fixture
def fake(monkeypatch) -> FakeGitea:
    fg = FakeGitea()
    monkeypatch.setattr(gitea, "api", fg.api)

    async def fake_index(token):
        return [{"path": p} for p in fg.library_main_files]
    monkeypatch.setattr(prompt_index, "get_index", fake_index)
    return fg


@pytest.fixture
def make_client(monkeypatch):
    def make(role: str = "contributor") -> TestClient:
        async def fake_get_role(session_id, token):
            return role
        monkeypatch.setattr(roles, "get_role", fake_get_role)
        app.dependency_overrides[current_session] = \
            lambda: UserSession("test-session", UMA, "tok")
        return TestClient(app)
    yield make
    app.dependency_overrides.clear()


# --- browser gate -----------------------------------------------------------

@pytest.mark.parametrize("method,url,body", [
    ("get", "/api/drafts", None),
    ("post", "/api/drafts", NEW_DRAFT),
    ("get", f"/api/drafts/{DRAFT_PATH}", None),
    ("get", f"/api/drafts/{DRAFT_PATH}/history", None),
    ("put", f"/api/drafts/{DRAFT_PATH}", {"body": "x"}),
    ("delete", f"/api/drafts/{DRAFT_PATH}", None),
    ("post", f"/api/drafts/{DRAFT_PATH}/publish", {"level": "community"}),
])
def test_browser_403_on_every_drafts_endpoint(make_client, method, url, body):
    with make_client("browser") as client:
        resp = getattr(client, method)(url, **({"json": body} if body is not None else {}))
    assert resp.status_code == 403


# --- path validation reuse --------------------------------------------------

@pytest.mark.parametrize("bad", ["foo.md", "_templates/x.md", "customer-support/readme.md"])
def test_draft_paths_use_library_path_rules(fake, make_client, bad):
    with make_client() as client:
        assert client.get(f"/api/drafts/{bad}").status_code == 404
        assert client.delete(f"/api/drafts/{bad}").status_code == 404


def test_create_draft_rejects_reserved_name(fake, make_client):
    """slugify() can't produce `_templates/`, but a "Readme" title slugs to the
    reserved readme.md filename — same guard create_prompt relies on."""
    with make_client() as client:
        resp = client.post("/api/drafts", json={**NEW_DRAFT, "title": "Readme"})
    assert resp.status_code == 400


# --- create / read / update / delete ----------------------------------------

def test_create_draft_commits_to_drafts_branch(fake, make_client):
    fake.has_fork = False
    fake.has_drafts_branch = False
    with make_client() as client:
        resp = client.post("/api/drafts", json=NEW_DRAFT)
    assert resp.status_code == 200
    assert resp.json()["path"] == DRAFT_PATH
    assert fake.has_fork and fake.has_drafts_branch
    saved = fake.draft_files[DRAFT_PATH]
    assert "status: draft" in saved
    assert f"owner: {UMA}" in saved
    assert "level:" not in saved  # level is chosen at publish time


def test_create_draft_409_when_draft_already_exists(fake, make_client):
    fake.draft_files[DRAFT_PATH] = DRAFT_CONTENT
    with make_client() as client:
        resp = client.post("/api/drafts", json=NEW_DRAFT)
    assert resp.status_code == 409


def test_read_update_delete_draft(fake, make_client):
    fake.draft_files[DRAFT_PATH] = DRAFT_CONTENT
    with make_client() as client:
        got = client.get(f"/api/drafts/{DRAFT_PATH}")
        assert got.status_code == 200
        assert got.json()["body"].rstrip("\n") == "Write a calm escalation email."

        assert client.put(f"/api/drafts/{DRAFT_PATH}",
                          json={"body": "New body."}).status_code == 200
        assert fake.draft_files[DRAFT_PATH].endswith("New body.\n")
        assert "title: Escalation Email Tone" in fake.draft_files[DRAFT_PATH]

        assert client.delete(f"/api/drafts/{DRAFT_PATH}").status_code == 200
        assert DRAFT_PATH not in fake.draft_files

        assert client.get(f"/api/drafts/{DRAFT_PATH}").status_code == 404


# --- history ----------------------------------------------------------------

def _removed_lines(diff: str) -> list[str]:
    """Content lines a diff removes — excludes the `---` file header."""
    return [ln for ln in diff.splitlines()
            if ln.startswith("-") and not ln.startswith("---")]


V1 = DRAFT_CONTENT
V2 = DRAFT_CONTENT.replace("Write a calm escalation email.",
                          "Write a very calm, measured escalation email.")


def test_draft_history_returns_revisions_newest_first_with_diffs(fake, make_client):
    fake.draft_files[DRAFT_PATH] = V2
    fake.add_revision(DRAFT_PATH, "sha-old", V1,
                      message="Draft: Escalation Email Tone", date="2026-01-01T00:00:00Z")
    fake.add_revision(DRAFT_PATH, "sha-new", V2,
                      message="Draft: update tone", date="2026-01-02T00:00:00Z")
    with make_client() as client:
        resp = client.get(f"/api/drafts/{DRAFT_PATH}/history")
    assert resp.status_code == 200
    history = resp.json()
    assert [h["sha"] for h in history] == ["sha-new", "sha-old"]  # newest first
    assert history[0]["author"] == UMA
    assert history[0]["message"] == "Draft: update tone"
    # Newest entry diffs against the previous revision.
    assert "+Write a very calm, measured escalation email." in history[0]["diff"]
    assert "-Write a calm escalation email." in history[0]["diff"]
    # Oldest entry diffs against nothing — a full add, no removed lines.
    assert "+Write a calm escalation email." in history[1]["diff"]
    assert _removed_lines(history[1]["diff"]) == []


def test_draft_history_single_commit_is_full_add(fake, make_client):
    fake.draft_files[DRAFT_PATH] = V1
    fake.add_revision(DRAFT_PATH, "sha-1", V1, message="Draft: first save")
    with make_client() as client:
        resp = client.get(f"/api/drafts/{DRAFT_PATH}/history")
    history = resp.json()
    assert len(history) == 1
    assert "+Write a calm escalation email." in history[0]["diff"]


def test_draft_history_404_for_missing_or_reserved_path(fake, make_client):
    with make_client() as client:
        assert client.get(f"/api/drafts/{DRAFT_PATH}/history").status_code == 404  # no draft
        assert client.get("/api/drafts/customer-support/readme.md/history").status_code == 404


# --- publish ----------------------------------------------------------------

def test_publish_renders_chosen_level(fake, make_client):
    fake.draft_files[DRAFT_PATH] = DRAFT_CONTENT
    with make_client() as client:
        resp = client.post(f"/api/drafts/{DRAFT_PATH}/publish",
                           json={"level": "community"})
    assert resp.status_code == 200
    assert resp.json()["id"] == 7
    committed = [j for m, p, j in fake.writes
                 if m == "POST" and p.endswith(f"/contents/{DRAFT_PATH}")
                 and j.get("new_branch")]
    assert committed, "publish never committed the file to a fresh branch"
    content = base64.b64decode(committed[-1]["content"]).decode()
    assert "level: community" in content
    assert f"owner: {UMA}" in content
    assert content.endswith("Write a calm escalation email.\n")


def test_publish_bank_level(fake, make_client):
    fake.draft_files[DRAFT_PATH] = DRAFT_CONTENT
    with make_client() as client:
        resp = client.post(f"/api/drafts/{DRAFT_PATH}/publish", json={"level": "bank"})
    assert resp.status_code == 200
    committed = [j for m, p, j in fake.writes if j.get("new_branch")]
    assert "level: bank" in base64.b64decode(committed[-1]["content"]).decode()


def test_publish_rejects_junk_level(fake, make_client):
    fake.draft_files[DRAFT_PATH] = DRAFT_CONTENT
    with make_client() as client:
        resp = client.post(f"/api/drafts/{DRAFT_PATH}/publish", json={"level": "secret"})
    assert resp.status_code == 422


def test_publish_409_when_path_exists_on_main(fake, make_client):
    fake.draft_files[DRAFT_PATH] = DRAFT_CONTENT
    fake.library_main_files[DRAFT_PATH] = "taken"
    with make_client() as client:
        resp = client.post(f"/api/drafts/{DRAFT_PATH}/publish",
                           json={"level": "community"})
    assert resp.status_code == 409
    assert "already exists" in resp.json()["detail"]


def test_publish_409_when_pr_already_pending(fake, make_client):
    fake.draft_files[DRAFT_PATH] = DRAFT_CONTENT
    fake.open_pr_files = [DRAFT_PATH]
    with make_client() as client:
        resp = client.post(f"/api/drafts/{DRAFT_PATH}/publish",
                           json={"level": "community"})
    assert resp.status_code == 409
    assert "waiting for review" in resp.json()["detail"]


# --- listing ----------------------------------------------------------------

def test_list_is_empty_without_fork_or_branch(fake, make_client):
    fake.has_fork = False
    with make_client() as client:
        assert client.get("/api/drafts").json() == []
    fake.has_fork = True
    fake.has_drafts_branch = False
    with make_client() as client:
        assert client.get("/api/drafts").json() == []
    assert not fake.writes  # listing never creates the fork or the branch


def test_list_shows_only_drafts_not_inherited_files(fake, make_client):
    """The drafts branch also carries every library file it was created from;
    only paths touched by drafts-branch commits are drafts."""
    fake.draft_files[DRAFT_PATH] = DRAFT_CONTENT
    fake.draft_files["internal-ops/some-seed-prompt.md"] = "inherited"
    fake.changed_paths = [DRAFT_PATH, "customer-support/deleted-draft.md"]
    with make_client() as client:
        data = client.get("/api/drafts").json()
    assert [d["path"] for d in data] == [DRAFT_PATH]
    assert data[0]["title"] == "Escalation Email Tone"
    assert data[0]["on_main"] is False
    assert data[0]["pending_pr"] is False


def test_list_annotates_on_main_and_pending_pr(fake, make_client):
    fake.draft_files[DRAFT_PATH] = DRAFT_CONTENT
    fake.changed_paths = [DRAFT_PATH]
    fake.library_main_files[DRAFT_PATH] = "landed"
    fake.open_pr_files = [DRAFT_PATH]
    with make_client() as client:
        data = client.get("/api/drafts").json()
    assert data[0]["on_main"] is True
    assert data[0]["pending_pr"] is True
