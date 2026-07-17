"""Tests for the front-matter split — the copy button depends on this being
flawless (spec §4): the body must never include YAML, and must survive odd
files (windows line endings, --- inside the body, missing front-matter)."""

from app.frontmatter import parse_prompt, replace_body, split_front_matter

FULL = """---
title: Payment Deferral Explainer
category: loan-servicing
tags: [loans, customer-facing, deferral]
status: approved
author: jsmith
target_model: internal-chatbot-v1
intended_use: Explain deferral options in plain language to a customer
review_notes: Compliance reviewed 2026-05; no PII, no commitments implied
---

You are a helpful assistant for loan servicing staff.

Explain the available payment deferral options in plain language.
"""


def test_split_returns_body_without_yaml():
    fm, meta, body = split_front_matter(FULL)
    assert meta["title"] == "Payment Deferral Explainer"
    assert meta["tags"] == ["loans", "customer-facing", "deferral"]
    assert body.startswith("You are a helpful assistant")
    assert "---" not in body
    assert "title:" not in body
    assert fm.startswith("---") and fm.endswith("---")


def test_horizontal_rule_in_body_does_not_resplit():
    raw = "---\ntitle: X\n---\n\nPart one.\n\n---\n\nPart two.\n"
    _, meta, body = split_front_matter(raw)
    assert meta == {"title": "X"}
    assert body == "Part one.\n\n---\n\nPart two.\n"


def test_windows_line_endings():
    raw = FULL.replace("\n", "\r\n")
    _, meta, body = split_front_matter(raw)
    assert meta["title"] == "Payment Deferral Explainer"
    assert body.startswith("You are a helpful assistant")
    assert "\r" not in body


def test_no_front_matter_means_whole_file_is_body():
    fm, meta, body = split_front_matter("Just a prompt with no metadata.\n")
    assert fm is None
    assert meta == {}
    assert body == "Just a prompt with no metadata.\n"


def test_unclosed_front_matter_treated_as_body():
    raw = "---\ntitle: Broken\nNo closing delimiter here."
    fm, meta, body = split_front_matter(raw)
    assert fm is None and meta == {}
    assert "title: Broken" in body  # visible, not silently eaten


def test_invalid_yaml_yields_empty_meta_but_correct_body():
    raw = "---\n[unclosed\n---\nThe body.\n"
    _, meta, body = split_front_matter(raw)
    assert meta == {}
    assert body == "The body.\n"


def test_empty_body():
    _, _, body = split_front_matter("---\ntitle: X\n---\n")
    assert body == ""


def test_parse_prompt_fields_and_defaults():
    p = parse_prompt("loan-servicing/payment-deferral-explainer.md", FULL)
    assert p["category"] == "loan-servicing"
    assert p["status"] == "approved"
    assert p["title"] == "Payment Deferral Explainer"
    p2 = parse_prompt("marketing/spring-campaign.md", "No metadata at all.")
    assert p2["title"] == "Spring Campaign"
    assert p2["status"] == "draft"
    assert p2["body"] == "No metadata at all."


def test_replace_body_preserves_front_matter_verbatim():
    new = replace_body(FULL, "A brand new body.\n\nWith two paragraphs.")
    fm_old, _, _ = split_front_matter(FULL)
    fm_new, meta, body = split_front_matter(new)
    assert fm_new == fm_old
    assert meta["review_notes"].startswith("Compliance reviewed")
    assert body == "A brand new body.\n\nWith two paragraphs.\n"


def test_replace_body_without_front_matter():
    assert replace_body("old text", "new text") == "new text\n"
