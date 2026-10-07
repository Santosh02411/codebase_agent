from __future__ import annotations
from ..utils import tokenize

_STOP = {"the", "a", "an", "is", "are", "where", "what", "how", "why", "does", "do", "in", "of", "to", "for",
         "and", "or", "this", "that", "it", "my", "i", "me", "with", "on", "when", "which", "from", "by", "be",
         "get", "getting", "after", "used", "use"}


def rerank(index, query: str, results, top_n: int = 5):
    """Lightweight lexical cross-scorer: query-term coverage + symbol-name match + path match.
    Interface is stable so a cross-encoder / LLM reranker can replace it (Phase 3)."""
    q = {t for t in tokenize(query) if t not in _STOP and len(t) > 1}
    scored = []
    for chunk, fused in results:
        doc = index.token_sets[chunk.id]
        overlap = len(q & doc) / len(q) if q else 0.0
        name_t = {t for t in tokenize(chunk.qualname) if len(t) > 1} if chunk.kind != "module" else set()
        name_hit = len(q & name_t) / len(name_t) if name_t else 0.0
        file_t = set(tokenize(chunk.file))
        file_hit = len(q & file_t) / max(len(file_t), 1)
        scored.append((chunk, 0.4 * fused + 0.4 * overlap + 0.3 * name_hit + 0.15 * file_hit))
    scored.sort(key=lambda x: -x[1])
    return scored[:top_n]
