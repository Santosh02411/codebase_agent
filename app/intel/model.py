from __future__ import annotations
import re
from dataclasses import asdict, dataclass, field, fields
from pathlib import PurePosixPath

EXTRACTOR_VERSION = 3  # bump when extraction output changes: cached per-file facts are then recomputed

LANG_BY_EXT = {
    ".py": "python", ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".java": "java", ".go": "go", ".rs": "rust",
    ".c": "c", ".h": "c", ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp",
    ".md": "markdown", ".json": "json", ".yml": "yaml", ".yaml": "yaml", ".toml": "toml", ".sql": "sql",
    ".sh": "shell", ".html": "html", ".css": "css", ".ini": "ini", ".cfg": "ini", ".txt": "text",
}
CODE_LANGS = {"python", "javascript", "typescript", "java", "go", "rust", "c", "cpp"}
SYMBOL_KINDS = {"function", "method", "class", "interface", "struct", "enum", "trait", "type"}  # carry a body worth a chunk
VALUE_KINDS = {"variable", "constant", "macro"}


def language_of(path: str) -> str:
    return LANG_BY_EXT.get(PurePosixPath(path).suffix.lower(), "text")


_TEST_PATH = re.compile(r"(^|/)(tests?|__tests__|spec)/|(^|/)test_[^/]*$|_test\.(py|go|rs|c|cpp)$|\.(test|spec)\.[jt]sx?$|(Test|Tests|IT)\.java$")


def is_test_path(path: str) -> bool:
    return bool(_TEST_PATH.search(path))


@dataclass
class Symbol:
    file: str = ""
    language: str = ""
    kind: str = ""
    name: str = ""
    qualname: str = ""
    start: int = 0
    end: int = 0
    id: str = ""
    signature: str = ""
    doc: str = ""
    parent: str = ""
    route: str = ""
    decorators: list[str] = field(default_factory=list)
    bases: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    exported: bool = False
    extra: dict = field(default_factory=dict)


@dataclass
class ImportRef:
    module: str = ""
    names: list[list[str]] = field(default_factory=list)  # [[original, alias or ""], ...]
    alias: str = ""   # `import a.b as x` / `import * as x` / `import x` (JS default)
    level: int = 0    # python relative level; c/c++: 1 for "local.h", 0 for <system.h>
    line: int = 0
    kind: str = ""    # "", "mod" (rust), "reexport", "require"


@dataclass
class ApiRoute:
    method: str = ""
    path: str = ""
    handler: str = ""
    line: int = 0
    framework: str = ""


@dataclass
class FileFacts:
    path: str = ""
    language: str = ""
    hash: str = ""
    lines: int = 0
    parser: str = ""
    symbols: list[Symbol] = field(default_factory=list)
    imports: list[ImportRef] = field(default_factory=list)
    apis: list[ApiRoute] = field(default_factory=list)
    tests: list[dict] = field(default_factory=list)   # [{name, line}]
    todos: list[dict] = field(default_factory=list)   # [{line, text}]
    comment_lines: int = 0
    is_test: bool = False
    module_doc: str = ""
    package: str = ""  # java/go package name
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "FileFacts":
        def build(klass, x):
            names = {f.name for f in fields(klass)}
            return klass(**{k: v for k, v in x.items() if k in names})
        out = build(cls, {k: v for k, v in d.items() if k not in ("symbols", "imports", "apis")})
        out.symbols = [build(Symbol, s) for s in d.get("symbols", [])]
        out.imports = [build(ImportRef, i) for i in d.get("imports", [])]
        out.apis = [build(ApiRoute, a) for a in d.get("apis", [])]
        return out


def finalize_ids(facts: FileFacts) -> None:
    """Stable, unique symbol ids: `file::qualname` (+ `@line` when the same qualname appears twice)."""
    seen: dict[str, int] = {}
    for s in facts.symbols:
        base = f"{s.file}::{s.qualname}"
        seen[base] = seen.get(base, 0) + 1
        s.id = base if seen[base] == 1 else f"{base}@{s.start}"


TODO_RE = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b[:\s]*(.*)", re.I)


def clean_comment(text: str) -> str:
    out = []
    for line in text.splitlines():
        line = line.strip()
        line = re.sub(r"^(/\*\*?|\*/|\*|//[/!]?|#+|--)\s?", "", line)
        line = re.sub(r"\s?\*/$", "", line)
        if line:
            out.append(line.strip())
    return " ".join(out)[:300]
