"""Unit tests for the owner-merge predicate (docs/phase-2-ownership.md).

No Gitea: `decide` is pure, taking an already-fetched view of the PR. These
cover the cases the design calls out, and the leak case in particular — a PR
mixing an owned file with an unowned one must be denied.
"""

from app.ownership import MAX_PR_FILES, decide, owner_of

UMA = "uma.user"
ADAM = "adam.approver"

OWNED = "customer-support/account-balance-faq.md"
OTHER = "customer-support/card-dispute.md"


def test_single_owned_file_allowed():
    result = decide(UMA, [OWNED], {OWNED: UMA})
    assert result.allowed
    assert result.paths == (OWNED,)


def test_single_unowned_file_denied():
    assert not decide(UMA, [OWNED], {OWNED: ADAM}).allowed


def test_mixed_ownership_denied():
    """The leak case: naive checks quantify over *any* file instead of *all*."""
    result = decide(UMA, [OWNED, OTHER], {OWNED: UMA, OTHER: ADAM})
    assert not result.allowed


def test_new_file_denied_even_when_claiming_ownership():
    """Not on main => None. Self-publishing a new prompt is authoring, not
    ownership, however the front-matter reads."""
    assert not decide(UMA, [OWNED], {OWNED: None}).allowed


def test_absent_owner_denied():
    """Seed prompts have no `owner` — they stay approver-only."""
    assert not decide(UMA, [OWNED], {OWNED: ""}).allowed


def test_uses_main_not_pr_head():
    """`decide` only ever sees main's value; a PR that rewrites `owner` to the
    requester cannot influence it. Modelled here as main still saying Adam."""
    assert not decide(UMA, [OWNED], {OWNED: ADAM}).allowed


def test_empty_file_list_denied():
    assert not decide(UMA, [], {}).allowed


def test_missing_owner_entry_denied():
    """A path absent from the map is 'couldn't determine' => denied."""
    assert not decide(UMA, [OWNED], {}).allowed


def test_non_prompt_file_denied():
    for path in ("_templates/prompt-template.md", "README.md",
                 "customer-support/README.md", "notes.txt", "../escape.md"):
        assert not decide(UMA, [path], {path: UMA}).allowed, path


def test_over_file_cap_denied():
    paths = [f"cat/prompt-{i}.md" for i in range(MAX_PR_FILES + 1)]
    assert not decide(UMA, paths, {p: UMA for p in paths}).allowed


def test_at_file_cap_allowed():
    paths = [f"cat/prompt-{i}.md" for i in range(MAX_PR_FILES)]
    assert decide(UMA, paths, {p: UMA for p in paths}).allowed


def test_blank_username_denied():
    assert not decide("", [OWNED], {OWNED: ""}).allowed


def test_owner_is_case_and_whitespace_exact():
    """Gitea usernames are matched exactly, bar surrounding whitespace."""
    assert decide(UMA, [OWNED], {OWNED: UMA}).allowed
    assert not decide(UMA, [OWNED], {OWNED: "Uma.User"}).allowed


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
