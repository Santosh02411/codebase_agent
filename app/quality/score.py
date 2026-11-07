"""The code-quality score: one 0-100 number and an A-F grade built from measurable parts, with the working shown.

Dimension           weight  how it is scored (100 = best)
tests                 30    pass rate of the suite; no tests at all = 0
coverage              20    line coverage percent (when it could be measured)
lint                  15    100 - 5 x weighted findings per 1000 lines (blocking x5, high x3, medium x2, low x0.5)
types                 10    100 - 5 x mypy errors per 1000 lines
security              20    100 - (critical 25 + high 15 + medium 5 + low 1 per finding) - code and dependency findings together
maintainability        5    share of functions that are not too long (>60 lines) or too branchy (cyclomatic complexity >15)
Dimensions that could not be measured (tool missing / not applicable / skipped) are left out and the rest are re-weighted, so a missing tool
never counts as a perfect score and never as a failure: the report says which dimensions were measured."""
from __future__ import annotations
import ast
import os
from pathlib import Path

WEIGHTS = {"tests": 30, "coverage": 20, "lint": 15, "types": 10, "security": 20, "maintainability": 5}
LINT_W = {"blocking": 5.0, "high": 3.0, "medium": 2.0, "low": 0.5, "info": 0.1}
SEC_PENALTY = {"critical": 25, "high": 15, "medium": 5, "low": 1, "info": 0}
CODE_EXT = (".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java")
SKIP = {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build", ".next", "target", "vendor"}


def grade(score: float) -> str:
    return "A" if score >= 90 else "B" if score >= 80 else "C" if score >= 70 else "D" if score >= 60 else "F"


def count_lines(root: Path) -> int:
    n = 0
    for dp, dirs, fs in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP]
        for f in fs:
            if f.endswith(CODE_EXT):
                try:
                    with open(os.path.join(dp, f), "rb") as fh:
                        n += sum(1 for _ in fh)
                except OSError:
                    pass
    return n


class _Complexity(ast.NodeVisitor):
    BRANCH = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.With, ast.AsyncWith, ast.IfExp, ast.comprehension, ast.Assert)

    def __init__(self) -> None:
        self.funcs: list[dict] = []

    def visit_FunctionDef(self, node):
        cx = 1 + sum(isinstance(n, self.BRANCH) for n in ast.walk(node)) + sum(len(n.values) - 1 for n in ast.walk(node) if isinstance(n, ast.BoolOp))
        self.funcs.append({"name": node.name, "line": node.lineno, "length": (node.end_lineno or node.lineno) - node.lineno + 1, "complexity": cx})
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef


def maintainability(root: Path, limit_files: int = 600) -> dict:
    """Function length and cyclomatic complexity of the Python code (parsed, never executed)."""
    funcs: list[dict] = []
    seen = 0
    for dp, dirs, fs in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP]
        for f in fs:
            if f.endswith(".py") and seen < limit_files:
                seen += 1
                path = os.path.join(dp, f)
                try:
                    v = _Complexity()
                    v.visit(ast.parse(Path(path).read_text(encoding="utf-8", errors="replace")))
                except (SyntaxError, ValueError, OSError):
                    continue
                rel = os.path.relpath(path, root)
                funcs += [{**x, "file": rel} for x in v.funcs]
    if not funcs:
        return {"available": False}
    bad = [x for x in funcs if x["length"] > 60 or x["complexity"] > 15]
    worst = sorted(funcs, key=lambda x: (x["complexity"], x["length"]), reverse=True)[:8]
    return {"available": True, "functions": len(funcs), "too_complex_or_long": len(bad), "avg_complexity": round(sum(x["complexity"] for x in funcs) / len(funcs), 1),
            "avg_length": round(sum(x["length"] for x in funcs) / len(funcs), 1), "worst": worst}


def compute(*, tests: dict | None, coverage: dict | None, analyzers: dict[str, dict], loc: int, maint: dict) -> dict:
    dims: dict[str, dict] = {}
    kloc = max(loc, 200) / 1000.0

    # tests
    if tests and tests.get("status") in ("passed", "failed"):
        c = tests.get("counts") or {}
        total = tests.get("total") or sum(c.get(k, 0) for k in ("passed", "failed", "error"))
        passed = c.get("passed", 0)
        s = 100.0 * passed / total if total else (100.0 if tests["status"] == "passed" else 0.0)
        dims["tests"] = {"score": round(s, 1), "detail": f"{passed} of {total} tests pass" + ("" if tests["status"] == "passed" else "; the suite is failing")}
    elif tests and tests.get("status") == "no_tests":
        dims["tests"] = {"score": 0.0, "detail": "no tests found"}
    # coverage
    if coverage and coverage.get("total"):
        dims["coverage"] = {"score": coverage["percent"], "detail": f"{coverage['percent']}% of {coverage['total']} lines"}
    # lint / types / security from analyzer findings
    def done(name: str) -> dict | None:
        a = analyzers.get(name)
        return a if a and a["status"] in ("ok", "issues") else None
    lint_tools = [n for n in ("ruff", "pylint", "eslint", "go-vet", "clippy") if done(n)]
    if lint_tools:
        w = 0.0
        for n in lint_tools:
            for f in analyzers[n]["findings"]:
                w += LINT_W["blocking"] if f["blocking"] else LINT_W.get(f["severity"], 0.5)
        dens = w / kloc / max(1, len(lint_tools))
        dims["lint"] = {"score": round(max(0.0, 100 - 5 * dens), 1), "detail": f"{sum(len(analyzers[n]['findings']) for n in lint_tools)} finding(s) from {', '.join(lint_tools)} in ~{loc} lines"}
    if done("mypy"):
        errs = len(analyzers["mypy"]["findings"])
        dims["types"] = {"score": round(max(0.0, 100 - 5 * errs / kloc), 1), "detail": f"{errs} type error(s)"}
    sec_tools = [n for n in ("bandit", "semgrep", "pip-audit", "npm-audit") if done(n)]
    if sec_tools:
        sev: dict[str, int] = {}
        for n in sec_tools:
            for f in analyzers[n]["findings"]:
                sev[f["severity"]] = sev.get(f["severity"], 0) + 1
        pen = sum(SEC_PENALTY.get(k, 0) * v for k, v in sev.items())
        dims["security"] = {"score": float(max(0, 100 - pen)), "detail": ", ".join(f"{v} {k}" for k, v in sorted(sev.items(), key=lambda x: list(SEC_PENALTY).index(x[0]))) or "no findings"}
    if maint.get("available"):
        share = 100.0 * (1 - maint["too_complex_or_long"] / maint["functions"])
        dims["maintainability"] = {"score": round(share, 1), "detail": f"{maint['too_complex_or_long']} of {maint['functions']} functions are very long or complex (avg complexity {maint['avg_complexity']})"}

    for k, v in dims.items():
        v["weight"] = WEIGHTS[k]
    total_w = sum(v["weight"] for v in dims.values())
    overall = round(sum(v["score"] * v["weight"] for v in dims.values()) / total_w, 1) if total_w else None
    return {"overall": overall, "grade": grade(overall) if overall is not None else "n/a", "dimensions": dims,
            "not_measured": [k for k in WEIGHTS if k not in dims], "measured_weight": total_w}
