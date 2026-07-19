"""Owner-merge authorization (docs/phase-2-ownership.md, tightened by PLAN.MD
phase A: levels).

This is the first place the app makes an authorization decision of its own,
rather than deferring to Gitea. That is unavoidable: branch protection on main
has `enable_approvals_whitelist: false`, so granting a member write access so
they can merge their own prompt would also give them approval rights over
everyone else's. There is no per-file permission in Gitea that expresses "may
merge only files they own".

So the rule lives here, and merging is executed with a service account. Every
check below is written to FAIL CLOSED — any error reading a file, parsing
front-matter, or listing PR files means "not owner-mergeable", never "allowed".

Phase A adds governance levels. A file is owner-mergeable only if it is
`level: community` BOTH on main AND on the PR head. The main-side check keeps
Bank prompts approver-only regardless of ownership; the head-side check stops
an owner self-merging a flip to `level: bank` and thereby forging a
bank-approved prompt.

The predicate itself (`decide`) is pure: it takes an already-fetched view of
the PR and returns a decision, so the interesting cases are unit-testable
without a Gitea running (tests/test_ownership.py).
"""

from dataclasses import dataclass

from fastapi import HTTPException

from . import gitea
from .config import settings
from .frontmatter import prompt_level, split_front_matter
from .paths import is_prompt_file

# Beyond this many files we stop and fall through to approver review rather
# than paginating a security check.
MAX_PR_FILES = 50


@dataclass(frozen=True)
class Decision:
    """Why a PR is or isn't owner-mergeable. `reason` is for logs, not users."""
    allowed: bool
    reason: str
    paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class FileFacts:
    """What main says about one file: who owns it and what level it is."""
    owner: str
    level: str


def owner_of(raw: str) -> str:
    """The `owner` front-matter value of a prompt file, or "" if absent.

    Anything that isn't a plain scalar (a list, a mapping, a parse failure)
    yields "", which denies — an owner we can't read is not an owner we match.
    """
    _fm, meta, _body = split_front_matter(raw)
    owner = meta.get("owner")
    if owner is None or isinstance(owner, (list, dict, bool)):
        return ""
    return str(owner).strip()


def level_of(raw: str) -> str:
    """The governance level of a prompt file. Anything but an exact
    `level: community` — including unreadable front-matter — is "bank",
    the tier that is never owner-mergeable."""
    _fm, meta, _body = split_front_matter(raw)
    return prompt_level(meta)


def decide(username: str, paths: list[str],
           facts_on_main: dict[str, FileFacts | None],
           levels_on_head: dict[str, str]) -> Decision:
    """Pure predicate: may `username` merge a PR touching `paths`?

    `facts_on_main` maps each path to its owner and level AS READ FROM MAIN —
    or None if the file does not exist on main (or could not be read). Never
    pass the PR's own version for authorization facts: an author could
    otherwise add `owner: me` (or `level: community`) to a file in the same PR
    that edits it, and self-merge. That is the single most important rule here.

    `levels_on_head` maps each path to its level on the PR HEAD. This is the
    one thing we do read from the PR — not to grant, only to further deny: a
    PR whose head turns a community file into `level: bank` must go to an
    approver, or the owner-merge would mint a bank prompt no Bank Approver
    ever saw. A path missing from the map denies.
    """
    if not username:
        return Decision(False, "no user")
    if not paths:
        return Decision(False, "PR touches no files")
    if len(paths) > MAX_PR_FILES:
        return Decision(False, f"PR touches {len(paths)} files (max {MAX_PR_FILES})")

    for path in paths:
        if not is_prompt_file(path):
            return Decision(False, f"not a prompt file: {path}")
        facts = facts_on_main.get(path)
        if facts is None:
            # Not on main: a new prompt. Self-publishing a brand-new file with
            # `owner: me` is authoring, not ownership.
            return Decision(False, f"not on main: {path}")
        if not facts.owner:
            return Decision(False, f"unowned on main: {path}")
        if facts.owner != username:
            return Decision(False, f"owned by {facts.owner}, not {username}: {path}")
        if facts.level != "community":
            return Decision(False, f"bank-level on main: {path}")
        if levels_on_head.get(path) != "community":
            return Decision(False, f"not community on PR head: {path}")

    return Decision(True, f"{username} owns all {len(paths)} community file(s)",
                    tuple(paths))


async def owner_mergeable(token: str, username: str, pr_id: int) -> Decision:
    """Fetch what `decide` needs and apply it. Reads use the USER's token, so
    Gitea's access control still applies to everything we look at.

    Any Gitea error is a denial, not an exception — a PR we cannot fully
    inspect is one we must send to an approver.
    """
    try:
        pr = await gitea.api(token, "GET", f"{settings.repo_api}/pulls/{pr_id}")
    except HTTPException:
        return Decision(False, "could not read PR")

    if pr.get("state") != "open" or pr.get("merged"):
        return Decision(False, "PR is not open")
    if pr.get("mergeable") is False:
        return Decision(False, "PR has conflicts")

    head_sha = (pr.get("head") or {}).get("sha")
    if not head_sha:
        return Decision(False, "PR has no head sha")

    try:
        files = await gitea.api(
            token, "GET", f"{settings.repo_api}/pulls/{pr_id}/files",
            # Ask for one more than the cap so an over-cap PR is visibly over,
            # rather than silently truncated to exactly the cap.
            params={"limit": MAX_PR_FILES + 1},
        )
    except HTTPException:
        return Decision(False, "could not list PR files")

    paths = [f.get("filename", "") for f in files or []]
    if any(not p for p in paths):
        return Decision(False, "unnamed file in PR")

    # Cheap structural checks first, so a junk PR costs no file reads.
    pre = decide(username, paths, {p: FileFacts("", "bank") for p in paths}, {})
    if not pre.allowed and not pre.reason.startswith("unowned on main"):
        return pre

    facts: dict[str, FileFacts | None] = {}
    levels_on_head: dict[str, str] = {}
    for path in paths:
        try:
            raw = await gitea.api(token, "GET", f"{settings.repo_api}/raw/{path}",
                                  params={"ref": "main"}, raw=True)
        except HTTPException as exc:
            if exc.status_code == 404:
                facts[path] = None  # new file — denied by `decide`
                continue
            return Decision(False, f"could not read {path} on main")
        facts[path] = FileFacts(owner_of(raw), level_of(raw))

        # Head level: what the file WOULD say after merge. A file deleted on
        # the head 404s here and stays absent from the map, which denies.
        try:
            head_raw = await gitea.api(token, "GET",
                                       f"{settings.repo_api}/raw/{path}",
                                       params={"ref": head_sha}, raw=True)
        except HTTPException as exc:
            if exc.status_code == 404:
                continue
            return Decision(False, f"could not read {path} on PR head")
        levels_on_head[path] = level_of(head_raw)

    return decide(username, paths, facts, levels_on_head)
