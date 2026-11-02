"""Shared Tree-sitter plumbing: lazy parser loading and a Visitor base class with the helpers every language needs."""
from __future__ import annotations
import importlib
import re
from functools import lru_cache

from .model import FileFacts, Symbol, TODO_RE, clean_comment, finalize_ids, is_test_path

# language key -> (python module, language() function)
GRAMMARS = {
    "python": ("tree_sitter_python", "language"),
    "javascript": ("tree_sitter_javascript", "language"),
    "typescript": ("tree_sitter_typescript", "language_typescript"),
    "tsx": ("tree_sitter_typescript", "language_tsx"),
    "java": ("tree_sitter_java", "language"),
    "c": ("tree_sitter_c", "language"),
    "cpp": ("tree_sitter_cpp", "language"),
    "go": ("tree_sitter_go", "language"),
    "rust": ("tree_sitter_rust", "language"),
}
EXT_TO_GRAMMAR = {
    ".py": "python", ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "tsx", ".java": "java", ".c": "c", ".h": "c", ".cpp": "cpp", ".cc": "cpp",
    ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp", ".go": "go", ".rs": "rust",
}


@lru_cache(maxsize=None)
def get_parser(key: str):
    """A Parser for `key`, or None when tree-sitter or that grammar package isn't installed."""
    spec = GRAMMARS.get(key)
    if not spec:
        return None
    try:
        from tree_sitter import Language, Parser

        module = importlib.import_module(spec[0])
        return Parser(Language(getattr(module, spec[1])()))
    except Exception:  # noqa: BLE001 - missing wheel, ABI mismatch, ...
        return None


def available_grammars() -> dict[str, bool]:
    return {k: get_parser(k) is not None for k in GRAMMARS}


def norm_callee(s: str) -> str:
    """'a.b(c).d' -> '?.d', 'std::vec::push' -> 'std.vec.push', 'obj->m' -> 'obj.m'."""
    s = re.sub(r"\s+", "", s).replace("::", ".").replace("->", ".")
    while True:
        t = re.sub(r"<[^<>]*>", "", s)
        if t == s:
            break
        s = t
    if "(" in s or "[" in s or "{" in s:
        last = re.split(r"[.]", s)[-1]
        m = re.match(r"[A-Za-z_$][\w$]*", last)
        return f"?.{m.group(0)}" if m else ""
    return s if re.fullmatch(r"[\w$.?]+", s) else ""


class Visitor:
    """Base for per-language extractors. Subclasses implement `run()` and fill `self.facts`."""

    language = ""
    call_types: tuple[str, ...] = ("call_expression",)

    def __init__(self, path: str, src: bytes, root, grammar: str) -> None:
        self.path, self.src, self.root, self.grammar = path, src, root, grammar
        self.facts = FileFacts(path=path, language=self.language, parser=f"tree-sitter:{grammar}",
                               lines=src.count(b"\n") + 1, is_test=is_test_path(path))
        if root.has_error:
            self.facts.errors.append("syntax errors: partial parse")

    # ---- node helpers ------------------------------------------------------------------------
    def t(self, n) -> str:
        return self.src[n.start_byte:n.end_byte].decode("utf-8", "replace") if n is not None else ""

    def fld(self, n, name: str):
        return n.child_by_field_name(name) if n is not None else None

    @staticmethod
    def span(n) -> tuple[int, int]:
        end = n.end_point[0] + (1 if n.end_point[1] > 0 else 0)
        return n.start_point[0] + 1, max(end, n.start_point[0] + 1)

    def signature(self, n, body_field: str = "body") -> str:
        body = self.fld(n, body_field)
        raw = self.src[n.start_byte:(body.start_byte if body is not None else n.end_byte)].decode("utf-8", "replace")
        sig = " ".join(raw.split())
        if body is None:
            sig = " ".join(self.t(n).splitlines()[:1]).strip()
        return sig[:220]

    def string_value(self, n) -> str:
        """Content of a string literal node, without quotes."""
        s = self.t(n).strip()
        if len(s) >= 2 and s[0] in "\"'`" and s[-1] == s[0]:
            return s[1:-1]
        if s.startswith(("r\"", "r#\"")):
            return s.strip("r#\"")
        return s

    def leading(self, n) -> tuple[str, list[str]]:
        """(doc comment text, attributes/decorators) directly above `n` (comments and `#[attr]`/`@Dec` siblings)."""
        doc_parts: list[str] = []
        attrs: list[str] = []
        prev, expect = n.prev_sibling, n.start_point[0]
        while prev is not None:
            ty = prev.type
            if "comment" in ty and prev.end_point[0] >= expect - 1:
                doc_parts.insert(0, self.t(prev))
            elif ty in ("attribute_item", "decorator") and prev.end_point[0] >= expect - 1:
                attrs.insert(0, self.t(prev))
            else:
                break
            expect = prev.start_point[0]
            prev = prev.prev_sibling
        return clean_comment("\n".join(doc_parts)), attrs

    # ---- symbols -----------------------------------------------------------------------------
    def add(self, kind: str, name: str, qual: str, node, parent: str = "", **kw) -> Symbol:
        s, e = self.span(node)
        sym = Symbol(file=self.path, language=self.language, kind=kind, name=name, qualname=qual, start=s, end=e, parent=parent, **kw)
        self.facts.symbols.append(sym)
        return sym

    # ---- calls -------------------------------------------------------------------------------
    def callee(self, n) -> str:
        if n.type in self.call_types:
            return self.t(self.fld(n, "function"))
        return ""

    def calls(self, node) -> list[str]:
        out: dict[str, None] = {}
        stack = [node]
        while stack:
            n = stack.pop()
            raw = self.callee(n)
            if raw:
                name = norm_callee(raw)
                if name:
                    out.setdefault(name, None)
            stack.extend(reversed(n.children))
        return list(out)

    def walk(self, node, types: set[str] | tuple[str, ...]):
        stack = [node]
        while stack:
            n = stack.pop()
            if n.type in types:
                yield n
            stack.extend(reversed(n.children))

    # ---- shared passes -----------------------------------------------------------------------
    def comment_pass(self) -> None:
        for n in self.walk(self.root, {"comment", "line_comment", "block_comment"}):
            s, e = n.start_point[0], n.end_point[0]
            self.facts.comment_lines += e - s + 1
            m = TODO_RE.search(self.t(n))
            if m:
                self.facts.todos.append({"line": s + 1, "text": f"{m.group(1).upper()}: {m.group(2).strip()}"[:160]})

    def run(self) -> None:  # pragma: no cover - overridden
        raise NotImplementedError

    def result(self) -> FileFacts:
        self.run()
        self.comment_pass()
        finalize_ids(self.facts)
        return self.facts
