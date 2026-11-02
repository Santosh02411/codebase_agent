"""Context construction and citations.

build_pack():  rank-ordered chunks -> a token-budgeted, de-duplicated, numbered context block ("[1] file:lines symbol ...")
extract_citations(): validates the [n] markers the LLM wrote against what it was actually shown."""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from functools import lru_cache

from ..intel.model import language_of

CITATION_RULES = ("Cite the snippets you rely on with their bracketed number, e.g. [2] or [1][3]. "
                  "Never cite a number that is not listed above. If the snippets do not contain the answer, say so.")


@lru_cache(maxsize=1)
def _tiktoken():
    try:
        import tiktoken
        return tiktoken.get_encoding("cl100k_base")
    except Exception:  # noqa: BLE001 - optional dependency, or its vocabulary file can't be downloaded offline
        return None


def estimate_tokens(text: str) -> int:
    """Token count: exact with tiktoken when available, otherwise ~3.5 characters per token (typical for source code)."""
    enc = _tiktoken()
    return len(enc.encode(text, disallowed_special=())) if enc else int(len(text) / 3.5) + 1


@dataclass
class CtxItem:
    cite: int
    chunk: dict
    tokens: int
    truncated: bool = False


@dataclass
class ContextPack:
    items: list[CtxItem]
    tokens: int
    budget: int
    dropped: list[dict] = field(default_factory=list)   # [{file, qualname, reason}]

    def chunks(self) -> list[dict]:
        """The kept chunks in citation order (text already truncated to what is rendered)."""
        return [i.chunk for i in self.items]

    def render(self, max_chars: int = 12000) -> str:
        return render_blocks(self.chunks(), max_chars)

    def sources(self, cited: set[int] | None = None) -> list[dict]:
        out = [{"file": i.chunk["file"], "lines": f"{i.chunk['start']}-{i.chunk['end']}", "symbol": i.chunk["qualname"], "cite": i.cite,
                "cited": bool(cited and i.cite in cited)} for i in self.items]
        return sorted(out, key=lambda s: (not s["cited"], s["cite"]))


def render_blocks(chunks: list[dict], max_chars: int = 3500) -> str:
    parts = []
    for n, c in enumerate(chunks, 1):
        route = f" · {c['route']}" if c.get("route") else ""
        kind = f" ({c['kind']})" if c.get("kind") and c["kind"] != "module" else ""
        sym = f" {c['qualname']}{kind}" if c.get("kind") != "module" else ""
        parts.append(f"[{n}] {c['file']}:{c['start']}-{c['end']}{sym}{route}\n```{language_of(c['file'])}\n{c['text'][:max_chars]}\n```")
    return "\n\n".join(parts)


def _overlap(a: dict, b: dict) -> float:
    if a["file"] != b["file"]:
        return 0.0
    lo, hi = max(a["start"], b["start"]), min(a["end"], b["end"])
    if hi < lo:
        return 0.0
    return (hi - lo + 1) / max(1, min(a["end"] - a["start"] + 1, b["end"] - b["start"] + 1))


def _cut(text: str, max_tokens: int) -> str:
    lines, keep, used = text.splitlines(), [], 0
    for ln in lines:
        t = estimate_tokens(ln) + 1
        if used + t > max_tokens:
            break
        keep.append(ln); used += t
    return "\n".join(keep) + "\n# ... (truncated)"


def build_pack(chunks: list[dict], budget: int = 6000, *, max_per_file: int = 4, overlap: float = 0.5, min_fragment: int = 150) -> ContextPack:
    """Greedy, rank-ordered packing under a token budget.
      1. drop chunks that mostly overlap a better-ranked chunk of the same file
      2. cap chunks per file in the first pass so one file can't crowd out the rest (leftover budget re-admits them)
      3. truncate the last chunk that doesn't fit if at least `min_fragment` tokens remain; otherwise skip it and try smaller ones"""
    kept: list[dict] = []
    dropped: list[dict] = []
    for c in chunks:
        if any(_overlap(c, k) >= overlap for k in kept):
            dropped.append({"file": c["file"], "qualname": c["qualname"], "reason": "overlaps a better-ranked chunk"})
        else:
            kept.append(c)
    chosen: list[tuple[int, dict, int, bool]] = []
    used, per_file = 0, {}
    deferred: list[tuple[int, dict]] = []

    def admit(rank: int, c: dict) -> bool:
        nonlocal used
        tok = estimate_tokens(c["text"]) + 12
        room = budget - used
        if tok <= room:
            chosen.append((rank, c, tok, False)); used += tok
            return True
        if room >= min_fragment:
            cut = dict(c, text=_cut(c["text"], room - 12), truncated=True)
            tcut = estimate_tokens(cut["text"]) + 12
            chosen.append((rank, cut, tcut, True)); used += tcut
            return True
        dropped.append({"file": c["file"], "qualname": c["qualname"], "reason": "token budget"})
        return False

    for rank, c in enumerate(kept):
        if per_file.get(c["file"], 0) >= max_per_file:
            deferred.append((rank, c)); continue
        if admit(rank, c):
            per_file[c["file"]] = per_file.get(c["file"], 0) + 1
    for rank, c in deferred:
        if not admit(rank, c):
            continue
    chosen.sort(key=lambda x: x[0])
    items = [CtxItem(n, c, t, tr) for n, (_, c, t, tr) in enumerate(chosen, 1)]
    return ContextPack(items, used, budget, dropped)


_FENCE = re.compile(r"```.*?```|`[^`\n]*`", re.S)
_MARK = re.compile(r"\[(\d{1,3}(?:\s*[,;]\s*\d{1,3})*)\]")


def extract_citations(text: str, n_items: int) -> dict:
    """Which of the [1]..[n] snippets did the answer cite? `invalid` lists numbers that were never shown to the model
    (a sign of fabricated support). Code spans are ignored so `items[1]` isn't mistaken for a citation."""
    cited: list[int] = []
    invalid: list[int] = []
    for m in _MARK.finditer(_FENCE.sub("", text or "")):
        for num in re.split(r"\s*[,;]\s*", m.group(1)):
            n = int(num)
            bucket = cited if 1 <= n <= n_items else invalid
            if n not in bucket:
                bucket.append(n)
    return {"cited": sorted(cited), "invalid": sorted(invalid)}
