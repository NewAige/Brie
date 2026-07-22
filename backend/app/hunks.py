"""Split a suggested edit into reviewable hunks, and apply a chosen subset.

Powers partial acceptance in the review flow (routers/pulls.py): a reviewer
may accept some of a suggestion's changes and decline the rest. Everything
here is pure text-to-text — no Gitea, no I/O — mirroring the decide/fetch
split used by ownership.py and roles.py, so it is unit-testable on its own
(tests/test_hunks.py).

Grouping is done here rather than borrowed from difflib's grouped opcodes so
that `split_hunks` (what the reviewer saw) and `apply_hunks` (what gets
published) can never disagree: both derive from the same `_change_groups`.
Hunk indices are deterministic for a given (base, head) pair, which is what
lets the API validate a selection made against an earlier render — callers
pin the exact revisions by sha and recompute.
"""

import difflib
from dataclasses import dataclass

# Unchanged lines shown around each change. Two changes separated by no more
# than 2*CONTEXT unchanged lines fold into one hunk — the standard unified-
# diff rule, so hunks look like the diffs reviewers already see.
CONTEXT = 3


@dataclass(frozen=True)
class Hunk:
    """One independently acceptable change. `lines` are unified-diff style
    (' ', '-', '+' prefixed) for display; `added`/`removed` are line counts."""
    index: int
    lines: tuple[str, ...]
    added: int
    removed: int


def _split(text: str) -> list[str]:
    # split("\n"), not splitlines(): "a\n" -> ["a", ""], so the presence or
    # absence of a trailing newline survives the round-trip through a diff.
    # An empty string means "no file" and contributes no lines at all.
    return text.split("\n") if text else []


def _opcodes(a: list[str], b: list[str]):
    return difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()


def _change_groups(ops) -> list[list[int]]:
    """Indices into `ops` of non-equal opcodes, grouped into hunks.

    Consecutive changes are always separated by exactly one equal run; they
    share a hunk when that run is short enough (<= 2*CONTEXT) that their
    context windows would touch.
    """
    groups: list[list[int]] = []
    for k, (tag, _i1, _i2, _j1, _j2) in enumerate(ops):
        if tag == "equal":
            continue
        if groups:
            gap = sum(op[2] - op[1] for op in ops[groups[-1][-1] + 1:k])
            if gap <= 2 * CONTEXT:
                groups[-1].append(k)
                continue
        groups.append([k])
    return groups


def split_hunks(base: str, head: str) -> list[Hunk]:
    """The changes turning `base` into `head`, as displayable hunks.

    Identical texts yield []. A file that only exists on one side yields a
    single all-added (or all-removed) hunk.
    """
    a, b = _split(base), _split(head)
    ops = _opcodes(a, b)
    hunks = []
    for index, group in enumerate(_change_groups(ops)):
        first, last = ops[group[0]], ops[group[-1]]
        lines: list[str] = []
        lines += [" " + l for l in a[max(first[1] - CONTEXT, 0):first[1]]]
        added = removed = 0
        for k in range(group[0], group[-1] + 1):
            tag, i1, i2, j1, j2 = ops[k]
            if tag == "equal":
                lines += [" " + l for l in a[i1:i2]]
            else:
                lines += ["-" + l for l in a[i1:i2]]
                lines += ["+" + l for l in b[j1:j2]]
                removed += i2 - i1
                added += j2 - j1
        lines += [" " + l for l in a[last[2]:min(last[2] + CONTEXT, len(a))]]
        hunks.append(Hunk(index, tuple(lines), added, removed))
    return hunks


def apply_hunks(base: str, head: str, selected: set[int]) -> str:
    """`base` with only the selected hunks (indices from `split_hunks` on the
    same pair) applied. Selecting every hunk reproduces `head` exactly;
    selecting none reproduces `base`. Unknown indices are simply inert —
    callers validate them against `len(split_hunks(...))` for a real error.
    """
    a, b = _split(base), _split(head)
    ops = _opcodes(a, b)
    take_head: set[int] = set()
    for index, group in enumerate(_change_groups(ops)):
        if index in selected:
            take_head.update(group)
    out: list[str] = []
    for k, (tag, i1, i2, j1, j2) in enumerate(ops):
        out += b[j1:j2] if k in take_head else a[i1:i2]
    return "\n".join(out)
