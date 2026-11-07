"""Tool implementations beyond code search: git history, docs, configuration, project inspection, optional web search.
Everything here is read-only. Secrets are never returned: secret FILES are refused and secret-looking VALUES are masked."""
from __future__ import annotations
import json
import os
import re
import shutil
from pathlib import Path

from .. import gitops, sandbox
from ..retrieval.bm25 import BM25, top_n
from ..utils import safe_path, tokenize

# ---- secrets -----------------------------------------------------------------------------------------------------------
SECRET_NAME = re.compile(r"(?i)(secret|token|passw(or)?d|passwd|api[_-]?key|private[_-]?key|credential|auth[_-]?key|access[_-]?key|signing[_-]?key|client[_-]?secret)")
_ASSIGN = re.compile(r"""(?ix)
    (?P<key>[\w.\-]*(?:secret|token|passw(?:or)?d|passwd|api[_-]?key|private[_-]?key|credential|access[_-]?key|signing[_-]?key)[\w.\-]*)
    (?P<sep>["']?\s*[:=]\s*)
    (?P<q>["']?)(?P<val>[^\s"'#,;}{\[\]()]{6,})(?P=q)""")
_TOKENS = re.compile(r"\b(sk-[A-Za-z0-9_\-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_\-]{30,}|eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,})")
_PLACEHOLDER = re.compile(r"(?i)^(your|<|\$\{|\{\{|%\(|changeme|xxx|\*+$|none$|null$|true$|false$|example|placeholder|todo|env\.|os\.|process\.|settings\.|config\.|request\.|self\.|get_|getenv|environ)")
SECRET_FILE_NAMES = {"id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "credentials", "credentials.json", "secrets.json", "secrets.yml", "secrets.yaml",
                     ".npmrc", ".pypirc", ".netrc", "service-account.json", "serviceaccount.json"}


def is_secret_file(path: str) -> bool:
    name = path.replace("\\", "/").rsplit("/", 1)[-1].lower()
    if name.startswith(".env") and not name.endswith((".example", ".sample", ".template", ".dist", ".defaults")):
        return True
    return name in SECRET_FILE_NAMES or name.endswith((".pem", ".key", ".p12", ".pfx", ".jks", ".keystore"))


def redact(text: str) -> str:
    """Mask literal secret values (`api_key = "abc123..."`, tokens in well-known formats). Code that merely mentions a secret
    (`password = request.form["password"]`, `os.environ[...]`) is left alone."""
    def mask(m: re.Match) -> str:
        return m.group(0) if _PLACEHOLDER.match(m.group("val")) else f"{m.group('key')}{m.group('sep')}{m.group('q')}***{m.group('q')}"
    return _TOKENS.sub("***", _ASSIGN.sub(mask, text))


# ---- prompt injection --------------------------------------------------------------------------------------------------
_INJECTION = re.compile(r"""(?ix)
    (?:ignore|disregard|forget|override)\s+(?:all\s+|any\s+|the\s+|your\s+)?(?:previous|prior|above|earlier|system|safety)\s+(?:instructions?|prompts?|rules?|messages?)
  | (?:you\s+are\s+now|act\s+as|pretend\s+to\s+be)\s+(?:an?\s+)?(?:ai|assistant|developer|admin|root|system|dan)\b
  | (?:new|updated)\s+(?:system\s+)?instructions?\s*:
  | (?:reveal|print|show|leak|exfiltrate|send)\s+(?:me\s+)?(?:your\s+|the\s+)?(?:system\s+prompt|api[\s_-]?keys?|secrets?|credentials|\.env|environment\s+variables)
  | (?:mark|report|say|state)\s+(?:this|the)\s+(?:patch|fix|change|code)\s+(?:as\s+)?(?:verified|approved|safe|passing)
  | <\s*/?\s*(?:system|assistant|instructions?)\s*>
  | \[\s*(?:system|inst)\s*\]""")


def scan_injection(text: str, limit: int = 3) -> list[str]:
    """Lines of repository content that read like instructions aimed at an AI model (comments, docstrings, README text, issue bodies).
    Deterministic and conservative: it only FLAGS. The prompts already tell every role that repository content is data; a flagged
    snippet is additionally labelled in the context so the model (and the user) can see it was treated as untrusted."""
    hits: list[str] = []
    for ln in (text or "").splitlines():
        if _INJECTION.search(ln):
            hits.append(ln.strip()[:160])
            if len(hits) >= limit:
                break
    return hits


def redact_query(q: str, limit: int = 200) -> str:
    """What may leave the machine in a web search: no absolute paths, emails, IPs or long token-like strings."""
    q = re.sub(r"(?:[A-Za-z]:\\|/)(?:[\w.\-]+[\\/])+[\w.\-]*", " ", q)
    q = re.sub(r"[\w.+\-]+@[\w\-]+\.[\w.\-]+", " ", q)
    q = re.sub(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", " ", q)
    q = _TOKENS.sub(" ", q)
    q = re.sub(r"\b[A-Za-z0-9_\-]{28,}\b", " ", q)
    return re.sub(r"\s+", " ", q).strip()[:limit]


# ---- git ---------------------------------------------------------------------------------------------------------------
_REF = re.compile(r"^[\w./~^@{}\-]{1,80}$")


def _git(tools, *args: str, limit: int = 6000) -> str:
    if not gitops.ensure_repo(tools.root):
        return "git is not available on this server."
    try:
        out = gitops._git(tools.root, *args, timeout=30).stdout
    except gitops.GitError as e:
        return f"git failed: {e}"
    out = redact(out)
    return out if len(out) <= limit else out[:limit] + f"\n... (truncated, {len(out) - limit} more characters)"


def _path_arg(tools, path: str | None) -> list[str]:
    if not path:
        return []
    safe_path(tools.root, path)           # raises on traversal
    return ["--", path]


def git_status(tools) -> str:
    st = gitops.status(tools.root)
    if not st["available"]:
        return "git is not available on this server."
    if not st["files"]:
        return f"branch {st['branch']}: working tree clean (no changes since the imported / committed version)."
    return f"branch {st['branch']}: {len(st['files'])} changed file(s)\n" + "\n".join(f"{f['status']:>10}  {f['path']}" for f in st["files"][:60])


def git_log(tools, path: str | None = None, n: int = 10) -> str:
    n = max(1, min(int(n or 10), 30))
    out = _git(tools, "log", f"-n{n}", "--date=short", "--format=%h  %ad  %an  %s", *_path_arg(tools, path))
    return out.strip() or "no commits" + (f" touching {path}" if path else "")


def git_diff(tools, path: str | None = None, ref: str | None = None, staged: bool = False) -> str:
    if ref and (not _REF.match(ref) or ref.startswith("-")):
        return f"invalid ref {ref!r}"
    args = ["diff", "--no-color", "--no-ext-diff", "--no-textconv"] + (["--cached"] if staged else []) + ([ref] if ref else []) + _path_arg(tools, path)
    out = _git(tools, *args)
    return out.strip() or "no differences" + (f" in {path}" if path else "")


# ---- docs --------------------------------------------------------------------------------------------------------------
DOC_EXT = (".md", ".rst", ".txt", ".adoc", ".markdown")
SECTION_LINES = 40


def _doc_sections(tools) -> list[dict]:
    out = []
    for rel in tools.index.tree:
        if not rel.lower().endswith(DOC_EXT) or rel.rsplit("/", 1)[-1].lower() in ("license.txt", "requirements.txt") or "requirements" in rel.lower():
            continue
        try:
            lines = safe_path(tools.root, rel).read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError, ValueError):
            continue
        starts = [i for i, l in enumerate(lines) if re.match(r"^#{1,4}\s", l) or (i and re.match(r"^(=+|-{3,})\s*$", l) and lines[i - 1].strip())] or [0]
        if starts[0] != 0:
            starts.insert(0, 0)
        for a, b in zip(starts, starts[1:] + [len(lines)]):
            for s in range(a, b, SECTION_LINES):
                e = min(b, s + SECTION_LINES)
                body = "\n".join(lines[s:e]).strip()
                if len(body) < 20:
                    continue
                heading = re.sub(r"^#+\s*", "", lines[a]).strip() or rel
                out.append({"file": rel, "start": s + 1, "end": e, "heading": heading[:80], "text": body})
    return out


def search_docs(tools, query: str, k: int = 5) -> list[dict]:
    """BM25 over README / docs sections. Returns chunk-shaped dicts so they join the evidence like code does."""
    cache = getattr(tools, "_doc_cache", None)
    if cache is None:
        secs = _doc_sections(tools)
        cache = tools._doc_cache = (secs, BM25([tokenize(f"{s['heading']} {s['heading']} {s['file']} {s['text']}") for s in secs]) if secs else None)
    secs, bm = cache
    if not bm:
        return []
    scores = bm.scores(tokenize(query))
    out = []
    for i in top_n(scores, max(1, min(k, 8)), positive_only=True):
        s = secs[i]
        out.append({"id": f"doc:{s['file']}:{s['start']}", "file": s["file"], "kind": "doc", "name": s["heading"], "qualname": f"{s['file']}#{s['heading']}",
                    "start": s["start"], "end": s["end"], "text": redact(s["text"]), "via": "docs", "route": None, "score": round(float(scores[i]), 3)})
    return out


# ---- configuration -------------------------------------------------------------------------------------------------------
CONFIG_EXT = (".json", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".conf", ".properties", ".env.example", ".env.sample", ".env.template")
CONFIG_PY = re.compile(r"(^|/)(settings|config|configuration|conf|constants)(_\w+)?\.py$|(^|/)(settings|config)/[\w/]+\.py$")
SKIP_CONFIG = ("package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "composer.lock", "tsconfig.tsbuildinfo")


def config_files(tools) -> list[str]:
    out = []
    for rel in tools.index.tree:
        low = rel.lower()
        if is_secret_file(rel) or low.rsplit("/", 1)[-1] in SKIP_CONFIG or "node_modules/" in low:
            continue
        if low.endswith(CONFIG_EXT) or CONFIG_PY.search(low) or low.rsplit("/", 1)[-1] in ("dockerfile", "docker-compose.yml", "makefile", "procfile"):
            out.append(rel)
    return out


def find_config(tools, query: str, limit: int = 15) -> dict:
    """Configuration lines related to `query` (auth, database, timeout, ...). Secret values are masked."""
    terms = {t for t in re.split(r"[^A-Za-z0-9]+", query.lower()) if len(t) >= 3}
    terms |= {t[:-3] for t in list(terms) if t.endswith(("ion", "ing")) and len(t) > 6}      # authentication -> authenticat ~ auth
    terms |= {t[:4] for t in list(terms) if len(t) >= 7}
    hits = []
    for rel in config_files(tools):
        try:
            lines = safe_path(tools.root, rel).read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError, ValueError):
            continue
        if len(lines) > 3000:
            continue
        for n, line in enumerate(lines, 1):
            low = line.lower()
            matched = {t for t in terms if t in low}
            if matched and not line.strip().startswith(("#", "//")) or (matched and len(matched) > 1):
                hits.append((len(matched) + (0.5 if rel.endswith(".py") else 0), rel, n, line, lines))
    hits.sort(key=lambda h: (-h[0], h[1], h[2]))
    matches, chunks, seen = [], [], set()
    for _, rel, n, line, lines in hits[:limit]:
        matches.append({"file": rel, "line": n, "text": redact(line.strip())[:200]})
        key = (rel, n // 8)
        if key not in seen and len(chunks) < 5:
            seen.add(key)
            a, b = max(0, n - 4), min(len(lines), n + 4)
            chunks.append({"id": f"cfg:{rel}:{a + 1}", "file": rel, "kind": "config", "name": rel, "qualname": f"{rel}:{a + 1}-{b}", "start": a + 1, "end": b,
                           "text": redact("\n".join(lines[a:b])), "via": "config", "route": None})
    return {"matches": matches, "chunks": chunks, "files_scanned": len(config_files(tools))}


# ---- project inspection ----------------------------------------------------------------------------------------------------
LANG = {".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript (React)", ".ts": "TypeScript", ".tsx": "TypeScript (React)", ".java": "Java", ".go": "Go",
        ".rs": "Rust", ".c": "C", ".cpp": "C++", ".h": "C/C++ header", ".sql": "SQL", ".html": "HTML", ".css": "CSS", ".sh": "Shell", ".md": "Markdown"}
FRAMEWORKS = {"flask": "Flask", "django": "Django", "fastapi": "FastAPI", "starlette": "Starlette", "tornado": "Tornado", "sqlalchemy": "SQLAlchemy",
              "celery": "Celery", "pydantic": "Pydantic", "pytest": "pytest", "react": "React", "next": "Next.js", "vue": "Vue", "express": "Express",
              "nestjs": "NestJS", "@nestjs/core": "NestJS", "jest": "Jest", "vitest": "Vitest", "mocha": "Mocha", "typescript": "TypeScript",
              "spring-boot": "Spring Boot", "langchain": "LangChain", "langgraph": "LangGraph", "numpy": "NumPy", "pandas": "pandas", "torch": "PyTorch"}
ENTRY_NAMES = ("main.py", "app.py", "manage.py", "wsgi.py", "asgi.py", "run.py", "cli.py", "__main__.py", "server.py", "server.js", "index.js", "app.js", "main.ts",
               "index.ts", "src/index.js", "src/index.ts", "src/main.ts", "src/app.py", "app/main.py", "main.go", "cmd/main.go")
LINT_CONFIGS = ("ruff.toml", ".ruff.toml", ".flake8", ".pylintrc", ".eslintrc", ".eslintrc.js", ".eslintrc.json", ".eslintrc.cjs", "eslint.config.js", "eslint.config.mjs",
                ".pre-commit-config.yaml", ".prettierrc", "mypy.ini")


def inspect_project(tools) -> dict:
    tree = tools.index.tree
    root = tools.root
    langs: dict[str, int] = {}
    for f in tree:
        lang = LANG.get(os.path.splitext(f)[1].lower())
        if lang and lang != "Markdown":
            langs[lang] = langs.get(lang, 0) + 1
    deps = tools.index.deps or {}
    names = {str(d).lower().split("[")[0].split("=")[0].split(">")[0].split("<")[0].strip() for k in ("python", "node") for d in deps.get(k, [])}
    frameworks = sorted({v for k, v in FRAMEWORKS.items() if k in names})
    entries = [f for f in tree if f in ENTRY_NAMES or f.endswith("/" + "__main__.py")][:8]
    scripts: dict = {}
    pkg = root / "package.json"
    if pkg.is_file():
        try:
            data = json.loads(pkg.read_text())
            scripts = {k: v for k, v in (data.get("scripts") or {}).items() if k in ("start", "dev", "build", "test", "lint")}
            if data.get("main"):
                entries.append(data["main"])
        except (OSError, ValueError):
            pass
    pyproject = (root / "pyproject.toml").read_text(errors="ignore") if (root / "pyproject.toml").is_file() else ""
    tests = [f for f in tree if re.search(r"(^|/)(tests?|__tests__)/|(^|/)test_[^/]*\.py$|\.(test|spec)\.[jt]sx?$", f)]
    lint_cfg = [f for f in tree if f.rsplit("/", 1)[-1] in LINT_CONFIGS] + (["pyproject.toml [tool.ruff]"] if "[tool.ruff" in pyproject else [])
    top: dict[str, int] = {}
    for f in tree:
        k = f.split("/")[0] + "/" if "/" in f else "(root files)"
        top[k] = top.get(k, 0) + 1
    st = gitops.status(root) if gitops.available() else {"available": False}
    last = ""
    if st.get("available"):
        last = _git(tools, "log", "-n1", "--date=short", "--format=%h %ad %s", limit=200).strip()
    return {"name": root.name, "files": len(tree), "languages": dict(sorted(langs.items(), key=lambda x: -x[1])), "frameworks": frameworks,
            "entry_points": list(dict.fromkeys(entries)), "scripts": scripts, "config_files": config_files(tools)[:25],
            "layout": dict(sorted(top.items(), key=lambda x: -x[1])[:12]),
            "tests": {"files": len(tests), "runner": "pytest" if ("pytest" in names or "pytest" in pyproject or (root / "pytest.ini").exists()) else
                      next((n for n in ("jest", "vitest", "mocha") if n in names), "unittest/unknown"), "command": " ".join(sandbox.detect_command(root)).replace(os.sys.executable, "python")},
            "lint": {"configs": lint_cfg, "ruff_installed": bool(shutil.which("ruff")) or _has_module("ruff"), "eslint_installed": (root / "node_modules/.bin/eslint").exists()},
            "dependencies": {"python": len(deps.get("python", [])), "node": len(deps.get("node", [])), "manifests": deps.get("files", [])[:8]},
            "git": {"available": bool(st.get("available")), "branch": st.get("branch", ""), "changed_files": len(st.get("files", [])), "last_commit": last}}


def _has_module(name: str) -> bool:
    import importlib.util
    return importlib.util.find_spec(name) is not None


# ---- web search ------------------------------------------------------------------------------------------------------------
class WebSearch:
    """Optional. Providers: Brave Search API (BRAVE_API_KEY) or Tavily (TAVILY_API_KEY), chosen by WEB_SEARCH_PROVIDER.
    Queries are scrubbed of paths / emails / IPs / tokens first; results are returned as UNTRUSTED text (they can contain prompt injection)."""

    def __init__(self, provider: str = "", brave_key: str = "", tavily_key: str = "", client=None) -> None:
        self.provider = (provider or ("brave" if brave_key else "tavily" if tavily_key else "")).lower()
        self.key = brave_key if self.provider == "brave" else tavily_key if self.provider == "tavily" else ""
        self._client = client

    @property
    def available(self) -> bool:
        return bool(self.provider and self.key)

    def search(self, query: str, n: int = 5) -> list[dict]:
        import httpx
        if not self.available:
            raise ValueError("web search is not configured (set WEB_SEARCH_PROVIDER and BRAVE_API_KEY or TAVILY_API_KEY)")
        q = redact_query(query)
        if not q:
            raise ValueError("the query was empty after removing paths, emails and tokens")
        n = max(1, min(int(n or 5), 8))
        client = self._client or httpx.Client(timeout=12.0, follow_redirects=False)
        if self.provider == "brave":
            r = client.get("https://api.search.brave.com/res/v1/web/search", params={"q": q, "count": n},
                           headers={"Accept": "application/json", "X-Subscription-Token": self.key})
            r.raise_for_status()
            rows = (r.json().get("web") or {}).get("results") or []
            return [{"title": x.get("title", ""), "url": x.get("url", ""), "snippet": re.sub(r"<[^>]+>", "", x.get("description") or "")} for x in rows[:n]]
        if self.provider == "tavily":
            r = client.post("https://api.tavily.com/search", json={"query": q, "max_results": n, "search_depth": "basic", "include_answer": False},
                            headers={"Authorization": f"Bearer {self.key}"})
            r.raise_for_status()
            return [{"title": x.get("title", ""), "url": x.get("url", ""), "snippet": x.get("content", "")} for x in (r.json().get("results") or [])[:n]]
        raise ValueError("web search is not configured (set WEB_SEARCH_PROVIDER and BRAVE_API_KEY or TAVILY_API_KEY)")
