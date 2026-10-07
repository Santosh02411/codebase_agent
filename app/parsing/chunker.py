from __future__ import annotations
import ast
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

LANG = {".py": "python", ".js": "javascript", ".jsx": "javascript", ".ts": "typescript", ".tsx": "typescript",
        ".java": "java", ".go": "go", ".rs": "rust", ".md": "markdown", ".json": "json", ".yml": "yaml",
        ".yaml": "yaml", ".toml": "toml", ".sql": "sql", ".sh": "shell", ".html": "html", ".css": "css"}


@dataclass
class Chunk:
    id: int
    file: str
    kind: str  # function | method | class | module | block
    name: str
    qualname: str
    start: int
    end: int
    text: str
    language: str
    calls: list[str] = field(default_factory=list)


def _calls(node: ast.AST) -> list[str]:
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name):
                out.add(f.id)
            elif isinstance(f, ast.Attribute):
                out.add(f.attr)
    return sorted(out)


def _span(node) -> tuple[int, int]:
    start = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
    return start, node.end_lineno


def chunk_python(path: str, text: str) -> list[Chunk]:
    """AST-aware chunking: one chunk per function / method / class header / module-level code."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return chunk_windows(path, text, "python")
    lines = text.splitlines()
    chunks: list[Chunk] = []
    covered: set[int] = set()
    funcs = (ast.FunctionDef, ast.AsyncFunctionDef)

    def emit(kind, name, qual, s, e, calls=None):
        chunks.append(Chunk(-1, path, kind, name, qual, s, e, "\n".join(lines[s - 1 : e]), "python", calls or []))

    for node in tree.body:
        if isinstance(node, funcs):
            s, e = _span(node)
            emit("function", node.name, node.name, s, e, _calls(node))
            covered.update(range(s, e + 1))
        elif isinstance(node, ast.ClassDef):
            s, e = _span(node)
            covered.update(range(s, e + 1))
            methods = [n for n in node.body if isinstance(n, funcs)]
            first = min((_span(m)[0] for m in methods), default=e + 1)
            emit("class", node.name, node.name, s, min(first - 1, e))
            for m in methods:
                ms, me = _span(m)
                emit("method", m.name, f"{node.name}.{m.name}", ms, me, _calls(m))
    rest = [i for i in range(1, len(lines) + 1) if i not in covered and lines[i - 1].strip()]
    if rest:
        body = "\n".join(lines[i - 1] for i in rest[:120])
        chunks.append(Chunk(-1, path, "module", "<module>", path, rest[0], rest[-1], body, "python"))
    return chunks


_JS = re.compile(
    r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?(function\*?|class)\s+(\w+)"
    r"|^(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?(?:\(|function|\w+\s*=>)"
)


def chunk_js(path: str, text: str, lang: str) -> list[Chunk]:
    """Regex-based top-level boundaries for JS/TS (interim; Tree-sitter planned)."""
    lines = text.splitlines()
    starts = []
    for i, line in enumerate(lines):
        m = _JS.match(line)
        if m:
            starts.append((i + 1, m.group(2) or m.group(3), "class" if m.group(1) == "class" else "function"))
    if not starts:
        return chunk_windows(path, text, lang)
    chunks = []
    if starts[0][0] > 1 and "\n".join(lines[: starts[0][0] - 1]).strip():
        chunks.append(Chunk(-1, path, "module", "<module>", path, 1, starts[0][0] - 1, "\n".join(lines[: starts[0][0] - 1]), lang))
    for n, (s, name, kind) in enumerate(starts):
        e = starts[n + 1][0] - 1 if n + 1 < len(starts) else len(lines)
        body = "\n".join(lines[s - 1 : e])
        calls = sorted(set(re.findall(r"\b(\w+)\s*\(", body)) - {name})
        chunks.append(Chunk(-1, path, kind, name, name, s, e, body, lang, calls))
    return chunks


def chunk_windows(path: str, text: str, lang: str, size: int = 50, overlap: int = 10) -> list[Chunk]:
    lines = text.splitlines()
    out, i = [], 0
    while i < len(lines):
        j = min(i + size, len(lines))
        body = "\n".join(lines[i:j])
        if body.strip():
            out.append(Chunk(-1, path, "block", f"{path}:{i + 1}", f"{path}:{i + 1}", i + 1, j, body, lang))
        if j == len(lines):
            break
        i = j - overlap
    return out


def chunk_file(path: str, text: str) -> list[Chunk]:
    if not text.strip():
        return []
    ext = PurePosixPath(path).suffix.lower()
    lang = LANG.get(ext, "text")
    if ext == ".py":
        return chunk_python(path, text)
    if ext in (".js", ".jsx", ".ts", ".tsx"):
        return chunk_js(path, text, lang)
    return chunk_windows(path, text, lang, size=40 if ext == ".md" else 50)
