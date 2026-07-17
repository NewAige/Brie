"""Suggestions (pull requests) — list, diff, approve + merge.

Merging is attempted with the requesting user's token; Gitea's branch
protection is what actually decides whether they may merge (spec §6). This
code enforces nothing itself.
"""

from fastapi import APIRouter, Depends, HTTPException

from .. import gitea
from ..config import settings
from ..deps import UserSession, current_session

router = APIRouter(prefix="/api")


def _pr_summary(pr: dict) -> dict:
    user = pr.get("user") or {}
    return {
        "id": pr["number"],
        "title": pr.get("title", ""),
        "note": pr.get("body") or "",
        "author": user.get("login", "unknown"),
        "author_name": user.get("full_name") or user.get("login", "unknown"),
        "created_at": pr.get("created_at"),
        "state": "merged" if pr.get("merged") else pr.get("state", "open"),
        "merged_at": pr.get("merged_at"),
    }


@router.get("/pulls")
async def list_pulls(state: str = "open",
                     session: UserSession = Depends(current_session)):
    if state not in ("open", "closed", "all"):
        raise HTTPException(status_code=400, detail="state must be open, closed or all")
    prs = await gitea.api(session.token, "GET", f"{settings.repo_api}/pulls",
                          params={"state": state, "limit": 50})
    return [_pr_summary(pr) for pr in prs]


@router.get("/pulls/{pr_id}/diff")
async def pull_diff(pr_id: int, session: UserSession = Depends(current_session)):
    diff = await gitea.api(session.token, "GET",
                           f"{settings.repo_api}/pulls/{pr_id}.diff", raw=True)
    return {"diff": diff}


@router.post("/pulls/{pr_id}/merge")
async def merge_pull(pr_id: int, session: UserSession = Depends(current_session)):
    """Approve, then merge. Branch protection on main requires >= 1 approval,
    so the two happen together from the approver's point of view."""
    try:
        await gitea.api(session.token, "POST",
                        f"{settings.repo_api}/pulls/{pr_id}/reviews",
                        json={"event": "APPROVED", "body": "Approved via Prompt Library"})
    except HTTPException as exc:
        # Gitea refuses self-approval of one's own suggestion; let the merge
        # attempt below produce the authoritative error in that case.
        if exc.status_code not in (403, 422):
            raise

    try:
        await gitea.api(session.token, "POST",
                        f"{settings.repo_api}/pulls/{pr_id}/merge",
                        json={"Do": "merge", "delete_branch_after_merge": True})
    except HTTPException as exc:
        if exc.status_code == 405:
            raise HTTPException(
                status_code=403,
                detail="Gitea did not allow this merge. You may not have approver "
                       "rights, or the suggestion may need review by someone else.",
            )
        raise
    return {"message": "Suggestion approved and published."}
