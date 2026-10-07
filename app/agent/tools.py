from __future__ import annotations
from pathlib import Path

from .. import sandbox
from ..retrieval.index import CodeIndex
from ..retrieval.reranker import rerank
from ..utils import safe_path


def chunk_dict(c, score: float | None = None, via: str = "search") -> dict:
    d = {"id": c.id, "file": c.file, "kind": c.kind, "name": c.name, "qualname": c.qualname,
         "start": c.start, "end": c.end, "text": c.text, "via": via}
    if score is not None:
        d["score"] = round(float(score), 3)
    return d


class RepoTools:
    """Tools the agent can call. Each is a plain method so they can also be exposed as LLM function-calls."""

    def __init__(self, root: Path, index: CodeIndex, test_timeout: int = 120) -> None:
        self.root, self.index, self.test_timeout = root, index, test_timeout

    def search_code(self, query: str, k: int = 5, candidates: int = 20) -> list[dict]:
        hits = rerank(self.index, query, self.index.search(query, k=candidates), top_n=k)
        return [chunk_dict(c, s) for c, s in hits]

    def related(self, chunk_id: int) -> list[dict]:
        c = self.index.chunks[chunk_id]
        return ([chunk_dict(x, via="callee") for x in self.index.callees(c)]
                + [chunk_dict(x, via="caller") for x in self.index.callers(c)])

    def read_file(self, path: str, start: int | None = None, end: int | None = None) -> str:
        lines = safe_path(self.root, path).read_text(encoding="utf-8").splitlines()
        s = (start or 1) - 1
        return "\n".join(lines[s : end or len(lines)])

    def find_symbol(self, name: str) -> list[dict]:
        return [chunk_dict(c, via="symbol") for c in self.index.by_name.get(name, [])]

    def list_tree(self, max_lines: int = 80) -> str:
        t = self.index.tree
        return "\n".join(t[:max_lines]) + (f"\n... (+{len(t) - max_lines} more files)" if len(t) > max_lines else "")

    def get_dependencies(self, path: str | None = None) -> dict:
        if path is None:
            return self.index.deps
        mods = self.index.imports.get(path, [])
        tree = set(self.index.tree)
        internal = []
        for m in mods:
            for cand in (m.replace(".", "/") + ".py", m.replace(".", "/") + "/__init__.py"):
                if cand in tree:
                    internal.append(cand)
        return {"imports": mods, "internal_files": internal}

    def run_tests(self) -> dict:
        work = sandbox.copy_repo(self.root)
        try:
            return sandbox.run_tests(work, self.test_timeout)
        finally:
            sandbox.cleanup(work)
