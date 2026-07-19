"""Prompt path rules. Kept dependency-free so it's trivially unit-testable."""

import posixpath
import re
import unicodedata

EXCLUDED_DIRS = {"_templates"}


def slugify(text: str) -> str:
    """Filename-safe slug: lowercase ascii, words joined by single dashes.
    Returns "" if nothing usable survives (caller decides how to fail)."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def is_valid_prompt_path(path: str) -> bool:
    """Paths come from URLs — accept only clean, relative .md paths inside a
    category folder."""
    if not path.endswith(".md") or path.startswith("/") or "\\" in path or "\x00" in path:
        return False
    if posixpath.normpath(path) != path or ".." in path.split("/"):
        return False
    parts = path.split("/")
    return len(parts) >= 2 and all(parts)


def is_prompt_file(path: str) -> bool:
    """Is this repo file part of the browsable library? Excludes `_templates/`
    and README files."""
    if not is_valid_prompt_path(path):
        return False
    if path.split("/")[0] in EXCLUDED_DIRS:
        return False
    if path.rsplit("/", 1)[-1].lower() == "readme.md":
        return False
    return True
