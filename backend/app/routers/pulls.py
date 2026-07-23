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

import base64
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import db, frontmatter, gitea, hunks, ownership, roles
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

    # Gitea only knows merged vs closed; the app's outcome log is what tells a
    # partially published suggestion apart from a plain declined one.
    if any(s["state"] == "closed" for s in summaries):
        outcomes = db.suggestion_outcomes()
        for summary in summaries:
            if summary["state"] == "closed":
                summary["outcome"] = outcomes.get(summary["id"], "declined")
    return summaries


@router.get("/pulls/attention")
async def pulls_attention(session: UserSession = Depends(current_session)):
    """How many open suggestions this user can decide — the nav badge count.

    Approvers/admins can decide every open suggestion; everyone else counts
    the ones they may publish as owner (peer suggestions to their prompts,
    plus their own not-yet-published ones). Purely cosmetic, so every failure
    is a silent zero rather than an error — a broken badge must never take
    the page down. Cost matches list_pulls (the ownership checks dominate);
    the frontend polls this only once a minute.
    """
    try:
        role = await roles.get_role(session.session_id, session.token)
        prs = await gitea.api(session.token, "GET", f"{settings.repo_api}/pulls",
                              params={"state": "open", "limit": 50}) or []
        if role in ("approver", "admin"):
            return {"count": len(prs)}
        if not settings.owner_merge_enabled:
            return {"count": 0}
        count = 0
        for pr in prs:
            decision = await ownership.owner_mergeable(
                session.token, session.username, pr["number"])
            if decision.allowed:
                count += 1
        return {"count": count}
    except HTTPException:
        return {"count": 0}


@router.get("/pulls/{pr_id}/diff")
async def pull_diff(pr_id: int, session: UserSession = Depends(current_session)):
    diff = await gitea.api(session.token, "GET",
                           f"{settings.repo_api}/pulls/{pr_id}.diff", raw=True)
    return {"diff": diff}


# --- partial acceptance & decline (review flow) ------------------------------
#
# A suggestion's branch usually lives in the author's fork, which neither the
# reviewer nor the bot can write to — so "accept only some of the edits"
# cannot amend the suggestion itself. Instead the accepted subset is published
# as a direct change to main and the leftover suggestion is closed:
#
#   - Approver path: the reviewer's OWN token writes to main. Branch
#     protection permits direct pushes for write users (seed.py:
#     `enable_push: True`), so Gitea still decides who may do this.
#   - Owner path: `ownership.owner_mergeable` authorizes (re-checked at
#     execution, exactly like merge_pull) and the bot executes.
#
# The reviewer selects hunks against pinned revisions (main sha + suggestion
# head sha); publishing re-derives the same hunks from the same shas, so what
# was shown is exactly what lands. Either sha moving is a 409, never a guess.


STALE_REVIEW = ("The suggestion may have changed while you were reviewing "
                "it — reload and review again.")


async def _main_sha(token: str) -> str:
    branch = await gitea.api(token, "GET", f"{settings.repo_api}/branches/main")
    sha = ((branch or {}).get("commit") or {}).get("id") or ""
    if not sha:
        raise HTTPException(status_code=502, detail="Could not read the library's current state.")
    return sha


async def _file_at(token: str, path: str, ref: str) -> str | None:
    """Raw file content at `ref`, or None where it doesn't exist."""
    try:
        return await gitea.api(token, "GET", f"{settings.repo_api}/raw/{path}",
                               params={"ref": ref}, raw=True)
    except HTTPException as exc:
        if exc.status_code == 404:
            return None
        raise


async def _open_pr_files(token: str, pr_id: int) -> list[str]:
    """Paths an open PR touches, refusing shapes partial review can't handle
    (renames, over-cap file counts) so callers fall back to the plain flow."""
    files = await gitea.api(token, "GET", f"{settings.repo_api}/pulls/{pr_id}/files",
                            params={"limit": ownership.MAX_PR_FILES + 1})
    files = files or []
    if len(files) > ownership.MAX_PR_FILES:
        raise HTTPException(status_code=400,
                            detail="This suggestion is too large to review change by change.")
    paths = []
    for f in files:
        if f.get("previous_filename"):
            raise HTTPException(status_code=400,
                                detail="This suggestion is too complex to review change by change.")
        path = f.get("filename", "")
        if not path:
            raise HTTPException(status_code=400, detail="Could not read the suggestion's files.")
        paths.append(path)
    return paths


@router.get("/pulls/{pr_id}/review")
async def pull_review(pr_id: int, session: UserSession = Depends(current_session)):
    """The suggestion split into individually acceptable changes ("hunks"),
    each computed between the library's CURRENT content and the suggestion —
    with both revisions pinned so a later publish can verify nothing moved."""
    pr = await gitea.api(session.token, "GET", f"{settings.repo_api}/pulls/{pr_id}")
    if pr.get("state") != "open" or pr.get("merged"):
        raise HTTPException(status_code=409, detail="This suggestion has already been decided.")
    head_sha = (pr.get("head") or {}).get("sha") or ""
    if not head_sha:
        raise HTTPException(status_code=400, detail="Could not read the suggestion.")
    base_sha = await _main_sha(session.token)

    out = []
    for path in await _open_pr_files(session.token, pr_id):
        base = await _file_at(session.token, path, base_sha)
        head = await _file_at(session.token, path, head_sha)
        status = ("added" if base is None else
                  "removed" if head is None else "changed")
        file_hunks = hunks.split_hunks(base or "", head or "")
        out.append({
            "path": path,
            "status": status,
            "hunks": [{"index": h.index, "lines": list(h.lines),
                       "added": h.added, "removed": h.removed}
                      for h in file_hunks],
        })
    return {"head_sha": head_sha, "base_sha": base_sha, "files": out}


# --- side-by-side comparison -------------------------------------------------
#
# pull_review shows a suggestion edit by edit; reviewers also want to read the
# two versions whole — the prompt as it is today next to the prompt as
# suggested — and copy either one out to try against a model before deciding.
# Bodies only, split by frontmatter.py exactly like the copy button (spec §4):
# what a reviewer copies to test is byte-for-byte what a user would copy after
# publishing.


def compare_file(path: str, base: str | None, head: str | None) -> dict:
    """Pure: one touched file shaped for the comparison view. `base` is the
    file on main, `head` the suggested version; None means the file doesn't
    exist on that side (a brand-new or removed prompt)."""
    base_split = frontmatter.split_front_matter(base) if base is not None else None
    head_split = frontmatter.split_front_matter(head) if head is not None else None
    return {
        "path": path,
        "status": ("added" if base is None else
                   "removed" if head is None else "changed"),
        "current": None if base_split is None else {"body": base_split[2]},
        "suggested": None if head_split is None else {"body": head_split[2]},
        # Front-matter edits (title, tags, level…) are invisible in a
        # body-only view; flag them so the UI can point the reviewer at the
        # change-by-change view instead of silently hiding part of the edit.
        "details_changed": (base_split is not None and head_split is not None
                            and base_split[0] != head_split[0]),
    }


@router.get("/pulls/{pr_id}/compare")
async def pull_compare(pr_id: int, session: UserSession = Depends(current_session)):
    """Each touched prompt's current and suggested text, whole, for the
    side-by-side view. Content comes from the same pinned revisions
    pull_review uses, but this is display-only — nothing here feeds a
    publish, so no shas are returned."""
    pr = await gitea.api(session.token, "GET", f"{settings.repo_api}/pulls/{pr_id}")
    if pr.get("state") != "open" or pr.get("merged"):
        raise HTTPException(status_code=409, detail="This suggestion has already been decided.")
    head_sha = (pr.get("head") or {}).get("sha") or ""
    if not head_sha:
        raise HTTPException(status_code=400, detail="Could not read the suggestion.")
    base_sha = await _main_sha(session.token)

    files = []
    for path in await _open_pr_files(session.token, pr_id):
        base = await _file_at(session.token, path, base_sha)
        head = await _file_at(session.token, path, head_sha)
        files.append(compare_file(path, base, head))
    return {"files": files}


class FileSelection(BaseModel):
    path: str
    hunks: list[int] = Field(default_factory=list)


class PartialAccept(BaseModel):
    head_sha: str = Field(min_length=1)
    base_sha: str = Field(min_length=1)
    files: list[FileSelection]
    note: str = Field("", max_length=2000)


@router.post("/pulls/{pr_id}/apply")
async def apply_partial(pr_id: int, accept: PartialAccept,
                        session: UserSession = Depends(current_session)):
    """Publish only the selected changes of a suggestion, then close it.

    Accepting everything goes through merge_pull instead (the frontend routes
    it there); this endpoint exists for genuine subsets — including declining
    every change of one file in a multi-file suggestion.
    """
    pr = await gitea.api(session.token, "GET", f"{settings.repo_api}/pulls/{pr_id}")
    if pr.get("state") != "open" or pr.get("merged"):
        raise HTTPException(status_code=409, detail="This suggestion has already been decided.")
    if ((pr.get("head") or {}).get("sha") or "") != accept.head_sha:
        raise HTTPException(status_code=409, detail=STALE_REVIEW)
    if await _main_sha(session.token) != accept.base_sha:
        raise HTTPException(status_code=409, detail=STALE_REVIEW)

    pr_author = str((pr.get("user") or {}).get("login") or "")
    title = pr.get("title", "")
    paths = await _open_pr_files(session.token, pr_id)
    selection = {f.path: set(f.hunks) for f in accept.files}
    if not set(selection) <= set(paths):
        raise HTTPException(status_code=400, detail=STALE_REVIEW)

    # Recompute every file's hunks from the pinned shas and apply the
    # selection. Content is fetched with the USER's token — Gitea's read
    # permissions still apply — and nothing is written until every file has
    # validated cleanly.
    total = accepted = 0
    changes = []  # (path, base, new_content)
    for path in paths:
        base = await _file_at(session.token, path, accept.base_sha)
        head = await _file_at(session.token, path, accept.head_sha)
        file_hunks = hunks.split_hunks(base or "", head or "")
        chosen = selection.get(path, set())
        if not chosen <= {h.index for h in file_hunks}:
            raise HTTPException(status_code=400, detail=STALE_REVIEW)
        total += len(file_hunks)
        accepted += len(chosen)
        content = hunks.apply_hunks(base or "", head or "", chosen)
        if content != (base or ""):
            changes.append((path, base, content))
    if accepted == 0:
        raise HTTPException(status_code=400,
                            detail="No changes selected — decline the suggestion instead.")

    # Authorization: owner path first (bot executes), else the user's own
    # token writes to main and Gitea itself decides. Conflict state doesn't
    # matter here — nothing merges; selected hunks apply to main by
    # construction.
    decision = await ownership.owner_mergeable(
        session.token, session.username, pr_id,
        require_mergeable=False) if settings.owner_merge_enabled else None
    as_owner = bool(decision and decision.allowed)
    if as_owner:
        # The published mix of main-side and suggestion-side lines must still
        # be a community-level prompt: both sources were checked, but the
        # level line itself is re-verified on the OUTCOME, fail closed —
        # the owner path must never mint a bank prompt (spec §8, phase A).
        for path, _base, content in changes:
            if content and ownership.level_of(content) != "community":
                raise HTTPException(
                    status_code=403,
                    detail="These changes would alter the prompt's governance "
                           "level, which needs a Bank Approver.")

    async def write(method: str, path: str, **kw):
        if as_owner:
            return await gitea.bot_api(method, path, **kw)
        return await gitea.api(session.token, method, path, **kw)

    message = (f"Publish parts of suggestion #{pr_id}: {title}\n\n"
               f"{accepted} of {total} changes accepted by {session.username}; "
               f"suggested by {pr_author or 'unknown'}.")
    try:
        for path, base, content in changes:
            contents_url = f"{settings.repo_api}/contents/{path}"
            if content == "" and base is not None:
                current = await write("GET", contents_url, params={"ref": "main"})
                await write("DELETE", contents_url,
                            json={"branch": "main", "sha": current["sha"],
                                  "message": message})
            elif base is None:
                await write("POST", contents_url,
                            json={"branch": "main", "message": message,
                                  "content": base64.b64encode(content.encode()).decode()})
            else:
                current = await write("GET", contents_url, params={"ref": "main"})
                await write("PUT", contents_url,
                            json={"branch": "main", "sha": current["sha"],
                                  "message": message,
                                  "content": base64.b64encode(content.encode()).decode()})
    except HTTPException as exc:
        if exc.status_code in (403, 404):
            raise HTTPException(
                status_code=403,
                detail="Gitea did not allow publishing this change. You may "
                       "not have approver rights, and only a prompt's owner "
                       "can publish suggestions to it.")
        raise

    # The record of what happened lives on the suggestion itself, then it
    # closes. Failures past this point leave the changes published (correct)
    # and the suggestion open (annoying, recoverable) — never the reverse.
    comment = (f"{accepted} of {total} changes were accepted and published by "
               f"{session.username}; the rest were declined.")
    if accept.note.strip():
        comment += f"\n\n{accept.note.strip()}"
    await write("POST", f"{settings.repo_api}/issues/{pr_id}/comments",
                json={"body": comment})
    await write("PATCH", f"{settings.repo_api}/pulls/{pr_id}",
                json={"state": "closed"})

    db.log_suggestion_outcome(pr_id, "partial", session.username,
                              pr_author=pr_author, detail=f"{accepted} of {total}")
    if as_owner:
        # Same audit trail as owner merges: a publish no approver reviewed.
        db.log_owner_merge(session.username, pr_id,
                           [path for path, _b, _c in changes],
                           pr_author=pr_author, kind="partial")
    log.info("partial publish: %s accepted %s/%s changes of PR %s by %s (%s)",
             session.username, accepted, total, pr_id, pr_author or "unknown",
             "owner" if as_owner else "approver")
    return {"message": f"Published {accepted} of {total} changes. "
                       "The rest of the suggestion was declined."}


class Decline(BaseModel):
    note: str = Field("", max_length=2000)


@router.post("/pulls/{pr_id}/decline")
async def decline_pull(pr_id: int, decline: Decline,
                       session: UserSession = Depends(current_session)):
    """Decline (or, for its author, withdraw) an open suggestion.

    Tried first with the user's own token — Gitea allows write users and the
    suggestion's author to close it. Anyone else gets the owner path: the same
    ownership check as publishing (minus the pointless conflict gate), with
    the bot executing and the comment recording who decided.
    """
    pr = await gitea.api(session.token, "GET", f"{settings.repo_api}/pulls/{pr_id}")
    if pr.get("state") != "open" or pr.get("merged"):
        raise HTTPException(status_code=409, detail="This suggestion has already been decided.")
    pr_author = str((pr.get("user") or {}).get("login") or "")
    note = decline.note.strip()

    closed_as_self = True
    try:
        await gitea.api(session.token, "PATCH", f"{settings.repo_api}/pulls/{pr_id}",
                        json={"state": "closed"})
    except HTTPException as exc:
        if exc.status_code not in (403, 404):
            raise
        closed_as_self = False

    if closed_as_self:
        if note:
            # Best effort — the decline already happened; a lost note must
            # not resurrect the suggestion as an error.
            try:
                await gitea.api(session.token, "POST",
                                f"{settings.repo_api}/issues/{pr_id}/comments",
                                json={"body": note})
            except HTTPException:
                log.warning("decline note failed for PR %s", pr_id)
    else:
        decision = await ownership.owner_mergeable(
            session.token, session.username, pr_id, require_mergeable=False)
        if not decision.allowed:
            log.info("decline refused for %s on PR %s: %s",
                     session.username, pr_id, decision.reason)
            raise HTTPException(
                status_code=403,
                detail="Only an approver or the prompt's owner can decline "
                       "this suggestion.")
        body = (f"Declined by {session.username}, owner of "
                f"{', '.join(decision.paths)}.")
        if note:
            body += f"\n\n{note}"
        await gitea.bot_api("POST", f"{settings.repo_api}/issues/{pr_id}/comments",
                            json={"body": body})
        await gitea.bot_api("PATCH", f"{settings.repo_api}/pulls/{pr_id}",
                            json={"state": "closed"})

    db.log_suggestion_outcome(pr_id, "declined", session.username,
                              pr_author=pr_author, detail=note[:300])
    log.info("declined: %s closed PR %s by %s", session.username, pr_id,
             pr_author or "unknown")
    if pr_author == session.username:
        return {"message": "Suggestion withdrawn."}
    return {"message": "Suggestion declined."}


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
