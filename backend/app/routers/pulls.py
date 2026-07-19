"""Suggestions (pull requests) — list, diff, approve + merge.

Two ways a suggestion gets published:

- **Approver flow** (phase 1): merged with the requesting user's own token.
  Gitea's branch protection decides whether they may merge; this code enforces
  nothing itself.
- **Owner merge** (phase 2): a member publishing a change to a prompt they own,
  with no approver. Gitea *cannot* express this permission (see ownership.py),
  so the app authorizes it and a service account executes it.

The owner path is a real authorization boundary. It re-checks immediately
before merging — never trusting the check that rendered the button, since the
PR can gain commits between page load and click.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from .. import db, gitea, ownership
from ..config import settings
from ..deps import UserSession, current_session

router = APIRouter(prefix="/api")

log = logging.getLogger(__name__)


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


async def _can_approve(session: UserSession) -> bool:
    """Does this user have real write access on the repo? Asked of Gitea, never
    stored — same rule as /api/me."""
    try:
        repo = await gitea.api(session.token, "GET", settings.repo_api)
    except HTTPException:
        return False
    return bool((repo.get("permissions") or {}).get("push"))


@router.get("/pulls")
async def list_pulls(state: str = "open",
                     session: UserSession = Depends(current_session)):
    if state not in ("open", "closed", "all"):
        raise HTTPException(status_code=400, detail="state must be open, closed or all")
    prs = await gitea.api(session.token, "GET", f"{settings.repo_api}/pulls",
                          params={"state": state, "limit": 50})
    summaries = [_pr_summary(pr) for pr in prs]

    # Annotate open PRs the viewer may publish as owner, so the list can offer
    # "Publish" instead of "Approve & publish". Advisory only — the merge
    # endpoint re-checks. Skipped entirely for approvers, who already have the
    # button, and when no service account is configured.
    if settings.owner_merge_enabled and not await _can_approve(session):
        for summary in summaries:
            if summary["state"] != "open":
                continue
            decision = await ownership.owner_mergeable(
                session.token, session.username, summary["id"])
            summary["owner_mergeable"] = decision.allowed
    return summaries


@router.get("/pulls/{pr_id}/diff")
async def pull_diff(pr_id: int, session: UserSession = Depends(current_session)):
    diff = await gitea.api(session.token, "GET",
                           f"{settings.repo_api}/pulls/{pr_id}.diff", raw=True)
    return {"diff": diff}


@router.post("/pulls/{pr_id}/merge")
async def merge_pull(pr_id: int, session: UserSession = Depends(current_session)):
    """Approve, then merge. Branch protection on main requires >= 1 approval,
    so the two happen together from the approver's point of view.

    A member with no write access gets the owner-merge path if — and only if —
    they own every file the PR touches.
    """
    if settings.owner_merge_enabled and not await _can_approve(session):
        # Authoritative check, run now rather than trusting the list response.
        decision = await ownership.owner_mergeable(
            session.token, session.username, pr_id)
        if decision.allowed:
            return await _owner_merge(session, pr_id, decision)
        log.info("owner-merge declined for %s on PR %s: %s",
                 session.username, pr_id, decision.reason)
        # Fall through: Gitea will refuse below with the existing message.

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


async def _owner_merge(session: UserSession, pr_id: int,
                       decision: ownership.Decision) -> dict:
    """Publish a PR the user owns, using the service account.

    The bot credential is used for exactly these two calls, on exactly this PR
    id. Branch protection still requires an approval, so the bot approves as
    well — that approval is a record of the app's check having passed, which is
    why the merge message names both identities.
    """
    paths = list(decision.paths)
    try:
        await gitea.bot_api("POST", f"{settings.repo_api}/pulls/{pr_id}/reviews",
                            json={"event": "APPROVED",
                                  "body": f"Published by {session.username}, "
                                          f"owner of {', '.join(paths)}."})
    except HTTPException as exc:
        if exc.status_code not in (403, 422):  # already approved / self-review
            raise

    pr = await gitea.api(session.token, "GET", f"{settings.repo_api}/pulls/{pr_id}")
    title = pr.get("title", "") if isinstance(pr, dict) else ""

    await gitea.bot_api(
        "POST", f"{settings.repo_api}/pulls/{pr_id}/merge",
        json={
            "Do": "merge",
            "delete_branch_after_merge": True,
            "MergeTitleField": f"Publish (owner merge): {title}",
            "MergeMessageField": f"Merged by {session.username} as owner of "
                                 f"{', '.join(paths)}.",
        },
    )

    # Audit AFTER the merge lands, so the log records publishes that happened.
    db.log_owner_merge(session.username, pr_id, paths)
    log.info("owner-merge: %s published PR %s (%s)",
             session.username, pr_id, ", ".join(paths))
    return {"message": "Published. Your change is live."}
