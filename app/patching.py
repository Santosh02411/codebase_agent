"""Compatibility layer over the patch engine (app/patchset.py): the older edit / change helpers, now with the engine's safety and
fidelity (whitespace-tolerant matching, EOL/BOM preservation, syntax checks, atomic writes)."""
from __future__ import annotations
from pathlib import Path

from .patchset import PatchError, PatchSet, PatchSpec, apply_patchset, build_patchset  # noqa: F401  (re-exported)


def validate_edit(root: Path, edit: dict) -> tuple[bool, str]:
    """An edit is {file, search, replace}: `search` must occur exactly once in `file`."""
    if not edit or not edit.get("file") or not edit.get("search"):
        return False, "edit is missing file/search"
    try:
        build_patchset(root, PatchSpec(edits=[edit]), allow_noop=True)
    except PatchError as e:
        return False, str(e)
    return True, ""


def apply_edit(root: Path, edit: dict) -> str:
    ps = build_patchset(root, PatchSpec(edits=[edit]), allow_noop=True)
    apply_patchset(root, ps)
    return ps.changes[0].new or ""


def make_diff(root: Path, edit: dict) -> str:
    return build_patchset(root, PatchSpec(edits=[edit]), allow_noop=True).diff


def plan_changes(root: Path, edits: list[dict] | None, new_files: list[dict] | None, delete_files: list[str] | None = None) -> dict[str, tuple[str, str]]:
    """Dry run. Returns {path: (old_text, new_text)} or raises ValueError. Deleted files map to (old_text, "")."""
    ps = build_patchset(root, PatchSpec(edits=edits or [], new_files=new_files or [], delete_files=delete_files or []), allow_noop=True)
    return {c.path: (c.old or "", c.new or "") for c in ps.changes}


def apply_changes(root: Path, edits: list[dict] | None, new_files: list[dict] | None, delete_files: list[str] | None = None) -> list[str]:
    ps = build_patchset(root, PatchSpec(edits=edits or [], new_files=new_files or [], delete_files=delete_files or []), allow_noop=True)
    apply_patchset(root, ps, verify_base=False)
    return ps.paths


def apply_spec(root: Path, spec: dict) -> list[str]:
    """Apply any patch spec (edits / unified_diff / rewrites / new_files / delete_files) to a directory. Used on sandbox copies."""
    ps = build_patchset(root, PatchSpec.from_dict(spec), allow_noop=True)
    apply_patchset(root, ps, verify_base=False)
    return ps.paths


def changes_diff(plan: dict[str, tuple[str, str]]) -> str:
    from .patchset import unified
    return "".join(unified(old if old else None, new, f)[0] for f, (old, new) in plan.items())
