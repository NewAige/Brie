"""Browse, search, view, history, suggest-an-edit, and copy-event endpoints."""

import base64
import difflib
import re
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import db, gitea, prompt_index
from ..config import settings
from ..deps import UserSession, current_session
from ..frontmatter import build_prompt_file, parse_prompt, replace_body, split_front_matter

router = APIRouter(prefix="/api", dependencies=[Depends(current_session)])


def _public(prompt: dict, with_body: bool) -> dict:
    fields = ["path", "category", "title", "tags", "status", "author",
              "target_model", "intended_use", "review_notes"]
    out = {k: prompt[k] for k in fields}
    if with_body:
        out["body"] = prompt["body"]
    return out


@router.get("/categories")
async def categories(session: UserSession = Depends(current_session)):
    prompts = await prompt_index.get_index(session.token)
    counts: dict[str, int] = {}
    for p in prompts:
        if p["status"] == "deprecated":
            continue
        counts[p["category"]] = counts.get(p["category"], 0) + 1
    return [{"name": name, "count": counts[name]} for name in sorted(counts)]


@router.get("/prompts")
async def list_prompts(category: str = "", tag: str = "", q: str = "",
                       include_deprecated: bool = False,
                       session: UserSession = Depends(current_session)):
    prompts = await prompt_index.get_index(session.token)
    query = q.strip().lower()
    results = []
    for p in prompts:
        if p["status"] == "deprecated" and not include_deprecated:
            continue  # hidden from default browse, still reachable by direct link
        if category and p["category"] != category:
            continue
        if tag and tag not in p["tags"]:
            continue
        if query:
            haystack = " ".join([p["title"], " ".join(p["tags"]), p["body"]]).lower()
            if query not in haystack:
                continue
        results.append(_public(p, with_body=False))
    return results


@router.get("/prompts/{path:path}/history")
async def prompt_history(path: str, session: UserSession = Depends(current_session)):
    _require_valid_path(path)
    commits = await gitea.api(
        session.token, "GET", f"{settings.repo_api}/commits",
        params={"path": path, "sha": "main", "limit": 20,
                "stat": "false", "verification": "false", "files": "false"},
    )

    async def content_at(sha: str) -> str:
        try:
            return await gitea.api(
                session.token, "GET", f"{settings.repo_api}/raw/{path}",
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


@router.get("/prompts/{path:path}")
async def get_prompt(path: str, session: UserSession = Depends(current_session)):
    _require_valid_path(path)
    raw = await _fetch_file(session.token, path)
    out = _public(parse_prompt(path, raw["text"]), with_body=True)
    out.update(db.favorite_state(session.username, path))
    return out


@router.put("/prompts/{path:path}/favorite")
async def favorite(path: str, session: UserSession = Depends(current_session)):
    _require_valid_path(path)
    db.add_favorite(session.username, path)
    return db.favorite_state(session.username, path)


@router.delete("/prompts/{path:path}/favorite")
async def unfavorite(path: str, session: UserSession = Depends(current_session)):
    _require_valid_path(path)
    db.remove_favorite(session.username, path)
    return db.favorite_state(session.username, path)


class Suggestion(BaseModel):
    body: str = Field(min_length=1, description="The new prompt body (no front-matter)")
    note: str = Field(min_length=1, max_length=2000, description="What changed and why")


@router.post("/prompts/{path:path}/suggest")
async def suggest_edit(path: str, suggestion: Suggestion,
                       session: UserSession = Depends(current_session)):
    """Create branch + commit + PR using the SUGGESTER's own token, so git
    history records them as the author. The UI never shows git terminology.

    Users with write access branch inside the library repo. Read-only users
    cannot push branches there, so for them we transparently maintain a fork
    under their own account and open the suggestion from it — the standard
    git contribution flow, fully hidden behind "Suggest an edit".
    """
    _require_valid_path(path)
    current = await _fetch_file(session.token, path)
    _fm, meta, old_body = split_front_matter(current["text"])
    if suggestion.body.replace("\r\n", "\n").strip("\n") == old_body.strip("\n"):
        raise HTTPException(status_code=400, detail="No changes to suggest — the text is identical.")

    new_content = replace_body(current["text"], suggestion.body)
    title = str(meta.get("title") or path)
    branch = _branch_name(session.username)
    message = f"Suggest edit: {title}\n\n{suggestion.note}"

    repo = await gitea.api(session.token, "GET", settings.repo_api)
    if (repo.get("permissions") or {}).get("push"):
        await _commit_to_new_branch(session.token, settings.repo_api, path,
                                    base_branch="main", new_branch=branch,
                                    content=new_content, message=message)
        head = branch
    else:
        fork = await _ensure_fork(session.token, session.username)
        await _commit_to_new_branch(session.token, f"/repos/{fork['full_name']}", path,
                                    base_branch=fork["default_branch"] or "main",
                                    new_branch=branch, content=new_content, message=message)
        head = f"{fork['owner']['login']}:{branch}"

    pr = await gitea.api(
        session.token, "POST", f"{settings.repo_api}/pulls",
        json={"base": "main", "head": head,
              "title": f"Suggestion: {title}", "body": suggestion.note},
    )
    return {"message": "Your suggestion has been sent for review.", "id": pr["number"]}


class SaveAsCopy(BaseModel):
    title: str = Field(min_length=1, max_length=200, description="Title for the new prompt")
    category: str = Field(min_length=1, description="Existing category folder for the new prompt")
    body: str = Field(min_length=1, description="The new prompt body (no front-matter)")
    note: str = Field(min_length=1, max_length=2000, description="What this copy is for")


@router.post("/prompts/{path:path}/save-as")
async def save_as_copy(path: str, req: SaveAsCopy,
                       session: UserSession = Depends(current_session)):
    """Save a copy of an existing prompt as a brand-new prompt file, submitted
    for review through the same branch/fork + PR flow as "suggest an edit".
    The source prompt is credited via a `derived_from` front-matter field and
    the remix is tallied for the activity leaderboards.
    """
    _require_valid_path(path)
    prompts = await prompt_index.get_index(session.token)
    source = next((p for p in prompts if p["path"] == path), None)
    if source is None:
        raise HTTPException(status_code=404, detail="Unknown prompt")
    if req.category not in {p["category"] for p in prompts}:
        raise HTTPException(status_code=400, detail="Pick an existing category for the new prompt.")

    slug = re.sub(r"[^a-z0-9]+", "-", req.title.lower()).strip("-")
    if not slug:
        raise HTTPException(status_code=400, detail="The title must contain letters or numbers.")
    new_path = f"{req.category}/{slug}.md"
    if any(p["path"] == new_path for p in prompts):
        raise HTTPException(status_code=400,
                            detail="A prompt with that title already exists in this category — pick another title.")

    content = build_prompt_file({
        "title": req.title.strip(),
        "author": session.username,
        "status": "draft",
        "tags": source["tags"],
        "target_model": source["target_model"],
        "intended_use": source["intended_use"],
        "derived_from": path,
    }, req.body)

    branch = _branch_name(session.username)
    message = f"New prompt: {req.title.strip()}\n\nSaved as a copy of {path}.\n\n{req.note}"

    repo = await gitea.api(session.token, "GET", settings.repo_api)
    if (repo.get("permissions") or {}).get("push"):
        await _commit_to_new_branch(session.token, settings.repo_api, new_path,
                                    base_branch="main", new_branch=branch,
                                    content=content, message=message)
        head = branch
    else:
        fork = await _ensure_fork(session.token, session.username)
        await _commit_to_new_branch(session.token, f"/repos/{fork['full_name']}", new_path,
                                    base_branch=fork["default_branch"] or "main",
                                    new_branch=branch, content=content, message=message)
        head = f"{fork['owner']['login']}:{branch}"

    pr = await gitea.api(
        session.token, "POST", f"{settings.repo_api}/pulls",
        json={"base": "main", "head": head,
              "title": f"New prompt: {req.title.strip()}",
              "body": f"Saved as a copy of `{path}`.\n\n{req.note}"},
    )
    db.log_remix_event(path)
    return {"message": "Your new prompt has been sent for review.", "id": pr["number"]}


class CopyEvent(BaseModel):
    path: str


@router.post("/events/copy")
async def copy_event(event: CopyEvent):
    # Schema is deliberately just path + timestamp — no user id, no content,
    # no PII (spec §7).
    _require_valid_path(event.path)
    db.log_copy_event(event.path)
    return {"ok": True}


# --- helpers ----------------------------------------------------------------

def _require_valid_path(path: str) -> None:
    if not prompt_index.is_valid_prompt_path(path):
        raise HTTPException(status_code=404, detail="Unknown prompt")


async def _fetch_file(token: str, path: str) -> dict:
    """File content + blob sha on main (the sha is needed to commit an edit)."""
    data = await gitea.api(token, "GET", f"{settings.repo_api}/contents/{path}",
                           params={"ref": "main"})
    if data.get("type") != "file" or data.get("encoding") != "base64":
        raise HTTPException(status_code=404, detail="Unknown prompt")
    return {"sha": data["sha"], "text": base64.b64decode(data["content"]).decode("utf-8")}


def _branch_name(username: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]", "-", username).strip("-.") or "user"
    return f"suggest/{slug}-{int(time.time() * 1000)}"


async def _commit_to_new_branch(token: str, repo_api: str, path: str, *,
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


async def _ensure_fork(token: str, username: str) -> dict:
    """Find or create the user's fork of the library repo."""
    forks = await gitea.api(token, "GET", f"{settings.repo_api}/forks",
                            params={"limit": 50})
    for fork in forks or []:
        if fork.get("owner", {}).get("login") == username:
            await _sync_fork(token, fork)
            return fork
    return await gitea.api(token, "POST", f"{settings.repo_api}/forks", json={})


async def _sync_fork(token: str, fork: dict) -> None:
    """Best-effort fast-forward of an existing fork's default branch so
    suggestions are built on current content. Ignore failures — a stale fork
    still produces a correct PR diff (merge-base semantics)."""
    branch = fork.get("default_branch") or "main"
    try:
        await gitea.api(token, "POST",
                        f"/repos/{fork['full_name']}/sync_fork",
                        json={"branch": branch})
    except HTTPException:
        pass
