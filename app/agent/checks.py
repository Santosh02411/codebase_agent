"""Deterministic code checks (no model involved). Used by the reviewer and by the /review endpoint.

Every finding carries: file, line, severity (high|medium|low), confidence (high|medium|low), message, evidence (the offending source
line), fix (an actionable remediation) and source. `dedupe_findings` merges repeats; `suppression_findings` flags patches that hide an
error instead of fixing its cause."""
from __future__ import annotations
import ast
import re

SECRET = re.compile(r"(?i)\b(api[_-]?key|secret|password|token)\b\s*=\s*[\"'][^\"']{8,}[\"']")
# Values that are obviously not real credentials (placeholders, templates, env lookups): never reported as hard-coded secrets.
_FAKE_VALUE = re.compile(r"(?i)^(your|<|\$\{|\{\{|%\(|changeme|change[-_ ]me|xxx|\*+$|example|placeholder|todo|dummy|test|fake|sample|secret$|password$|token$|\.\.\.)")
_TEST_PATH = re.compile(r"(^|/)(tests?|__tests__|fixtures?|examples?|docs?)/|(^|/)(test_[^/]*|[^/]*_test\.py|conftest\.py|[^/]*\.(test|spec)\.[jt]sx?)$")
_SEV_ORDER = {"high": 0, "medium": 1, "low": 2}


def _finding(path: str, line: int, severity: str, message: str, *, confidence: str = "high", evidence: str = "", fix: str = "", source: str = "static") -> dict:
    return {"file": path, "line": line, "severity": severity, "confidence": confidence, "message": message,
            "evidence": evidence.strip()[:200], "fix": fix, "source": source}


def static_checks(path: str, text: str) -> list[dict]:
    out: list[dict] = []
    lines = text.splitlines()
    is_test = bool(_TEST_PATH.search(path))

    def add(line: int, sev: str, msg: str, *, confidence: str = "high", fix: str = "") -> None:
        ev = lines[line - 1] if 0 < line <= len(lines) else ""
        out.append(_finding(path, line, sev, msg, confidence=confidence, evidence=ev, fix=fix))

    for i, l in enumerate(lines, 1):
        m = SECRET.search(l)
        if m:
            value = m.group(0).split("=", 1)[1].strip().strip("\"'")
            if not _FAKE_VALUE.match(value):
                # lower severity inside tests/examples, where literals are usually fixtures
                add(i, "low" if is_test else "high", "Looks like a hard-coded secret. Move it to an environment variable.",
                    confidence="low" if is_test else "medium", fix="Read the value from an environment variable or a secrets manager and rotate the exposed credential.")
        if re.search(r"#\s*(TODO|FIXME)", l):
            add(i, "low", "Unfinished work marked in a comment.", confidence="high", fix="Finish it or track it in an issue.")
    if path.endswith(".py"):
        try:
            tree = ast.parse(text)
        except SyntaxError as e:
            return out + [_finding(path, e.lineno or 1, "high", f"Syntax error: {e.msg}", evidence=(lines[(e.lineno or 1) - 1] if e.lineno and e.lineno <= len(lines) else ""),
                                   fix="Fix the syntax so the file parses.")]
        for n in ast.walk(tree):
            if isinstance(n, ast.ExceptHandler) and n.type is None:
                add(n.lineno, "medium", "Bare `except:` hides real errors. Catch specific exceptions.", fix="Catch the specific exception types you expect and handle or re-raise them.")
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if any(isinstance(d, (ast.List, ast.Dict, ast.Set)) for d in n.args.defaults + [x for x in n.args.kw_defaults if x]):
                    add(n.lineno, "medium", f"`{n.name}` uses a mutable default argument.", fix="Default to None and create the list/dict inside the function.")
                if (n.end_lineno or n.lineno) - n.lineno > 60:
                    add(n.lineno, "low", f"`{n.name}` is over 60 lines. Consider splitting it.", confidence="medium", fix="Extract cohesive blocks into helper functions.")
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("eval", "exec"):
                # a constant string argument (eval("1+1")) is not injectable; dynamic input is
                dynamic = not (n.args and isinstance(n.args[0], ast.Constant))
                if dynamic:
                    add(n.lineno, "high" if not is_test else "medium", f"`{n.func.id}()` on dynamic input is a security risk.",
                        confidence="high" if not is_test else "medium", fix="Use ast.literal_eval or a purpose-built parser; never evaluate untrusted text.")
    return out


_STOP = {"this", "that", "with", "from", "into", "when", "should", "could", "would", "which", "instead", "consider", "using", "used", "code", "line"}


def _words(msg: str) -> set[str]:
    return {w[:6] for w in re.findall(r"[a-z]{4,}", str(msg).lower()) if w not in _STOP}


def _same_issue(a: dict, b: dict) -> bool:
    """Two findings on the same line describe the same issue when their significant words overlap enough (min-overlap coefficient >= 0.5)."""
    wa, wb = _words(a.get("message", "")), _words(b.get("message", ""))
    return bool(wa and wb) and len(wa & wb) / min(len(wa), len(wb)) >= 0.5


def dedupe_findings(findings: list[dict]) -> list[dict]:
    """One finding per issue. Findings on the same (file, line) whose messages overlap are merged: the most severe (then the most confident)
    wins, missing evidence/fix are filled in from the others, and the other sources are remembered in `also`. Sorted by severity, file, line."""
    conf = {"high": 0, "medium": 1, "low": 2}
    rank = lambda f: (_SEV_ORDER.get(f.get("severity", "low"), 2), conf.get(f.get("confidence", "medium"), 1))   # noqa: E731
    groups: dict[tuple, list[dict]] = {}
    for f in findings:
        if not f.get("message"):
            continue
        key = (f.get("file", ""), int(f.get("line") or 0))
        for kept in groups.setdefault(key, []):
            if _same_issue(kept, f):
                also = set(kept.get("also", [])) | set(f.get("also", []))
                winner, loser = (dict(f), kept) if rank(f) < rank(kept) else (kept, f)
                if loser.get("source") and loser["source"] != winner.get("source"):
                    also.add(loser["source"])
                for k in ("evidence", "fix"):
                    if not winner.get(k) and loser.get(k):
                        winner[k] = loser[k]
                if also:
                    winner["also"] = sorted(also)
                kept.clear(); kept.update(winner)
                break
        else:
            groups[key].append(dict(f))
    return sorted((f for g in groups.values() for f in g), key=lambda x: (_SEV_ORDER.get(x.get("severity", "low"), 2), x.get("file", ""), x.get("line") or 0))


def ground_findings(findings: list[dict], texts: dict[str, str]) -> list[dict]:
    """Model findings must point at real code. A finding whose file was not read, or whose line is outside the file, is kept but marked
    low confidence and `ungrounded`; one that points at a real line gets that line as evidence."""
    out = []
    for f in findings:
        g = dict(f)
        text = texts.get(g.get("file", ""))
        line = int(g.get("line") or 0)
        if text is None:
            g.update(confidence="low", grounded=False)
        else:
            lines = text.splitlines()
            if 1 <= line <= len(lines):
                g.setdefault("evidence", lines[line - 1].strip()[:200])
                g["grounded"] = True
            else:
                g.update(confidence="low", grounded=False)
        out.append(g)
    return out


# ---- patches that hide the error instead of fixing it ------------------------------------------------------------------
_SWALLOW = re.compile(r"^\s*(pass|\.\.\.|return(\s+None)?|continue|print\(.*\)|logging\.\w+\(.*\)|logger\.\w+\(.*\))\s*$")


def _swallowing_handlers(text: str) -> int:
    """Number of except-blocks (Python) whose whole body only passes / returns None / logs: the error is hidden, not handled."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return 0
    n = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            body = [b for b in node.body if not (isinstance(b, ast.Expr) and isinstance(getattr(b, "value", None), ast.Constant))]
            if not body:
                n += 1
                continue
            if all(isinstance(b, (ast.Pass, ast.Continue)) or (isinstance(b, ast.Return) and (b.value is None or (isinstance(b.value, ast.Constant) and b.value.value in (None, False, 0, ""))))
                   or (isinstance(b, ast.Expr) and isinstance(b.value, ast.Call) and _is_log_call(b.value)) for b in body):
                if not any(isinstance(b, ast.Raise) for b in ast.walk(node)):
                    n += 1
    return n


def _is_log_call(call: ast.Call) -> bool:
    f = call.func
    if isinstance(f, ast.Name):
        return f.id == "print"
    return isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id in ("logging", "logger", "log", "_log")


def suppression_findings(before: dict[str, str], after: dict[str, str]) -> list[dict]:
    """Compare original and patched files. Flag a patch that ADDS handlers which swallow an exception, adds a blanket `except Exception`/`except:`
    around the failing code, or only adds `# noqa` / `type: ignore` markers. These make a symptom disappear without fixing its cause.
    Deterministic: no model involved. Returns high-severity findings so the reviewer rejects the patch."""
    out: list[dict] = []
    for path, new in after.items():
        old = before.get(path, "")
        if not path.endswith(".py"):
            continue
        added = _swallowing_handlers(new) - _swallowing_handlers(old)
        if added > 0:
            line = next((i for i, l in enumerate(new.splitlines(), 1) if re.match(r"\s*except\b", l) and i not in {j for j, x in enumerate(old.splitlines(), 1) if re.match(r"\s*except\b", x)}), 1)
            out.append(_finding(path, line, "high", f"The patch adds {added} exception handler(s) that swallow the error (pass / return None / log only) instead of fixing its cause.",
                                evidence=new.splitlines()[line - 1] if line <= len(new.splitlines()) else "",
                                fix="Fix the code that raises the error. If an exception is expected, handle it explicitly (return a meaningful result, re-raise, or report it).", source="patch-guard"))
        old_markers = len(re.findall(r"#\s*(noqa|type:\s*ignore|pylint:\s*disable|nosec)", old))
        new_markers = len(re.findall(r"#\s*(noqa|type:\s*ignore|pylint:\s*disable|nosec)", new))
        if new_markers > old_markers:
            out.append(_finding(path, 1, "medium", "The patch adds lint/type/security suppression comments (noqa / type: ignore / nosec) instead of resolving the reported problem.",
                                confidence="medium", fix="Resolve the underlying warning rather than silencing it.", source="patch-guard"))
    return out
