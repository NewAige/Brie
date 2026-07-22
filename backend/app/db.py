"""SQLite storage.

Holds a handful of things, none of which is prompt data (Gitea's git repo is
the single source of truth):

- sessions:      session id -> the user's Gitea OAuth tokens. Tokens live
                 server-side ONLY; the browser holds just the opaque session id
                 in an httpOnly cookie.
- oauth_states:  short-lived CSRF `state` values for in-flight OAuth logins.
- copy_events:   prompt path + timestamp per copy click. Deliberately nothing
                 else — no user id, no prompt content, no PII (spec §7).
- favorites:     (username, prompt path) pairs — a user's starred prompts.
                 The username is required so a user can star a prompt at most
                 once; no prompt content is stored.
- remix_events:  source prompt path + timestamp, logged when someone saves a
                 copy of a prompt as a new prompt. Same minimal shape as
                 copy_events.
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
CREATE TABLE IF NOT EXISTS favorites (
    username TEXT NOT NULL,
    path     TEXT NOT NULL,
    ts       REAL NOT NULL,
    PRIMARY KEY (username, path)
);
CREATE INDEX IF NOT EXISTS idx_favorites_path ON favorites(path);
CREATE TABLE IF NOT EXISTS remix_events (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL,
    ts   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_remix_events_path ON remix_events(path);
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


def most_copied(limit: int = 10) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT path, COUNT(*) AS copies FROM copy_events GROUP BY path "
            "ORDER BY copies DESC, path ASC LIMIT ?",
            (limit,),
        ).fetchall()
    return [{"path": r["path"], "copies": r["copies"]} for r in rows]


# --- favorites --------------------------------------------------------------

def add_favorite(username: str, path: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO favorites (username, path, ts) VALUES (?, ?, ?)",
            (username, path, time.time()),
        )


def remove_favorite(username: str, path: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM favorites WHERE username = ? AND path = ?",
                     (username, path))


def favorite_state(username: str, path: str) -> dict:
    """The star count for a prompt plus whether this user has starred it."""
    with connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM favorites WHERE path = ?", (path,)
        ).fetchone()["n"]
        mine = conn.execute(
            "SELECT 1 FROM favorites WHERE username = ? AND path = ?",
            (username, path),
        ).fetchone()
    return {"favorites": count, "favorited": mine is not None}


def most_favorited(limit: int = 10) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT path, COUNT(*) AS favorites FROM favorites GROUP BY path "
            "ORDER BY favorites DESC, path ASC LIMIT ?",
            (limit,),
        ).fetchall()
    return [{"path": r["path"], "favorites": r["favorites"]} for r in rows]


# --- remix events -----------------------------------------------------------

def log_remix_event(path: str) -> None:
    with connect() as conn:
        conn.execute("INSERT INTO remix_events (path, ts) VALUES (?, ?)",
                     (path, time.time()))


def most_remixed(limit: int = 10) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT path, COUNT(*) AS remixes FROM remix_events GROUP BY path "
            "ORDER BY remixes DESC, path ASC LIMIT ?",
            (limit,),
        ).fetchall()
    return [{"path": r["path"], "remixes": r["remixes"]} for r in rows]
