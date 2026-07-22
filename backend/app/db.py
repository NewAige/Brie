"""SQLite storage.

Holds exactly three things, none of which is prompt data (Gitea's git repo is
the single source of truth):

- sessions:      session id -> the user's Gitea OAuth tokens. Tokens live
                 server-side ONLY; the browser holds just the opaque session id
                 in an httpOnly cookie.
- oauth_states:  short-lived CSRF `state` values for in-flight OAuth logins.
- copy_events:   prompt path + timestamp per copy click. Deliberately nothing
                 else — no user id, no prompt content, no PII (spec §7).
- owner_merges:  audit trail of publishes that bypassed approver review. This
                 one DOES record the username: it is a security audit log for
                 an authorization bypass, not usage analytics, and "who" is the
                 whole point of keeping it.
- favorites:     which prompts a user marked to come back to. Also records the
                 username, for the same reason a bookmark list has to: it is
                 the user's own data, shown back only to them, and useless
                 without knowing whose it is. Not analytics — nothing aggregates
                 across users, and it is deleted when the user unmarks it.
- suggestion_outcomes: how a closed suggestion was decided — declined outright,
                 or partially published (some changes accepted, the rest
                 declined). Gitea only knows "closed", so without this the
                 Decided list would show a half-accepted suggestion as plain
                 "Declined". Records the deciding user: like owner_merges it is
                 a record of a review decision, and "who decided" is the point.
"""

import os
import sqlite3
import time

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id            TEXT PRIMARY KEY,
    username      TEXT NOT NULL,
    access_token  TEXT NOT NULL,
    refresh_token TEXT,
    expires_at    REAL NOT NULL,
    created_at    REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS oauth_states (
    state      TEXT PRIMARY KEY,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS copy_events (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL,
    ts   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_copy_events_path ON copy_events(path);
CREATE TABLE IF NOT EXISTS owner_merges (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    username  TEXT NOT NULL,
    pr_id     INTEGER NOT NULL,
    paths     TEXT NOT NULL,
    ts        REAL NOT NULL,
    pr_author TEXT NOT NULL DEFAULT '',
    kind      TEXT NOT NULL DEFAULT 'self'
);
CREATE INDEX IF NOT EXISTS idx_owner_merges_ts ON owner_merges(ts);
CREATE TABLE IF NOT EXISTS suggestion_outcomes (
    pr_id     INTEGER PRIMARY KEY,
    outcome   TEXT NOT NULL,             -- 'declined' | 'partial'
    actor     TEXT NOT NULL,
    pr_author TEXT NOT NULL DEFAULT '',
    detail    TEXT NOT NULL DEFAULT '',
    ts        REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS favorites (
    username TEXT NOT NULL,
    path     TEXT NOT NULL,
    ts       REAL NOT NULL,
    PRIMARY KEY (username, path)
);
CREATE INDEX IF NOT EXISTS idx_favorites_username ON favorites(username);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def init_db() -> None:
    os.makedirs(os.path.dirname(os.path.abspath(settings.db_path)), exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)
        # Phase C: databases created before pr_author/kind existed get the
        # columns added here. CREATE IF NOT EXISTS won't touch an existing
        # table, so this is the upgrade path; the defaults ('', 'self') are
        # also the truthful backfill — every pre-phase-C merge was a
        # self-publish with the author unrecorded.
        existing = {row["name"] for row in
                    conn.execute("PRAGMA table_info(owner_merges)")}
        if "pr_author" not in existing:
            conn.execute("ALTER TABLE owner_merges "
                         "ADD COLUMN pr_author TEXT NOT NULL DEFAULT ''")
        if "kind" not in existing:
            conn.execute("ALTER TABLE owner_merges "
                         "ADD COLUMN kind TEXT NOT NULL DEFAULT 'self'")


# --- sessions ---------------------------------------------------------------

def create_session(session_id: str, username: str, access_token: str,
                   refresh_token: str | None, expires_at: float) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO sessions (id, username, access_token, refresh_token, expires_at, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, username, access_token, refresh_token, expires_at, time.time()),
        )


def get_session(session_id: str) -> sqlite3.Row | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if row is None:
        return None
    if time.time() - row["created_at"] > settings.session_max_age:
        delete_session(session_id)
        return None
    return row


def update_session_tokens(session_id: str, access_token: str,
                          refresh_token: str | None, expires_at: float) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE sessions SET access_token = ?, refresh_token = ?, expires_at = ? WHERE id = ?",
            (access_token, refresh_token, expires_at, session_id),
        )


def delete_session(session_id: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))


# --- oauth states -----------------------------------------------------------

STATE_TTL = 600  # authorization codes expire after ~10 minutes; states match that


def create_state(state: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM oauth_states WHERE created_at < ?", (time.time() - STATE_TTL,))
        conn.execute("INSERT INTO oauth_states (state, created_at) VALUES (?, ?)", (state, time.time()))


def consume_state(state: str) -> bool:
    """Return True iff the state exists and is fresh. Single-use: always deleted."""
    with connect() as conn:
        row = conn.execute("SELECT created_at FROM oauth_states WHERE state = ?", (state,)).fetchone()
        conn.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
    return row is not None and (time.time() - row["created_at"]) <= STATE_TTL


# --- copy events ------------------------------------------------------------

def log_copy_event(path: str) -> None:
    with connect() as conn:
        conn.execute("INSERT INTO copy_events (path, ts) VALUES (?, ?)", (path, time.time()))


def log_owner_merge(username: str, pr_id: int, paths: list[str],
                    pr_author: str = "", kind: str = "self") -> None:
    """Record an approver-free publish. Called only after the merge succeeds.

    `kind` is 'self' when the owner published their own change, 'peer' when
    they published someone else's suggestion — in which case `pr_author` says
    whose.
    """
    with connect() as conn:
        conn.execute(
            "INSERT INTO owner_merges (username, pr_id, paths, ts, pr_author, kind) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (username, pr_id, "\n".join(paths), time.time(), pr_author, kind),
        )


def recent_owner_merges(limit: int = 50) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT username, pr_id, paths, ts, pr_author, kind FROM owner_merges "
            "ORDER BY ts DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [{"username": r["username"], "pr_id": r["pr_id"],
             "paths": r["paths"].split("\n"), "ts": r["ts"],
             "pr_author": r["pr_author"], "kind": r["kind"]} for r in rows]


# --- suggestion outcomes ----------------------------------------------------

def log_suggestion_outcome(pr_id: int, outcome: str, actor: str,
                           pr_author: str = "", detail: str = "") -> None:
    """Record how a suggestion was decided ('declined' or 'partial').
    REPLACE, not INSERT: a re-decided suggestion (reopened in Gitea, decided
    again) keeps one row — the latest decision is the one the list shows."""
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO suggestion_outcomes "
            "(pr_id, outcome, actor, pr_author, detail, ts) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (pr_id, outcome, actor, pr_author, detail, time.time()),
        )


def suggestion_outcomes() -> dict[int, str]:
    """pr_id -> outcome, for annotating the Decided list in one query."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT pr_id, outcome FROM suggestion_outcomes").fetchall()
    return {r["pr_id"]: r["outcome"] for r in rows}


# --- favorites --------------------------------------------------------------

def add_favorite(username: str, path: str) -> None:
    """Mark a prompt. Idempotent — re-marking keeps the original timestamp."""
    with connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO favorites (username, path, ts) VALUES (?, ?, ?)",
            (username, path, time.time()),
        )


def remove_favorite(username: str, path: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM favorites WHERE username = ? AND path = ?",
                     (username, path))


def favorite_paths(username: str) -> set[str]:
    """Every path this user has marked. A set — callers do membership tests."""
    with connect() as conn:
        rows = conn.execute("SELECT path FROM favorites WHERE username = ?",
                            (username,)).fetchall()
    return {r["path"] for r in rows}


def most_copied(limit: int = 10) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT path, COUNT(*) AS copies FROM copy_events GROUP BY path "
            "ORDER BY copies DESC, path ASC LIMIT ?",
            (limit,),
        ).fetchall()
    return [{"path": r["path"], "copies": r["copies"]} for r in rows]
