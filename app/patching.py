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


# ---- multi-file changes: several edits + brand-new files, validated together before anything is written ----
def plan_changes(root: Path, edits: list[dict] | None, new_files: list[dict] | None) -> dict[str, tuple[str, str]]:
    """Dry run. Returns {path: (old_text, new_text)} or raises ValueError. Edits to one file apply in order."""
    files: dict[str, list[str]] = {}
    for e in edits or []:
        f = e.get("file")
        if not f or not e.get("search"):
            raise ValueError("edit is missing file/search")
        p = safe_path(root, f)
        if f not in files:
            if not p.is_file():
                raise ValueError(f"file not found: {f}")
            old = p.read_text(encoding="utf-8")
            files[f] = [old, old]
        n = files[f][1].count(e["search"])
        if n != 1:
            raise ValueError(f"`search` text in {f} must match exactly once (found {n})")
        files[f][1] = files[f][1].replace(e["search"], e.get("replace", ""), 1)
    for nf in new_files or []:
        f = nf.get("path")
        if not f or not isinstance(nf.get("content"), str):
            raise ValueError("new file needs a path and content")
        if f in files or safe_path(root, f).exists():
            raise ValueError(f"file already exists: {f}")
        files[f] = ["", nf["content"]]
    if not files:
        raise ValueError("no changes proposed")
    return {k: (v[0], v[1]) for k, v in files.items()}


def apply_changes(root: Path, edits: list[dict] | None, new_files: list[dict] | None) -> list[str]:
    plan = plan_changes(root, edits, new_files)
    for f, (_, new) in plan.items():
        p = safe_path(root, f)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(new, encoding="utf-8")
    return list(plan)


def changes_diff(plan: dict[str, tuple[str, str]]) -> str:
    return "".join("".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                                f"a/{f}" if old else "/dev/null", f"b/{f}"))
                   for f, (old, new) in plan.items())
