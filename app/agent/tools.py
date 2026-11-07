from __future__ import annotations
from pathlib import Path

from .. import lint as lint_mod
from .. import patching, sandbox
from ..config import get_settings
from ..patchset import PatchError, PatchSpec, build_patchset
from ..retrieval.index import CodeIndex
from ..utils import safe_path
from . import extras
from .. import git_intel


def chunk_dict(c, score: float | None = None, via: str = "search", why: str = "") -> dict:
    d = {"id": c.id, "file": c.file, "kind": c.kind, "name": c.name, "qualname": c.qualname,
         "start": c.start, "end": c.end, "text": c.text, "via": via, "route": c.route}
    if score is not None:
        d["score"] = round(float(score), 3)
    if why:
        d["why"] = why
    return d


class RepoTools:
    """Tools the agent can call. Each is a plain method so they can also be exposed as LLM function-calls."""

    def __init__(self, root: Path, index: CodeIndex, test_timeout: int = 120, llm=None) -> None:
        self.root, self.index, self.test_timeout, self.llm = root, index, test_timeout, llm
        self.last_trace: dict = {}
        s = get_settings()
        self.web = extras.WebSearch(s.web_search_provider, s.brave_api_key, s.tavily_api_key)

    def search_code(self, query: str, k: int = 5, candidates: int = 20) -> list[dict]:
        """Hybrid search (vectors + BM25, fused with RRF) -> rerank -> top-k chunks. `candidates` = fused pool size."""
        r = self.index.retriever(llm=self.llm).retrieve(query, k=k, pool=max(candidates, k))
        self.last_trace = r.trace
        return [chunk_dict(h.chunk, h.score, why=h.why()) for h in r.hits]

    def related(self, chunk_id: int) -> list[dict]:
        c = self.index.chunks[chunk_id]
        return ([chunk_dict(x, via="callee") for x in self.index.callees(c)]
                + [chunk_dict(x, via="caller") for x in self.index.callers(c)])

    def chunk_at(self, path: str, line: int) -> dict | None:
        """The smallest indexed chunk (function / method / class) that contains `path:line`."""
        best = None
        for c in self.index.chunks:
            if c.file == path and c.start <= line <= c.end and (best is None or (c.end - c.start) < (best.end - best.start)):
                best = c
        return chunk_dict(best, via="traceback") if best else None

    def grep(self, query: str, regex: bool = False, limit: int = 20) -> dict:
        """Exact text / regex search over every file (error strings, config keys, names the semantic search misses)."""
        from ..textsearch import grep
        return grep(self.root, self.index.tree, query, regex=regex, limit=limit)

    def list_files(self, prefix: str = "", limit: int = 60) -> list[str]:
        return [f for f in self.index.tree if f.startswith(prefix)][:limit]

    def read_file(self, path: str, start: int | None = None, end: int | None = None) -> str:
        if extras.is_secret_file(path):
            raise ValueError(f"{path} looks like a secrets file and is never read")
        lines = safe_path(self.root, path).read_text(encoding="utf-8").splitlines()
        s = (start or 1) - 1
        return "\n".join(lines[s : end or len(lines)])

    def find_symbol(self, name: str) -> list[dict]:
        return [chunk_dict(c, via="symbol") for c in self.index.by_name.get(name, [])]

    def list_tree(self, max_lines: int = 80) -> str:
        t = self.index.tree
        return "\n".join(t[:max_lines]) + (f"\n... (+{len(t) - max_lines} more files)" if len(t) > max_lines else "")

    def get_dependencies(self, path: str | None = None) -> dict:
        """Declared dependencies of the repo, or for one file: what it imports, who imports it, external packages."""
        if path is None:
            return self.index.deps
        g = self.index.graph
        f = self.index.facts.get(path)
        return {"imports": sorted({i.module for i in f.imports if i.module}) if f else self.index.imports.get(path, []),
                "internal_files": sorted(g.imports_of.get(path, ())), "imported_by": sorted(g.imported_by.get(path, ())),
                "external": sorted(g.external.get(path, ()))}

    def _symbols(self, name: str):
        g = self.index.graph
        return [g.symbols[name]] if name in g.symbols else g.find(name)

    def callers(self, name: str) -> list[dict]:
        """Who calls this function/method (resolved through imports and class hierarchy)."""
        out = []
        for s in self._symbols(name)[:3]:
            for c, conf in self.index.graph.callers(s.id):
                out.append({"symbol": s.qualname, "caller": c.qualname, "file": c.file, "start": c.start, "end": c.end, "confidence": conf})
        return out

    def callees(self, name: str) -> list[dict]:
        out = []
        for s in self._symbols(name)[:3]:
            for c, conf in self.index.graph.callees(s.id):
                out.append({"symbol": s.qualname, "callee": c.qualname, "file": c.file, "start": c.start, "end": c.end, "confidence": conf})
        return out

    def impact(self, path: str) -> dict:
        """Files that would be affected by changing `path` (reverse import graph) and the tests among them."""
        return self.index.graph.impact(path)

    def relations(self, chunk_id: int) -> str:
        """One-line summary of how a chunk connects to the rest of the code (for prompts)."""
        c = self.index.chunks[chunk_id]
        if not c.symbol_id:
            return ""
        g = self.index.graph
        s = g.symbols[c.symbol_id]
        parts = []
        if s.bases:
            parts.append("extends " + ", ".join(s.bases[:4]))
        callees = [x.qualname for x, _ in g.callees(s.id)][:6]
        callers = [x.qualname for x, _ in g.callers(s.id)][:6]
        if callees:
            parts.append("calls " + ", ".join(callees))
        if callers:
            parts.append("called by " + ", ".join(callers))
        if s.kind in ("class", "interface", "struct", "trait") and g.derived.get(s.id):
            parts.append("subclassed by " + ", ".join(g.symbols[i].qualname for i in g.derived[s.id][:4]))
        return f"{c.file}::{c.qualname}: " + "; ".join(parts) if parts else ""

    # ---- git / docs / config / project / web ---------------------------------------------------------------
    def git_status(self) -> str:
        return extras.git_status(self)

    def git_log(self, path: str | None = None, n: int = 10) -> str:
        return extras.git_log(self, path, n)

    def git_diff(self, path: str | None = None, ref: str | None = None, staged: bool = False) -> str:
        return extras.git_diff(self, path, ref, staged)

    def git_branches(self) -> dict:
        return git_intel.summary(self.root)

    def git_show(self, rev: str = "HEAD", path: str | None = None) -> dict:
        return git_intel.show(self.root, rev, path, True, 6000)

    def git_blame(self, path: str, start: int | None = None, end: int | None = None, ref: str | None = None) -> dict:
        return git_intel.blame(self.root, path, start, end, ref)

    def git_file_at(self, path: str, ref: str) -> dict:
        return git_intel.file_at(self.root, path, ref)

    def git_changed_files(self, base: str, head: str | None = None) -> list[dict]:
        return git_intel.changed_files(self.root, base, head)

    def git_authors(self, path: str | None = None, since: str | None = None) -> list[dict]:
        return git_intel.authors(self.root, path, since)

    def git_history(self, path: str | None = None, author: str | None = None, since: str | None = None, grep: str | None = None, ref: str | None = None, n: int = 15) -> list[dict]:
        return git_intel.log(self.root, path=path, author=author, since=since, grep=grep, ref=ref, limit=n)

    def search_docs(self, query: str, k: int = 5) -> list[dict]:
        return extras.search_docs(self, query, k)

    def find_config(self, query: str, limit: int = 15) -> dict:
        return extras.find_config(self, query, limit)

    def inspect_project(self) -> dict:
        return extras.inspect_project(self)

    def search_web(self, query: str, n: int = 5) -> list[dict]:
        return self.web.search(query, n)

    # ---- running things (always in a throw-away copy; the repository itself is never modified) ------------
    def run_tests(self, targets: list[str] | None = None, spec: dict | None = None) -> dict:
        """Run the test suite (or `targets`) in a copy of the repo, optionally with a patch spec applied to the copy first."""
        work = sandbox.copy_repo(self.root)
        try:
            if spec:
                patching.apply_spec(work, spec)
            return sandbox.run_tests(work, self.test_timeout, targets=targets)
        finally:
            sandbox.cleanup(work)

    def lint(self, paths: list[str] | None = None, spec: dict | None = None) -> dict:
        """Lint the repo (or `paths`). With a spec, lint the copy the patch was applied to."""
        if not spec:
            return lint_mod.run_linter(self.root, paths, 60)
        work = sandbox.copy_repo(self.root)
        try:
            patching.apply_spec(work, spec)
            return lint_mod.run_linter(work, paths, 60)
        finally:
            sandbox.cleanup(work)

    def check_patch(self, spec: dict, with_tests: bool = False) -> dict:
        """Apply a patch spec to a sandbox copy and check it: syntax, new lint findings vs. the original, optionally the test suite."""
        ps = build_patchset(self.root, PatchSpec.from_dict(spec), allow_noop=True)
        changed = [c.path for c in ps.changes if c.op != "delete"]
        before = lint_mod.run_linter(self.root, [c.path for c in ps.changes if c.op != "create"] or None, 60) if any(c.op != "create" for c in ps.changes) else {"issues": []}
        work = sandbox.copy_repo(self.root)
        try:
            patching.apply_spec(work, spec)
            after = lint_mod.run_linter(work, changed, 60) if changed else {"issues": [], "counts": {"blocking": 0, "total": 0}, "tool": "none", "summary": "nothing to lint"}
            tests = sandbox.run_tests(work, self.test_timeout) if with_tests else None
        finally:
            sandbox.cleanup(work)
        return {"stats": ps.stats(), "paths": ps.paths, "lint": after, "lint_new": lint_mod.new_issues(before, after), "tests": tests}
