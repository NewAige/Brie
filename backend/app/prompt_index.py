"""In-memory index of all prompt files, keyed to the tip commit of main.

The index is rebuilt only when main's head SHA changes, so browsing and
search stay fast without this backend ever becoming a second source of truth.
Access control is preserved: every request first asks Gitea for the branch
head using the REQUESTING USER's token, so a user without read access on the
repo gets Gitea's 403/404 before any cached data is touched.
"""

import asyncio

from fastapi import HTTPException

from . import gitea
from .config import settings
from .frontmatter import parse_prompt
from .paths import is_prompt_file, is_valid_prompt_path  # noqa: F401 (re-exported)

_cache: dict = {"sha": None, "prompts": []}
_lock = asyncio.Lock()


async def head_sha(token: str) -> str:
    branch = await gitea.api(token, "GET", f"{settings.repo_api}/branches/main")
    return branch["commit"]["id"]


async def get_index(token: str) -> list[dict]:
    sha = await head_sha(token)
    if _cache["sha"] == sha:
        return _cache["prompts"]
    async with _lock:
        if _cache["sha"] == sha:  # another request rebuilt it while we waited
            return _cache["prompts"]
        tree = await gitea.api(
            token, "GET", f"{settings.repo_api}/git/trees/{sha}",
            params={"recursive": "true"},
        )
        paths = [
            entry["path"]
            for entry in tree.get("tree", [])
            if entry.get("type") == "blob" and is_prompt_file(entry["path"])
        ]

        # Bounds files in flight during a rebuild (each file is two concurrent
        # Gitea reads). High enough that a few-hundred-prompt library rebuilds
        # in a couple of seconds; low enough not to slam Gitea.
        semaphore = asyncio.Semaphore(16)

        async def last_updated(path: str) -> str:
            """ISO timestamp of the newest commit touching this file. Display
            metadata only — any failure is an empty string, never an error."""
            try:
                commits = await gitea.api(
                    token, "GET", f"{settings.repo_api}/commits",
                    params={"path": path, "sha": sha, "limit": 1, "stat": "false",
                            "verification": "false", "files": "false"},
                )
                info = (commits[0].get("commit") or {}) if commits else {}
                return (info.get("author") or {}).get("date") or ""
            except (HTTPException, LookupError, AttributeError, TypeError):
                return ""

        async def fetch(path: str) -> dict | None:
            async with semaphore:
                try:
                    # Content and newest-commit timestamp are independent
                    # reads — fetch them concurrently. last_updated never
                    # raises, so only the raw fetch can abort the pair.
                    raw, updated = await asyncio.gather(
                        gitea.api(token, "GET",
                                  f"{settings.repo_api}/raw/{path}",
                                  params={"ref": sha}, raw=True),
                        last_updated(path),
                    )
                except HTTPException:
                    return None
                prompt = parse_prompt(path, raw)
                prompt["updated"] = updated
                return prompt

        prompts = [p for p in await asyncio.gather(*(fetch(p) for p in paths)) if p]
        prompts.sort(key=lambda p: (p["category"], p["title"].lower()))
        _cache.update(sha=sha, prompts=prompts)
        return prompts


def invalidate() -> None:
    _cache.update(sha=None, prompts=[])
