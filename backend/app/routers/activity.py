"""Activity feed: recent approvals, recent suggestions, most-copied prompts.

Everything except "most copied" comes straight from Gitea; copy counts come
from the local copy-event log because copying happens client-side (spec §7).
"""

from fastapi import APIRouter, Depends

from .. import db, gitea, prompt_index
from ..config import settings
from ..deps import UserSession, current_session
from .pulls import _pr_summary

router = APIRouter(prefix="/api")


@router.get("/activity")
async def activity(session: UserSession = Depends(current_session)):
    open_prs = await gitea.api(session.token, "GET", f"{settings.repo_api}/pulls",
                               params={"state": "open", "limit": 10})
    closed_prs = await gitea.api(session.token, "GET", f"{settings.repo_api}/pulls",
                                 params={"state": "closed", "limit": 30})
    merged = [pr for pr in closed_prs if pr.get("merged")]
    merged.sort(key=lambda pr: pr.get("merged_at") or "", reverse=True)

    # Resolve copy-event paths to live titles; drop prompts that no longer exist.
    prompts = {p["path"]: p for p in await prompt_index.get_index(session.token)}
    most_copied = [
        {**entry, "title": prompts[entry["path"]]["title"],
         "category": prompts[entry["path"]]["category"]}
        for entry in db.most_copied(limit=10)
        if entry["path"] in prompts
    ]

    return {
        "recent_approvals": [_pr_summary(pr) for pr in merged[:10]],
        "recent_suggestions": [_pr_summary(pr) for pr in open_prs],
        "most_copied": most_copied,
    }
