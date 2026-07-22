"""Activity feed: recently published changes plus engagement leaderboards.

PR-derived data (recent publishes, top contributors) comes straight from
Gitea; prompt authorship comes from front-matter via the prompt index; copy,
favorite, and remix tallies come from the local event log because those
actions happen in this app, not in git (spec §7).
"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from .. import db, gitea, prompt_index
from ..config import settings
from ..deps import UserSession, current_session
from ..paths import is_prompt_file
from .pulls import _pr_summary

router = APIRouter(prefix="/api")

LEADERBOARD_SIZE = 10


@router.get("/activity")
async def activity(session: UserSession = Depends(current_session)):
    closed_prs = await gitea.api(session.token, "GET", f"{settings.repo_api}/pulls",
                                 params={"state": "closed", "limit": 50})
    merged = [pr for pr in closed_prs if pr.get("merged")]
    merged.sort(key=lambda pr: pr.get("merged_at") or "", reverse=True)

    prompts = {p["path"]: p for p in await prompt_index.get_index(session.token)}

    # Resolve which prompt each recently merged PR touched, so the feed can
    # link straight to it. Prompts that have since been renamed/deleted just
    # render unlinked.
    recent = merged[:10]
    paths = await asyncio.gather(*(_changed_prompt_path(session.token, pr["number"])
                                   for pr in recent))
    recent_published = [
        {**_pr_summary(pr), "path": path if path in prompts else None}
        for pr, path in zip(recent, paths)
    ]

    return {
        "recent_published": recent_published,
        "leaderboards": {
            "top_authors": _top_authors(prompts.values()),
            "top_contributors": _top_contributors(merged),
            "most_favorited": _resolve(db.most_favorited(LEADERBOARD_SIZE), "favorites", prompts),
            "most_copied": _resolve(db.most_copied(LEADERBOARD_SIZE), "copies", prompts),
            "most_remixed": _resolve(db.most_remixed(LEADERBOARD_SIZE), "remixes", prompts),
        },
    }


async def _changed_prompt_path(token: str, pr_number: int) -> str | None:
    """The first prompt file a PR changed (suggestions touch exactly one)."""
    try:
        files = await gitea.api(token, "GET",
                                f"{settings.repo_api}/pulls/{pr_number}/files",
                                params={"limit": 5})
    except HTTPException:
        return None
    for f in files or []:
        if is_prompt_file(f.get("filename", "")):
            return f["filename"]
    return None


def _top_authors(prompts) -> list[dict]:
    """Prompts authored per user, from each prompt's front-matter author."""
    counts: dict[str, int] = {}
    for p in prompts:
        if p["status"] == "deprecated" or not p["author"]:
            continue
        counts[p["author"]] = counts.get(p["author"], 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))
    return [{"name": name, "count": n} for name, n in ranked[:LEADERBOARD_SIZE]]


def _top_contributors(merged_prs: list[dict]) -> list[dict]:
    """Accepted suggestions per user (merged PRs, most recent 50 closed)."""
    counts: dict[str, dict] = {}
    for pr in merged_prs:
        user = pr.get("user") or {}
        login = user.get("login", "unknown")
        entry = counts.setdefault(login, {
            "name": user.get("full_name") or login, "count": 0,
        })
        entry["count"] += 1
    ranked = sorted(counts.values(), key=lambda e: (-e["count"], e["name"].lower()))
    return ranked[:LEADERBOARD_SIZE]


def _resolve(entries: list[dict], count_key: str, prompts: dict) -> list[dict]:
    """Attach live title/category to event-log tallies; drop prompts that no
    longer exist."""
    return [
        {"path": e["path"], "title": prompts[e["path"]]["title"],
         "category": prompts[e["path"]]["category"], "count": e[count_key]}
        for e in entries
        if e["path"] in prompts
    ]
