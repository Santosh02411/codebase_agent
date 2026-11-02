"""Chunks follow the code's own structure: one per function/method, one header per class, one for module-level code."""
from __future__ import annotations
import re

from ..parsing.chunker import Chunk, chunk_windows
from .model import SYMBOL_KINDS, FileFacts

_COMMENT_LINE = re.compile(r"^\s*(//|/\*|\*|#|--|///)")
CLASS_LIKE = {"class", "interface", "struct", "enum", "trait", "type"}


def _with_leading_comments(lines: list[str], start: int, floor: int) -> int:
    s = start
    while s - 1 > floor and s - 2 >= 0 and _COMMENT_LINE.match(lines[s - 2]) and start - s < 15:
        s -= 1
    return s


def chunks_for(facts: FileFacts, text: str) -> list[Chunk]:
    lines = text.splitlines()
    if not text.strip():
        return []
    syms = [s for s in facts.symbols if s.kind in SYMBOL_KINDS and s.start >= 1 and s.end >= s.start]
    if not syms:
        size = 40 if facts.language == "markdown" else 50
        return chunk_windows(facts.path, text, facts.language, size=size)
    members: dict[str, list] = {}
    for s in syms:
        if s.parent:
            members.setdefault(s.parent, []).append(s)
    out: list[Chunk] = []
    covered: set[int] = set()
    prev_end = 0
    for s in sorted(syms, key=lambda x: (x.start, -x.end)):
        end = s.end
        if s.kind in CLASS_LIKE:
            kids = [m for m in members.get(s.qualname, []) if m.kind in ("function", "method")]
            first = min((k.start for k in kids), default=0)
            end = min(first - 1, s.end) if first and first > s.start else s.end
            end = min(end, s.start + (59 if kids else 79))
        start = _with_leading_comments(lines, s.start, prev_end if s.kind not in CLASS_LIKE else 0)
        body = "\n".join(lines[start - 1:end])
        kind = "class" if s.kind in CLASS_LIKE else s.kind
        out.append(Chunk(-1, facts.path, kind, s.name, s.qualname, start, end, body, facts.language,
                         [c.split(".")[-1] for c in s.calls], s.route, s.id, s.signature, s.doc))
        covered.update(range(start, end + 1))
        if s.kind in ("function", "method"):
            prev_end = max(prev_end, s.end)
    rest = [i for i in range(1, len(lines) + 1) if i not in covered and lines[i - 1].strip()]
    if rest:
        body = "\n".join(lines[i - 1] for i in rest[:120])
        out.append(Chunk(-1, facts.path, "module", "<module>", facts.path, rest[0], rest[-1], body, facts.language))
    return out
