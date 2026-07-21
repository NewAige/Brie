"""Personal drafts (PLAN.MD phase D).

A draft lives on a long-lived `drafts` branch in the user's own Gitea fork,
at the file's real future `<category>/<slug>.md` path. Privacy is enforced by
Gitea itself — the fork is visible only to its owner (and to Gitea instance
admins; see docs) — never by app-side filtering. Saving a draft commits
directly to the branch (no review); "Publish" exports the single file through
the same propose-a-PR flow that suggestions use, on a fresh branch off the
synced fork main, so a publish PR never drags other drafts along.

Every endpoint requires the Contributor role: browsers have nowhere to draft.
"""

import difflib
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import forks, gitea, prompt_index, roles
from ..deps import UserSession, require_contributor
from ..frontmatter import parse_prompt, render_prompt, replace_body
from ..paths import is_prompt_file, slugify
from . import pulls
from .prompts import NewPrompt

router = APIRouter(prefix="/api/drafts")

DRAFTS_BRANCH = "drafts"

_VIEW_FIELDS = ["path", "category", "title", "tags", "status", "author",
                "target_model", "intended_use", "copied_from"]


def _view(prompt: dict, **extra) -> dict:
    out = {k: prompt[k] for k in _VIEW_FIELDS}
    out["body"] = prompt["body"]
    out.update(extra)
    return out


@router.get("")
async def list_drafts(session: UserSession = Depends(require_contributor)):
    """All of the user's drafts, annotated with whether the same path already
    exists in the library (`on_main`) and whether an open PR is proposing it
    (`pending_pr`). Read-only: never creates the fork or the branch."""
    fork = await forks.find_fork(session.token, session.username)
    if fork is None or not await _branch_exists(session.token, fork):
        return []

    changed = await _changed_paths(session.token, fork)
    existing = await _tree_paths(session.token, fork)
    paths = sorted(p for p in changed & existing if is_prompt_file(p))

    index_paths = {p["path"] for p in await prompt_index.get_index(session.token)}
    pr_paths = await forks.open_pr_paths(session.token) if paths else set()

    drafts = []
    for path in paths:
        try:
            raw = await gitea.api(
                session.token, "GET", f"{_fork_api(fork)}/raw/{path}",
                params={"ref": DRAFTS_BRANCH}, raw=True)
        except HTTPException:
            continue  # deleted between the tree fetch and now
        drafts.append(_view(parse_prompt(path, raw),
                            on_main=path in index_paths,
                            pending_pr=path in pr_paths))
    return drafts


@router.post("")
async def create_draft(new: NewPrompt,
                       session: UserSession = Depends(require_contributor)):
    """Save instantly to the user's drafts branch — no review, no PR. The
    path is derived exactly like create_prompt's, so publishing later never
    changes it."""
    category = slugify(new.category)
    slug = slugify(new.title)
    if not category or not slug:
        raise HTTPException(status_code=400,
                            detail="Title and category must contain letters or numbers.")
    path = f"{category}/{slug}.md"
    if not is_prompt_file(path):
        raise HTTPException(status_code=400, detail="That name is reserved.")

    fork = await forks.ensure_fork(session.token, session.username)
    await _ensure_drafts_branch(session.token, fork)
    if await _draft_exists(session.token, fork, path):
        raise HTTPException(status_code=409,
                            detail="You already have a draft with this name in that category.")

    tags = list(dict.fromkeys(t for t in (slugify(t) for t in new.tags) if t))
    # No `level` yet — the level is chosen at publish time (PLAN.MD phase D).
    content = render_prompt({
        "title": new.title.strip(),
        "category": category,
        "tags": tags,
        "status": "draft",
        "author": session.username,
        "owner": session.username,
        "target_model": new.target_model,
        "intended_use": new.intended_use,
        "copied_from": new.copied_from,
    }, new.body)

    await forks.commit_to_branch(
        session.token, _fork_api(fork), path, branch=DRAFTS_BRANCH,
        content=content, message=f"Draft: {new.title.strip()}")
    return {"message": "Saved to your personal drafts.", "path": path}


@router.get("/{path:path}/history")
async def draft_history(path: str,
                        session: UserSession = Depends(require_contributor)):
    """Version history of one draft: every save on the user's `drafts` branch,
    newest first, with a unified diff against the previous revision. Same shape
    as `prompt_history` — read from the owner's fork instead of the library
    `main`, so it stays private (the user's own token, the user's own fork).

    Nuance: the `drafts` branch is created off `main`, so a draft whose path
    happens to shadow a library file would also list that file's `main`
    history. That case is rare — publishing is blocked when the path already
    exists on `main` — so for a genuinely new draft this is exactly its saves.
    """
    fork, _raw = await _fetch_draft(session, path)  # validates path, 404s
    fork_api = _fork_api(fork)
    commits = await gitea.api(
        session.token, "GET", f"{fork_api}/commits",
        params={"path": path, "sha": DRAFTS_BRANCH, "limit": 20,
                "stat": "false", "verification": "false", "files": "false"},
    )

    async def content_at(sha: str) -> str:
        try:
            return await gitea.api(
                session.token, "GET", f"{fork_api}/raw/{path}",
                params={"ref": sha}, raw=True,
            )
        except HTTPException:
            return ""  # file did not exist at this commit

    versions = [await content_at(c["sha"]) for c in commits]

    history = []
    for i, commit in enumerate(commits):
        older = versions[i + 1] if i + 1 < len(versions) else ""
        newer = versions[i]
        diff = "\n".join(difflib.unified_diff(
            older.splitlines(), newer.splitlines(),
            fromfile=f"a/{path}", tofile=f"b/{path}", lineterm="",
        ))
        info = commit.get("commit", {})
        author = (commit.get("author") or {}).get("login") or \
                 (info.get("author") or {}).get("name") or "unknown"
        history.append({
            "sha": commit["sha"],
            "author": author,
            "date": (info.get("author") or {}).get("date") or "",
            "message": info.get("message", "").strip(),
            "diff": diff,
        })
    return history


@router.get("/{path:path}")
async def get_draft(path: str, session: UserSession = Depends(require_contributor)):
    fork, raw = await _fetch_draft(session, path)
    return _view(parse_prompt(path, raw))


class DraftUpdate(BaseModel):
    body: str = Field(min_length=1, description="The new draft body (no front-matter)")
    # Metadata is optional: omit every field and this stays a body-only save,
    # preserving the original front-matter byte-for-byte (the old behaviour).
    title: str | None = None
    category: str | None = None
    tags: list[str] | None = None
    target_model: str | None = None
    intended_use: str | None = None

    def touches_metadata(self) -> bool:
        return any(v is not None for v in (self.title, self.category, self.tags,
                                           self.target_model, self.intended_use))


@router.put("/{path:path}")
async def update_draft(path: str, update: DraftUpdate,
                       session: UserSession = Depends(require_contributor)):
    """Save a draft. Body-only edits preserve the front-matter verbatim; when
    metadata is supplied the front-matter is re-rendered. Because the path is
    derived from title+category (exactly as in create_draft), editing either
    one MOVES the file: commit at the new path, then delete the old one."""
    fork, raw = await _fetch_draft(session, path)
    fork_api = _fork_api(fork)

    if not update.touches_metadata():
        await forks.commit_to_branch(
            session.token, fork_api, path, branch=DRAFTS_BRANCH,
            content=replace_body(raw, update.body), message=f"Draft: update {path}")
        return {"message": "Draft saved.", "path": path}

    current = parse_prompt(path, raw)
    title = (update.title if update.title is not None else current["title"]).strip()
    category = slugify(update.category if update.category is not None
                       else current["category"])
    slug = slugify(title)
    if not category or not slug:
        raise HTTPException(status_code=400,
                            detail="Title and category must contain letters or numbers.")
    new_path = f"{category}/{slug}.md"
    if not is_prompt_file(new_path):
        raise HTTPException(status_code=400, detail="That name is reserved.")

    if new_path != path:
        if await _draft_exists(session.token, fork, new_path):
            raise HTTPException(
                status_code=409,
                detail="You already have a draft with this name in that category.")
        if await forks.file_exists_on_main(session.token, new_path):
            raise HTTPException(
                status_code=409,
                detail="A prompt with this name already exists in the library. "
                       "Pick a different title or category.")

    tags = (current["tags"] if update.tags is None else
            list(dict.fromkeys(t for t in (slugify(t) for t in update.tags) if t)))
    # `status`/`level` stay backend-owned: the review flow sets them, never the
    # draft editor. `author`/`owner` likewise come from the session.
    content = render_prompt({
        "title": title,
        "category": category,
        "tags": tags,
        "status": "draft",
        "author": current["author"] or session.username,
        "owner": current["owner"] or session.username,
        "target_model": (update.target_model if update.target_model is not None
                         else current["target_model"]),
        "intended_use": (update.intended_use if update.intended_use is not None
                         else current["intended_use"]),
        "copied_from": current["copied_from"],
    }, update.body)

    await forks.commit_to_branch(
        session.token, fork_api, new_path, branch=DRAFTS_BRANCH,
        content=content, message=f"Draft: update {new_path}")
    if new_path != path:
        # Write-then-delete: if the delete fails the draft still exists at the
        # new path, so no content is ever lost.
        await forks.delete_file(session.token, fork_api, path,
                                branch=DRAFTS_BRANCH,
                                message=f"Draft: rename {path} -> {new_path}")
    return {"message": "Draft saved.", "path": new_path}


@router.delete("/{path:path}")
async def delete_draft(path: str, session: UserSession = Depends(require_contributor)):
    fork, _raw = await _fetch_draft(session, path)
    await forks.delete_file(session.token, _fork_api(fork), path,
                            branch=DRAFTS_BRANCH, message=f"Draft: delete {path}")
    return {"message": "Draft deleted."}


class PublishRequest(BaseModel):
    # Community is the default publication level: a contributor who says
    # nothing gets the tier they are allowed to publish at.
    level: Literal["bank", "community"] = "community"


@router.post("/{path:path}/publish")
async def publish_draft(path: str, publish: PublishRequest,
                        session: UserSession = Depends(require_contributor)):
    """Send one draft to the library at the chosen level.

    Community is the default and needs no approver: the PR it opens is
    self-mergeable by its author (ownership.py phase E). Bank is approver-only
    — and gated HERE, not merely in the UI, because asking for `level: bank`
    is what puts a prompt in the tier whose every future edit requires a Bank
    Approver. The front-matter is always re-rendered server-side, so the level
    is never taken from draft content.
    """
    if publish.level == "bank" and not await _is_approver(session):
        raise HTTPException(
            status_code=403,
            detail="Only a Bank Approver can publish a prompt at Bank level. "
                   "Publish it to the Community library instead — an approver "
                   "can raise it to Bank later.")
    fork, raw = await _fetch_draft(session, path)
    if await forks.file_exists_on_main(session.token, path):
        raise HTTPException(status_code=409,
                            detail="A prompt with this name already exists in the library. "
                                   "Rename your draft by saving it under a new title.")
    if await forks.pending_pr_for(session.token, path):
        raise HTTPException(status_code=409,
                            detail="This draft is already waiting for review — "
                                   "find it under Suggestions.")

    prompt = parse_prompt(path, raw)
    content = render_prompt({
        "title": prompt["title"],
        "category": prompt["category"],
        "tags": prompt["tags"],
        "status": "draft",
        "level": publish.level,
        "author": session.username,
        "owner": session.username,
        "target_model": prompt["target_model"],
        "intended_use": prompt["intended_use"],
        "copied_from": prompt["copied_from"],
    }, prompt["body"])

    origin = f"\n\nPublished from a personal draft at `{publish.level}` level."
    pr = await forks.propose_change(
        session.token, session.username, path, content,
        branch=forks.branch_name(session.username, "publish"),
        message=f"New prompt: {prompt['title']}{origin}",
        pr_title=f"New prompt: {prompt['title']}",
        pr_body=(prompt["intended_use"] or "New prompt.") + origin,
    )
    # Community publishes are self-mergeable, so finish them here — the PR was
    # only ever a step on the way in. Bank publishes are the case that really
    # does wait for someone, and try_publish_now refuses them anyway.
    published = False
    if publish.level == "community":
        published = await pulls.try_publish_now(session, pr["number"])
    if published:
        message = "Published. Your prompt is live in the Community library."
    elif publish.level == "community":
        message = ("Your prompt is ready to publish — open it under "
                   "Suggestions and publish it to the library.")
    else:
        message = "Your draft has been sent to a Bank Approver for review."
    return {"message": message, "id": pr["number"], "path": path,
            "level": publish.level, "published": published}


# --- helpers ----------------------------------------------------------------

def _fork_api(fork: dict) -> str:
    return f"/repos/{fork['full_name']}"


async def _is_approver(session: UserSession) -> bool:
    """May this user publish at Bank level? Derived live from Gitea like every
    other role check; anything short of approver (or admin) is a no."""
    role = await roles.get_role(session.session_id, session.token)
    return role in ("approver", "admin")


async def _fetch_draft(session: UserSession, path: str) -> tuple[dict, str]:
    """The user's fork + the draft's raw content, or 404."""
    if not is_prompt_file(path):
        raise HTTPException(status_code=404, detail="No such draft")
    fork = await forks.find_fork(session.token, session.username)
    if fork is None:
        raise HTTPException(status_code=404, detail="No such draft")
    try:
        raw = await gitea.api(session.token, "GET", f"{_fork_api(fork)}/raw/{path}",
                              params={"ref": DRAFTS_BRANCH}, raw=True)
    except HTTPException as exc:
        if exc.status_code == 404:
            raise HTTPException(status_code=404, detail="No such draft")
        raise
    return fork, raw


async def _branch_exists(token: str, fork: dict) -> bool:
    try:
        await gitea.api(token, "GET",
                        f"{_fork_api(fork)}/branches/{DRAFTS_BRANCH}")
    except HTTPException as exc:
        if exc.status_code == 404:
            return False
        raise
    return True


async def _ensure_drafts_branch(token: str, fork: dict) -> None:
    if await _branch_exists(token, fork):
        return
    await gitea.api(token, "POST", f"{_fork_api(fork)}/branches",
                    json={"new_branch_name": DRAFTS_BRANCH,
                          "old_branch_name": fork.get("default_branch") or "main"})


async def _draft_exists(token: str, fork: dict, path: str) -> bool:
    try:
        await gitea.api(token, "GET", f"{_fork_api(fork)}/contents/{path}",
                        params={"ref": DRAFTS_BRANCH})
    except HTTPException as exc:
        if exc.status_code == 404:
            return False
        raise
    return True


async def _changed_paths(token: str, fork: dict) -> set[str]:
    """Paths touched by commits unique to the drafts branch.

    The branch is created off the fork's main, so its tree also contains every
    library file — a plain tree listing can't tell drafts from inherited
    content. `compare` with three-dot (merge-base) semantics returns exactly
    the commits made on `drafts`, and our app is the only writer there, one
    file per commit. Intersected with the live tree so deleted drafts drop out.
    """
    base = fork.get("default_branch") or "main"
    data = await gitea.api(
        token, "GET", f"{_fork_api(fork)}/compare/{base}...{DRAFTS_BRANCH}")
    paths: set[str] = set()
    for commit in (data or {}).get("commits") or []:
        for f in commit.get("files") or []:
            if f.get("filename"):
                paths.add(f["filename"])
    return paths


async def _tree_paths(token: str, fork: dict) -> set[str]:
    tree = await gitea.api(
        token, "GET", f"{_fork_api(fork)}/git/trees/{DRAFTS_BRANCH}",
        params={"recursive": "true"})
    return {e["path"] for e in (tree or {}).get("tree") or []
            if e.get("type") == "blob"}
