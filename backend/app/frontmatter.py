"""YAML front-matter parsing.

The copy button copies ONLY the body below the closing `---` (spec §4,
"Critical"). This module is the single place that split happens, and it is
unit-tested in tests/test_frontmatter.py.
"""

import yaml

DELIMITER = "---"


def split_front_matter(raw: str) -> tuple[str | None, dict, str]:
    """Split a prompt file into (front_matter_block, metadata, body).

    - front_matter_block is the raw text INCLUDING both `---` delimiter lines
      (or None if the file has no front-matter). Kept verbatim so "suggest an
      edit" can replace the body without reformatting the YAML.
    - metadata is the parsed YAML mapping ({} if absent or invalid).
    - body is everything below the closing delimiter, with leading blank lines
      stripped. A `---` later in the body (e.g. a markdown horizontal rule)
      does NOT re-split: only the first closing delimiter counts.
    """
    # Normalize line endings so files authored on Windows behave identically.
    text = raw.replace("\r\n", "\n").replace("\r", "\n")

    lines = text.split("\n")
    if not lines or lines[0].strip() != DELIMITER:
        return None, {}, text.lstrip("\n")

    for i in range(1, len(lines)):
        if lines[i].strip() == DELIMITER:
            fm_block = "\n".join(lines[: i + 1])
            body = "\n".join(lines[i + 1:]).lstrip("\n")
            yaml_source = "\n".join(lines[1:i])
            try:
                meta = yaml.safe_load(yaml_source)
            except yaml.YAMLError:
                meta = None
            if not isinstance(meta, dict):
                meta = {}
            return fm_block, meta, body

    # Opening delimiter but no closing one: treat the whole file as body so a
    # malformed file can never leak "YAML-looking" text into a copy silently.
    return None, {}, text.lstrip("\n")


def parse_prompt(path: str, raw: str) -> dict:
    """Parse one prompt file into the structure the API returns."""
    fm_block, meta, body = split_front_matter(raw)
    category = path.split("/")[0] if "/" in path else ""
    tags = meta.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    return {
        "path": path,
        "category": category,
        "title": str(meta.get("title") or _title_from_path(path)),
        "tags": [str(t) for t in tags],
        "status": str(meta.get("status") or "draft"),
        "author": str(meta.get("author") or ""),
        "owner": str(meta.get("owner") or ""),
        "copied_from": str(meta.get("copied_from") or ""),
        "target_model": str(meta.get("target_model") or ""),
        "intended_use": str(meta.get("intended_use") or ""),
        "review_notes": str(meta.get("review_notes") or ""),
        "front_matter": fm_block,
        "body": body,
    }


def replace_body(raw: str, new_body: str) -> str:
    """Return the file content with the body replaced and the original
    front-matter block preserved byte-for-byte."""
    fm_block, _meta, _body = split_front_matter(raw)
    new_body = new_body.replace("\r\n", "\n").strip("\n")
    if fm_block is None:
        return new_body + "\n"
    return f"{fm_block}\n\n{new_body}\n"


def render_prompt(meta: dict, body: str) -> str:
    """Render a brand-new prompt file: front-matter block + body.

    Field order follows _templates/prompt-template.md. Empty values are
    omitted. Values are emitted through yaml.safe_dump per key so titles
    containing `:` or quotes stay valid YAML — except lists, which are
    rendered flow-style (`[a, b]`) to match the hand-authored files; list
    items are expected to be pre-slugified by the caller.
    """
    lines = [DELIMITER]
    for key, value in meta.items():
        if value is None or value == "" or value == []:
            continue
        if isinstance(value, list):
            lines.append(f"{key}: [{', '.join(value)}]")
        else:
            # Single-line fields only: collapse any stray newlines.
            value = " ".join(str(value).split())
            lines.append(yaml.safe_dump({key: value}, allow_unicode=True,
                                        width=100000).strip())
    lines.append(DELIMITER)
    return "\n".join(lines) + "\n\n" + body.replace("\r\n", "\n").strip("\n") + "\n"


def _title_from_path(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    if name.endswith(".md"):
        name = name[:-3]
    return name.replace("-", " ").replace("_", " ").title()
