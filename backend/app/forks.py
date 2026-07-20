"""Fork, branch, and commit plumbing shared by the prompt and draft routers.

Extracted from routers/prompts.py in phase D (PLAN.MD) so personal drafts —
which live on a `drafts` branch in the user's fork — reuse the exact code
paths that suggestions and new-prompt PRs already exercise. Everything here
runs with the USER's own token; the bot never forks or commits.
"""

import base64
import re
import time

from fastapi import HTTPException

from . import gitea
from .config import settings


def branch_name(username: str, prefix: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]", "-", username).strip("-.") or "user"
    return f"{prefix}/{slug}-{int(time.time() * 1000)}"


async def file_exists_on_main(token: str, path: str) -> bool:
    try:
        data = await gitea.api(token, "GET", f"{settings.repo_api}/contents/{path}",
                               params={"ref": "main"})
    except HTTPException as exc:
        if exc.status_code == 404:
            return False
        raise
    return data.get("type") == "file"


async def open_pr_paths(token: str) -> set[str]:
    """Paths touched by any open PR the user can read (capped at 50×50).

    A brand-new prompt isn't on main yet, so `file_exists_on_main` can't see
    one that is merely awaiting review — without this, submitting the same
    title twice silently opens a second competing PR.
    """
    pulls = await gitea.api(token, "GET", f"{settings.repo_api}/pulls",
                            params={"state": "open", "limit": 50})
    paths: set[str] = set()
    for pull in pulls or []:
        try:
            files = await gitea.api(
                token, "GET", f"{settings.repo_api}/pulls/{pull['number']}/files",
                params={"limit": 50},
            )
        except HTTPException:
            continue  # a PR we can't read can't be shown to the user anyway
        paths.update(f.get("filename") for f in files or [] if f.get("filename"))
    return paths


async def pending_pr_for(token: str, path: str) -> bool:
    """Is an open PR already proposing this exact path?"""
    return path in await open_pr_paths(token)


async def ensure_fork(token: str, username: str) -> dict:
    """Find or create the user's fork of the library repo."""
    forks = await gitea.api(token, "GET", f"{settings.repo_api}/forks",
                            params={"limit": 50})
    for fork in forks or []:
        if fork.get("owner", {}).get("login") == username:
            await sync_fork(token, fork)
            return fork
    try:
        return await gitea.api(token, "POST", f"{settings.repo_api}/forks", json={})
    except HTTPException as exc:
        if exc.status_code == 409:
            # The user already owns an unrelated repo with the library's name,
            # so Gitea refuses the fork. Surfacing Gitea's raw message here
            # reads like gibberish in the UI — say what to do instead.
            raise HTTPException(
                status_code=409,
                detail="A repository named "
                       f"'{settings.repo_name}' already exists under your Gitea "
                       "account but is not a fork of the library. Rename or "
                       "remove it, then try again.")
        raise


async def find_fork(token: str, username: str) -> dict | None:
    """The user's existing fork, or None. Never creates or syncs — safe for
    read-only endpoints that must not mutate anything."""
    forks = await gitea.api(token, "GET", f"{settings.repo_api}/forks",
                            params={"limit": 50})
    for fork in forks or []:
        if fork.get("owner", {}).get("login") == username:
            return fork
    return None


async def sync_fork(token: str, fork: dict) -> None:
    """Best-effort fast-forward of an existing fork's DEFAULT branch so
    changes are built on current content. Ignore failures — a stale fork
    still produces a correct PR diff (merge-base semantics).

    Only the default branch is synced: the long-lived `drafts` branch
    (phase D) must never be touched by a sync.
    """
    branch = fork.get("default_branch") or "main"
    try:
        await gitea.api(token, "POST",
                        f"/repos/{fork['full_name']}/sync_fork",
                        json={"branch": branch})
    except HTTPException:
        pass


async def commit_to_new_branch(token: str, repo_api: str, path: str, *,
                               base_branch: str, new_branch: str,
                               content: str, message: str) -> None:
    """Commit `content` to `path` on a new branch in one contents-API call.

    The blob sha must come from the repo being written to (a fork may be
    behind the library repo); if the file doesn't exist there yet, create it.
    """
    payload = {
        "branch": base_branch,
        "new_branch": new_branch,
        "content": base64.b64encode(content.encode()).decode(),
        "message": message,
    }
    try:
        existing = await gitea.api(token, "GET", f"{repo_api}/contents/{path}",
                                   params={"ref": base_branch})
        await gitea.api(token, "PUT", f"{repo_api}/contents/{path}",
                        json={**payload, "sha": existing["sha"]})
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        await gitea.api(token, "POST", f"{repo_api}/contents/{path}", json=payload)


async def commit_to_branch(token: str, repo_api: str, path: str, *,
                           branch: str, content: str, message: str) -> None:
    """Create or update `path` directly on an EXISTING branch (drafts saves)."""
    payload = {
        "branch": branch,
        "content": base64.b64encode(content.encode()).decode(),
        "message": message,
    }
    try:
        existing = await gitea.api(token, "GET", f"{repo_api}/contents/{path}",
                                   params={"ref": branch})
        await gitea.api(token, "PUT", f"{repo_api}/contents/{path}",
                        json={**payload, "sha": existing["sha"]})
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        await gitea.api(token, "POST", f"{repo_api}/contents/{path}", json=payload)


async def delete_file(token: str, repo_api: str, path: str, *,
                      branch: str, message: str) -> None:
    """Delete `path` from `branch` (contents API needs the current blob sha)."""
    existing = await gitea.api(token, "GET", f"{repo_api}/contents/{path}",
                               params={"ref": branch})
    await gitea.api(token, "DELETE", f"{repo_api}/contents/{path}",
                    json={"branch": branch, "sha": existing["sha"],
                          "message": message})


async def propose_change(token: str, username: str, path: str, content: str, *,
                         branch: str, message: str,
                         pr_title: str, pr_body: str) -> dict:
    """Commit `content` to `path` on a new branch and open a PR against main,
    using the USER's own token. Users with push access branch inside the
    library repo; read-only users go through their transparently-managed fork."""
    repo = await gitea.api(token, "GET", settings.repo_api)
    if (repo.get("permissions") or {}).get("push"):
        await commit_to_new_branch(token, settings.repo_api, path,
                                   base_branch="main", new_branch=branch,
                                   content=content, message=message)
        head = branch
    else:
        fork = await ensure_fork(token, username)
        await commit_to_new_branch(token, f"/repos/{fork['full_name']}", path,
                                   base_branch=fork["default_branch"] or "main",
                                   new_branch=branch, content=content, message=message)
        head = f"{fork['owner']['login']}:{branch}"

    return await gitea.api(
        token, "POST", f"{settings.repo_api}/pulls",
        json={"base": "main", "head": head, "title": pr_title, "body": pr_body},
    )
