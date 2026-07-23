"""Activity feed: recently published changes plus engagement leaderboards.

Everything Gitea knows (merged suggestions, prompt metadata) is fetched here
with the requesting user's token, so Gitea's read permissions still apply.
Copy/favorite tallies and partial-accept outcomes come from the local event
log because Gitea never sees those actions (spec §7). Ranking math lives in
leaderboards.py — pure functions, unit-tested without Gitea.
"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from .. import db, gitea, leaderboards, prompt_index
from ..config import settings
from ..deps import UserSession, current_session
from .pulls import _pr_summary

router = APIRouter(prefix="/api")

# How far back the contributor leaderboard looks: pages of closed suggestions,
# newest first. 4 x 50 keeps the page fast; anything older simply ages out of
# the ranking instead of being paged in forever.
_CLOSED_PAGE = 50
_CLOSED_PAGES = 4


async def _closed_prs(token: str) -> list[dict]:
    out: list[dict] = []
    for page in range(1, _CLOSED_PAGES + 1):
        batch = await gitea.api(token, "GET", f"{settings.repo_api}/pulls",
                                params={"state": "closed", "limit": _CLOSED_PAGE,
                                        "page": page}) or []
        out.extend(batch)
        if len(batch) < _CLOSED_PAGE:
            break
    return out


async def _published_path(token: str, pr_id: int, known: set[str]) -> str:
    """The library path a merged suggestion touched, so the feed entry can
    link to its prompt. Cosmetic only — any failure, and any path that no
    longer exists on main (deleted since), is just '' (no link)."""
    try:
        files = await gitea.api(token, "GET",
                                f"{settings.repo_api}/pulls/{pr_id}/files",
                                params={"limit": 5}) or []
    except HTTPException:
        return ""
    for f in files:
        if isinstance(f, dict) and f.get("filename") in known:
            return f["filename"]
    return ""


@router.get("/activity")
async def activity(session: UserSession = Depends(current_session)):
    closed = await _closed_prs(session.token)
    merged = [pr for pr in closed if pr.get("merged")]
    merged.sort(key=lambda pr: pr.get("merged_at") or "", reverse=True)

    prompts = await prompt_index.get_index(session.token)
    known = {p["path"] for p in prompts}

    recent = merged[:10]
    paths = await asyncio.gather(
        *(_published_path(session.token, pr["number"], known) for pr in recent))
    recent_approvals = [{**_pr_summary(pr), "path": path}
                        for pr, path in zip(recent, paths)]

    # Display names for the per-user boards, harvested from the suggestion
    # authors already fetched (every publish goes through a suggestion, so
    # this covers active users); anyone unseen falls back to their username.
    names: dict[str, str] = {}
    for pr in closed:
        user = pr.get("user") or {}
        if user.get("login") and user.get("full_name"):
            names[user["login"]] = user["full_name"]

    # The db queries over-fetch (25 for a top-10) so a few deleted prompts
    # dropped by the join don't shorten the board. Off-thread (synchronous
    # sqlite must not block the event loop) and concurrent with each other.
    copied, favorited, partials = await asyncio.gather(
        asyncio.to_thread(db.most_copied, limit=25),
        asyncio.to_thread(db.most_favorited, limit=25),
        asyncio.to_thread(db.partial_accept_counts),
    )
    return {
        "recent_approvals": recent_approvals,
        "leaderboards": {
            "most_copied": leaderboards.join_prompts(copied, prompts),
            "most_favorited": leaderboards.join_prompts(favorited, prompts),
            "most_remixed": leaderboards.top_remixed(prompts),
            "top_authors": leaderboards.top_authors(prompts, names),
            "top_contributors": leaderboards.top_contributors(
                merged, partials, names),
        },
    }
