"""Static analysis, type checking, security scanning and dependency auditing: one interface over Ruff, ESLint, Pylint, mypy, Bandit, Semgrep,
pip-audit, npm audit, go vet and Clippy. Every tool runs in the sandbox (app/sandbox_exec.py) on a read-only mount of the project: linters read
project config and plugins, which are code. Findings are normalised to one shape and severity scale (critical / high / medium / low / info)."""
from __future__ import annotations
import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .. import lint as lint_mod
from .. import sandbox_exec
from ..config import get_settings
from . import tools

SKIP = {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build", ".next", "target", "vendor", ".tox", ".mypy_cache"}
SEVERITIES = ("critical", "high", "medium", "low", "info")
LOCAL_RULES = Path(__file__).resolve().parents[2] / "sandbox" / "semgrep-rules"


@dataclass
class Finding:
    tool: str
    category: str            # lint | types | security | dependency
    file: str
    line: int
    code: str
    message: str
    severity: str = "low"
    blocking: bool = False
    col: int = 0
    cwe: str = ""
    confidence: str = ""
    fix: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AnalyzerResult:
    tool: str
    category: str
    status: str = "ok"       # ok | issues | unavailable | skipped | timeout | error
    findings: list[Finding] = field(default_factory=list)
    summary: str = ""
    duration_ms: int = 0
    command: str = ""
    note: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["findings"] = [f.to_dict() for f in self.findings]
        return d


def _files(root: Path, exts: tuple[str, ...]) -> list[str]:
    out = []
    for dp, dirs, fs in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP]
        out += [os.path.relpath(os.path.join(dp, f), root) for f in fs if f.endswith(exts)]
        if len(out) > 5000:
            break
    return out


def _rel(path: str, root: Path) -> str:
    p = path.replace("\\", "/")
    for prefix in ("/work/", str(root).replace("\\", "/") + "/", "./"):
        if p.startswith(prefix):
            return p[len(prefix):]
    return p


def _result(tool: str, category: str, res: sandbox_exec.ExecResult | None, findings: list[Finding], *, command: str = "", note: str = "") -> AnalyzerResult:
    blocking = sum(f.blocking for f in findings)
    return AnalyzerResult(tool, category, "issues" if findings else "ok", findings, (f"{len(findings)} finding(s)" + (f", {blocking} blocking" if blocking else "")) if findings else "no findings",
                          res.duration_ms if res else 0, command, note)


def _exec(root: Path, argv: list[str], language: str, timeout: int, network: bool = False, env: dict | None = None):
    """-> (ExecResult | None, early AnalyzerResult-status-dict | None)"""
    try:
        r = sandbox_exec.run(root, argv, language=language, timeout=timeout, readonly=True, network=network, env=env)
    except sandbox_exec.SandboxUnavailable as e:
        return None, ("unavailable", str(e))
    if r.timed_out:
        return r, ("timeout", f"timed out after {timeout}s")
    if tools.missing(r):
        return r, ("unavailable", f"{argv[0]} is not installed in the {language} sandbox image")
    return r, None


def _early(tool: str, category: str, early: tuple, r) -> AnalyzerResult:
    return AnalyzerResult(tool, category, early[0], [], early[1][:300], r.duration_ms if r else 0)


# ---- Python ------------------------------------------------------------------------------------------------------------------------------
def run_ruff(root: Path, timeout: int = 90) -> AnalyzerResult:
    res = lint_mod.run_linter(root, None, timeout)
    if res.get("sandbox_problem"):
        return AnalyzerResult("ruff", "lint", "unavailable", [], res["sandbox_problem"][:300])
    name = "ruff" if "ruff" in res["tool"] else res["tool"].split(" + ")[-1]
    fs = [Finding(name, "lint", i["file"], i["line"], i["code"], i["message"], "high" if i["blocking"] else "low", i["blocking"], i.get("col", 0)) for i in res["issues"]]
    out = _result("ruff", "lint", None, fs, command=res.get("command", ""), note=res.get("summary", "") if res.get("limited") else "")
    if res.get("limited"):
        out.note = "ruff is not installed in the sandbox: only a syntax check ran"
    return out


def run_pylint(root: Path, timeout: int = 180) -> AnalyzerResult:
    argv = tools.argv("pylint", "--output-format=json", "--exit-zero", "--recursive=y", "--ignore=" + ",".join(sorted(SKIP)), "--persistent=n", ".")
    r, early = _exec(root, argv, "python", timeout)
    if early:
        return _early("pylint", "lint", early, r)
    try:
        rows = json.loads(r.stdout or "[]")
    except ValueError:
        return AnalyzerResult("pylint", "lint", "error", [], (r.stderr or r.stdout)[:200])
    sev = {"fatal": "high", "error": "high", "warning": "medium", "refactor": "low", "convention": "info", "info": "info"}
    fs = [Finding("pylint", "lint", _rel(x.get("path", ""), root), x.get("line", 0), x.get("message-id", ""), f"{x.get('message', '')} ({x.get('symbol', '')})", sev.get(x.get("type", ""), "low"),
                  x.get("message-id") in ("E0001", "E0602", "E0601"), x.get("column", 0)) for x in rows]
    return _result("pylint", "lint", r, fs, command="pylint --recursive=y .")


_MYPY = re.compile(r"^(?P<file>[^:\n]+):(?P<line>\d+):(?:(?P<col>\d+):)? (?P<level>error|warning|note): (?P<msg>.*?)(?:  \[(?P<code>[\w-]+)\])?$", re.M)


def run_mypy(root: Path, timeout: int = 240) -> AnalyzerResult:
    argv = tools.argv("mypy", "--no-error-summary", "--show-column-numbers", "--show-error-codes", "--no-color-output", "--ignore-missing-imports", "--cache-dir=/tmp/mypy-cache",
                      "--exclude", "(^|/)(venv|\\.venv|node_modules|build|dist)/", ".")
    r, early = _exec(root, argv, "python", timeout)
    if early:
        return _early("mypy", "types", early, r)
    fs = [Finding("mypy", "types", _rel(m["file"], root), int(m["line"]), m["code"] or "mypy", m["msg"], "medium" if m["level"] == "error" else "low", False, int(m["col"] or 0))
          for m in _MYPY.finditer(r.stdout) if m["level"] != "note"]
    return _result("mypy", "types", r, fs, command="mypy .")


def run_bandit(root: Path, timeout: int = 120) -> AnalyzerResult:
    argv = tools.argv("bandit", "-r", ".", "-f", "json", "-q", "--exclude", ",".join(f"./{d}" for d in sorted(SKIP)))
    r, early = _exec(root, argv, "python", timeout)
    if early:
        return _early("bandit", "security", early, r)
    try:
        d = json.loads(r.stdout[r.stdout.index("{"):]) if "{" in r.stdout else {}
    except ValueError:
        return AnalyzerResult("bandit", "security", "error", [], (r.stderr or r.stdout)[:200])
    sev = {"HIGH": "high", "MEDIUM": "medium", "LOW": "low"}
    fs = [Finding("bandit", "security", _rel(x["filename"], root), x.get("line_number", 0), x.get("test_id", ""), f"{x.get('issue_text', '')} ({x.get('test_name', '')})",
                  sev.get(x.get("issue_severity", "LOW"), "low"), False, 0, f"CWE-{(x.get('issue_cwe') or {}).get('id')}" if x.get("issue_cwe") else "", x.get("issue_confidence", "").lower())
          for x in d.get("results", [])]
    return _result("bandit", "security", r, fs, command="bandit -r .")


def run_semgrep(root: Path, timeout: int = 240) -> AnalyzerResult:
    rules = "/opt/semgrep-rules" if sandbox_exec.mode() == "docker" else str(LOCAL_RULES)
    argv = tools.argv("semgrep", "--config", rules, "--json", "--metrics=off", "--disable-version-check", "--quiet", "--timeout", "30", "--exclude", "node_modules", "--exclude", ".venv", ".")
    r, early = _exec(root, argv, "python", timeout, env={"SEMGREP_SEND_METRICS": "off", "XDG_CACHE_HOME": "/tmp/.cache"})
    if early:
        return _early("semgrep", "security", early, r)
    try:
        d = json.loads(r.stdout[r.stdout.index("{"):]) if "{" in r.stdout else {}
    except ValueError:
        return AnalyzerResult("semgrep", "security", "error", [], (r.stderr or r.stdout)[:200])
    sev = {"ERROR": "high", "WARNING": "medium", "INFO": "low"}
    fs = []
    for x in d.get("results", []):
        meta = (x.get("extra") or {}).get("metadata") or {}
        cwe = meta.get("cwe")
        fs.append(Finding("semgrep", "security", _rel(x.get("path", ""), root), (x.get("start") or {}).get("line", 0), x.get("check_id", "").rsplit(".", 1)[-1], (x.get("extra") or {}).get("message", "")[:300],
                          sev.get((x.get("extra") or {}).get("severity", "INFO"), "low"), False, (x.get("start") or {}).get("col", 0), cwe[0] if isinstance(cwe, list) and cwe else (cwe or "")))
    return _result("semgrep", "security", r, fs, command="semgrep --config <rules> .")


def _pinned_requirements(root: Path) -> list[str]:
    return [f for f in ("requirements.txt", "requirements-dev.txt", "requirements/base.txt", "requirements/prod.txt") if (root / f).is_file()]


def run_pip_audit(root: Path, timeout: int = 180) -> AnalyzerResult:
    if not get_settings().sandbox_audit_network:
        return AnalyzerResult("pip-audit", "dependency", "skipped", [], "needs access to the vulnerability database: set SANDBOX_AUDIT_NETWORK=true to allow this one networked, read-only, non-executing step")
    files = _pinned_requirements(root)
    if not files:
        return AnalyzerResult("pip-audit", "dependency", "skipped", [], "no requirements.txt found")
    findings: list[Finding] = []
    last = None
    for f in files[:2]:
        argv = tools.argv("pip-audit", "-r", f, "-f", "json", "--disable-pip", "--no-deps", "--progress-spinner", "off")
        r, early = _exec(root, argv, "python", timeout, network=True)
        if early:
            return _early("pip-audit", "dependency", early, r)
        last = r
        text = r.stdout[r.stdout.index("{"):] if "{" in r.stdout else ""
        if not text:
            return AnalyzerResult("pip-audit", "dependency", "error", [], (r.stderr or "no output")[-250:])
        try:
            d = json.loads(text)
        except ValueError:
            return AnalyzerResult("pip-audit", "dependency", "error", [], (r.stderr or r.stdout)[:200])
        for dep in d.get("dependencies", []):
            for v in dep.get("vulns", []):
                fix = ", ".join(v.get("fix_versions") or [])
                findings.append(Finding("pip-audit", "dependency", f, 0, v.get("id", ""), f"{dep['name']} {dep.get('version', '')}: {(v.get('description') or 'known vulnerability')[:160]}",
                                        "high", False, 0, ", ".join(a for a in v.get("aliases", []) if a.startswith("CVE-"))[:60], "", f"upgrade to {fix}" if fix else ""))
    res = _result("pip-audit", "dependency", last, findings, command="pip-audit -r requirements.txt")
    res.note = "pip-audit does not report severities; every known vulnerability is shown as high"
    return res


def run_npm_audit(root: Path, timeout: int = 180) -> AnalyzerResult:
    if not get_settings().sandbox_audit_network:
        return AnalyzerResult("npm audit", "dependency", "skipped", [], "needs access to the npm advisory database: set SANDBOX_AUDIT_NETWORK=true to allow this one networked, read-only step")
    if not (root / "package-lock.json").is_file():
        return AnalyzerResult("npm audit", "dependency", "skipped", [], "no package-lock.json (npm audit needs one)")
    r, early = _exec(root, ["npm", "audit", "--json", "--package-lock-only"], "node", timeout, network=True, env={"npm_config_cache": "/tmp/.npm", "npm_config_update_notifier": "false"})
    if early:
        return _early("npm audit", "dependency", early, r)
    try:
        d = json.loads(r.stdout[r.stdout.index("{"):]) if "{" in r.stdout else {}
    except ValueError:
        return AnalyzerResult("npm audit", "dependency", "error", [], (r.stderr or r.stdout)[:200])
    if d.get("error"):
        return AnalyzerResult("npm audit", "dependency", "error", [], str((d["error"] or {}).get("summary") or d["error"])[:200])
    sev = {"critical": "critical", "high": "high", "moderate": "medium", "low": "low", "info": "info"}
    fs = []
    for name, v in (d.get("vulnerabilities") or {}).items():
        via = [x for x in v.get("via", []) if isinstance(x, dict)]
        title = (via[0].get("title") if via else "") or "vulnerable dependency"
        fix = v.get("fixAvailable")
        fs.append(Finding("npm audit", "dependency", "package-lock.json", 0, (via[0].get("url", "").rsplit("/", 1)[-1] if via else "") or name, f"{name} {v.get('range', '')}: {title}"[:240],
                          sev.get(v.get("severity", "low"), "low"), False, 0, "", "", ("run npm audit fix" + (f" (upgrade {fix['name']} to {fix['version']})" if isinstance(fix, dict) else "")) if fix else ""))
    return _result("npm audit", "dependency", r, fs, command="npm audit --package-lock-only")


# ---- JavaScript / Go / Rust -------------------------------------------------------------------------------------------------------------------
def run_eslint(root: Path, timeout: int = 180) -> AnalyzerResult:
    has_cfg = any((root / f).exists() for f in (".eslintrc", ".eslintrc.js", ".eslintrc.cjs", ".eslintrc.json", ".eslintrc.yml", "eslint.config.js", "eslint.config.mjs", "eslint.config.cjs")) \
        or '"eslintConfig"' in ((root / "package.json").read_text(errors="ignore") if (root / "package.json").is_file() else "")
    if not has_cfg:
        return AnalyzerResult("eslint", "lint", "skipped", [], "no ESLint configuration in the project")
    local = (root / "node_modules" / ".bin" / "eslint").exists()
    argv = ["node_modules/.bin/eslint", "-f", "json", "."] if local else ["eslint", "-f", "json", "."]
    r, early = _exec(root, argv, "node", timeout)
    if early:
        return _early("eslint", "lint", early, r)
    try:
        data = json.loads(r.stdout[r.stdout.index("["):]) if "[" in r.stdout else []
    except ValueError:
        return AnalyzerResult("eslint", "lint", "error", [], (r.stderr or r.stdout)[:200])
    fs = []
    for f in data:
        for m in f.get("messages", []):
            blocking = bool(m.get("fatal")) or m.get("ruleId") == "no-undef"
            fs.append(Finding("eslint", "lint", _rel(f["filePath"], root), m.get("line", 0), m.get("ruleId") or "parse-error", m.get("message", ""),
                              "high" if blocking else "medium" if m.get("severity") == 2 else "low", blocking, m.get("column", 0)))
    return _result("eslint", "lint", r, fs, command="eslint .")


def run_go_vet(root: Path, timeout: int = 180) -> AnalyzerResult:
    r, early = _exec(root, ["go", "vet", "./..."], "go", timeout, env={"GOFLAGS": "-mod=mod", "GOCACHE": "/tmp/gocache", "GOPATH": "/tmp/gopath"})
    if early:
        return _early("go vet", "lint", early, r)
    fs = [Finding("go vet", "lint", _rel(m["file"], root), int(m["line"]), "vet", m["msg"], "medium", False, int(m["col"] or 0))
          for m in re.finditer(r"^(?P<file>[^\s:#][^:\n]*\.go):(?P<line>\d+):(?:(?P<col>\d+):)?\s*(?P<msg>.+)$", r.stderr + "\n" + r.stdout, re.M)]
    return _result("go vet", "lint", r, fs, command="go vet ./...")


def run_clippy(root: Path, timeout: int = 300) -> AnalyzerResult:
    r, early = _exec(root, ["cargo", "clippy", "--message-format=json", "--quiet", "--offline"], "rust", timeout, env={"CARGO_HOME": "/tmp/cargo", "CARGO_TARGET_DIR": "/tmp/target"})
    if early:
        return _early("clippy", "lint", early, r)
    fs = []
    for line in r.stdout.splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        m = e.get("message") if e.get("reason") == "compiler-message" else None
        if not m or m.get("level") not in ("warning", "error"):
            continue
        span = next((s for s in m.get("spans", []) if s.get("is_primary")), None)
        if span:
            fs.append(Finding("clippy", "lint", span["file_name"], span.get("line_start", 0), (m.get("code") or {}).get("code") or "clippy", m["message"][:240],
                              "high" if m["level"] == "error" else "low", m["level"] == "error", span.get("column_start", 0)))
    return _result("clippy", "lint", r, fs, command="cargo clippy")


# ---- registry ---------------------------------------------------------------------------------------------------------------------------------------
@dataclass
class Analyzer:
    name: str
    category: str
    languages: tuple[str, ...]
    run: object
    applies: object
    label: str = ""


def _has(root: Path, *exts: str) -> bool:
    return bool(_files(root, tuple(exts))[:1])


ANALYZERS: dict[str, Analyzer] = {a.name: a for a in [
    Analyzer("ruff", "lint", ("python",), run_ruff, lambda r: _has(r, ".py"), "Ruff"),
    Analyzer("pylint", "lint", ("python",), run_pylint, lambda r: _has(r, ".py"), "Pylint"),
    Analyzer("mypy", "types", ("python",), run_mypy, lambda r: _has(r, ".py"), "mypy"),
    Analyzer("bandit", "security", ("python",), run_bandit, lambda r: _has(r, ".py"), "Bandit"),
    Analyzer("semgrep", "security", ("python", "javascript"), run_semgrep, lambda r: _has(r, ".py", ".js", ".jsx", ".ts", ".tsx"), "Semgrep"),
    Analyzer("pip-audit", "dependency", ("python",), run_pip_audit, lambda r: bool(_pinned_requirements(r)), "pip-audit"),
    Analyzer("eslint", "lint", ("javascript",), run_eslint, lambda r: _has(r, ".js", ".jsx", ".ts", ".tsx", ".mjs"), "ESLint"),
    Analyzer("npm-audit", "dependency", ("javascript",), run_npm_audit, lambda r: (r / "package-lock.json").is_file(), "npm audit"),
    Analyzer("go-vet", "lint", ("go",), run_go_vet, lambda r: (r / "go.mod").is_file(), "go vet"),
    Analyzer("clippy", "lint", ("rust",), run_clippy, lambda r: (r / "Cargo.toml").is_file(), "Clippy"),
]}


def applicable(root: Path) -> list[str]:
    return [n for n, a in ANALYZERS.items() if a.applies(root)]


def run(root: Path, name: str, timeout: int | None = None) -> AnalyzerResult:
    a = ANALYZERS.get(name)
    if a is None:
        raise ValueError(f"unknown analyzer {name!r}; available: {', '.join(ANALYZERS)}")
    t0 = time.time()
    res = a.run(root, timeout) if timeout else a.run(root)
    res.duration_ms = res.duration_ms or int((time.time() - t0) * 1000)
    return res
