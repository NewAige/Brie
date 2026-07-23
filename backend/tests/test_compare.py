"""Tests for compare_file — the pure half of GET /pulls/{id}/compare.

The side-by-side view exists so a reviewer can read and copy either version
of a prompt to test it externally before deciding. The copy contract is the
same as the copy button's (spec §4): bodies only, never YAML — so these tests
lean on the same odd-file cases test_frontmatter.py covers.
"""

from app.routers.pulls import compare_file

BASE = """---
title: Payment Deferral Explainer
level: community
---

You are a helpful assistant for loan servicing staff.
"""

HEAD = """---
title: Payment Deferral Explainer
level: community
---

You are a precise assistant for loan servicing staff.

Always answer in plain language.
"""


def test_changed_file_carries_both_bodies_without_yaml():
    out = compare_file("loan-servicing/deferral.md", BASE, HEAD)
    assert out["status"] == "changed"
    assert out["current"]["body"].startswith("You are a helpful assistant")
    assert out["suggested"]["body"].startswith("You are a precise assistant")
    for side in (out["current"], out["suggested"]):
        assert "title:" not in side["body"]
        assert "---" not in side["body"]
    assert out["details_changed"] is False


def test_front_matter_edit_is_flagged_not_shown():
    head = HEAD.replace("title: Payment Deferral Explainer",
                        "title: Deferral Options Explainer")
    out = compare_file("p.md", BASE, head)
    assert out["details_changed"] is True
    assert "Deferral Options" not in out["suggested"]["body"]


def test_new_prompt_has_no_current_side():
    out = compare_file("p.md", None, HEAD)
    assert out["status"] == "added"
    assert out["current"] is None
    assert out["suggested"]["body"].startswith("You are a precise assistant")
    assert out["details_changed"] is False


def test_removed_prompt_has_no_suggested_side():
    out = compare_file("p.md", BASE, None)
    assert out["status"] == "removed"
    assert out["suggested"] is None
    assert out["current"]["body"].startswith("You are a helpful assistant")
    assert out["details_changed"] is False


def test_file_without_front_matter_is_all_body():
    out = compare_file("p.md", "Just text.\n", "Just better text.\n")
    assert out["current"]["body"] == "Just text.\n"
    assert out["suggested"]["body"] == "Just better text.\n"
    assert out["details_changed"] is False


def test_unclosed_front_matter_never_leaks_yaml_silently():
    # split_front_matter treats an unclosed block as body; adding a proper
    # block is then a front-matter change plus a body change, both visible.
    broken = "---\ntitle: X\n\nBody under broken yaml.\n"
    out = compare_file("p.md", broken, HEAD)
    assert out["current"]["body"] == broken
    assert out["details_changed"] is True
