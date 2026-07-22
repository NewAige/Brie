"""Browse, search, view, history, suggest-an-edit, and copy-event endpoints."""

import base64
import difflib
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import db, forks, gitea, prompt_index
from ..categories import DEPARTMENTS
from ..config import settings
from ..deps import UserSession, current_session, require_approver, require_contributor
from ..frontmatter import (parse_prompt, prompt_level, render_prompt,
                           replace_body, replace_level, split_front_matter)
from ..paths import is_prompt_file, slugify
from . import pulls

router = APIRouter(prefix="/api", dependencies=[Depends(current_session)])


def _public(prompt: dict, with_body: bool, favorited: bool = False) -> dict:
    fields = ["path", "category", "title", "tags", "status", "level", "author",
              "owner", "copied_from", "target_model", "intended_use", "review_notes"]
    out = {k: prompt[k] for k in fields}
    # Set by prompt_index at rebuild time; absent when parsing a single file
    # (detail view, faked indexes in tests), where "" simply hides the date.
    out["updated"] = prompt.get("updated", "")
    out["favorited"] = favorited
    if with_body:
        out["body"] = prompt["body"]
    return out


@router.get("/categories")
async def categories(session: UserSession = Depends(current_session)):
    prompts = await prompt_index.get_index(session.token)
    counts: dict[str, int] = {name: 0 for name in DEPARTMENTS}
    for p in prompts:
        if p["status"] == "deprecated":
            continue
        counts[p["category"]] = counts.get(p["category"], 0) + 1
    names = DEPARTMENTS + sorted(name for name in counts if name not in DEPARTMENTS)
    return [{"name": name, "count": counts[name]} for name in names]


@router.get("/prompts")
async def list_prompts(category: str = "", tag: str = "", q: str = "",
                       include_deprecated: bool = False,
                       favorites: bool = False, mine: bool = False,
                       session: UserSession = Depends(current_session)):
    """`favorites=true` narrows to prompts this user marked; `mine=true` to
    prompts they wrote. Both are per-user views of the same library, so they
    filter the shared index rather than querying a separate collection."""
    prompts = await prompt_index.get_index(session.token)
    query = q.strip().lower()
    marked = db.favorite_paths(session.username)
    results = []
    for p in prompts:
        if p["status"] == "deprecated" and not include_deprecated:
            continue  # hidden from default browse, still reachable by direct link
        if favorites and p["path"] not in marked:
            continue
        # Authored-by-me covers both fields: `author` is who wrote it, but a
        # prompt handed over to a new maintainer should still show up for the
        # person now responsible for it.
        if mine and session.username not in (p["author"], p["owner"]):
            continue
        if category and p["category"] != category:
            continue
        if tag and tag not in p["tags"]:
            continue
        if query:
            haystack = " ".join([p["title"], " ".join(p["tags"]), p["body"]]).lower()
            if query not in haystack:
                continue
        results.append(_public(p, with_body=False, favorited=p["path"] in marked))
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
    favorited = path in db.favorite_paths(session.username)
    return _public(parse_prompt(path, raw["text"]), with_body=True,
                   favorited=favorited)


class Suggestion(BaseModel):
    body: str = Field(min_length=1, description="The new prompt body (no front-matter)")
    note: str = Field(min_length=1, max_length=2000, description="What changed and why")


@router.post("/prompts/{path:path}/suggest")
async def suggest_edit(path: str, suggestion: Suggestion,
                       session: UserSession = Depends(require_contributor)):
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
    pr = await forks.propose_change(
        session.token, session.username, path, new_content,
        branch=forks.branch_name(session.username, "suggest"),
        message=f"Suggest edit: {title}\n\n{suggestion.note}",
        pr_title=f"Suggestion: {title}", pr_body=suggestion.note,
    )
    return {"message": "Your suggestion has been sent for review.", "id": pr["number"]}


class LevelChange(BaseModel):
    # v1 is promotion-only. Demotion is NOT this endpoint with the values
    # swapped — it re-arms a possibly-stale owner's self-publish and needs its
    # own design (docs/bank-upgrade.md "Demotion is a separate question");
    # constraining the type keeps it structurally impossible until then.
    level: Literal["bank"]


@router.post("/prompts/{path:path}/level")
async def raise_level(path: str, change: LevelChange,
                      session: UserSession = Depends(require_approver)):
    """Raise a live Community prompt to Bank (docs/bank-upgrade.md).

    A single direct commit to `main` with the promoting approver's OWN token —
    never a PR, never the bot — so the owner-merge machinery (`ownership.py`,
    including its levels_on_head guard) stays out of the path entirely.
    Approvers hold push access, so Gitea remains a real second layer: a
    non-writer's token cannot make this commit even if the role check were
    bypassed.

    Only the `level:` line changes; the body and every other front-matter line
    are byte-identical, so the commit diff records exactly what was decided.
    The current level is read from `main` here, never trusted from the caller,
    and the blob sha from that read guards the write: if anything lands on
    main in between, Gitea refuses and we surface a conflict instead of
    silently re-deciding on content the approver never saw.
    """
    # Stricter than _require_valid_path: `_templates/` and README files are
    # not library prompts, so they have no level to raise.
    if not is_prompt_file(path):
        raise HTTPException(status_code=404, detail="Unknown prompt")
    current = await _fetch_file(session.token, path)  # 404 if not on main
    _fm, meta, _body = split_front_matter(current["text"])
    if prompt_level(meta) != "community":
        raise HTTPException(status_code=409,
                            detail="This prompt is already Bank approved.")
    try:
        content = replace_level(current["text"], "bank")
    except ValueError:
        # The level parsed as community but the line cannot be rewritten
        # safely (e.g. duplicate keys). Fail closed: no write we cannot
        # stand behind as a one-line change.
        raise HTTPException(
            status_code=409,
            detail="This prompt's details could not be safely updated. "
                   "Review the prompt and try again.")

    title = str(meta.get("title") or path)
    try:
        await gitea.api(
            session.token, "PUT", f"{settings.repo_api}/contents/{path}",
            json={"branch": "main", "sha": current["sha"],
                  "content": base64.b64encode(content.encode()).decode(),
                  "message": f"Raise to Bank: {title}\n\n"
                             f"Raised by {session.username}. Every future "
                             "change now requires a Bank Approver."})
    except HTTPException as exc:
        if exc.status_code in (409, 422):
            # Blob-sha mismatch: main moved between our read and this write.
            # Deliberately no internal retry — re-reading means re-deciding,
            # and the approver should see what changed first.
            raise HTTPException(
                status_code=409,
                detail="This prompt changed while you were raising it. "
                       "Review the latest version and try again.")
        raise
    return {"message": f"{title} is now Bank approved. Every future change "
                       "requires a Bank Approver's sign-off.",
            "path": path, "level": "bank"}


class NewPrompt(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    category: str = Field(min_length=1, max_length=60)
    body: str = Field(min_length=1, description="The prompt text (no front-matter)")
    tags: list[str] = Field(default_factory=list, max_length=10)
    intended_use: str = Field("", max_length=300)
    target_model: str = Field("", max_length=100)
    copied_from: str = Field("", description="Path of the prompt this was copied from, if any")


@router.post("/prompts")
async def create_prompt(new: NewPrompt,
                        session: UserSession = Depends(require_contributor)):
    """Create a brand-new prompt (from scratch, or "Make a copy" of an
    existing one) as a PR, through the same fork/branch chain as suggestions.
    The path is derived server-side: <category-slug>/<title-slug>.md.
    A category matching one of the fixed departments is used verbatim (so it
    lands in the same folder as the seeded prompts for that department);
    anything else is slugified, same as a title."""
    category = new.category.strip() if new.category.strip() in DEPARTMENTS else slugify(new.category)
    slug = slugify(new.title)
    if not category or not slug:
        raise HTTPException(status_code=400,
                            detail="Title and category must contain letters or numbers.")
    path = f"{category}/{slug}.md"
    if not is_prompt_file(path):
        raise HTTPException(status_code=400, detail="That name is reserved.")
    if await forks.file_exists_on_main(session.token, path):
        raise HTTPException(status_code=409,
                            detail="A prompt with this name already exists in that category.")
    if await forks.pending_pr_for(session.token, path):
        raise HTTPException(
            status_code=409,
            detail="A prompt with this name is already waiting for review. "
                   "Pick a different title, or find it under Suggestions.")
    if new.copied_from:
        _require_valid_path(new.copied_from)

    tags = list(dict.fromkeys(t for t in (slugify(t) for t in new.tags) if t))
    content = render_prompt({
        "title": new.title.strip(),
        "category": category,
        "tags": tags,
        "status": "draft",
        # New prompts are always Community — the default publication level,
        # owner-maintained from the moment they land. Bank is deliberately not
        # offered here: promotion is the only way into that tier — an approver
        # raises the live prompt afterwards via `raise_level` above.
        "level": "community",
        "author": session.username,
        "owner": session.username,
        "target_model": new.target_model,
        "intended_use": new.intended_use,
        "copied_from": new.copied_from,
    }, new.body)

    origin = f"\n\nCopied from `{new.copied_from}`." if new.copied_from else ""
    pr = await forks.propose_change(
        session.token, session.username, path, content,
        branch=forks.branch_name(session.username, "new"),
        message=f"New prompt: {new.title.strip()}{origin}",
        pr_title=f"New prompt: {new.title.strip()}",
        pr_body=(new.intended_use or "New prompt.") + origin,
    )
    # New community prompts are self-mergeable by their author, so finish the
    # job here rather than leaving a PR the author must go and click again.
    # If that does not land, the PR stays open and Suggestions still works.
    published = await pulls.try_publish_now(session, pr["number"])
    message = ("Published. Your prompt is live in the Community library."
               if published else
               "Your prompt is ready to publish — open it under "
               "Suggestions and publish it to the library.")
    return {"message": message, "id": pr["number"], "path": path,
            "level": "community", "published": published}


@router.put("/prompts/{path:path}/favorite")
async def add_favorite(path: str, session: UserSession = Depends(current_session)):
    """Mark a prompt to come back to later. Available to every role including
    browsers — it changes nothing about the prompt, only the user's own view."""
    _require_valid_path(path)
    db.add_favorite(session.username, path)
    return {"favorited": True}


@router.delete("/prompts/{path:path}/favorite")
async def remove_favorite(path: str, session: UserSession = Depends(current_session)):
    # No path validation: a prompt deleted from the library leaves a stale row,
    # and the user must still be able to clear it.
    db.remove_favorite(session.username, path)
    return {"favorited": False}


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
