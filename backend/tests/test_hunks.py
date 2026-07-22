"""Pure hunk splitting/applying (app/hunks.py) — the engine behind accepting
only some of a suggestion's edits. The critical properties: what is shown is
what gets applied, all-selected == suggestion, none-selected == unchanged."""

from app import hunks

BASE = "\n".join([
    "line 1", "line 2", "line 3", "line 4", "line 5",
    "line 6", "line 7", "line 8", "line 9", "line 10",
    "line 11", "line 12", "line 13", "line 14", "line 15",
]) + "\n"

# Two edits far enough apart (> 2*CONTEXT unchanged lines) to be two hunks:
# a rewrite of line 2 and an insertion after line 12.
HEAD = BASE.replace("line 2", "LINE TWO").replace(
    "line 12\n", "line 12\nline 12.5\n")


def test_identical_texts_have_no_hunks():
    assert hunks.split_hunks(BASE, BASE) == []
    assert hunks.apply_hunks(BASE, BASE, set()) == BASE


def test_far_apart_edits_are_separate_hunks():
    assert len(hunks.split_hunks(BASE, HEAD)) == 2


def test_select_all_reproduces_head():
    assert hunks.apply_hunks(BASE, HEAD, {0, 1}) == HEAD


def test_select_none_reproduces_base():
    assert hunks.apply_hunks(BASE, HEAD, set()) == BASE


def test_each_hunk_applies_independently():
    only_first = hunks.apply_hunks(BASE, HEAD, {0})
    assert "LINE TWO" in only_first and "line 12.5" not in only_first
    only_second = hunks.apply_hunks(BASE, HEAD, {1})
    assert "LINE TWO" not in only_second and "line 12.5" in only_second


def test_nearby_edits_fold_into_one_hunk():
    close = BASE.replace("line 2", "LINE TWO").replace("line 4", "LINE FOUR")
    assert len(hunks.split_hunks(BASE, close)) == 1


def test_unknown_indices_are_inert():
    assert hunks.apply_hunks(BASE, HEAD, {7}) == BASE


def test_new_file_is_one_all_added_hunk():
    got = hunks.split_hunks("", "new\ncontent\n")
    assert len(got) == 1
    assert got[0].removed == 0 and got[0].added == 3  # incl. trailing blank
    assert hunks.apply_hunks("", "new\ncontent\n", {0}) == "new\ncontent\n"
    assert hunks.apply_hunks("", "new\ncontent\n", set()) == ""


def test_deleted_file_is_one_all_removed_hunk():
    got = hunks.split_hunks("old\ncontent\n", "")
    assert len(got) == 1
    assert got[0].added == 0
    assert hunks.apply_hunks("old\ncontent\n", "", {0}) == ""
    assert hunks.apply_hunks("old\ncontent\n", "", set()) == "old\ncontent\n"


def test_display_lines_use_diff_prefixes():
    (hunk,) = hunks.split_hunks(BASE, BASE.replace("line 8", "LINE EIGHT"))
    assert "-line 8" in hunk.lines
    assert "+LINE EIGHT" in hunk.lines
    context = [l for l in hunk.lines if l.startswith(" ")]
    assert len(context) == 2 * hunks.CONTEXT  # three lines each side
    assert hunk.added == 1 and hunk.removed == 1


def test_trailing_newline_changes_survive_the_round_trip():
    assert hunks.apply_hunks("a\nb", "a\nb\n", {0}) == "a\nb\n"
    assert hunks.apply_hunks("a\nb\n", "a\nb", {0}) == "a\nb"


def test_hunks_are_deterministic_for_the_same_pair():
    assert hunks.split_hunks(BASE, HEAD) == hunks.split_hunks(BASE, HEAD)
