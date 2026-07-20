"""Unit tests for the owner-merge predicate (docs/phase-2-ownership.md,
tightened by PLAN.MD phase A: levels).

No Gitea: `decide` is pure, taking an already-fetched view of the PR. These
cover the cases the design calls out — the mixed-PR leak case, and the two
phase-A denials in particular: bank-on-main (owned bank prompts are never
owner-mergeable) and bank-on-head (an owner cannot self-merge a flip to
`level: bank`).
"""

from app.ownership import MAX_PR_FILES, FileFacts, decide, level_of, owner_of

UMA = "uma.user"
ADAM = "adam.approver"

OWNED = "customer-support/account-balance-faq.md"
OTHER = "customer-support/card-dispute.md"


def community(owner: str) -> FileFacts:
    return FileFacts(owner=owner, level="community")


def bank(owner: str) -> FileFacts:
    return FileFacts(owner=owner, level="bank")


def heads(*paths: str) -> dict[str, str]:
    """All paths community on the PR head — the well-behaved case."""
    return {p: "community" for p in paths}


def test_owned_community_file_allowed():
    result = decide(UMA, [OWNED], {OWNED: community(UMA)}, heads(OWNED))
    assert result.allowed
    assert result.paths == (OWNED,)


def test_owned_bank_file_denied():
    """The phase-A tightening: ownership no longer suffices — a bank-level
    prompt always goes to an approver, even for its owner."""
    result = decide(UMA, [OWNED], {OWNED: bank(UMA)}, heads(OWNED))
    assert not result.allowed
    assert "bank-level on main" in result.reason


def test_absent_level_is_bank_and_denied():
    """FileFacts built from a file with no `level` carries "bank" (fail
    closed), which denies. Modelled via level_of below; here at facts level."""
    assert not decide(UMA, [OWNED], {OWNED: FileFacts(UMA, "bank")},
                      heads(OWNED)).allowed


def test_community_on_main_bank_on_head_denied():
    """The forged-level attack: a PR flipping community → bank on an owned
    file must not be owner-mergeable, or the owner mints a "bank approved"
    prompt no Bank Approver ever saw."""
    result = decide(UMA, [OWNED], {OWNED: community(UMA)}, {OWNED: "bank"})
    assert not result.allowed
    assert "not community on PR head" in result.reason


def test_missing_head_level_denied():
    """A path absent from the head map (unreadable, deleted on head) denies."""
    assert not decide(UMA, [OWNED], {OWNED: community(UMA)}, {}).allowed


def test_single_unowned_file_denied():
    assert not decide(UMA, [OWNED], {OWNED: community(ADAM)}, heads(OWNED)).allowed


def test_mixed_ownership_denied():
    """The leak case: naive checks quantify over *any* file instead of *all*."""
    result = decide(UMA, [OWNED, OTHER],
                    {OWNED: community(UMA), OTHER: community(ADAM)},
                    heads(OWNED, OTHER))
    assert not result.allowed


def test_mixed_levels_denied():
    """A PR mixing an owned community file with an owned bank file is denied
    whole — no partial owner-merge."""
    result = decide(UMA, [OWNED, OTHER],
                    {OWNED: community(UMA), OTHER: bank(UMA)},
                    heads(OWNED, OTHER))
    assert not result.allowed


def test_new_file_denied_when_author_unknown():
    """Not on main => None. Without a PR author to match, a new file has no
    trustworthy owner signal at all, so it goes to an approver."""
    assert not decide(UMA, [OWNED], {OWNED: None}, heads(OWNED)).allowed


def test_absent_owner_denied():
    """Unowned prompts stay approver-only."""
    assert not decide(UMA, [OWNED], {OWNED: community("")}, heads(OWNED)).allowed


def test_uses_main_not_pr_head():
    """`decide` only ever sees main's owner value; a PR that rewrites `owner`
    to the requester cannot influence it. Modelled here as main still saying
    Adam."""
    assert not decide(UMA, [OWNED], {OWNED: community(ADAM)}, heads(OWNED)).allowed


def test_empty_file_list_denied():
    assert not decide(UMA, [], {}, {}).allowed


def test_missing_facts_entry_denied():
    """A path absent from the map is 'couldn't determine' => denied."""
    assert not decide(UMA, [OWNED], {}, heads(OWNED)).allowed


def test_non_prompt_file_denied():
    for path in ("_templates/prompt-template.md", "README.md",
                 "customer-support/README.md", "notes.txt", "../escape.md"):
        assert not decide(UMA, [path], {path: community(UMA)},
                          heads(path)).allowed, path


def test_over_file_cap_denied():
    paths = [f"cat/prompt-{i}.md" for i in range(MAX_PR_FILES + 1)]
    assert not decide(UMA, paths, {p: community(UMA) for p in paths},
                      heads(*paths)).allowed


def test_at_file_cap_allowed():
    paths = [f"cat/prompt-{i}.md" for i in range(MAX_PR_FILES)]
    assert decide(UMA, paths, {p: community(UMA) for p in paths},
                  heads(*paths)).allowed


def test_blank_username_denied():
    assert not decide("", [OWNED], {OWNED: community("")}, heads(OWNED)).allowed


def test_owner_is_case_and_whitespace_exact():
    """Gitea usernames are matched exactly, bar surrounding whitespace."""
    assert decide(UMA, [OWNED], {OWNED: community(UMA)}, heads(OWNED)).allowed
    assert not decide(UMA, [OWNED], {OWNED: community("Uma.User")},
                      heads(OWNED)).allowed


# --- phase C: peer suggestions ----------------------------------------------

def test_peer_suggestion_to_owned_community_file_allowed():
    """Phase C: who authored the PR is irrelevant to the predicate — an owner
    may publish a peer's suggestion under exactly the same conditions as their
    own. The author is carried on the Decision for the audit trail."""
    result = decide(UMA, [OWNED], {OWNED: community(UMA)}, heads(OWNED),
                    pr_author=ADAM)
    assert result.allowed
    assert result.pr_author == ADAM


def test_peer_suggestion_to_bank_file_denied():
    """A peer suggestion to a bank prompt goes to a Bank Approver, owner or
    not."""
    result = decide(UMA, [OWNED], {OWNED: bank(UMA)}, heads(OWNED),
                    pr_author=ADAM)
    assert not result.allowed


def test_peer_merger_who_is_not_owner_denied():
    """Being the PR's author or reviewer grants nothing — only the file's
    owner (per main) may merge, whoever wrote the change."""
    result = decide(ADAM, [OWNED], {OWNED: community(UMA)}, heads(OWNED),
                    pr_author=ADAM)
    assert not result.allowed


def test_pr_author_defaults_empty():
    """Callers that don't know the author (or pre-checks) still work."""
    result = decide(UMA, [OWNED], {OWNED: community(UMA)}, heads(OWNED))
    assert result.allowed
    assert result.pr_author == ""


# --- phase E: self-publishing a new community prompt ------------------------

def owned_head(path: str, user: str) -> dict[str, str]:
    return {path: user}


def test_new_community_prompt_self_published_by_author():
    """The phase-E case: publishing your own brand-new community prompt needs
    no approver. Authorized on the PR author (a Gitea fact) plus a head that
    names them as owner at community level."""
    result = decide(UMA, [OWNED], {OWNED: None}, heads(OWNED),
                    pr_author=UMA, owners_on_head=owned_head(OWNED, UMA))
    assert result.allowed
    assert result.paths == (OWNED,)


def test_new_bank_prompt_not_self_publishable():
    """Picking `bank` at publish time still buys a Bank Approver's review —
    that is the whole point of the level."""
    result = decide(UMA, [OWNED], {OWNED: None}, {OWNED: "bank"},
                    pr_author=UMA, owners_on_head=owned_head(OWNED, UMA))
    assert not result.allowed
    assert "not community" in result.reason


def test_new_prompt_naming_someone_else_as_owner_denied():
    """The forged-owner attack on the new-file path: the author cannot mint a
    prompt owned by someone else and merge it themselves."""
    result = decide(UMA, [OWNED], {OWNED: None}, heads(OWNED),
                    pr_author=UMA, owners_on_head=owned_head(OWNED, ADAM))
    assert not result.allowed
    assert "not owned by" in result.reason


def test_new_prompt_merged_by_non_author_denied():
    """A brand-new prompt has no established owner, so nobody but its author
    can self-publish it — a peer's new prompt goes to an approver."""
    result = decide(ADAM, [OWNED], {OWNED: None}, heads(OWNED),
                    pr_author=UMA, owners_on_head=owned_head(OWNED, UMA))
    assert not result.allowed
    assert "another author" in result.reason


def test_new_prompt_missing_head_owner_denied():
    """No owner readable on the head (absent, malformed) => denied."""
    assert not decide(UMA, [OWNED], {OWNED: None}, heads(OWNED),
                      pr_author=UMA, owners_on_head={}).allowed
    assert not decide(UMA, [OWNED], {OWNED: None}, heads(OWNED),
                      pr_author=UMA, owners_on_head={OWNED: ""}).allowed


def test_new_prompt_still_path_checked():
    """Self-publish does not bypass the prompt-path rules."""
    for path in ("_templates/prompt-template.md", "README.md", "../escape.md"):
        assert not decide(UMA, [path], {path: None}, heads(path),
                          pr_author=UMA,
                          owners_on_head=owned_head(path, UMA)).allowed, path


def test_existing_file_ignores_head_owner():
    """The load-bearing invariant: for a file that EXISTS on main, the head's
    `owner` is never consulted. A PR rewriting `owner: uma` on Adam's prompt
    stays denied even though the head now claims Uma."""
    result = decide(UMA, [OWNED], {OWNED: community(ADAM)}, heads(OWNED),
                    pr_author=UMA, owners_on_head=owned_head(OWNED, UMA))
    assert not result.allowed
    assert "owned by" in result.reason


def test_new_and_owned_files_together_allowed():
    """A PR adding a new community prompt alongside an edit to one the author
    already owns is publishable as a whole."""
    result = decide(UMA, [OWNED, OTHER],
                    {OWNED: community(UMA), OTHER: None},
                    heads(OWNED, OTHER), pr_author=UMA,
                    owners_on_head={OWNED: UMA, OTHER: UMA})
    assert result.allowed


def test_new_file_mixed_with_someone_elses_denied():
    """No partial merge: one unpublishable path denies the PR whole."""
    result = decide(UMA, [OWNED, OTHER],
                    {OWNED: community(ADAM), OTHER: None},
                    heads(OWNED, OTHER), pr_author=UMA,
                    owners_on_head={OWNED: UMA, OTHER: UMA})
    assert not result.allowed


# --- owner_of ---------------------------------------------------------------

def test_owner_of_reads_front_matter():
    raw = f"---\ntitle: Thing\nowner: {UMA}\n---\n\nBody text.\n"
    assert owner_of(raw) == UMA


def test_owner_of_strips_whitespace():
    assert owner_of(f"---\nowner: '  {UMA}  '\n---\n\nBody\n") == UMA


def test_owner_of_absent_is_empty():
    assert owner_of("---\ntitle: Thing\n---\n\nBody\n") == ""


def test_owner_of_no_front_matter_is_empty():
    assert owner_of("Just a body, no front-matter.\n") == ""


def test_owner_of_malformed_yaml_is_empty():
    assert owner_of("---\nowner: [unclosed\n---\n\nBody\n") == ""


def test_owner_of_non_scalar_is_empty():
    """A list owner is not a v1 owner — deny rather than guess which entry."""
    assert owner_of(f"---\nowner: [{UMA}, {ADAM}]\n---\n\nBody\n") == ""
    assert owner_of("---\nowner:\n  name: uma\n---\n\nBody\n") == ""


# --- level_of ---------------------------------------------------------------

def test_level_of_community():
    assert level_of("---\nlevel: community\n---\n\nBody\n") == "community"


def test_level_of_bank():
    assert level_of("---\nlevel: bank\n---\n\nBody\n") == "bank"


def test_level_of_absent_is_bank():
    assert level_of("---\ntitle: Thing\n---\n\nBody\n") == "bank"


def test_level_of_junk_is_bank():
    """Anything but the exact scalar "community" fails closed to bank."""
    assert level_of("---\nlevel: Community\n---\n\nBody\n") == "bank"
    assert level_of("---\nlevel: [community]\n---\n\nBody\n") == "bank"
    assert level_of("---\nlevel: personal\n---\n\nBody\n") == "bank"
    assert level_of("---\nlevel:\n---\n\nBody\n") == "bank"
    assert level_of("No front-matter at all.\n") == "bank"
    assert level_of("---\nlevel: [unclosed\n---\n\nBody\n") == "bank"
