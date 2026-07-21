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
    # endpoint re-checks. Computed for approvers too: they take the owner path
    # for their own community prompts (see merge_pull), so skipping them here
    # would label a self-publish "Approve & publish".
    #
    # `needs_your_review` marks the phase-C peer case: someone else's
    # suggestion to a prompt this viewer owns, which only they can publish.
    if settings.owner_merge_enabled:
        for summary in summaries:
            if summary["state"] != "open":
                continue
            decision = await ownership.owner_mergeable(
                session.token, session.username, summary["id"])
            summary["owner_mergeable"] = decision.allowed
            summary["needs_your_review"] = (
                decision.allowed and summary["author"] != session.username)
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
    if settings.owner_merge_enabled:
        # Authoritative check, run now rather than trusting the list response.
        #
        # Tried for EVERY user, approvers included. Owner-merge was originally
        # reserved for members without push access, on the assumption that an
        # approver never needs it — but that left approvers unable to publish
        # their own community prompts at all: Gitea refuses self-approval, and
        # branch protection requires one, so the fall-through below always
        # failed. Ownership is a property of the prompt, not of the merger's
        # Gitea permissions, so the check applies to everyone and `decide` is
        # unchanged: bank prompts and prompts you don't own are still refused
        # here and still go to a second approver.
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


async def try_publish_now(session: UserSession, pr_id: int) -> bool:
    """Publish a freshly-opened PR immediately, if its author may self-merge.

    Used by the create/publish endpoints so that "Publish to Community" means
    what it says: a new community prompt the author owns lands in the library
    on the button press, instead of parking in Suggestions for a second click
    that only ever had one possible outcome.

    Authorization is NOT special-cased here — this runs the same
    `owner_mergeable` predicate the merge endpoint does, so a bank-level or
    peer-owned PR is refused and stays in the queue for an approver.

    Returns True if the prompt is live. Any failure (denied, conflict, Gitea
    error) returns False and leaves the PR open, so the caller falls back to
    the "finish it under Suggestions" path rather than losing the work.
    """
    if not settings.owner_merge_enabled:
        return False
    try:
        decision = await ownership.owner_mergeable(
            session.token, session.username, pr_id)
        if not decision.allowed:
            log.info("auto-publish declined for %s on PR %s: %s",
                     session.username, pr_id, decision.reason)
            return False
        await _owner_merge(session, pr_id, decision)
        return True
    except Exception:
        # The PR is still open and still self-mergeable by hand; that is a
        # worse experience but not a lost prompt, so never surface this.
        log.exception("auto-publish failed for %s on PR %s", session.username, pr_id)
        return False


async def _owner_merge(session: UserSession, pr_id: int,
                       decision: ownership.Decision) -> dict:
    """Publish a PR the user owns, using the service account.

    The bot credential is used for exactly these two calls, on exactly this PR
    id. Branch protection still requires an approval, so the bot approves as
    well — that approval is a record of the app's check having passed, which is
    why the merge message names both identities.

    Phase C: the same path publishes a peer's suggestion to a prompt the
    merger owns — the audit row and merge message then record both the owner
    who approved (`username`) and the peer who authored (`pr_author`).
    """
    paths = list(decision.paths)
    peer = bool(decision.pr_author) and decision.pr_author != session.username
    kind = "peer" if peer else "self"
    review_body = (
        f"Published by {session.username}, owner of {', '.join(paths)}, "
        f"approving a suggestion by {decision.pr_author}."
        if peer else
        f"Published by {session.username}, owner of {', '.join(paths)}."
    )
    try:
        await gitea.bot_api("POST", f"{settings.repo_api}/pulls/{pr_id}/reviews",
                            json={"event": "APPROVED", "body": review_body})
    except HTTPException as exc:
        if exc.status_code not in (403, 422):  # already approved / self-review
            raise

    pr = await gitea.api(session.token, "GET", f"{settings.repo_api}/pulls/{pr_id}")
    title = pr.get("title", "") if isinstance(pr, dict) else ""

    merge_message = (
        f"Merged by {session.username} as owner of {', '.join(paths)}, "
        f"approving a suggestion by {decision.pr_author}."
        if peer else
        f"Merged by {session.username} as owner of {', '.join(paths)}."
    )
    await gitea.bot_api(
        "POST", f"{settings.repo_api}/pulls/{pr_id}/merge",
        json={
            "Do": "merge",
            "delete_branch_after_merge": True,
            "MergeTitleField": f"Publish (owner merge): {title}",
            "MergeMessageField": merge_message,
        },
    )

    # Audit AFTER the merge lands, so the log records publishes that happened.
    db.log_owner_merge(session.username, pr_id, paths,
                       pr_author=decision.pr_author, kind=kind)
    log.info("owner-merge (%s): %s published PR %s by %s (%s)",
             kind, session.username, pr_id, decision.pr_author or "unknown",
             ", ".join(paths))
    if peer:
        return {"message": f"Published. {decision.pr_author}'s suggestion "
                           "to your prompt is live."}
    return {"message": "Published. Your change is live."}
