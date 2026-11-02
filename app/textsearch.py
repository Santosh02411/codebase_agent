"""Whole-repository text search and symbol lookup (the exact-match side of the IDE search panel)."""
from __future__ import annotations
import re
from pathlib import Path

from .ingest import MAX_BYTES
from .intel.model import SYMBOL_KINDS

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
    """Functions, methods, classes, interfaces, structs, enums and traits (variables excluded)."""
    out = []
    needle = (q or "").lower()
    for s in index.graph.symbols.values():
        if s.kind not in SYMBOL_KINDS or (path and s.file != path):
            continue
        if needle and needle not in s.qualname.lower():
            continue
        out.append({"id": s.id, "name": s.name, "qualname": s.qualname, "kind": s.kind, "file": s.file, "start": s.start, "end": s.end,
                    "route": s.route, "signature": s.signature, "doc": s.doc, "parent": s.parent})
    out.sort(key=lambda x: (x["file"], x["start"]) if path else (x["name"].lower(), x["file"]))
    return out[:limit]
