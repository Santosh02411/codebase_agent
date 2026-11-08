"""The strict review: every parsable source file of the project is analysed, with real parsers and real rules (no model, no sampling, no scoring guesses).

`review_project(root)` returns the findings plus an honest account of what was and was not analysed (per language, files skipped and why, and the
limits of the analysis), so a clean result can be trusted for exactly what it covers and nothing more."""
from __future__ import annotations
import time
from pathlib import Path

from ..ingest import iter_source_files
from . import datacheck, jscheck, pycheck, treecheck
from .pycheck import Finding, Project

ENGINE_VERSION = "1.0"
MAX_FILE_BYTES = 600_000
SEV_ORDER = {"high": 0, "medium": 1, "low": 2}
SKIP_JSON = ("tsconfig", "jsconfig", ".eslintrc", "package-lock", "composer.lock", "oxlintrc", "babelrc", "prettierrc", "swcrc", ".vscode", "devcontainer", "renovate", "biome")
GENERATED_DIRS = {"_next", "vendor", "third_party", "site-packages", "bower_components", "coverage", "out", "webapp"}


def _generated(rel: str, text: str) -> str | None:
    """Build output and minified bundles are not code anyone wrote: reviewing them only produces noise."""
    parts = set(Path(rel).parts[:-1])
    if parts & GENERATED_DIRS and rel.endswith((".js", ".css", ".map")):
        return "generated build output"
    if rel.endswith((".min.js", ".min.css", ".bundle.js")):
        return "minified file"
    ls = text.splitlines()
    if ls and rel.endswith((".js", ".css")) and (max(len(l) for l in ls) > 1500 or (len(text) > 5000 and len(text) / max(1, len(ls)) > 300)):
        return "minified/generated (very long lines)"
    return None

DEPTH = {
    "python": "syntax (Python's own compiler), undefined names and misspellings, `self.` attribute typos, standard-library attribute typos, imports and calls between project files "
              "(missing names, wrong argument counts, unknown keywords), unused imports and variables, redefinitions, unreachable code, common bug patterns and security rules",
    "javascript": "syntax (Tree-sitter grammar: missing/extra braces, brackets, quotes, unclosed JSX tags), import paths that do not resolve, imports of names a module does not export, packages missing from package.json, undefined identifiers / JSX components / hooks, assignment in conditions, `debugger`, empty `catch`, loose equality, unreachable code, unused imports",
    "typescript": "syntax (Tree-sitter grammar) and the same import / undefined-name / pattern rules as JavaScript (no type checking)",
    "tsx": "syntax (Tree-sitter grammar) and the same import / undefined-name / pattern rules as JavaScript (no type checking)",
    "java": "syntax only (Tree-sitter grammar)", "go": "syntax only (Tree-sitter grammar)", "rust": "syntax only (Tree-sitter grammar)", "c": "syntax only (Tree-sitter grammar)", "cpp": "syntax only (Tree-sitter grammar)",
    "json": "strict JSON syntax", "yaml": "YAML syntax", "toml": "TOML syntax", "html": "tag balance and bracket balance in inline scripts", "css": "bracket balance",
}
LIMITS = [
    "No type checking: wrong argument TYPES, wrong return types and type-annotation violations are not detected (use the Code Quality scan's mypy for Python).",
    "Python names are resolved statically: names created dynamically (exec, setattr, star imports, metaprogramming) cannot be seen, and those cases are skipped rather than guessed.",
    "JavaScript/TypeScript: only the listed rules run; undeclared names are only reported when they are a near-miss of a declared name (a likely typo).",
    "Java, Go, Rust, C and C++ are checked for syntax errors only.",
    "Logic errors that are syntactically and semantically valid (wrong formula, wrong condition) cannot be found by static analysis; the AI review can look for those when a model is configured.",
]


def _lang_of(rel: str) -> str | None:
    ext = Path(rel).suffix.lower()
    if ext == ".py":
        return "python"
    if ext in treecheck.LANG_BY_EXT:
        return treecheck.LANG_BY_EXT[ext]
    return {".json": "json", ".yml": "yaml", ".yaml": "yaml", ".toml": "toml", ".html": "html", ".htm": "html", ".css": "css"}.get(ext)


def _secrets(rel: str, text: str) -> list[Finding]:
    """Regex secret scan for non-Python files (Python is checked on its syntax tree). Comment lines are ignored."""
    from ..agent.checks import static_checks
    out = []
    lines = text.splitlines()
    for f in static_checks(rel, text):
        ln = lines[f["line"] - 1].lstrip() if 0 < f["line"] <= len(lines) else ""
        if "hard-coded secret" in f["message"] and not ln.startswith(("#", "//", "*", "/*", "<!--")):
            out.append(Finding("SECRET", "security", f["severity"], f["message"], f["line"], 0, confidence=f["confidence"], fix=f["fix"]))
    return out


def analyse_file(rel: str, text: str, project: Project, js: "jscheck.JsProject | None" = None) -> list[Finding]:
    lang = _lang_of(rel)
    out: list[Finding] = []
    if lang == "python":
        out = pycheck.check_python(rel, text, project)
    elif lang in ("javascript", "typescript", "tsx", "java", "go", "rust", "c", "cpp"):
        out = treecheck.syntax_errors(lang, text)
        if treecheck.get_parser is None or (not out and treecheck._parse(lang, b"") is None):
            out = treecheck.brace_balance(text)
        if lang in ("javascript", "typescript", "tsx") and treecheck.get_parser is not None:
            out += treecheck.js_rules(lang, text)
            if js is not None:
                out += jscheck.project_checks(rel, lang, text, js)
    elif lang == "json":
        if not any(s in Path(rel).name for s in SKIP_JSON):
            out = datacheck.check_json(text)
    elif lang == "yaml":
        out = datacheck.check_yaml(text)
    elif lang == "toml":
        out = datacheck.check_toml(text)
    elif lang == "html":
        out = datacheck.check_html(text)
    elif lang == "css":
        out = datacheck.check_css(text)
    if lang in ("javascript", "typescript", "tsx", "java", "go", "yaml", "json", "toml"):
        out += _secrets(rel, text)
    return out


def review_project(root: Path, only: list[str] | None = None, progress=None) -> dict:
    t0 = time.time()
    root = Path(root)
    paths = [(rel, p) for rel, p in iter_source_files(root)]
    if only:
        want = set(only)
        paths = [(r, p) for r, p in paths if r in want]
    texts: dict[str, str] = {}
    skipped: list[dict] = []
    for rel, p in paths:
        try:
            raw = p.read_bytes()
        except OSError as e:
            skipped.append({"file": rel, "reason": f"unreadable: {e.__class__.__name__}"}); continue
        if len(raw) > MAX_FILE_BYTES:
            skipped.append({"file": rel, "reason": f"larger than {MAX_FILE_BYTES // 1000} KB"}); continue
        if b"\x00" in raw[:2000]:
            skipped.append({"file": rel, "reason": "binary file"}); continue
        t = raw.decode("utf-8", "replace")
        why = _generated(rel, t)
        if why:
            skipped.append({"file": rel, "reason": why}); continue
        texts[rel] = t
    # the whole project is the context for import/call checks, even when only some files are reviewed
    ctx_files = texts if not only else {rel: p.read_text("utf-8", "replace") for rel, p in iter_source_files(root) if rel.endswith(".py") and _small(p)}
    project = Project({r: t for r, t in ctx_files.items() if r.endswith(".py")})
    all_paths = _all_paths(root)
    js_texts = {r: t for r, t in texts.items() if r.endswith((".js", ".jsx", ".ts", ".tsx", ".mjs", ".json"))}
    if only:        # reviewing a few files still needs the project's other JS files and package.json as context
        for r, p in iter_source_files(root):
            if r not in js_texts and r.endswith((".js", ".jsx", ".ts", ".tsx", ".mjs", "package.json")) and _small(p):
                js_texts[r] = p.read_text("utf-8", "replace")
    js = jscheck.JsProject(js_texts, all_paths)
    findings: list[dict] = []
    by_lang: dict[str, dict] = {}
    n = 0
    for rel, text in texts.items():
        lang = _lang_of(rel)
        if lang is None:
            continue
        n += 1
        if progress:
            progress(n, len(texts), rel)
        info = by_lang.setdefault(lang, {"language": lang, "files": 0, "findings": 0, "depth": DEPTH.get(lang, "")})
        info["files"] += 1
        try:
            fs = analyse_file(rel, text, project, js)
        except Exception as e:                       # one broken analyser must never hide the rest: report it
            skipped.append({"file": rel, "reason": f"analyser error: {type(e).__name__}: {e}"[:160]})
            continue
        lines = text.splitlines()
        seen: set[tuple] = set()
        imp_lines = {f.line for f in fs if f.rule == "PY-IMPORT"}
        for f in sorted(fs, key=lambda x: (SEV_ORDER.get(x.severity, 3), x.line, x.col)):
            key = (f.rule, f.line, f.col, f.message)
            if key in seen or (f.rule == "PY-UNUSEDIMPORT" and f.line in imp_lines):
                continue
            seen.add(key)
            ln = max(1, f.line)
            lo, hi = max(1, ln - 2), min(len(lines), ln + 2)
            findings.append({"id": f"{rel}:{ln}:{f.col}:{f.rule}", "rule": f.rule, "category": f.category, "severity": f.severity, "confidence": f.confidence, "file": rel, "line": ln, "col": f.col,
                             "end_col": f.end_col or 0, "message": f.message, "fix": f.fix, "evidence": (lines[ln - 1] if 0 < ln <= len(lines) else "").rstrip()[:240], "language": lang,
                             "context": [{"n": i, "text": lines[i - 1][:240]} for i in range(lo, hi + 1)], "source": "static-analysis"})
            info["findings"] += 1
            if info["findings"] > 400:
                break
    agg: dict[tuple, dict] = {}
    keep: list[dict] = []
    for f in findings:
        if f["rule"] == "JS-LOOSEEQ":                       # one note per file, not one per comparison
            a = agg.setdefault((f["file"], f["rule"]), {**f, "count": 0})
            a["count"] += 1
            continue
        keep.append(f)
    for a in agg.values():
        n = a.pop("count")
        a["message"] = f"{n} loose `==` / `!=` comparison{'s' if n > 1 else ''} in this file (first shown): they coerce types and can hide bugs."
        keep.append(a)
    findings = keep
    findings.sort(key=lambda f: (SEV_ORDER.get(f["severity"], 3), f["file"], f["line"], f["col"]))
    counts = {"high": 0, "medium": 0, "low": 0}
    cats: dict[str, int] = {}
    rules: dict[str, int] = {}
    for f in findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
        cats[f["category"]] = cats.get(f["category"], 0) + 1
        rules[f["rule"]] = rules.get(f["rule"], 0) + 1
    not_analysed = sorted({Path(r).suffix.lower() or Path(r).name for r, _ in paths if _lang_of(r) is None})
    return {"findings": findings, "summary": {"total": len(findings), "by_severity": counts, "by_category": cats, "by_rule": dict(sorted(rules.items(), key=lambda x: -x[1]))},
            "coverage": {"files_analysed": sum(i["files"] for i in by_lang.values()), "languages": sorted(by_lang.values(), key=lambda i: -i["files"]), "skipped": skipped[:50], "not_analysed_types": not_analysed},
            "limits": LIMITS, "duration_ms": int((time.time() - t0) * 1000), "engine": f"strict-static {ENGINE_VERSION}", "scope": "file" if only else "project"}


def _all_paths(root: Path) -> set[str]:
    """Every file of the working copy (images and assets too), so that imports of `./logo.svg` resolve. Dependency folders are not walked, only noted."""
    import os
    skip = {".git", "node_modules", "venv", ".venv", "__pycache__", ".next", ".cache", "site-packages"}
    out: set[str] = set()
    base = str(root)
    for d, dirs, files in os.walk(base):
        if "node_modules" in dirs and d == base:
            out.add("node_modules/.present")
        dirs[:] = [x for x in dirs if x not in skip]
        rel_d = os.path.relpath(d, base).replace(os.sep, "/")
        prefix = "" if rel_d == "." else rel_d + "/"
        for f in files:
            out.add(prefix + f)
        if len(out) > 60000:
            break
    return out


def _small(p: Path) -> bool:
    try:
        return p.stat().st_size <= MAX_FILE_BYTES
    except OSError:
        return False


def review_snippet(filename: str, text: str) -> dict:
    """Review one pasted file (no project around it, so checks that need other files, such as imports between project files, are skipped)."""
    t0 = time.time()
    rel = filename or "snippet.py"
    project = Project({rel: text} if rel.endswith(".py") else {})
    lang = _lang_of(rel)
    findings: list[dict] = []
    if lang is None:
        return {"findings": [], "summary": {"total": 0, "by_severity": {"high": 0, "medium": 0, "low": 0}, "by_category": {}, "by_rule": {}},
                "coverage": {"files_analysed": 0, "languages": [], "skipped": [{"file": rel, "reason": "no checker for this file type"}], "not_analysed_types": [Path(rel).suffix]}, "limits": LIMITS,
                "duration_ms": 0, "engine": f"strict-static {ENGINE_VERSION}", "scope": "snippet"}
    fs = analyse_file(rel, text, project, None)
    lines = text.splitlines()
    seen: set[tuple] = set()
    counts = {"high": 0, "medium": 0, "low": 0}; cats: dict[str, int] = {}; rules: dict[str, int] = {}
    for f in sorted(fs, key=lambda x: (SEV_ORDER.get(x.severity, 3), x.line, x.col)):
        key = (f.rule, f.line, f.col, f.message)
        if key in seen:
            continue
        seen.add(key)
        ln = max(1, f.line); lo, hi = max(1, ln - 2), min(len(lines), ln + 2)
        findings.append({"id": f"{rel}:{ln}:{f.col}:{f.rule}", "rule": f.rule, "category": f.category, "severity": f.severity, "confidence": f.confidence, "file": rel, "line": ln, "col": f.col, "end_col": f.end_col or 0,
                         "message": f.message, "fix": f.fix, "evidence": (lines[ln - 1] if 0 < ln <= len(lines) else "").rstrip()[:240], "language": lang,
                         "context": [{"n": i, "text": lines[i - 1][:240]} for i in range(lo, hi + 1)], "source": "static-analysis"})
        counts[f.severity] = counts.get(f.severity, 0) + 1; cats[f.category] = cats.get(f.category, 0) + 1; rules[f.rule] = rules.get(f.rule, 0) + 1
    return {"findings": findings, "summary": {"total": len(findings), "by_severity": counts, "by_category": cats, "by_rule": rules},
            "coverage": {"files_analysed": 1, "languages": [{"language": lang, "files": 1, "findings": len(findings), "depth": DEPTH.get(lang, "")}], "skipped": [], "not_analysed_types": []},
            "limits": LIMITS, "duration_ms": int((time.time() - t0) * 1000), "engine": f"strict-static {ENGINE_VERSION}", "scope": "snippet"}
