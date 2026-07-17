"""Path validation — prompt paths arrive from URLs and must stay inside the
repo's category folders."""

from app.paths import is_prompt_file, is_valid_prompt_path


def test_valid_paths():
    assert is_valid_prompt_path("loan-servicing/payment-deferral-explainer.md")
    assert is_valid_prompt_path("customer-support/sub/topic.md")


def test_invalid_paths():
    bad = [
        "README.md",                      # root files are not prompts
        "loan-servicing/../secrets.md",   # traversal
        "../etc/passwd.md",
        "/etc/passwd.md",
        "loan-servicing/file.txt",        # not markdown
        "loan-servicing//double.md",      # empty segment
        "loan-servicing/x.md\x00",        # NUL
        "a\\b.md",                        # backslashes
        "",
    ]
    for path in bad:
        assert not is_valid_prompt_path(path), path


def test_browsable_exclusions():
    assert is_prompt_file("loan-servicing/deferral.md")
    assert not is_prompt_file("_templates/prompt-template.md")  # spec §4
    assert not is_prompt_file("loan-servicing/README.md")
