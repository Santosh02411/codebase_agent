"""Pick the right extractor for a file: Python `ast`, Tree-sitter, or a regex fallback when no grammar is installed."""
from __future__ import annotations
import hashlib
import re
from pathlib import PurePosixPath

from .model import FileFacts, Symbol, finalize_ids, is_test_path, language_of
from .python_ast import extract_python
from .ts_core import EXT_TO_GRAMMAR, get_parser
from .ts_langs import VISITORS

_JS_FALLBACK = re.compile(
    r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?(function\*?|class)\s+(\w+)"
    r"|^(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?(?:\(|function|\w+\s*=>)")


def sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def _regex_fallback(path: str, text: str, language: str) -> FileFacts:
    """Used only when Tree-sitter isn't installed: top-level JS/TS functions and classes by regex."""
    lines = text.splitlines()
    facts = FileFacts(path=path, language=language, lines=len(lines), parser="regex", is_test=is_test_path(path))
    starts = []
    for i, line in enumerate(lines):
        m = _JS_FALLBACK.match(line) if language in ("javascript", "typescript") else None
        if m:
            starts.append((i + 1, m.group(2) or m.group(3), "class" if m.group(1) == "class" else "function"))
    for n, (s, name, kind) in enumerate(starts):
        e = starts[n + 1][0] - 1 if n + 1 < len(starts) else len(lines)
        body = "\n".join(lines[s - 1:e])
        facts.symbols.append(Symbol(file=path, language=language, kind=kind, name=name, qualname=name, start=s, end=e,
                                    calls=sorted(set(re.findall(r"\b(\w+)\s*\(", body)) - {name})))
    finalize_ids(facts)
    return facts


def extract_file(path: str, data: bytes) -> FileFacts:
    """Never raises: a parse failure yields an empty-but-valid FileFacts with `errors` filled."""
    language = language_of(path)
    text = data.decode("utf-8", "replace")
    digest = sha1(data)
    facts: FileFacts | None = None
    try:
        if language == "python":
            try:
                facts = extract_python(path, text)
            except (SyntaxError, ValueError, RecursionError):
                grammar = get_parser("python")
                if grammar is not None:
                    facts = VISITORS["python"](path, data, grammar.parse(data).root_node, "python").result()
                    facts.errors.append("python syntax error: extracted with Tree-sitter instead")
        else:
            key = EXT_TO_GRAMMAR.get(PurePosixPath(path).suffix.lower())
            parser = get_parser(key) if key else None
            if parser is not None:
                facts = VISITORS[key](path, data, parser.parse(data).root_node, key).result()
                facts.language = language
            elif key:
                facts = _regex_fallback(path, text, language)
    except Exception as e:  # noqa: BLE001 - one bad file must never break indexing
        facts = FileFacts(path=path, language=language, lines=text.count("\n") + 1, parser="error", errors=[f"{type(e).__name__}: {e}"[:200]])
    if facts is None:
        facts = FileFacts(path=path, language=language, lines=text.count("\n") + 1, parser="none", is_test=is_test_path(path))
    facts.hash = digest
    facts.lines = facts.lines or text.count("\n") + 1
    return facts
