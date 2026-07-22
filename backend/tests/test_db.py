"""Phase C storage changes: the owner_merges audit trail records who authored
the PR (`pr_author`) and whether the publish was a self- or peer-approval
(`kind`), and databases created before those columns existed are upgraded in
place by init_db.
"""

import sqlite3

import pytest

from app import db
from app.config import settings


@pytest.fixture
def fresh_db(tmp_path):
    """Point the app at an empty per-test database. Settings is a frozen
    dataclass, so the swap goes through object.__setattr__."""
    original = settings.db_path
    object.__setattr__(settings, "db_path", str(tmp_path / "app.db"))
    yield
    object.__setattr__(settings, "db_path", original)


def test_log_owner_merge_records_author_and_kind(fresh_db):
    db.init_db()
    db.log_owner_merge("uma.user", 7, ["a/b.md"],
                       pr_author="adam.approver", kind="peer")
    row = db.recent_owner_merges()[0]
    assert row["username"] == "uma.user"
    assert row["pr_author"] == "adam.approver"
    assert row["kind"] == "peer"


def test_log_owner_merge_defaults_to_self(fresh_db):
    """Pre-phase-C call shape still works and reads as a self-publish."""
    db.init_db()
    db.log_owner_merge("uma.user", 7, ["a/b.md"])
    row = db.recent_owner_merges()[0]
    assert row["pr_author"] == ""
    assert row["kind"] == "self"


def test_init_db_upgrades_legacy_owner_merges(fresh_db):
    """A database created before phase C (no pr_author/kind columns) gains
    them on init_db, and its existing rows read back as self-publishes."""
    with sqlite3.connect(settings.db_path) as conn:
        conn.execute(
            "CREATE TABLE owner_merges ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " username TEXT NOT NULL, pr_id INTEGER NOT NULL,"
            " paths TEXT NOT NULL, ts REAL NOT NULL)")
        conn.execute(
            "INSERT INTO owner_merges (username, pr_id, paths, ts) "
            "VALUES ('uma.user', 3, 'a/b.md', 1.0)")

    db.init_db()

    rows = db.recent_owner_merges()
    assert rows[0]["pr_author"] == ""
    assert rows[0]["kind"] == "self"

    db.log_owner_merge("uma.user", 4, ["a/b.md"],
                       pr_author="peer.person", kind="peer")
    assert db.recent_owner_merges()[0]["kind"] == "peer"


def test_init_db_idempotent_after_upgrade(fresh_db):
    db.init_db()
    db.init_db()  # must not fail on already-added columns


def test_suggestion_outcome_roundtrip(fresh_db):
    db.init_db()
    db.log_suggestion_outcome(4, "declined", "uma.user",
                              pr_author="carl.contributor", detail="off-brand")
    db.log_suggestion_outcome(9, "partial", "adam.approver", detail="2 of 3")
    assert db.suggestion_outcomes() == {4: "declined", 9: "partial"}


def test_suggestion_outcome_keeps_latest_decision(fresh_db):
    """A suggestion reopened in Gitea and decided again keeps one row —
    the newest decision wins."""
    db.init_db()
    db.log_suggestion_outcome(4, "declined", "uma.user")
    db.log_suggestion_outcome(4, "partial", "uma.user", detail="1 of 2")
    assert db.suggestion_outcomes() == {4: "partial"}


def test_most_favorited_counts_without_usernames(fresh_db):
    """The leaderboard aggregate exposes per-prompt totals only — no
    usernames leave the table."""
    db.init_db()
    db.add_favorite("uma.user", "a/one.md")
    db.add_favorite("carl.contributor", "a/one.md")
    db.add_favorite("uma.user", "b/two.md")
    db.add_favorite("uma.user", "b/two.md")  # idempotent re-mark
    rows = db.most_favorited()
    assert rows == [{"path": "a/one.md", "favorites": 2},
                    {"path": "b/two.md", "favorites": 1}]
    assert all(set(r) == {"path", "favorites"} for r in rows)


def test_most_favorited_unmark_removes_from_tally(fresh_db):
    db.init_db()
    db.add_favorite("uma.user", "a/one.md")
    db.remove_favorite("uma.user", "a/one.md")
    assert db.most_favorited() == []


def test_partial_accept_counts_credits_suggestion_authors(fresh_db):
    """Only partial outcomes count, grouped by who authored the suggestion;
    pre-phase-C rows with no recorded author credit nobody."""
    db.init_db()
    db.log_suggestion_outcome(1, "partial", "adam.approver", pr_author="uma.user")
    db.log_suggestion_outcome(2, "partial", "adam.approver", pr_author="uma.user")
    db.log_suggestion_outcome(3, "declined", "adam.approver", pr_author="uma.user")
    db.log_suggestion_outcome(4, "partial", "adam.approver")  # no author recorded
    assert db.partial_accept_counts() == {"uma.user": 2}
