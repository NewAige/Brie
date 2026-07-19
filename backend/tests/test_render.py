"""Tests for new-prompt creation building blocks: slugify and render_prompt.

render_prompt must round-trip through split_front_matter/parse_prompt — a
file the app writes must be a file the app (and the copy button) can read
back perfectly.
"""

from app.frontmatter import parse_prompt, render_prompt, split_front_matter
from app.paths import slugify


def test_slugify_basic():
    assert slugify("Customer Refund Email") == "customer-refund-email"
    assert slugify("  EMEA -- Outreach!! ") == "emea-outreach"
    assert slugify("Café Décor") == "cafe-decor"


def test_slugify_unusable_input_returns_empty():
    assert slugify("!!!") == ""
    assert slugify("") == ""


def test_render_round_trips_through_parser():
    content = render_prompt({
        "title": "Refund Email: EMEA edition",
        "category": "support",
        "tags": ["support", "emea"],
        "status": "draft",
        "author": "avogel",
        "owner": "avogel",
        "target_model": "",
        "intended_use": "When replying to refund requests",
        "copied_from": "support/refund-email.md",
    }, "Dear [CUSTOMER NAME],\n\nWe processed your refund.\n")

    fm, meta, body = split_front_matter(content)
    assert fm.startswith("---") and fm.endswith("---")
    # The colon in the title must survive YAML round-trip.
    assert meta["title"] == "Refund Email: EMEA edition"
    assert meta["tags"] == ["support", "emea"]
    assert meta["owner"] == "avogel"
    assert meta["copied_from"] == "support/refund-email.md"
    # Empty target_model was omitted entirely.
    assert "target_model" not in meta
    assert body == "Dear [CUSTOMER NAME],\n\nWe processed your refund.\n"

    parsed = parse_prompt("support/refund-email-emea-edition.md", content)
    assert parsed["owner"] == "avogel"
    assert parsed["copied_from"] == "support/refund-email.md"
    assert parsed["status"] == "draft"


def test_render_collapses_newlines_in_single_line_fields():
    content = render_prompt({
        "title": "X",
        "category": "ops",
        "intended_use": "line one\nline two",
    }, "Body.")
    _, meta, body = split_front_matter(content)
    assert meta["intended_use"] == "line one line two"
    assert body == "Body.\n"


def test_render_windows_line_endings_in_body():
    content = render_prompt({"title": "X", "category": "ops"},
                            "Line one.\r\nLine two.\r\n")
    _, _, body = split_front_matter(content)
    assert body == "Line one.\nLine two.\n"
