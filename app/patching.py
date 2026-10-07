from __future__ import annotations
import difflib
from pathlib import Path

from .utils import safe_path


def validate_edit(root: Path, edit: dict) -> tuple[bool, str]:
    """An edit is {file, search, replace}: `search` must occur exactly once in `file`."""
    if not edit or not edit.get("file") or not edit.get("search"):
        return False, "edit is missing file/search"
    try:
        p = safe_path(root, edit["file"])
    except ValueError as e:
        return False, str(e)
    if not p.is_file():
        return False, f"file not found: {edit['file']}"
    n = p.read_text(encoding="utf-8").count(edit["search"])
    if n != 1:
        return False, f"`search` text must match exactly once (found {n})"
    return True, ""


def apply_edit(root: Path, edit: dict) -> str:
    ok, err = validate_edit(root, edit)
    if not ok:
        raise ValueError(err)
    p = safe_path(root, edit["file"])
    new = p.read_text(encoding="utf-8").replace(edit["search"], edit.get("replace", ""), 1)
    p.write_text(new, encoding="utf-8")
    return new


def make_diff(root: Path, edit: dict) -> str:
    p = safe_path(root, edit["file"])
    old = p.read_text(encoding="utf-8")
    new = old.replace(edit["search"], edit.get("replace", ""), 1)
    return "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                        f"a/{edit['file']}", f"b/{edit['file']}"))
