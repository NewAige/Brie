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

Phase E adds self-publish: a brand-new community prompt may be merged by its
own author, so posting to the Community path needs no approver. New files have
no main-side facts to check, so the rule cannot lean on `owner` front-matter
(the PR could simply assert it). It leans on the PR AUTHOR instead — a Gitea
fact the file's content cannot forge — and still requires the head to declare
`level: community` and `owner: <that same author>`. Consequences, all
deliberate: a new `level: bank` prompt remains approver-only, a new file naming
someone else as owner is not self-mergeable, and a peer's brand-new prompt is
approver-only (it has no established owner to route to yet). Once it lands,
the file exists on main and every later edit follows the ordinary owner rule
above — back to its owner.

The predicate itself (`decide`) is pure: it takes an already-fetched view of
the PR and returns a decision, so the interesting cases are unit-testable
without a Gitea running (tests/test_ownership.py).
"""

import asyncio
import time
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
    """Why a PR is or isn't owner-mergeable. `reason` is for logs, not users.

    `pr_author` is who opened the PR — carried for the audit trail (phase C:
    the merger and the author differ on a peer suggestion), never consulted
    by the predicate itself: authorization depends only on who is merging.
    """
    allowed: bool
    reason: str
    paths: tuple[str, ...] = ()
    pr_author: str = ""


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
           levels_on_head: dict[str, str], pr_author: str = "",
           owners_on_head: dict[str, str] | None = None) -> Decision:
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

    `pr_author` (who opened the PR) is passed through to the Decision for the
    audit log. For files that exist on main it plays no part in the answer: an
    owner may merge their own change and a peer's suggestion under exactly the
    same conditions. For NEW files it is load-bearing — see below.

    `owners_on_head` maps each path to its `owner` on the PR head. It is
    consulted ONLY for paths absent from main (phase E self-publish), where
    there is no main-side owner to read. Trusting it is safe only in
    combination with the `pr_author == username` check: a PR may assert any
    owner it likes, but it cannot assert who opened it. For paths that DO exist
    on main this map is ignored entirely — main remains the sole authority on
    ownership, which is the rule that makes the whole predicate safe.
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
            # Not on main: a brand-new prompt (phase E self-publish). There is
            # no main-side fact to check, so authorize on the PR author — which
            # the file cannot forge — plus a head that declares the author as
            # owner at community level. Anything else goes to an approver.
            if not pr_author or pr_author != username:
                return Decision(False, f"new file by another author: {path}")
            if (owners_on_head or {}).get(path) != username:
                return Decision(False, f"new file not owned by {username}: {path}")
            if levels_on_head.get(path) != "community":
                return Decision(False, f"new file not community: {path}")
            continue
        if not facts.owner:
            return Decision(False, f"unowned on main: {path}")
        if facts.owner != username:
            return Decision(False, f"owned by {facts.owner}, not {username}: {path}")
        if facts.level != "community":
            return Decision(False, f"bank-level on main: {path}")
        if levels_on_head.get(path) != "community":
            return Decision(False, f"not community on PR head: {path}")

    new_count = sum(1 for p in paths if facts_on_main.get(p) is None)
    detail = f" ({new_count} newly published)" if new_count else ""
    return Decision(True,
                    f"{username} owns all {len(paths)} community file(s){detail}",
                    tuple(paths), pr_author)


async def owner_mergeable(token: str, username: str, pr_id: int, *,
                          require_mergeable: bool = True) -> Decision:
    """Fetch what `decide` needs and apply it. Reads use the USER's token, so
    Gitea's access control still applies to everything we look at.

    Any Gitea error is a denial, not an exception — a PR we cannot fully
    inspect is one we must send to an approver.

    `require_mergeable=False` skips only the merge-conflict gate, for callers
    who are NOT about to merge the branch: declining a suggestion, or
    publishing an accepted subset of it as a fresh commit (routers/pulls.py).
    A conflict makes a merge pointless but says nothing about ownership, and
    without this an owner could never decline a conflicted peer suggestion.
    Every ownership and level check still runs unchanged.
    """
    try:
        pr = await gitea.api(token, "GET", f"{settings.repo_api}/pulls/{pr_id}")
    except HTTPException:
        return Decision(False, "could not read PR")

    if pr.get("state") != "open" or pr.get("merged"):
        return Decision(False, "PR is not open")
    if require_mergeable and pr.get("mergeable") is False:
        return Decision(False, "PR has conflicts")

    head_sha = (pr.get("head") or {}).get("sha")
    if not head_sha:
        return Decision(False, "PR has no head sha")

    pr_author = str((pr.get("user") or {}).get("login") or "")

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

    # Cheap structural checks first (path shape, file cap), so a junk PR costs
    # no file reads. Feeding owner-less facts makes every path fail at the
    # ownership step, so only the structural reasons can come back — anything
    # about ownership or level has to wait for the real reads below.
    pre = decide(username, paths, {p: FileFacts("", "bank") for p in paths}, {})
    if not pre.allowed and not pre.reason.startswith("unowned on main"):
        return pre

    # All file reads (each path on main AND on the head) run concurrently,
    # bounded by _READ_CONCURRENCY. The semantics per read are unchanged from
    # the old sequential loop: a 404 is a fact (absent file), any other error
    # is a denial of the whole decision.
    semaphore = asyncio.Semaphore(_READ_CONCURRENCY)
    try:
        views = await asyncio.gather(
            *(_file_view(token, path, head_sha, semaphore) for path in paths))
    except _DenyRead as exc:
        return Decision(False, str(exc))

    facts: dict[str, FileFacts | None] = {}
    levels_on_head: dict[str, str] = {}
    owners_on_head: dict[str, str] = {}
    for path, (main_facts, head_raw) in zip(paths, views):
        # None: not on main. Not a denial by itself (phase E): the head reads
        # are where a self-publish is authorized.
        facts[path] = main_facts
        if head_raw is None:
            # Deleted on the head: stays absent from the level map, which denies.
            continue
        levels_on_head[path] = level_of(head_raw)
        # Only consulted for files absent from main (phase E self-publish);
        # read unconditionally because it costs nothing extra here.
        owners_on_head[path] = owner_of(head_raw)

    return decide(username, paths, facts, levels_on_head, pr_author,
                  owners_on_head)


# At most this many Gitea reads in flight per decision. A PR may touch up to
# MAX_PR_FILES files (2 reads each); issuing all of them at once would trade
# request latency for a thundering herd against Gitea.
_READ_CONCURRENCY = 8


class _DenyRead(Exception):
    """Carries a fail-closed denial reason out of the concurrent reads in
    `owner_mergeable`. Never escapes this module."""


async def _file_view(token: str, path: str, head_sha: str,
                     semaphore: asyncio.Semaphore
                     ) -> tuple[FileFacts | None, str | None]:
    """One path's facts on main (None if absent there) and its raw content on
    the PR head (None if absent — deleted on the head). The two reads run
    concurrently. Any Gitea error other than a 404 raises _DenyRead: a file we
    cannot inspect fails the whole decision (fail closed)."""
    async def read(ref: str, where: str) -> str | None:
        async with semaphore:
            try:
                return await gitea.api(token, "GET",
                                       f"{settings.repo_api}/raw/{path}",
                                       params={"ref": ref}, raw=True)
            except HTTPException as exc:
                if exc.status_code == 404:
                    return None
                raise _DenyRead(f"could not read {path} on {where}")

    main_raw, head_raw = await asyncio.gather(read("main", "main"),
                                              read(head_sha, "PR head"))
    main_facts = None if main_raw is None else \
        FileFacts(owner_of(main_raw), level_of(main_raw))
    return main_facts, head_raw


# --- advisory cache ----------------------------------------------------------
#
# The Suggestions list and the nav badge ask the same question for every open
# PR, per user, re-polled every minute — by far the app's hottest Gitea path.
# The decision is a pure function of the revisions it reads (each file on main
# and on the PR head), so it can be cached keyed by the exact revisions of
# both sides: any publish to main or push to the suggestion changes a sha and
# misses the cache. The main sha in the key must come from a read made with
# the REQUESTING user's token (routers use prompt_index.head_sha), so a user
# without repo access can never form a key, let alone hit someone's entry.
#
# ADVISORY ONLY: anything that executes — merge, decline, partial apply —
# must call owner_mergeable directly so authorization is decided on live
# reads immediately before acting (the boundary described in routers/pulls.py).

ADVISORY_TTL = 60  # seconds; also bounds staleness when a PR closes sha-unchanged
_advisory: dict[tuple[str, int, str, str], tuple[float, Decision]] = {}


async def owner_mergeable_advisory(token: str, username: str, pr_id: int,
                                   head_sha: str, main_sha: str) -> Decision:
    """Cached `owner_mergeable` for display purposes only. Callers pass the
    shas they already hold from the PR listing; a missing sha bypasses the
    cache (an unkeyable decision is computed live, never mis-filed)."""
    if not head_sha or not main_sha:
        return await owner_mergeable(token, username, pr_id)
    key = (username, pr_id, head_sha, main_sha)
    now = time.time()
    hit = _advisory.get(key)
    if hit and hit[0] > now:
        return hit[1]
    decision = await owner_mergeable(token, username, pr_id)
    if len(_advisory) >= 4096:
        # Simple memory bound; entries age out by TTL, this catches key churn.
        _advisory.clear()
    _advisory[key] = (now + ADVISORY_TTL, decision)
    return decision
