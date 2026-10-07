from __future__ import annotations
from pathlib import PurePosixPath
from ..utils import tokenize

_STOP = {"the", "a", "an", "is", "are", "where", "what", "how", "why", "does", "do", "in", "of", "to", "for",
         "and", "or", "this", "that", "it", "my", "i", "me", "with", "on", "when", "which", "from", "by", "be",
         "get", "getting", "after", "used", "use", "am", "walk", "through"}
_DOC_WORDS = {"readme", "docs", "doc", "documentation", "guide", "changelog", "markdown", "workflow", "log"}
_TEST_WORDS = {"test", "tests", "pytest", "spec", "fixture", "fixtures"}
_CFG_WORDS = {"config", "configuration", "docker", "dockerfile", "deploy", "deployment", "ci", "pipeline",
              "dependency", "dependencies", "requirements", "package", "settings", "env", "workflow"}
_ENDPOINT_WORDS = {"endpoint", "route", "api", "request", "handled", "handler", "http", "500", "handl"}
_KIND_W = {"function": 1.0, "method": 1.0, "class": 0.9, "module": 0.7, "block": 0.55}
_BACKEND_WORDS = {"backend", "endpoint", "api", "route", "server", "database", "db", "model", "service"}
_FRONTEND_WORDS = {"ui", "page", "component", "screen", "button", "frontend", "react", "view", "mobile"}
_METHODS = {"get", "post", "put", "patch", "delete"}
_WRITE = ("creat", "add", "submit", "new", "regist", "insert", "save")
_READ = ("list", "fetch", "show", "retriev", "read")


def _category(file: str) -> str:
    p = PurePosixPath(file)
    name, ext = p.name.lower(), p.suffix.lower()
    if ext in (".md", ".txt", ".rst") and name != "requirements.txt" or file.startswith("docs/"):
        return "doc"
    if "tests/" in file or "/test_" in file or name.startswith("test_") or ".test." in name or ".spec." in name:
        return "test"
    if ext in (".json", ".yml", ".yaml", ".toml", ".ini", ".cfg") or name in ("dockerfile", "requirements.txt", "makefile") or file.startswith(".github/"):
        return "config"
    return "code"


def rerank(index, query: str, results, top_n: int = 5):
    """Lightweight lexical cross-scorer: term coverage + symbol/path/route match, with priors that favour
    real code (functions, handlers) over docs, tests and config unless the question asks for them.
    Interface is stable so a cross-encoder / LLM reranker can replace it (Phase 3)."""
    qtoks = set(tokenize(query))
    q = {t for t in qtoks if t not in _STOP and len(t) > 1}
    endpointish = bool(qtoks & _ENDPOINT_WORDS)
    writes = any(t.startswith(_WRITE) for t in qtoks)
    reads = any(t.startswith(_READ) for t in qtoks)
    mult = {"doc": 1.5 if qtoks & _DOC_WORDS else 0.45,
            "test": 1.0 if qtoks & _TEST_WORDS else 0.6,
            "config": 1.0 if qtoks & _CFG_WORDS else 0.5, "code": 1.0}
    scored = []
    for chunk, fused in results:
        doc = index.token_sets[chunk.id]
        overlap = len(q & doc) / len(q) if q else 0.0
        name_t = {t for t in tokenize(chunk.qualname) if len(t) > 1} if chunk.kind != "module" else set()
        name_hit = len(q & name_t) / len(name_t) if name_t else 0.0
        file_t = set(tokenize(chunk.file))
        file_hit = len(q & file_t) / max(len(file_t), 1)
        score = 0.4 * fused + 0.4 * overlap + 0.3 * name_hit + 0.15 * file_hit
        if chunk.route:  # HTTP handlers are the entry point for most "where is X handled" questions
            rt = {t for t in tokenize(chunk.route) if t not in _METHODS}
            score += 0.35 * (len(q & rt) / max(len(rt), 1)) + (0.1 if endpointish else 0.0)
            method = chunk.route.split()[0].lower()
            if qtoks & _METHODS and method in qtoks:
                score += 0.1
            if (method == "post" and writes) or (method == "get" and reads):
                score += 0.1
        if chunk.kind == "module":  # mostly-import blocks say little about behaviour
            ls = [l for l in chunk.text.splitlines() if l.strip()]
            if ls and sum(l.lstrip().startswith(("import ", "from ", "const ", "export {")) for l in ls) / len(ls) > 0.5:
                score *= 0.6
        top = chunk.file.split("/")[0]
        if qtoks & _BACKEND_WORDS and not qtoks & _FRONTEND_WORDS:
            score *= 1.15 if top == "backend" else 0.85 if top in ("frontend", "mobile") else 1.0
        elif qtoks & _FRONTEND_WORDS and not qtoks & _BACKEND_WORDS:
            score *= 1.15 if top in ("frontend", "mobile") else 0.85 if top == "backend" else 1.0
        cat = _category(chunk.file)
        score *= (1.0 if cat == "doc" else _KIND_W.get(chunk.kind, 0.7)) * mult[cat]
        scored.append((chunk, score))
    scored.sort(key=lambda x: -x[1])
    return scored[:top_n]
