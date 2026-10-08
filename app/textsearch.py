"""Whole-repository text search and symbol lookup (the exact-match side of the IDE search panel)."""
from __future__ import annotations
import re
from pathlib import Path

from .ingest import MAX_BYTES

SYMBOL_KINDS = {"function", "method", "class"}


def grep(root: Path, files: list[str], query: str, regex: bool = False, case: bool = False,
         limit: int = 300) -> dict:
    if not query:
        return {"matches": [], "truncated": False, "files": 0}
    flags = 0 if case else re.IGNORECASE
    try:
        pat = re.compile(query if regex else re.escape(query), flags)
    except re.error as e:
        raise ValueError(f"invalid regular expression: {e}")
    matches, files_hit, truncated = [], set(), False
    base = root.resolve()
    for rel in files:
        p = (root / rel).resolve()
        if base not in p.parents or not p.is_file() or p.stat().st_size > MAX_BYTES:
            continue
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for n, line in enumerate(lines, 1):
            m = pat.search(line)
            if m:
                matches.append({"file": rel, "line": n, "col": m.start() + 1, "length": max(m.end() - m.start(), 1),
                                "text": line.strip()[:240]})
                files_hit.add(rel)
                if len(matches) >= limit:
                    truncated = True
                    break
        if truncated:
            break
    return {"matches": matches, "truncated": truncated, "files": len(files_hit)}


def symbols(index, path: str | None = None, q: str | None = None, limit: int = 200) -> list[dict]:
    out = []
    needle = (q or "").lower()
    for c in index.chunks:
        if c.kind not in SYMBOL_KINDS or (path and c.file != path):
            continue
        if needle and needle not in c.qualname.lower():
            continue
        out.append({"name": c.name, "qualname": c.qualname, "kind": c.kind, "file": c.file,
                    "start": c.start, "end": c.end, "route": c.route})
    out.sort(key=lambda s: (s["file"], s["start"]) if path else (s["name"].lower(), s["file"]))
    return out[:limit]
