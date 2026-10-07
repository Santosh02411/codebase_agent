"""Higher-level agent capabilities built on the same retrieval, sandbox and patch layers:
architecture overview, code review, multi-file code changes and test generation."""
from __future__ import annotations
import ast
import re

from . import patching, sandbox
from .agent.nodes import SYSTEM, format_context

SCHEMA = ('Return JSON: {"edits": [{"file": "path", "search": "exact existing text occurring exactly once in that file", '
          '"replace": "new text"}], "new_files": [{"path": "new/file.py", "content": "full file text"}], '
          '"explanation": "what changed and why"}. Use edits for existing files and new_files only for files that do not exist.')


def _context(tools, queries: list[str], k: int = 4) -> list[dict]:
    seen, out = set(), []
    for q in queries:
        for h in tools.search_code(q, k=k):
            if h["id"] not in seen:
                seen.add(h["id"]); out.append(h)
    return out[:12]


def _sources(ctx: list[dict]) -> list[dict]:
    return [{"file": c["file"], "lines": f"{c['start']}-{c['end']}", "symbol": c["qualname"]} for c in ctx]


# ---- architecture ---------------------------------------------------------------------------
def architecture(llm, tools) -> dict:
    idx = tools.index
    folders: dict[str, int] = {}
    for f in idx.tree:
        top = f.split("/")[0] if "/" in f else "(root)"
        folders[top] = folders.get(top, 0) + 1
    routes = sorted({f"{c.route} → {c.file}::{c.name}" for c in idx.chunks if c.route})
    edges = [f"{f} → {t}" for f in idx.imports for t in tools.get_dependencies(f)["internal_files"] if t != f]
    facts = {"folders": folders, "routes": routes[:40], "imports": edges[:60], "dependencies": idx.deps}
    try:
        readme = tools.read_file("README.md")[:1500]
    except Exception:
        readme = ""
    res = llm.json("architecture", SYSTEM, f"README:\n{readme}\n\nFacts extracted from the code:\n{facts}\n\n"
                   'Explain the architecture for a new engineer: purpose, main components and what each does, '
                   'how a request or data flows through them, and key dependencies. Return JSON: {"summary": "markdown"}',
                   hints={})
    fallback = ("**Structure**\n" + "\n".join(f"- `{k}`: {v} files" for k, v in folders.items())
                + ("\n\n**Routes**\n" + "\n".join(f"- `{r}`" for r in routes[:15]) if routes else "")
                + ("\n\n**Internal imports**\n" + "\n".join(f"- `{e}`" for e in edges[:15]) if edges else "")
                + "\n\n_(Connect an AI model for a written explanation of how these parts fit together.)_")
    return {"answer": res.get("summary") or fallback, "facts": facts,
            "steps": [{"node": "inspect", "message": f"{len(idx.tree)} files, {len(routes)} routes, {len(edges)} internal imports"},
                      {"node": "explain", "message": "wrote the overview"}], "sources": []}


# ---- review ---------------------------------------------------------------------------------
SECRET = re.compile(r"(?i)\b(api[_-]?key|secret|password|token)\b\s*=\s*[\"'][^\"']{8,}[\"']")


def static_checks(path: str, text: str) -> list[dict]:
    out: list[dict] = []

    def add(line, sev, msg):
        out.append({"file": path, "line": line, "severity": sev, "message": msg, "source": "static"})

    for i, l in enumerate(text.splitlines(), 1):
        if SECRET.search(l):
            add(i, "high", "Looks like a hard-coded secret. Move it to an environment variable.")
        if re.search(r"#\s*(TODO|FIXME)", l):
            add(i, "low", "Unfinished work marked in a comment.")
    if path.endswith(".py"):
        try:
            tree = ast.parse(text)
        except SyntaxError as e:
            return out + [{"file": path, "line": e.lineno or 1, "severity": "high", "message": f"Syntax error: {e.msg}", "source": "static"}]
        for n in ast.walk(tree):
            if isinstance(n, ast.ExceptHandler) and n.type is None:
                add(n.lineno, "medium", "Bare `except:` hides real errors. Catch specific exceptions.")
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if any(isinstance(d, (ast.List, ast.Dict, ast.Set)) for d in n.args.defaults + [x for x in n.args.kw_defaults if x]):
                    add(n.lineno, "medium", f"`{n.name}` uses a mutable default argument.")
                if (n.end_lineno or n.lineno) - n.lineno > 60:
                    add(n.lineno, "low", f"`{n.name}` is over 60 lines. Consider splitting it.")
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("eval", "exec"):
                add(n.lineno, "high", f"`{n.func.id}()` on dynamic input is a security risk.")
    return out


def review(llm, tools, path: str | None = None) -> dict:
    files = [path] if path else [f for f in tools.index.tree if f.endswith((".py", ".js", ".ts"))][:40]
    findings, texts = [], {}
    for f in files:
        try:
            texts[f] = tools.read_file(f)
        except Exception:
            continue
        findings += static_checks(f, texts[f])
    code = "\n\n".join(f"### {f}\n```\n{t[:2500]}\n```" for f, t in list(texts.items())[:6])
    res = llm.json("review", SYSTEM, f"Review this code for bugs, security problems, error handling and maintainability. "
                   f"Only report real issues you can point to.\n\n{code}\n\n"
                   'Return JSON: {"summary": "2-3 sentences", "findings": [{"file": "path", "line": 1, '
                   '"severity": "high|medium|low", "message": "issue and how to fix"}]}', hints={})
    for f in res.get("findings") or []:
        if isinstance(f, dict) and f.get("message"):
            findings.append({"file": str(f.get("file", "")), "line": f.get("line") or 0,
                             "severity": f.get("severity") if f.get("severity") in ("high", "medium", "low") else "low",
                             "message": str(f["message"]), "source": "ai"})
    order = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda x: (order[x["severity"]], x["file"], x["line"] or 0))
    n = len(findings)
    summary = res.get("summary") or f"{n} issue{'s' * (n != 1)} found by automatic checks in {len(texts)} file{'s' * (len(texts) != 1)}."
    return {"summary": summary, "findings": findings,
            "steps": [{"node": "static checks", "message": f"scanned {len(texts)} files"},
                      {"node": "review", "message": f"{n} findings"}], "sources": []}


# ---- code changes and test generation (shared engine) ---------------------------------------
def _change(llm, tools, s, task: str, head: str, queries: list[str], verify: bool, extra: str = "") -> dict:
    ctx = _context(tools, queries)
    steps = [{"node": "retrieve", "message": f"read {len(ctx)} relevant code pieces"}]
    before = after = plan = None
    res: dict = {}
    feedback = ""
    status = "no_change"
    for attempt in range(1, s.max_fix_attempts + 1):
        res = llm.json(task, SYSTEM, f"{head}\n\n{extra}Relevant code:\n{format_context(ctx)}\n{feedback}\n{SCHEMA}", hints={})
        try:
            plan = patching.plan_changes(tools.root, res.get("edits"), res.get("new_files"))
        except ValueError as e:
            plan = None
            steps.append({"node": "generate", "message": f"attempt {attempt} rejected: {e}"})
            feedback = f"\nYour previous answer was invalid: {e}\n"
            continue
        steps.append({"node": "generate", "message": f"attempt {attempt}: {len(plan)} file(s): {', '.join(plan)}"})
        if not verify:
            status = "unverified"
            break
        if before is None:
            work = sandbox.copy_repo(tools.root)
            try:
                before = sandbox.run_tests(work, s.test_timeout)
            finally:
                sandbox.cleanup(work)
            steps.append({"node": "verify", "message": f"tests before: {before['status']} ({before['summary']})"})
        work = sandbox.copy_repo(tools.root)
        try:
            patching.apply_changes(work, res.get("edits"), res.get("new_files"))
            after = sandbox.run_tests(work, s.test_timeout)
        finally:
            sandbox.cleanup(work)
        steps.append({"node": "verify", "message": f"tests after: {after['status']} ({after['summary']})"})
        if after["status"] == "passed":
            status = "verified"
            break
        status = "unverified" if after["status"] == "no_tests" else "failed"
        feedback = f"\nYour previous change FAILED the tests:\n{after['output'][-1500:]}\n"
        if status == "unverified":
            break
    out = {"status": status if plan else "no_change", "explanation": res.get("explanation", ""), "steps": steps,
           "test_before": before, "test_after": after, "sources": _sources(ctx),
           "edits": [], "new_files": [], "files": [], "final_files": {}, "diff": ""}
    if plan:
        out.update(edits=res.get("edits") or [], new_files=res.get("new_files") or [], files=list(plan),
                   final_files={f: new[:200_000] for f, (_, new) in plan.items()}, diff=patching.changes_diff(plan))
    return out


def change_code(llm, tools, s, request: str, verify: bool = True) -> dict:
    return _change(llm, tools, s, "generate_change",
                   f"Implement this change across the codebase. Touch as few files as needed and follow the existing style.\n\nRequest:\n{request}",
                   [request], verify)


def generate_tests(llm, tools, s, target: str, verify: bool = True) -> dict:
    try:
        src = f"Source of {target}:\n```\n{tools.read_file(target)[:6000]}\n```\n\n"
    except Exception:
        src = ""
    return _change(llm, tools, s, "generate_tests",
                   f"Write pytest tests for `{target}`: normal cases, edge cases and error cases. "
                   "Add exactly one new file under tests/ via new_files and do not edit existing files.",
                   [target], verify, extra=src)
