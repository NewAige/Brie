"""Favourites: per-user marks on library prompts, and the two personal filters
on the browse endpoint (`favorites=`, `mine=`).

The prompt index is faked so the tests exercise the real filtering loop in
routers/prompts.py against a known library, and the real SQLite storage.
"""

import pytest
from fastapi.testclient import TestClient

from app import db, prompt_index, roles
from app.config import settings
from app.deps import UserSession, current_session
from app.main import app

UMA = "uma.user"
OTHER = "otto.other"

FAVE = "customer-support/account-balance-faq.md"
MINE = "customer-support/escalation-email-tone.md"
THEIRS = "marketing/launch-copy.md"
DEPRECATED = "marketing/old-tagline.md"


def _prompt(path, *, author=OTHER, owner=OTHER, status="approved", tags=(),
            title="A Prompt", body="body text"):
    return {"path": path, "category": path.split("/")[0], "title": title,
            "tags": list(tags), "status": status, "level": "community",
            "author": author, "owner": owner, "copied_from": "",
            "target_model": "", "intended_use": "", "review_notes": "",
            "body": body}


LIBRARY = [
    _prompt(FAVE, title="Account Balance FAQ", tags=["support"]),
    _prompt(MINE, author=UMA, owner=UMA, title="Escalation Tone", tags=["support"]),
    _prompt(THEIRS, title="Launch Copy", tags=["marketing"]),
    _prompt(DEPRECATED, title="Old Tagline", status="deprecated"),
]


@pytest.fixture
def fresh_db(tmp_path):
    """Point the app at an empty per-test database (settings is frozen)."""
    original = settings.db_path
    object.__setattr__(settings, "db_path", str(tmp_path / "app.db"))
    db.init_db()
    yield
    object.__setattr__(settings, "db_path", original)


@pytest.fixture
def client(monkeypatch, fresh_db) -> TestClient:
    async def fake_index(token):
        return [dict(p) for p in LIBRARY]
    monkeypatch.setattr(prompt_index, "get_index", fake_index)
    monkeypatch.setattr(prompt_index, "is_valid_prompt_path",
                        lambda path: path in {p["path"] for p in LIBRARY})

    async def fake_get_role(session_id, token):
        return "contributor"
    monkeypatch.setattr(roles, "get_role", fake_get_role)

    app.dependency_overrides[current_session] = \
        lambda: UserSession("test-session", UMA, "tok")
    yield TestClient(app)
    app.dependency_overrides.clear()


def paths(response) -> list[str]:
    return [p["path"] for p in response.json()]


# --- storage ----------------------------------------------------------------

def test_add_and_remove_favorite(fresh_db):
    db.add_favorite(UMA, FAVE)
    assert db.favorite_paths(UMA) == {FAVE}
    db.remove_favorite(UMA, FAVE)
    assert db.favorite_paths(UMA) == set()


def test_add_favorite_is_idempotent(fresh_db):
    """Double-marking must not raise on the composite primary key."""
    db.add_favorite(UMA, FAVE)
    db.add_favorite(UMA, FAVE)
    assert db.favorite_paths(UMA) == {FAVE}


def test_favorites_are_per_user(fresh_db):
    db.add_favorite(UMA, FAVE)
    db.add_favorite(OTHER, THEIRS)
    assert db.favorite_paths(UMA) == {FAVE}
    assert db.favorite_paths(OTHER) == {THEIRS}


def test_remove_favorite_unmarked_is_noop(fresh_db):
    db.remove_favorite(UMA, FAVE)  # never marked
    assert db.favorite_paths(UMA) == set()


# --- mark / unmark endpoints ------------------------------------------------

def test_put_then_delete_favorite(client):
    assert client.put(f"/api/prompts/{FAVE}/favorite").json() == {"favorited": True}
    assert db.favorite_paths(UMA) == {FAVE}
    assert client.delete(f"/api/prompts/{FAVE}/favorite").json() == {"favorited": False}
    assert db.favorite_paths(UMA) == set()


def test_favoriting_unknown_prompt_404s(client):
    assert client.put("/api/prompts/nope/does-not-exist.md/favorite").status_code == 404


def test_unfavoriting_unknown_prompt_succeeds(client):
    """A prompt deleted from the library leaves a stale row the user must
    still be able to clear, so DELETE deliberately skips path validation."""
    db.add_favorite(UMA, "gone/deleted.md")
    assert client.delete("/api/prompts/gone/deleted.md/favorite").status_code == 200
    assert db.favorite_paths(UMA) == set()


# --- the favorited flag -----------------------------------------------------

def test_list_reports_favorited_flag(client):
    client.put(f"/api/prompts/{FAVE}/favorite")
    flags = {p["path"]: p["favorited"] for p in client.get("/api/prompts").json()}
    assert flags[FAVE] is True
    assert flags[THEIRS] is False


# --- filtering --------------------------------------------------------------

def test_favorites_filter_narrows_to_marked(client):
    client.put(f"/api/prompts/{FAVE}/favorite")
    assert paths(client.get("/api/prompts?favorites=true")) == [FAVE]


def test_favorites_filter_empty_when_nothing_marked(client):
    assert client.get("/api/prompts?favorites=true").json() == []


def test_favorites_filter_is_per_user(client):
    """Another user's marks must not leak into this user's view."""
    db.add_favorite(OTHER, THEIRS)
    assert client.get("/api/prompts?favorites=true").json() == []


def test_mine_filter_matches_author_and_owner(client):
    assert paths(client.get("/api/prompts?mine=true")) == [MINE]


def test_mine_filter_includes_prompts_handed_over(client, monkeypatch):
    """Authored by someone else but now maintained by us — still 'mine'."""
    handed_over = _prompt("marketing/handover.md", author=OTHER, owner=UMA)

    async def fake_index(token):
        return [dict(p) for p in LIBRARY] + [handed_over]
    monkeypatch.setattr(prompt_index, "get_index", fake_index)

    assert "marketing/handover.md" in paths(client.get("/api/prompts?mine=true"))


def test_filters_compose_with_each_other_and_with_search(client):
    client.put(f"/api/prompts/{FAVE}/favorite")
    client.put(f"/api/prompts/{MINE}/favorite")

    # favourites ∩ mine
    assert paths(client.get("/api/prompts?favorites=true&mine=true")) == [MINE]
    # favourites ∩ category
    assert paths(client.get(
        "/api/prompts?favorites=true&category=customer-support")) == [FAVE, MINE]
    # favourites ∩ tag
    assert paths(client.get("/api/prompts?favorites=true&tag=support")) == [FAVE, MINE]
    # favourites ∩ full-text search
    assert paths(client.get("/api/prompts?favorites=true&q=escalation")) == [MINE]


def test_favorites_filter_still_hides_deprecated(client):
    """Marking a prompt that later got deprecated must not resurrect it in the
    default browse view — the deprecation check runs first."""
    db.add_favorite(UMA, DEPRECATED)
    assert client.get("/api/prompts?favorites=true").json() == []
    assert paths(client.get(
        "/api/prompts?favorites=true&include_deprecated=true")) == [DEPRECATED]


def test_no_filters_returns_everything_visible(client):
    assert paths(client.get("/api/prompts")) == [FAVE, MINE, THEIRS]


def test_list_always_includes_updated_field(client):
    """The library table shows a last-modified column; `updated` is set by the
    real index at rebuild time and must fall back to "" (not a KeyError) when
    the index entry predates the field — as this faked library does."""
    rows = client.get("/api/prompts").json()
    assert rows
    assert all(p["updated"] == "" for p in rows)
