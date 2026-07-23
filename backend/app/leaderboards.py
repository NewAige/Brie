"""Leaderboards for the Activity page.

Pure computation over already-fetched data — the same fetch/decide split as
roles.derive_role and ownership.decide, so every ranking unit-tests without
Gitea. Fetching (and therefore access control) stays in routers/activity.py,
which only calls in here with data the requesting user's own token was
allowed to read.

Privacy: the per-user boards (authors, contributors) rank facts that are
already public inside the library — front-matter authorship and published
suggestions. The per-prompt boards (copies, favorites, remixes) are anonymous
totals; no usernames are attached to them anywhere.
"""

from .frontmatter import HIDDEN_STATUSES


def top_authors(prompts: list[dict], names: dict[str, str] | None = None,
                limit: int = 10) -> list[dict]:
    """Users ranked by how many live (non-retired) prompts they authored."""
    counts: dict[str, int] = {}
    for p in prompts:
        if p.get("status") in HIDDEN_STATUSES:
            continue
        author = str(p.get("author") or "").strip()
        if author:
            counts[author] = counts.get(author, 0) + 1
    return _ranked_users(counts, "prompts", names, limit)


def top_contributors(merged_prs: list[dict],
                     partial_counts: dict[str, int] | None = None,
                     names: dict[str, str] | None = None,
                     limit: int = 10) -> list[dict]:
    """Users ranked by accepted suggestions: every merged suggestion they
    authored, plus partially published ones — Gitea records those as plain
    'closed', so only the outcome log knows whose changes were accepted."""
    counts: dict[str, int] = {}
    for pr in merged_prs:
        login = str((pr.get("user") or {}).get("login") or "").strip()
        if login:
            counts[login] = counts.get(login, 0) + 1
    for username, n in (partial_counts or {}).items():
        username = str(username or "").strip()
        if username:
            counts[username] = counts.get(username, 0) + n
    return _ranked_users(counts, "accepted", names, limit)


def top_remixed(prompts: list[dict], limit: int = 10) -> list[dict]:
    """Prompts ranked by how many live prompts were saved as a copy of them
    (`copied_from` front-matter — "remixes" in the UI)."""
    counts: dict[str, int] = {}
    for p in prompts:
        if p.get("status") in HIDDEN_STATUSES:
            continue
        source = str(p.get("copied_from") or "").strip()
        if source and source != p.get("path"):
            counts[source] = counts.get(source, 0) + 1
    rows = [{"path": path, "remixes": n} for path, n in counts.items()]
    rows.sort(key=lambda r: (-r["remixes"], r["path"]))
    return join_prompts(rows, prompts, limit)


def join_prompts(rows: list[dict], prompts: list[dict],
                 limit: int = 10) -> list[dict]:
    """Attach the live title/category to per-path count rows, dropping rows
    whose prompt no longer exists in the library."""
    index = {p["path"]: p for p in prompts}
    out = []
    for row in rows:
        p = index.get(row.get("path"))
        if p is not None:
            out.append({**row, "title": p["title"], "category": p["category"]})
    return out[:limit]


def _ranked_users(counts: dict[str, int], key: str,
                  names: dict[str, str] | None, limit: int) -> list[dict]:
    """Counts -> ranked rows. Ties break alphabetically so the order is
    stable between reloads; display names fall back to the username."""
    names = names or {}
    rows = [{"username": u, "name": names.get(u) or u, key: n}
            for u, n in counts.items()]
    rows.sort(key=lambda r: (-r[key], r["username"].lower()))
    return rows[:limit]
