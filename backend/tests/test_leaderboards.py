"""Activity leaderboards are pure functions over already-fetched data (the
same fetch/decide split as roles and ownership), so everything here runs
without Gitea."""

from app import leaderboards


def prompt(path, author="", status="approved", copied_from=""):
    return {"path": path, "author": author, "status": status,
            "copied_from": copied_from, "title": f"Title of {path}",
            "category": path.split("/")[0]}


# --- top_authors -------------------------------------------------------------

def test_top_authors_counts_and_ranks():
    prompts = [prompt("a/one.md", author="uma.user"),
               prompt("a/two.md", author="uma.user"),
               prompt("b/three.md", author="carl.contributor")]
    rows = leaderboards.top_authors(prompts)
    assert rows == [
        {"username": "uma.user", "name": "uma.user", "prompts": 2},
        {"username": "carl.contributor", "name": "carl.contributor", "prompts": 1},
    ]


def test_top_authors_skips_deprecated_and_authorless():
    prompts = [prompt("a/one.md", author="uma.user", status="deprecated"),
               prompt("a/two.md", author=""),
               prompt("a/three.md", author="   ")]
    assert leaderboards.top_authors(prompts) == []


def test_top_authors_skips_archived():
    """Archived prompts are retired like deprecated ones — they don't count
    toward an author's live-prompt tally."""
    prompts = [prompt("a/one.md", author="uma.user", status="archived")]
    assert leaderboards.top_authors(prompts) == []


def test_top_authors_ties_break_alphabetically_and_limit_applies():
    prompts = [prompt(f"a/{name}-{i}.md", author=name)
               for name in ("zoe.z", "amy.a", "mia.m") for i in range(2)]
    rows = leaderboards.top_authors(prompts, limit=2)
    assert [r["username"] for r in rows] == ["amy.a", "mia.m"]


def test_top_authors_uses_display_names_with_fallback():
    prompts = [prompt("a/one.md", author="uma.user"),
               prompt("a/two.md", author="carl.contributor")]
    rows = leaderboards.top_authors(prompts, names={"uma.user": "Uma User"})
    assert {r["username"]: r["name"] for r in rows} == {
        "uma.user": "Uma User", "carl.contributor": "carl.contributor"}


# --- top_contributors --------------------------------------------------------

def merged_pr(login, full_name=""):
    return {"user": {"login": login, "full_name": full_name}}


def test_top_contributors_counts_merged_suggestions():
    rows = leaderboards.top_contributors(
        [merged_pr("uma.user"), merged_pr("uma.user"), merged_pr("adam.approver")])
    assert rows == [
        {"username": "uma.user", "name": "uma.user", "accepted": 2},
        {"username": "adam.approver", "name": "adam.approver", "accepted": 1},
    ]


def test_top_contributors_adds_partial_acceptances():
    """A partially published suggestion is closed, not merged, in Gitea —
    the outcome log is what credits its author."""
    rows = leaderboards.top_contributors(
        [merged_pr("uma.user")],
        partial_counts={"uma.user": 1, "carl.contributor": 2, "": 5})
    assert rows == [
        {"username": "carl.contributor", "name": "carl.contributor", "accepted": 2},
        {"username": "uma.user", "name": "uma.user", "accepted": 2},
    ]


def test_top_contributors_survives_malformed_pr_payloads():
    """Fail closed on junk: a PR without a usable author counts nobody."""
    rows = leaderboards.top_contributors(
        [{"user": None}, {}, {"user": {"login": ""}}, merged_pr("uma.user")])
    assert [r["username"] for r in rows] == ["uma.user"]


# --- top_remixed -------------------------------------------------------------

def test_top_remixed_groups_by_source():
    prompts = [prompt("a/original.md"),
               prompt("b/copy1.md", copied_from="a/original.md"),
               prompt("b/copy2.md", copied_from="a/original.md"),
               prompt("c/other.md"),
               prompt("c/copy3.md", copied_from="c/other.md")]
    rows = leaderboards.top_remixed(prompts)
    assert [(r["path"], r["remixes"], r["title"]) for r in rows] == [
        ("a/original.md", 2, "Title of a/original.md"),
        ("c/other.md", 1, "Title of c/other.md"),
    ]


def test_top_remixed_ignores_deleted_sources_deprecated_and_self_reference():
    prompts = [prompt("a/original.md"),
               prompt("b/gone.md", copied_from="a/deleted.md"),
               prompt("b/old.md", copied_from="a/original.md",
                      status="deprecated"),
               prompt("b/loop.md", copied_from="b/loop.md")]
    assert leaderboards.top_remixed(prompts) == []


# --- join_prompts ------------------------------------------------------------

def test_join_prompts_attaches_titles_and_drops_deleted():
    prompts = [prompt("a/one.md")]
    rows = leaderboards.join_prompts(
        [{"path": "a/deleted.md", "copies": 9}, {"path": "a/one.md", "copies": 3}],
        prompts)
    assert rows == [{"path": "a/one.md", "copies": 3,
                     "title": "Title of a/one.md", "category": "a"}]


def test_join_prompts_limit_applies_after_dropping():
    prompts = [prompt("a/one.md"), prompt("a/two.md")]
    rows = leaderboards.join_prompts(
        [{"path": "a/deleted.md", "copies": 9},
         {"path": "a/one.md", "copies": 3},
         {"path": "a/two.md", "copies": 1}],
        prompts, limit=2)
    assert [r["path"] for r in rows] == ["a/one.md", "a/two.md"]
